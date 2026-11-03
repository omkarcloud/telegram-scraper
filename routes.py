"""The 7 Telegram endpoints. Every path is served with and without the
`/telegram` prefix, so code generated against the hosted API on RapidAPI
(paths like /channels/messages) runs unchanged against this server.

Each route validates the query with the module's marshmallow schema
(telegram/schemas.py: one param per input, a bare id or any t.me link),
calls the endpoint function (telegram/api.py) and maps the module's failure
taxonomy to HTTP exactly like the hosted API: bad params -> 400, an unknown
username / post / invite / gift -> 404 with a plain message, a block or
upstream failure -> 502, anything else -> 500."""
import json

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from telegram import api, schemas


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands
    back latin-1 decoded bytes, so a UTF-8 query would arrive mangled)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema_cls, impl):
    """Validate with the schema, run impl(**data), map errors to HTTP."""
    data, error = load_query(schema_cls, query_dict())
    if error:
        return json_response(error, 400)
    try:
        return json_response(impl(**data))
    except ValueError as e:                 # bad id / params
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                 # upstream rejected the request
        return json_response({"error": f"telegram rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"telegram blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"telegram {label} failed: {e}"}, 502)
    except Exception as e:                  # parser surprises
        return json_response({"error": f"telegram {label} failed: {type(e).__name__}: {e}"}, 500)


def mount(path, schema_cls, impl):
    """Serve an endpoint at /path and /telegram/path."""
    label = path.strip("/")

    def handler():
        return call(label, schema_cls, impl)
    handler.__name__ = "telegram_" + label.replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/telegram" + path, method="GET")(handler)


ENDPOINTS = [
    ("/channels/messages", schemas.ChannelMessagesSchema, api.channel_messages),
    ("/channels/details", schemas.ChannelSchema, api.channel_details),
    ("/messages/search", schemas.MessagesSearchSchema, api.messages_search),
    ("/messages/details", schemas.MessageSchema, api.message_details),
    ("/messages/comments", schemas.MessageCommentsSchema, api.message_comments),
    ("/invites/details", schemas.InviteSchema, api.invite_details),
    ("/gifts/details", schemas.GiftSchema, api.gift_details),
]

for _path, _schema, _impl in ENDPOINTS:
    mount(_path, _schema, _impl)


@route("/", method="GET")
@route("/health", method="GET")
@route("/telegram/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})

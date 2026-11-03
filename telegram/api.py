"""The /telegram/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Caching sits on the upstream SURFACES (cache.cached_call, one namespace per
page type, keyed on the resolved reference + cursor): channels/details
composes the cached preview with the cached newest feed page, which is the
same row channels/messages serves as page 1; messages/details composes the
cached embed with a cached one-comment discussion page (its header carries
the total; a different comments_limit than the comments endpoint's page, so
the two never share Telegram's author-stripping window). No endpoint
fetches a page it does not need, and an author-stripped discussion page is
served but not cached (DontCache).

Paging is by cursor because t.me pages by id: a feed page carries
`before=<message id>` for the older page, a discussion page
`before_id=<comment id>`; the API hands that back as `next_cursor` with
`has_more`, and a page past the end is an empty page.
"""
from cache import DontCache, cached_call
from telegram import cache_config as ttl
from telegram import parsers
from telegram.fetch import (fetch_comments, fetch_embed, fetch_feed, fetch_gift, fetch_invite,
                            fetch_preview, COMMENTS_PAGE_SIZE)
from telegram.refs import channel_link, feed_link, message_link, split_message

FEED_PAGE_SIZE = 20   # t.me's own /s/ page size


# ---- cached surfaces -----------------------------------------------------------------------

def _preview_record(username):
    return parsers.parse_preview(fetch_preview(username), username)


def _preview(username):
    return cached_call("telegram.preview", {"username": username}, _preview_record, ttl.PREVIEW_CACHE)


def _feed_record(username, before=None, query=None):
    return parsers.parse_feed(fetch_feed(username, before=before, query=query))


def _feed(username, before=None, query=None):
    data = {"username": username, "before": before, "query": query}
    return cached_call("telegram.feed", data, _feed_record,
                       ttl.SEARCH_CACHE if query else ttl.FEED_CACHE)


def _embed_record(username, msg_id):
    return parsers.parse_embed(fetch_embed(username, msg_id))


def _embed(username, msg_id):
    return cached_call("telegram.message", {"username": username, "msg_id": msg_id},
                       _embed_record, ttl.MESSAGE_CACHE)


def _comments_record(username, msg_id, before_id=None):
    html, payload = fetch_comments(username, msg_id, before_id=before_id)
    record = parsers.parse_comments(html, payload)
    if record["is_authors_hidden"]:
        # Telegram's author-stripped copy of a page someone requested within
        # the last ~minute: serve it (the text and ids are right) but do not
        # keep it, so the next call gets the authored page once the window
        # has passed.
        return DontCache(record)
    return record


def _comments(username, msg_id, before_id=None):
    data = {"username": username, "msg_id": msg_id, "before_id": before_id}
    return cached_call("telegram.comments", data, _comments_record, ttl.COMMENTS_CACHE)


# ---- channels/details ----------------------------------------------------------------------

def _latest(messages):
    if not messages:
        return None
    newest = max(messages, key=lambda m: m.get("id") or 0)
    return {"id": newest.get("id"), "link": newest.get("link"), "date": newest.get("date")}


def channel_details(channel):
    """The public entity page of a channel / group / bot / user, plus — for
    a channel with a web preview — the feed header's media counters, the
    numeric channel id and the newest post."""
    record = _preview(channel)
    if record is None:   # fetch_preview raises first; defensive
        from telegram.fetch import TelegramNotFound
        raise TelegramNotFound(f"@{channel} has no public Telegram page")
    out = {
        "username": record["username"],
        "link": record["link"],
        "type": record["type"],
        "id": None,
        "title": record["title"],
        "is_verified": record["is_verified"],
        "description": record["description"],
        "description_html": record["description_html"],
        "photo": record["photo"],
        "subscribers_count": record["subscribers_count"],
        "members_count": record["members_count"],
        "online_count": record["online_count"],
        "monthly_users_count": record["monthly_users_count"],
        "photos_count": None,
        "videos_count": None,
        "files_count": None,
        "links_count": None,
        "has_web_preview": record["has_web_preview"],
        "feed_link": record["feed_link"],
        "latest_message": None,
    }
    if record["has_web_preview"]:
        try:
            feed = _feed(record["username"])
        except Exception:   # the preview is the record; the feed only enriches it
            feed = None
        if feed:
            header = feed.get("channel") or {}
            messages = feed.get("messages") or []
            out["id"] = next((m["channel"]["id"] for m in messages if m.get("channel", {}).get("id")), None)
            for key in ("photos_count", "videos_count", "files_count", "links_count"):
                out[key] = header.get(key)
            if out["subscribers_count"] is None:
                out["subscribers_count"] = header.get("subscribers_count")
            out["latest_message"] = _latest(messages)
    return out


# ---- channels/messages + messages/search ---------------------------------------------------

def _feed_page(username, cursor=None, query=None):
    feed = _feed(username, before=cursor, query=query)
    header = feed.get("channel") or {}
    messages = feed.get("messages") or []
    return {
        "channel": {
            "username": header.get("username") or username,
            "link": header.get("link") or channel_link(username),
            "id": next((m["channel"]["id"] for m in messages if m.get("channel", {}).get("id")), None),
            "title": header.get("title"),
            "is_verified": header.get("is_verified"),
            "photo": header.get("photo"),
            "description": header.get("description"),
            "subscribers_count": header.get("subscribers_count"),
            "photos_count": header.get("photos_count"),
            "videos_count": header.get("videos_count"),
            "files_count": header.get("files_count"),
            "links_count": header.get("links_count"),
            "feed_link": feed_link(username),
        },
        "messages": messages,
        "message_count": len(messages),
        "items_per_page": FEED_PAGE_SIZE,
        "next_cursor": feed.get("before_cursor"),
        "has_more": feed.get("before_cursor") is not None,
    }


def channel_messages(channel, cursor=None):
    """One page (20) of a channel's public posts, newest first; `cursor` =
    next_cursor of the previous page."""
    page = _feed_page(channel, cursor=cursor)
    return {"cursor": cursor, **page}


def messages_search(channel, query, cursor=None):
    """Telegram's own full-text search inside one channel, 20 per page,
    newest matches first."""
    page = _feed_page(channel, cursor=cursor, query=query)
    return {"query": query, "cursor": cursor, **page}


# ---- messages/details ----------------------------------------------------------------------

def _summary_record(username, msg_id):
    html, _ = fetch_comments(username, msg_id, limit=1)
    page = parsers.parse_comments(html)
    return {"is_discussion_enabled": page["is_available"],
            "comments_count": page["total_count"] if page["is_available"] else 0}


def _discussion_summary(username, msg_id):
    """The discussion widget's header for a post: whether comments are
    enabled and how many there are (one cached fetch of a one-comment page,
    a separate key from the comments endpoint's 50-comment page)."""
    try:
        return cached_call("telegram.comments_summary", {"username": username, "msg_id": msg_id},
                           _summary_record, ttl.COMMENTS_CACHE)
    except Exception:   # the message is the record; the discussion only enriches it
        return {"is_discussion_enabled": None, "comments_count": None}


def message_details(message):
    """One public post (channel or public group message) with its views,
    reactions, media, link preview, buttons, and the discussion summary."""
    username, msg_id = split_message(message)
    record = _embed(username, msg_id)
    if record is None:
        from telegram.fetch import TelegramNotFound
        raise TelegramNotFound(f"message {message} not found")
    return {**record, **_discussion_summary(username, msg_id)}


# ---- messages/comments ---------------------------------------------------------------------

def message_comments(message, cursor=None):
    """The comments under a post (newest page first, up to 50 per page);
    `cursor` = next_cursor of the previous page. A post without comments
    enabled answers an empty page with is_discussion_enabled false; an
    unknown post is a 404. `is_authors_hidden` is true when Telegram served
    its author-stripped copy (the same page was requested by someone
    within the last ~minute): names, handles and avatars are null then,
    the text, ids and dates are complete, and the page is not cached, so
    a retry after a minute gets the authored one."""
    username, msg_id = split_message(message)
    page = _comments(username, msg_id, before_id=cursor)
    if not page["is_available"]:
        _embed(username, msg_id)   # raises NotFound for an unknown post
    comments = page["comments"] if page["is_available"] else []
    return {
        "message": {"id": msg_id, "link": message_link(username, msg_id),
                    "channel": {"username": username, "link": channel_link(username)}},
        "cursor": cursor,
        "is_discussion_enabled": page["is_available"],
        "is_authors_hidden": page["is_authors_hidden"],
        "comments_count": page["total_count"] if page["is_available"] else 0,
        "discussion_group_id": next((c["discussion_group_id"] for c in comments if c.get("discussion_group_id")), None),
        "comments": comments,
        "comment_count": len(comments),
        "items_per_page": COMMENTS_PAGE_SIZE,
        "next_cursor": page["before_cursor"] if page["is_available"] else None,
        "has_more": page["is_available"] and page["before_cursor"] is not None,
    }


# ---- invites/details -----------------------------------------------------------------------

def _invite_record(invite):
    return parsers.parse_invite(fetch_invite(invite), invite)


def invite_details(invite):
    """What a t.me/+<hash> link opens: the chat's type, title, photo, counts
    and description. A revoked or invalid hash is a 404."""
    record = cached_call("telegram.invite", {"invite": invite}, _invite_record, ttl.INVITE_CACHE)
    if record is None:
        from telegram.fetch import TelegramNotFound
        raise TelegramNotFound(f"invite link +{invite} is invalid, expired or revoked")
    return record


# ---- gifts/details -------------------------------------------------------------------------

def _gift_record(gift):
    return parsers.parse_gift(fetch_gift(gift), gift)


def gift_details(gift):
    """A collectible gift (t.me/nft/<Collection>-<number>): owner, model /
    backdrop / symbol with rarity, quantity issued, sticker file."""
    record = cached_call("telegram.gift", {"gift": gift}, _gift_record, ttl.GIFT_CACHE)
    if record is None:
        from telegram.fetch import TelegramNotFound
        raise TelegramNotFound(f"collectible gift {gift} not found")
    return record

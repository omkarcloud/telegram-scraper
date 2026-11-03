"""Offline tests for the /telegram/* request schemas.

    python -m pytest telegram/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import schemas  # noqa: E402


def _error(schema_cls, data):
    with pytest.raises(ValidationError) as info:
        schema_cls().load(data)
    return info.value.normalized_messages()


def test_channel_schema_accepts_every_form():
    assert schemas.ChannelSchema().load({"channel": "Durov"}) == {"channel": "durov"}
    assert schemas.ChannelSchema().load({"channel": "@durov"}) == {"channel": "durov"}
    assert schemas.ChannelSchema().load({"channel": " https://t.me/s/durov?before=1 "}) == {"channel": "durov"}
    assert schemas.ChannelSchema().load({"channel": "https://t.me/durov/300"}) == {"channel": "durov"}


@pytest.mark.parametrize("value,fragment", [
    ("", "Must not be empty"),
    ("ab", "Not a valid Telegram username"),
    ("https://example.com/durov", "t.me link"),
    ("https://t.me/+7G7QpTO2PDE0YWE6", "invites/details"),
    ("https://t.me/c/1234567890/1", "private"),
])
def test_channel_schema_rejects(value, fragment):
    errors = _error(schemas.ChannelSchema, {"channel": value})
    assert fragment in " ".join(errors["channel"])


def test_channel_schema_requires_channel_and_rejects_siblings():
    assert "channel" in _error(schemas.ChannelSchema, {})
    assert "url" in _error(schemas.ChannelSchema, {"channel": "durov", "url": "https://t.me/durov"})


def test_channel_messages_schema():
    assert schemas.ChannelMessagesSchema().load({"channel": "durov"}) == {"channel": "durov", "cursor": None}
    assert schemas.ChannelMessagesSchema().load({"channel": "durov", "cursor": "300"}) == {"channel": "durov", "cursor": 300}
    assert "cursor" in _error(schemas.ChannelMessagesSchema, {"channel": "durov", "cursor": "0"})
    assert "cursor" in _error(schemas.ChannelMessagesSchema, {"channel": "durov", "cursor": "abc"})


def test_messages_search_schema():
    loaded = schemas.MessagesSearchSchema().load({"channel": "@durov", "query": " crypto "})
    assert loaded == {"channel": "durov", "query": "crypto", "cursor": None}
    assert "query" in _error(schemas.MessagesSearchSchema, {"channel": "durov"})
    assert "query" in _error(schemas.MessagesSearchSchema, {"channel": "durov", "query": "x" * 201})


def test_message_schema():
    assert schemas.MessageSchema().load({"message": "durov/300"}) == {"message": "durov/300"}
    assert schemas.MessageSchema().load({"message": "https://t.me/durov/300?single"}) == {"message": "durov/300"}
    errors = _error(schemas.MessageSchema, {"message": "https://t.me/durov"})
    assert "message id" in " ".join(errors["message"])
    assert "message" in _error(schemas.MessageSchema, {})


def test_message_comments_schema():
    loaded = schemas.MessageCommentsSchema().load({"message": "tginfo/4430", "cursor": "1828162"})
    assert loaded == {"message": "tginfo/4430", "cursor": 1828162}
    assert "cursor" in _error(schemas.MessageCommentsSchema, {"message": "tginfo/4430", "cursor": "-1"})


def test_invite_schema():
    for value in ("7G7QpTO2PDE0YWE6", "+7G7QpTO2PDE0YWE6", "https://t.me/+7G7QpTO2PDE0YWE6",
                  "https://t.me/joinchat/7G7QpTO2PDE0YWE6"):
        assert schemas.InviteSchema().load({"invite": value}) == {"invite": "7G7QpTO2PDE0YWE6"}
    errors = _error(schemas.InviteSchema, {"invite": "https://t.me/durov"})
    assert "invite hash" in " ".join(errors["invite"])


def test_gift_schema():
    assert schemas.GiftSchema().load({"gift": "https://t.me/nft/PlushPepe-1"}) == {"gift": "PlushPepe-1"}
    assert schemas.GiftSchema().load({"gift": "PlushPepe-1"}) == {"gift": "PlushPepe-1"}
    errors = _error(schemas.GiftSchema, {"gift": "PlushPepe"})
    assert "PlushPepe-1" in " ".join(errors["gift"])


def test_every_field_is_documented():
    for schema_cls in (schemas.ChannelSchema, schemas.ChannelMessagesSchema, schemas.MessagesSearchSchema,
                       schemas.MessageSchema, schemas.MessageCommentsSchema, schemas.InviteSchema,
                       schemas.GiftSchema):
        for name, field in schema_cls().fields.items():
            assert field.metadata.get("description"), f"{schema_cls.__name__}.{name} has no description"

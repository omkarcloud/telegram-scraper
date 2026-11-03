"""Marshmallow request schemas for every /telegram/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair; the resolvers are in telegram/refs.py):

    channel   a username, @username or any t.me link of the entity
              (t.me/<u>, t.me/s/<u>, a post link whose channel is used)
    message   <channel>/<message id> or a t.me post link
    invite    an invite hash, +hash, or a t.me/+<hash> / joinchat link
    gift      a collectible slug (PlushPepe-1) or a t.me/nft/<slug> link
    query     free text searched inside one channel (t.me's own search)
    cursor    the `next_cursor` of the previous page: a message id (feed,
              search) or a comment id (comments) to page back from

Lists are cursor-paged because t.me pages by message id (before=<id>),
not by page number: `cursor` in, `next_cursor` / `has_more` out, like the
threads package.
"""
from schema_fields import BaseSchema, PositiveInt, QueryField, RefField
from telegram import refs


class ChannelRefField(RefField):
    resolver = staticmethod(refs.resolve_channel)


class MessageRefField(RefField):
    resolver = staticmethod(refs.resolve_message)


class InviteRefField(RefField):
    resolver = staticmethod(refs.resolve_invite)


class GiftRefField(RefField):
    resolver = staticmethod(refs.resolve_gift)


class ChannelSchema(BaseSchema):
    channel = ChannelRefField(metadata={
        "description": "channel username, @username or any t.me link of it "
                       "(https://t.me/durov, https://t.me/s/durov, or a post link); "
                       "groups, bots and users resolve too"})


class ChannelMessagesSchema(ChannelSchema):
    cursor = PositiveInt(metadata={
        "description": "next_cursor from the previous page: the message id to page back "
                       "from (older messages); omit for the newest page"})


class MessagesSearchSchema(ChannelSchema):
    query = QueryField(metadata={
        "description": "text to search for in the channel's messages (Telegram's own "
                       "full-text search, newest matches first)"})
    cursor = PositiveInt(metadata={
        "description": "next_cursor from the previous page: the message id to page back "
                       "from; omit for the first page"})


class MessageSchema(BaseSchema):
    message = MessageRefField(metadata={
        "description": "<channel>/<message id> (durov/300) or a t.me post link "
                       "(https://t.me/durov/300)"})


class MessageCommentsSchema(MessageSchema):
    cursor = PositiveInt(metadata={
        "description": "next_cursor from the previous page: the comment id to page back "
                       "from (older comments); omit for the latest page"})


class InviteSchema(BaseSchema):
    invite = InviteRefField(metadata={
        "description": "invite hash, +hash, or a t.me/+<hash> / t.me/joinchat/<hash> link"})


class GiftSchema(BaseSchema):
    gift = GiftRefField(metadata={
        "description": "collectible gift slug (PlushPepe-1) or a t.me/nft/<slug> link"})

"""Cache TTL per upstream surface of /telegram/* (cache.py, keyed on the
validated params). The endpoints compose cached surfaces (telegram/api.py):
channels/details reads the preview AND the newest feed page, and
channels/messages page 1 reads that same feed page, so a client hitting
both pays one feed fetch.
"""
from datetime import timedelta

# t.me/<username>: subscriber counts move by the minute on big channels,
# but a title / description / photo change is rare; an hour is fine.
PREVIEW_CACHE = timedelta(hours=1)
# One /s/ feed page: a new post shifts the newest page; older pages
# (before=<id>) only change in their view counts and reactions.
FEED_CACHE = timedelta(minutes=10)
# Search inside a channel: the same freshness as the feed.
SEARCH_CACHE = timedelta(minutes=10)
# One message embed: views and reactions move; text rarely.
MESSAGE_CACHE = timedelta(minutes=15)
# One discussion page: comments arrive continuously under hot posts.
COMMENTS_CACHE = timedelta(minutes=5)
# Invite previews: member counts move, the title does not.
INVITE_CACHE = timedelta(hours=1)
# Collectible gifts: the owner changes on a transfer, attributes never.
GIFT_CACHE = timedelta(hours=6)

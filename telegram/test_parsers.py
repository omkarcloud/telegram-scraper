"""Offline tests for the Telegram parsers, reference resolvers and value
helpers.

    python -m pytest telegram/test_parsers.py -q

Fixtures are real t.me pages captured 2026-11-03 (telegram/fixtures/):
entity previews (channel / group / bot / unknown / a user with no public
profile), channel feeds (page, before= JSON fragment, q= search, the oldest
page, feeds with albums / documents / inline buttons / replies), message
embeds (text, photo, not found, a public group message), the tginfo/4430
discussion (the page plus two loadComments payloads, one authored and one
author-stripped) and a disabled one, live group / channel invites and
a revoked one, two collectible gifts and the telegram.org redirect page an
unknown gift gets. No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


# ---- refs -------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("durov", "durov"),
    ("@Durov", "durov"),
    ("https://t.me/durov", "durov"),
    ("https://t.me/s/durov", "durov"),
    ("https://t.me/s/durov?before=300", "durov"),
    ("https://t.me/durov/300", "durov"),
    ("t.me/durov", "durov"),
    ("https://telegram.me/durov", "durov"),
    ("https://t.me/boost/durov", "durov"),
    ("tg://resolve?domain=durov", "durov"),
])
def test_resolve_channel(value, expected):
    assert refs.resolve_channel(value) == expected


@pytest.mark.parametrize("value", [
    "", "ab", "@", "has space", "-bad", "https://example.com/durov", "https://t.me/",
    "https://t.me/+7G7QpTO2PDE0YWE6", "https://t.me/joinchat/abcdefghijk",
    "https://t.me/c/1234567890/1", "https://t.me/nft/PlushPepe-1",
    "https://t.me/addstickers/Animals", "tg://join?invite=abcdefghijkl",
])
def test_resolve_channel_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_channel(value)


def test_resolve_channel_messages_name_the_right_endpoint():
    with pytest.raises(ValueError, match="invites/details"):
        refs.resolve_channel("https://t.me/+7G7QpTO2PDE0YWE6")
    with pytest.raises(ValueError, match="gifts/details"):
        refs.resolve_channel("https://t.me/nft/PlushPepe-1")
    with pytest.raises(ValueError, match="private"):
        refs.resolve_channel("https://t.me/c/1234567890/1")


@pytest.mark.parametrize("value,expected", [
    ("durov/300", "durov/300"),
    ("@Durov/300", "durov/300"),
    ("https://t.me/durov/300", "durov/300"),
    ("https://t.me/durov/300?single", "durov/300"),
    ("https://t.me/durov/300?comment=1828162", "durov/300"),
    ("https://t.me/s/durov/300", "durov/300"),
    ("t.me/durov/300", "durov/300"),
    ("https://telegram.me/tginfo/4430", "tginfo/4430"),
    ("tg://resolve?domain=durov&post=300", "durov/300"),
])
def test_resolve_message(value, expected):
    assert refs.resolve_message(value) == expected


@pytest.mark.parametrize("value", [
    "", "durov", "300", "durov/abc", "https://t.me/durov", "https://t.me/s/durov",
    "https://t.me/c/1234567890/1", "https://example.com/durov/300", "tg://resolve?domain=durov",
])
def test_resolve_message_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_message(value)


@pytest.mark.parametrize("value,expected", [
    ("7G7QpTO2PDE0YWE6", "7G7QpTO2PDE0YWE6"),
    ("+7G7QpTO2PDE0YWE6", "7G7QpTO2PDE0YWE6"),
    ("https://t.me/+7G7QpTO2PDE0YWE6", "7G7QpTO2PDE0YWE6"),
    ("https://t.me/joinchat/BhEzJWFW6Kg3YjM0", "BhEzJWFW6Kg3YjM0"),
    ("t.me/+7G7QpTO2PDE0YWE6", "7G7QpTO2PDE0YWE6"),
    ("tg://join?invite=7G7QpTO2PDE0YWE6", "7G7QpTO2PDE0YWE6"),
])
def test_resolve_invite(value, expected):
    assert refs.resolve_invite(value) == expected


@pytest.mark.parametrize("value", ["", "+", "short", "https://t.me/durov", "https://example.com/+7G7QpTO2PDE0YWE6",
                                   "has space12345"])
def test_resolve_invite_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_invite(value)


@pytest.mark.parametrize("value,expected", [
    ("PlushPepe-1", "PlushPepe-1"),
    ("https://t.me/nft/PlushPepe-1", "PlushPepe-1"),
    ("t.me/nft/DurovsCap-1", "DurovsCap-1"),
    ("tg://nft?slug=PlushPepe-1", "PlushPepe-1"),
])
def test_resolve_gift(value, expected):
    assert refs.resolve_gift(value) == expected


@pytest.mark.parametrize("value", ["", "PlushPepe", "Plush Pepe-1", "https://t.me/durov", "https://t.me/nft/"])
def test_resolve_gift_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_gift(value)


def test_links():
    assert refs.channel_link("durov") == "https://t.me/durov"
    assert refs.feed_link("durov") == "https://t.me/s/durov"
    assert refs.message_link("durov", 300) == "https://t.me/durov/300"
    assert refs.invite_link("abc") == "https://t.me/+abc"
    assert refs.gift_link("PlushPepe-1") == "https://t.me/nft/PlushPepe-1"
    assert refs.split_message("durov/300") == ("durov", 300)


# ---- value helpers -----------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("6.28M", 6280000), ("1.66K", 1660), ("10 147 852", 10147852), ("1,086", 1086),
    ("102", 102), ("49.3K", 49300), ("", None), (None, None), ("views", None),
])
def test_parse_number(text, expected):
    assert P.parse_number(text) == expected


def test_parse_counts():
    assert P.parse_counts("9 892 members, 1 444 online") == {"members": 9892, "online": 1444}
    assert P.parse_counts("10 147 852 subscribers") == {"subscribers": 10147852}
    assert P.parse_counts("7 996 041 monthly users") == {"monthly_users": 7996041}
    assert P.parse_counts("@alex") == {}


def test_parse_duration():
    assert P.parse_duration("1:15") == 75
    assert P.parse_duration("0:06") == 6
    assert P.parse_duration("1:02:03") == 3723
    assert P.parse_duration("") is None


def test_decode_view():
    token = "eyJjIjotMTAwNjUwMzEyMiwicCI6NTMxLCJ0IjoxNzkzNjk2Nzk3LCJoIjoiZmRiMWIwMzRlYTE1M2RkMzI2In0"
    assert P.decode_view(token)["c"] == -1006503122
    assert P.channel_id_from_view(token) == 1006503122
    assert P.decode_view("not base64!") is None
    assert P.channel_id_from_view(None) is None


# ---- previews ----------------------------------------------------------------------------

def test_preview_channel():
    rec = P.parse_preview(fixture("preview_channel_durov.html"), "durov")
    assert rec["type"] == "channel"
    assert rec["username"] == "durov" and rec["link"] == "https://t.me/durov"
    assert rec["title"] == "Pavel Durov" and rec["is_verified"] is True
    assert rec["subscribers_count"] == 10147231
    assert rec["description"] == "Founder of Telegram."
    assert rec["photo"].startswith("https://cdn4.telesco.pe/file/")
    assert rec["has_web_preview"] is True and rec["feed_link"] == "https://t.me/s/durov"
    assert rec["members_count"] is None and rec["monthly_users_count"] is None


def test_preview_group():
    rec = P.parse_preview(fixture("preview_group_pythontelegrambotgroup.html"), "pythontelegrambotgroup")
    assert rec["type"] == "group"
    assert rec["title"] == ">>> telegram.Bot()"
    assert rec["members_count"] == 9892 and rec["online_count"] == 1473
    assert rec["has_web_preview"] is False and rec["feed_link"] is None
    assert "@pythontelegrambottalk" in rec["description"]
    assert '<a href="https://t.me/pythontelegrambottalk">' in rec["description_html"]


def test_preview_bot():
    rec = P.parse_preview(fixture("preview_bot_botfather.html"), "BotFather")
    assert rec["type"] == "bot" and rec["username"] == "botfather"
    assert rec["monthly_users_count"] == 7996041 and rec["is_verified"] is True


def test_preview_unknown_and_private_user_are_none():
    assert P.parse_preview(fixture("preview_unknown_username.html"), "x") is None
    assert P.parse_preview(fixture("preview_no_web_preview_bbcnews.html"), "bbcnews") is None


# ---- the feed ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def durov_feed():
    return P.parse_feed(fixture("feed_durov.html"))


def test_feed_header(durov_feed):
    ch = durov_feed["channel"]
    assert ch["username"] == "durov" and ch["title"] == "Pavel Durov" and ch["is_verified"] is True
    assert ch["subscribers_count"] == 10100000
    assert ch["photos_count"] == 102 and ch["videos_count"] == 47 and ch["links_count"] == 200
    assert ch["files_count"] is None
    assert ch["description"] == "Founder of Telegram."


def test_feed_page_and_cursors(durov_feed):
    assert len(durov_feed["messages"]) == 20
    assert durov_feed["before_cursor"] == 531 and durov_feed["after_cursor"] is None
    assert durov_feed["notice"] is None
    ids = [m["id"] for m in durov_feed["messages"]]
    assert ids == sorted(ids) and ids[0] == 531


def test_feed_message_video(durov_feed):
    msg = durov_feed["messages"][0]
    assert msg["id"] == 531 and msg["link"] == "https://t.me/durov/531"
    assert msg["channel"] == {"username": "durov", "link": "https://t.me/durov", "id": 1006503122,
                              "title": "Pavel Durov"}
    assert msg["date"] == "2026-07-16T20:45:25+00:00"
    assert msg["text"].startswith("🩵 Telegram now has a Rich Text Editor.\n\nIt supports")
    assert "<b>Rich Text Editor</b>" in msg["text_html"] and "tg-emoji" not in msg["text_html"]
    assert msg["author_signature"] == "Pavel Durov"
    assert msg["views_count"] == 5870000
    assert msg["media_count"] == 1
    video = msg["media"][0]
    assert video["type"] == "video" and video["source"].startswith("https://cdn4.telesco.pe/file/")
    assert video["thumbnail"].startswith("https://cdn4.telesco.pe/file/")
    assert msg["reactions"][0] == {"emoji": None, "custom_emoji_id": None, "count": 6300, "is_paid": True}
    assert msg["reactions"][1]["custom_emoji_id"] == "5265077361648368841"
    assert msg["reactions"][1]["count"] == 54700
    assert msg["reactions_count"] == sum(r["count"] for r in msg["reactions"])
    assert msg["is_forwarded"] is False and msg["reply_to"] is None and msg["poll"] is None


def test_feed_message_forward_and_duration(durov_feed):
    msg = next(m for m in durov_feed["messages"] if m["id"] == 552)
    assert msg["is_forwarded"] is True
    assert msg["forwarded_from"] == {"name": None, "username": None, "link": None}   # hidden sender
    assert msg["media"][0]["type"] == "video" and msg["media"][0]["duration_seconds"] == 75
    assert msg["media"][0]["source"] is None   # large video: thumbnail only on the web
    assert "<blockquote>" in msg["text_html"]
    assert "designers" in msg["mentions"]


def test_feed_message_link_preview(durov_feed):
    msg = next(m for m in durov_feed["messages"] if m["id"] == 538)
    assert msg["link_preview"]["link"] == "https://telegram.org/safety"
    assert msg["link_preview"]["site_name"] == "Telegram"
    assert msg["link_preview"]["title"] == "Telegram Safety Overview"
    assert msg["link_preview"]["image"].startswith("https://cdn4.telesco.pe/file/")
    assert {"text": "all kinds of moderation tools", "link": "https://telegram.org/safety"} in msg["links"]


def test_feed_ajax_fragment():
    frag = P.parse_feed(json.loads(fixture("feed_durov_before_300.json")))
    assert frag["channel"] is None
    assert [m["id"] for m in frag["messages"]] == [280, 281, 282, 283, 284, 294, 295]
    assert frag["before_cursor"] == 280


def test_feed_search():
    page = P.parse_feed(fixture("feed_durov_q_crypto.html"))
    assert [m["id"] for m in page["messages"]] == [59, 120, 253, 265, 336, 386, 406, 500, 533]
    assert page["before_cursor"] is None and page["after_cursor"] is None


def test_feed_oldest_page():
    page = P.parse_feed(fixture("feed_telegram_before_2.html"))
    assert len(page["messages"]) == 1 and page["messages"][0]["id"] == 1
    assert page["before_cursor"] is None and page["after_cursor"] == 1


def test_feed_document_and_album_and_buttons():
    docs = P.parse_feed(fixture("feed_designers_media.html"))["messages"]
    doc = next(m for m in docs if any(x["type"] == "document" for x in m["media"]))
    assert doc["media"][0] == {"type": "document", "link": "https://t.me/designers/254", "source": None,
                               "thumbnail": None, "duration_seconds": None, "name": "PD.aep", "size": "1.3 MB"}
    album = next(m for m in P.parse_feed(fixture("feed_breakingmash_media.html"))["messages"] if m["is_album"])
    assert album["media_count"] >= 2
    assert {x["type"] for x in album["media"]} <= {"video", "photo"}
    assert album["media"][0]["duration_seconds"] == 6
    poll = next(m for m in P.parse_feed(fixture("feed_tginfo_q_poll_media.html"))["messages"] if m["inline_buttons"])
    assert poll["via_bot"] == {"name": "@vote", "username": "vote", "link": "https://t.me/vote"}
    assert poll["inline_buttons"][0] == {"text": "Да – 65%", "link": "https://t.me/tginfo/685"}


def test_feed_reply_hashtags_mentions():
    msg = next(m for m in P.parse_feed(fixture("feed_tginfo.html"))["messages"] if m["reply_to"])
    assert msg["reply_to"]["id"] == 4423 and msg["reply_to"]["link"] == "https://t.me/tginfo/4423"
    assert msg["reply_to"]["author"] == "Telegram Info" and msg["reply_to"]["text"].startswith("Реестр .me")
    assert "сбои" in msg["hashtags"] and "tginfo" in msg["mentions"]
    assert all(link["link"] for link in msg["links"])


# ---- embeds ------------------------------------------------------------------------------

def test_embed_message():
    msg = P.parse_embed(fixture("embed_message_durov_300.html"))
    assert msg["id"] == 300 and msg["link"] == "https://t.me/durov/300"
    assert msg["channel"]["id"] == 1006503122
    assert msg["date"] == "2024-06-30T06:48:04+00:00"
    assert msg["views_count"] == 3920000
    assert msg["is_album"] is True and msg["media_count"] >= 2
    assert msg["text"].startswith("🇺🇿 This week I visited Uzbekistan")


def test_embed_photo():
    msg = P.parse_embed(fixture("embed_message_durov_536_photo.html"))
    assert msg["media"] == [{"type": "photo", "link": "https://t.me/durov/536",
                             "source": msg["media"][0]["source"], "thumbnail": None,
                             "duration_seconds": None, "name": None, "size": None}]
    assert msg["media"][0]["source"].endswith(".jpg")
    assert msg["views_count"] == 6280000 and msg["text"] == "🇦🇫😈"
    assert msg["reactions"][0]["is_paid"] and msg["reactions"][0]["count"] == 49300


def test_embed_not_found():
    html = fixture("embed_message_not_found.html")
    assert P.parse_embed(html) is None
    assert P.embed_error(html) == "Post not found"


def test_embed_group_message():
    msg = P.parse_embed(fixture("embed_message_group_not_available.html"))
    assert msg["id"] == 5 and msg["channel"]["username"] == "pythontelegrambotgroup"
    assert msg["channel"]["title"] == ">>> telegram.Bot()" and msg["channel"]["id"] is None
    assert msg["sender"] == {"name": "Jasper", "username": "aaioeu", "link": "https://t.me/aaioeu"}
    assert msg["text"] == "Test; This message was edited by me :D"
    assert msg["views_count"] is None


# ---- comments ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def discussion():
    return P.parse_comments(fixture("comments_tginfo_4430.html"))


def test_comments_page(discussion):
    assert discussion["is_available"] is True and discussion["total_count"] == 59
    assert len(discussion["comments"]) == 50 and discussion["is_authors_hidden"] is False
    assert discussion["before_cursor"] == 1828162 and discussion["after_cursor"] == 1832585
    assert discussion["notice"] is None


def test_comment_fields(discussion):
    first = discussion["comments"][0]
    assert first["id"] == 1828162 and first["link"] == "https://t.me/tginfo/4430?comment=1828162"
    assert first["discussion_group_id"] == 1013954462
    assert first["author"]["name"] == "CHET -----" and first["author"]["username"] == "chet_roller"
    assert first["author"]["link"] == "https://t.me/chet_roller"
    assert first["author"]["photo"].startswith("https://cdn4.telesco.pe/file/")
    assert first["date"] == "2026-08-02T14:34:33+00:00"
    assert first["text"].startswith("Дуров такой балабол.")
    assert first["is_reply"] is False and first["reply_to"] is None
    second = discussion["comments"][1]
    assert second["is_reply"] is True
    assert second["reply_to"] == {"id": 1828162, "author": "CHET -----",
                                  "text": "Телега уже перестала быть стабильным мессенджером"}
    with_photo = next(c for c in discussion["comments"] if c["photos"])
    assert with_photo["photos"][0]["source"].startswith("https://cdn4.telesco.pe/file/")
    with_reaction = next(c for c in discussion["comments"] if c["reactions"])
    assert with_reaction["reactions_count"] >= 1 and with_reaction["reactions"][0]["emoji"]


def test_comments_api_older_page():
    payload = json.loads(fixture("comments_tginfo_4430_api_before_1832585.json"))
    page = P.parse_comments(fixture("comments_tginfo_4430.html"), payload)
    assert page["is_available"] is True and page["total_count"] == 59
    assert len(page["comments"]) == 50 and page["is_authors_hidden"] is False
    assert page["before_cursor"] == 1828154 and page["after_cursor"] is None
    assert all(c["id"] < 1832585 for c in page["comments"])
    anonymous = next(c for c in page["comments"] if c["author"]["username"] is None)
    assert anonymous["author"]["name"] and anonymous["author"]["link"] is None
    named = next(c for c in page["comments"] if c["author"]["username"])
    assert named["author"]["link"] == f"https://t.me/{named['author']['username']}"


def test_comments_api_author_stripped_page():
    payload = json.loads(fixture("comments_tginfo_4430_api_before_1828162.json"))
    page = P.parse_comments(fixture("comments_tginfo_4430.html"), payload)
    assert len(page["comments"]) == 9 and page["total_count"] == 59
    assert page["is_authors_hidden"] is True
    assert page["before_cursor"] is None   # the oldest comments
    assert all(c["author"] == {"name": None, "username": None, "link": None, "photo": None}
               for c in page["comments"])
    assert all(c["text"] or c["photos"] for c in page["comments"])


def test_comments_disabled():
    page = P.parse_comments(fixture("comments_disabled_telegram_460.html"))
    assert page["is_available"] is False and page["comments"] == []
    assert page["notice"] == "Discussion is not available at the moment."
    assert page["before_cursor"] is None


# ---- invites -----------------------------------------------------------------------------

def test_invite_group():
    rec = P.parse_invite(fixture("invite_group_live.html"), "7G7QpTO2PDE0YWE6")
    assert rec["type"] == "group" and rec["link"] == "https://t.me/+7G7QpTO2PDE0YWE6"
    assert rec["title"] == "Telegram Info Обжалование бана"
    assert rec["members_count"] == 86 and rec["online_count"] == 26 and rec["subscribers_count"] is None
    assert rec["photo"].startswith("https://cdn4.telesco.pe/file/")
    assert rec["description"].startswith("Чат для обсуждения")
    assert '<a href="https://t.me/tginfo">@tginfo</a>' in rec["description_html"]


def test_invite_channel():
    rec = P.parse_invite(fixture("invite_channel_live.html"), "mygREmk9YZhjY2Uy")
    assert rec["type"] == "channel" and rec["title"] == "Воронов"
    assert rec["subscribers_count"] == 676 and rec["members_count"] is None


def test_invite_revoked():
    assert P.parse_invite(fixture("invite_revoked.html"), "BhEzJWFW6Kg3YjM0") is None


# ---- gifts -------------------------------------------------------------------------------

def test_gift():
    rec = P.parse_gift(fixture("gift_plushpepe_1.html"), "PlushPepe-1")
    assert rec["name"] == "Plush Pepe #1" and rec["collection"] == "Plush Pepe" and rec["number"] == 1
    assert rec["link"] == "https://t.me/nft/PlushPepe-1"
    assert rec["owner"] == {"name": "Pavel Durov", "username": None, "link": None}
    assert rec["model"] == {"name": "Pumpkin", "rarity_percent": 3.0}
    assert rec["backdrop"] == {"name": "Onyx Black", "rarity_percent": 2.0}
    assert rec["symbol"] == {"name": "Illuminati", "rarity_percent": 0.5}
    assert rec["quantity"] == {"issued": 2825, "total": 2861}
    assert rec["image"].startswith("https://cdn4.telesco.pe/file/")
    assert rec["sticker_link"].startswith("https://cdn4.telesco.pe/file/sticker.tgs?token=")
    assert rec["description"] == "This NFT was created from a gift on Telegram."


def test_gift_second():
    rec = P.parse_gift(fixture("gift_durovscap_1.html"), "DurovsCap-1")
    assert rec["name"] == "Durov’s Cap #1" and rec["symbol"]["name"] == "Ram of Amun"
    assert rec["quantity"] == {"issued": 4710, "total": 4774}


def test_gift_not_found_pages():
    assert P.parse_gift(fixture("gift_not_found.html"), "PlushPepe-99999999") is None
    assert P.parse_gift(fixture("gift_bad_slug.html"), "NoSuchGift-1") is None


# ---- robustness ---------------------------------------------------------------------------

def test_parsers_survive_junk():
    assert P.parse_preview("<html><body>nothing</body></html>", "x") is None
    assert P.parse_invite("", "x") is None
    assert P.parse_gift("<html></html>", "x") is None
    assert P.parse_embed("") is None
    feed = P.parse_feed("")
    assert feed == {"channel": None, "messages": [], "before_cursor": None, "after_cursor": None, "notice": None}
    comments = P.parse_comments("")
    assert comments["comments"] == [] and comments["is_available"] is True and comments["total_count"] == 0
    assert comments["is_authors_hidden"] is False
    assert P.parse_comments("", {"ok": True, "comments_html": "", "header_html": "", "comments_cnt": 3})["total_count"] == 3

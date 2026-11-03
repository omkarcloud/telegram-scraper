"""t.me HTML -> clean dicts for every /telegram/* endpoint (pure functions,
no I/O).

Everything Telegram publishes on the web is server-rendered HTML with
stable `tgme_*` classes (the same markup the embed widget and the /s/
channel feed share):

  * PREVIEW  t.me/<username>          title, verified tick, photo, description
             and the exact count ("10 147 852 subscribers", "9 892 members,
             1 444 online", "7 996 041 monthly users" for bots). The page
             shape tells the entity type: a "Preview channel" context link
             = channel with a public feed, members = group, "Start Bot" =
             bot, a bare "Send Message" = user (or an unknown username —
             those two pages are identical and both carry no title).
  * FEED     t.me/s/<username>[?before=|?after=|?q=]   channel header
             (abbreviated counters) + 20 message blocks + `tme_messages_more`
             links whose data-before / data-after are the paging cursors.
             The same blocks come back as a JSON-encoded HTML string when
             the page is requested with X-Requested-With: XMLHttpRequest.
  * MESSAGE  t.me/<username>/<id>?embed=1&mode=tme   one message block (also
             for public GROUP messages); "Post not found" renders an
             err_message block.
  * COMMENTS t.me/<username>/<id>?embed=1&discussion=1&comments_limit=N
             the discussion widget: "59 comments" header, comment blocks
             (data-post-id, data-peer = the discussion group), data-before
             / data-after more links; older pages come from the widget's
             loadComments JSON ({header_html, comments_html, comments_cnt})
             with the same blocks. A post without a discussion says
             "Discussion is not available at the moment." A repeat request
             of the same page within ~60-90 s comes back with every author
             stripped (is_authors_hidden).
  * INVITE   t.me/+<hash>              title, photo, counts, description;
             a revoked hash renders the generic "Join group chat" page.
  * GIFT     t.me/nft/<Collection>-<n> owner, model / backdrop / symbol with
             rarity %, quantity issued, the animated sticker file.

Value conventions (shared with the other scraper packages): snake_case
keys, `link` not `url`, booleans as questions, ISO dates (UTC), numbers as
numbers (abbreviated "6.28M" -> 6280000), null for anything absent.

Message `data-view` is base64 JSON {"c": -1006503122, "p": 531, ...}: `c` is
the channel's numeric id (negative, as the MTProto chat id) — the only place
the web exposes it. An album message carries "p": "79065g".

Fixtures captured 2026-11-03 (telegram/fixtures/): channel / group / bot /
unknown previews, the durov feed (page, before= JSON fragment, q= search),
the oldest page of @telegram, feeds with albums / documents / inline
buttons / via-bot / replies (tginfo, designers, breakingmash, telegram),
message embeds (text, photo, not found, a public group message), the
tginfo/4430 discussion (the page, two loadComments payloads: an authored
older page and an author-stripped last page) and a disabled one, live
group / channel invites and a revoked one, two collectible gifts and the
telegram.org redirect an unknown gift gets.
"""
import base64
import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString

from telegram.refs import SITE, channel_link, feed_link, gift_link, invite_link, message_link

_NUMBER_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([KMB])?$", re.I)
_DIGITS_RE = re.compile(r"\d[\d\s ,]*")
_STYLE_URL_RE = re.compile(r"url\(['\"]?([^'\")]+)['\"]?\)")
_DURATION_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")
_HASHTAG_RE = re.compile(r"(?<![\w#])#([^\s#.,!?:;()\[\]{}<>\"']+)")
_COMMENT_HEADER_RE = re.compile(r"(\d[\d\s ,.]*)\s*([KMB])?\s*comments?", re.I)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_SUBS_RE = re.compile(r"([\d\s ,]+)\s*(subscribers?|members?|online|monthly users?)", re.I)

# Attributes that only serve the widget's own JS / styling.
_LINK_JUNK_ATTRS = ("onclick", "target", "rel", "class", "style", "dir")


# ---- generic helpers ---------------------------------------------------------------

def _soup(html):
    return BeautifulSoup(html or "", "lxml")


def _text(node, sep=" "):
    return " ".join(node.get_text(sep, strip=True).split()) if node is not None else ""


def _clean(value):
    if value is None:
        return None
    value = " ".join(str(value).replace(" ", " ").split())
    return value or None


def _attr(node, name):
    if node is None:
        return None
    value = node.get(name)
    if isinstance(value, list):
        value = " ".join(value)
    return _clean(value)


def _style_url(node):
    """The url(...) of an inline background-image style -> absolute link."""
    style = _attr(node, "style")
    if not style:
        return None
    match = _STYLE_URL_RE.search(style)
    return _absolute(match.group(1)) if match else None


def _absolute(link):
    link = _clean(link)
    if not link:
        return None
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return SITE + link
    return link


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_number(text):
    """"6.28M" / "1.66K" / "10 147 852" / "1,086" -> int; junk -> None.
    Abbreviated values are what Telegram shows, so 6.28M is 6280000 (the
    precision is the site's, not ours)."""
    text = _clean(text)
    if not text:
        return None
    compact = text.replace(" ", "").replace(",", "")
    match = _NUMBER_RE.match(compact)
    if not match:
        return None
    number, unit = match.group(1).replace(",", "."), (match.group(2) or "").upper()
    scale = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(unit, 1)
    try:
        return int(round(float(number) * scale))
    except ValueError:
        return None


def parse_counts(text):
    """"9 892 members, 1 444 online" -> {"members": 9892, "online": 1444};
    "10 147 852 subscribers" -> {"subscribers": ...}; "7 996 041 monthly
    users" -> {"monthly_users": ...}."""
    out = {}
    for number, kind in _SUBS_RE.findall(text or ""):
        key = kind.lower().rstrip("s") if not kind.lower().startswith("monthly") else "monthly_users"
        key = {"subscriber": "subscribers", "member": "members", "online": "online"}.get(key, key)
        out[key] = parse_number(number)
    return out


def parse_duration(text):
    """"1:15" / "0:06" / "1:02:03" -> seconds."""
    text = _clean(text)
    if not text:
        return None
    match = _DURATION_RE.match(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


def decode_view(token):
    """The message block's data-view: base64url JSON with the numeric
    channel id ("c", negative) and the post id ("p")."""
    token = _clean(token)
    if not token:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception:
        return None


def channel_id_from_view(token):
    view = decode_view(token)
    chat = view.get("c") if isinstance(view, dict) else None
    return abs(chat) if isinstance(chat, int) else None


def _username_from_link(link):
    """https://t.me/durov[/...] -> "durov"; anything else -> None."""
    link = _clean(link)
    if not link:
        return None
    url = urlparse(link if "://" in link else "https://" + link.lstrip("/"))
    if (url.hostname or "").lower() not in ("t.me", "telegram.me", "telegram.dog"):
        return None
    segments = [seg for seg in url.path.split("/") if seg]
    if not segments or segments[0] in ("s", "c", "nft", "joinchat") or segments[0].startswith("+"):
        return segments[1] if len(segments) > 1 and segments[0] == "s" else None
    return segments[0]


# ---- rich text ----------------------------------------------------------------------

def _rich_copy(node):
    """A working copy of a text node with Telegram's emoji wrappers reduced
    to the emoji itself, search highlights unwrapped and link attributes
    reduced to href."""
    copy = BeautifulSoup(str(node), "lxml")
    root = copy.find(True)
    while root is not None and root.name in ("html", "body"):
        child = root.find(True)
        if child is None:
            break
        root = child
    if root is None:
        return None
    for emoji in root.select("i.emoji"):
        glyph = emoji.find("b")
        emoji.replace_with(NavigableString(glyph.get_text() if glyph else emoji.get_text()))
    for tag in root.find_all("tg-emoji"):
        tag.unwrap()
    for mark in root.select("mark.highlight"):
        mark.unwrap()
    for anchor in root.find_all("a"):
        for attr in _LINK_JUNK_ATTRS:
            if attr in anchor.attrs:
                del anchor.attrs[attr]
    return root


def rich_text(node):
    """A tgme_widget_message_text node -> {"text", "html"} (plain text with
    newlines for <br>, HTML with b/i/u/s/a/code/pre/blockquote/spoilers kept
    and the widget's own attributes dropped)."""
    root = _rich_copy(node)
    if root is None:
        return {"text": None, "html": None}
    html = "".join(str(child) for child in root.contents).strip() or None
    for br in root.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for block in root.find_all(("blockquote", "pre", "p", "div")):
        block.insert_before(NavigableString("\n"))
        block.insert_after(NavigableString("\n"))
    text = root.get_text("")
    text = re.sub(r"[ \t ]+\n", "\n", text.replace(" ", " "))
    text = re.sub(r"\n{3,}", "\n\n", text).strip() or None
    return {"text": text, "html": html}


def text_links(node, plain_text):
    """Links, @mentions and #hashtags of a message text node."""
    links, mentions, hashtags = [], [], []
    if node is not None:
        for anchor in node.find_all("a"):
            href = _attr(anchor, "href")
            label = _text(anchor)
            if not href:
                continue
            if href.startswith("?q=%23") or href.startswith("?q=#"):
                tag = label.lstrip("#")
                if tag and tag not in hashtags:
                    hashtags.append(tag)
                continue
            username = _username_from_link(href)
            if username and label.startswith("@") and label[1:].lower() == username.lower():
                if username not in mentions:
                    mentions.append(username)
                continue
            if not any(item["link"] == href for item in links):
                links.append({"text": label or None, "link": href})
    for tag in _HASHTAG_RE.findall(plain_text or ""):
        if tag not in hashtags:
            hashtags.append(tag)
    return links, mentions, hashtags


# ---- reactions / buttons ------------------------------------------------------------

def parse_reactions(container):
    """.tgme_widget_message_reactions -> list of {emoji, custom_emoji_id,
    count, is_paid}; paid reactions are Telegram Stars."""
    reactions = []
    if container is None:
        return reactions
    for span in container.select(".tgme_reaction"):
        glyph = span.select_one("i.emoji b")
        custom = span.find("tg-emoji")
        count_text = "".join(child for child in span.strings if child.strip())
        count_text = count_text.replace(_text(glyph), "", 1) if glyph else count_text
        reactions.append({
            "emoji": _text(glyph) or None,
            "custom_emoji_id": _attr(custom, "emoji-id"),
            "count": parse_number(count_text),
            "is_paid": "tgme_reaction_paid" in (span.get("class") or []),
        })
    return reactions


def parse_inline_buttons(node):
    buttons = []
    for anchor in node.select(".tgme_widget_message_inline_button"):
        buttons.append({"text": _text(anchor) or None, "link": _absolute(_attr(anchor, "href"))})
    return buttons


# ---- a message block -----------------------------------------------------------------

def _author_block(bubble):
    """The first .tgme_widget_message_author under the bubble (never the
    reply's or the reply template's)."""
    if bubble is None:
        return None
    for child in bubble.find_all("div", recursive=False):
        if "tgme_widget_message_author" in (child.get("class") or []):
            return child
    return None


def _person(anchor_or_span):
    """An author / owner name element -> {name, username, link}."""
    if anchor_or_span is None:
        return None
    link = _absolute(_attr(anchor_or_span, "href")) if anchor_or_span.name == "a" else None
    return {"name": _text(anchor_or_span) or None,
            "username": _username_from_link(link),
            "link": link}


def _photo_url(node):
    """A user/channel avatar: the real CDN file, or None for the inline SVG
    placeholder Telegram renders when there is no photo."""
    img = node.find("img") if node is not None else None
    src = _attr(img, "src")
    if not src or src.startswith("data:"):
        return None
    return _absolute(src)


def _reply(node):
    reply = node.select_one(".tgme_widget_message_reply")
    if reply is None:
        return None
    link = _absolute(_attr(reply, "href"))
    reply_id = _int(_attr(reply, "data-reply-to"))
    if reply_id is None and link:
        tail = urlparse(link).path.rsplit("/", 1)[-1]
        reply_id = _int(tail)
    quote = reply.select_one(".js-message_reply_text") or reply.select_one(".tgme_widget_message_text")
    return {
        "id": reply_id,
        "link": link,
        "author": _text(reply.select_one(".tgme_widget_message_author_name")) or None,
        "text": _text(quote) or None,
        "thumbnail": _style_url(reply.select_one(".tgme_widget_message_reply_thumb")),
    }


def _forwarded(node):
    block = node.select_one(".tgme_widget_message_forwarded_from")
    if block is None:
        return None
    name = block.select_one(".tgme_widget_message_forwarded_from_name")
    anchor = name if name is not None and name.name == "a" else (name.find("a") if name is not None else None)
    link = _absolute(_attr(anchor, "href")) if anchor is not None else None
    return {"name": _text(name) or None, "username": _username_from_link(link), "link": link}


def _media(node):
    """Every attachment of a message block, albums included."""
    items = []
    for photo in node.select(".tgme_widget_message_photo_wrap"):
        if photo.find_parent(class_="tgme_widget_message_reply") is not None:
            continue
        items.append({"type": "photo", "link": _absolute(_attr(photo, "href")),
                      "source": _style_url(photo), "thumbnail": None, "duration_seconds": None,
                      "name": None, "size": None})
    for video in node.select(".tgme_widget_message_video_player, .tgme_widget_message_roundvideo_player"):
        classes = video.get("class") or []
        source = video.select_one("video")
        items.append({
            "type": "round_video" if "tgme_widget_message_roundvideo_player" in classes else "video",
            "link": _absolute(_attr(video, "href")),
            "source": _absolute(_attr(source, "src")),
            "thumbnail": _style_url(video.select_one(".tgme_widget_message_video_thumb, .tgme_widget_message_roundvideo_thumb")),
            "duration_seconds": parse_duration(_text(video.select_one(".message_video_duration, .tgme_widget_message_roundvideo_duration"))),
            "name": None, "size": None,
        })
    for doc in node.select(".tgme_widget_message_document_wrap"):
        items.append({"type": "document", "link": _absolute(_attr(doc, "href")), "source": None, "thumbnail": None,
                      "duration_seconds": None,
                      "name": _text(doc.select_one(".tgme_widget_message_document_title")) or None,
                      "size": _text(doc.select_one(".tgme_widget_message_document_extra")) or None})
    for audio in node.select(".tgme_widget_message_voice_player, .tgme_widget_message_audio_player, .tgme_widget_message_voice_wrap, .tgme_widget_message_audio_wrap"):
        classes = " ".join(audio.get("class") or [])
        source = audio.select_one("audio")
        items.append({
            "type": "voice" if "voice" in classes else "audio",
            "link": _absolute(_attr(audio, "href")),
            "source": _absolute(_attr(source, "src") or _attr(audio, "data-ogg") or _attr(audio, "data-mp3")),
            "thumbnail": None,
            "duration_seconds": parse_duration(_text(audio.select_one(".tgme_widget_message_voice_duration, .tgme_widget_message_audio_duration"))),
            "name": _text(audio.select_one(".tgme_widget_message_audio_title")) or None, "size": None,
        })
    for sticker in node.select(".tgme_widget_message_sticker_wrap, .tgme_widget_message_videosticker_wrap"):
        picture = sticker.select_one("picture source[srcset], img[src], video[src]")
        items.append({"type": "sticker", "link": _absolute(_attr(sticker, "href")),
                      "source": _absolute(_attr(picture, "srcset") or _attr(picture, "src")) if picture is not None else _style_url(sticker.select_one(".tgme_widget_message_sticker")),
                      "thumbnail": None, "duration_seconds": None, "name": None, "size": None})
    for location in node.select(".tgme_widget_message_location_wrap"):
        items.append({"type": "location", "link": _absolute(_attr(location, "href")), "source": None,
                      "thumbnail": _style_url(location.select_one(".tgme_widget_message_location")),
                      "duration_seconds": None, "name": None, "size": None})
    for contact in node.select(".tgme_widget_message_contact_wrap"):
        items.append({"type": "contact", "link": _absolute(_attr(contact, "href")), "source": None, "thumbnail": None,
                      "duration_seconds": None,
                      "name": _text(contact.select_one(".tgme_widget_message_contact_name")) or None,
                      "size": _text(contact.select_one(".tgme_widget_message_contact_phone")) or None})
    return items


def _poll(node):
    poll = node.select_one(".tgme_widget_message_poll")
    if poll is None:
        return None
    options = []
    for option in poll.select(".tgme_widget_message_poll_option"):
        percent = _text(option.select_one(".tgme_widget_message_poll_option_percent"))
        match = _PERCENT_RE.search(percent)
        options.append({"text": _text(option.select_one(".tgme_widget_message_poll_option_text")) or None,
                        "percent": float(match.group(1)) if match else None})
    return {
        "question": _text(poll.select_one(".tgme_widget_message_poll_question")) or None,
        "type": _text(poll.select_one(".tgme_widget_message_poll_type")) or None,
        "options": options,
        "voters_count": parse_number(_DIGITS_RE.search(_text(poll.select_one(".tgme_widget_message_voters"))).group(0))
        if _DIGITS_RE.search(_text(poll.select_one(".tgme_widget_message_voters"))) else None,
    }


def _link_preview(node):
    preview = node.select_one(".tgme_widget_message_link_preview")
    if preview is None:
        return None
    image = preview.select_one(".link_preview_image, .link_preview_right_image, .link_preview_video_thumb")
    return {
        "link": _absolute(_attr(preview, "href")),
        "site_name": _text(preview.select_one(".link_preview_site_name")) or None,
        "title": _text(preview.select_one(".link_preview_title")) or None,
        "description": _text(preview.select_one(".link_preview_description")) or None,
        "image": _style_url(image),
    }


def parse_message(node):
    """One .tgme_widget_message block (feed, embed or group embed) -> dict."""
    post = _attr(node, "data-post") or ""
    username, _, post_id = post.rpartition("/")
    msg_id = _int(post_id)
    bubble = node.select_one(".tgme_widget_message_bubble")
    author = _author_block(bubble)
    owner = _person(author.select_one(".tgme_widget_message_owner_name")) if author is not None else None
    sender = _person(author.select_one(".tgme_widget_message_author_name")) if author is not None else None
    via_bot = _person(author.select_one(".tgme_widget_message_via_bot")) if author is not None else None
    text_node = node.select_one(".tgme_widget_message_text.js-message_text")
    text = rich_text(text_node)
    links, mentions, hashtags = text_links(text_node, text["text"])
    date_anchor = node.select_one(".tgme_widget_message_date")
    time_node = date_anchor.find("time") if date_anchor is not None else node.select_one("time[datetime]")
    meta = _text(node.select_one(".tgme_widget_message_meta"))
    link = _absolute(_attr(date_anchor, "href")) or (message_link(username, msg_id) if username and msg_id else None)
    if link and "?" in link:
        link = link.split("?", 1)[0]
    media = _media(node)
    service = node.select_one(".tgme_widget_message_service_text, .service_message")
    reactions = parse_reactions(node.select_one(".tgme_widget_message_reactions"))
    return {
        "id": msg_id,
        "link": link,
        "channel": {
            "username": username or None,
            "link": channel_link(username) if username else None,
            "id": channel_id_from_view(_attr(node, "data-view")),
            "title": owner["name"] if owner else None,
        },
        "date": _attr(time_node, "datetime"),
        "text": text["text"],
        "text_html": text["html"],
        "author_signature": _text(node.select_one(".tgme_widget_message_from_author")) or None,
        "sender": sender,
        "via_bot": via_bot,
        "is_forwarded": node.select_one(".tgme_widget_message_forwarded_from") is not None,
        "forwarded_from": _forwarded(node),
        "reply_to": _reply(node),
        "is_edited": "edited" in meta.lower(),
        "is_album": isinstance((decode_view(_attr(node, "data-view")) or {}).get("p"), str),
        "views_count": parse_number(_text(node.select_one(".tgme_widget_message_views"))),
        "media": media,
        "media_count": len(media),
        "poll": _poll(node),
        "link_preview": _link_preview(node),
        "links": links,
        "mentions": mentions,
        "hashtags": hashtags,
        "reactions": reactions,
        "reactions_count": sum(r["count"] or 0 for r in reactions) if reactions else 0,
        "inline_buttons": parse_inline_buttons(node),
        "service_text": _text(service) or None,
    }


# ---- the channel feed ---------------------------------------------------------------

def parse_feed_header(soup):
    """The .tgme_channel_info sidebar of a /s/ page -> channel block (None
    for an AJAX fragment, which has no header)."""
    info = soup.select_one(".tgme_channel_info")
    if info is None:
        return None
    header = info.select_one(".tgme_channel_info_header")
    username_text = _text(info.select_one(".tgme_channel_info_header_username"))
    username = username_text.lstrip("@") or None
    counters = {}
    for counter in info.select(".tgme_channel_info_counter"):
        kind = _text(counter.select_one(".counter_type")).lower()
        counters[kind] = parse_number(_text(counter.select_one(".counter_value")))
    description = info.select_one(".tgme_channel_info_description")
    rich = rich_text(description) if description is not None else {"text": None, "html": None}
    return {
        "username": username,
        "link": channel_link(username) if username else None,
        "title": _text(info.select_one(".tgme_channel_info_header_title")) or None,
        "is_verified": info.select_one(".tgme_channel_info_header_labels .verified-icon") is not None,
        "photo": _photo_url(header),
        "description": rich["text"],
        "description_html": rich["html"],
        "subscribers_count": counters.get("subscribers", counters.get("subscriber", counters.get("members"))),
        "photos_count": counters.get("photos", counters.get("photo")),
        "videos_count": counters.get("videos", counters.get("video")),
        "files_count": counters.get("files", counters.get("file")),
        "links_count": counters.get("links", counters.get("link")),
    }


def _cursors(soup):
    """data-before / data-after of the "more" links (feed and discussion)."""
    before = after = None
    for more in soup.select(".tme_messages_more"):
        if more.get("data-before"):
            before = _int(more.get("data-before"))
        if more.get("data-after"):
            after = _int(more.get("data-after"))
    return before, after


def parse_feed(html):
    """A /s/<username> page (or the JSON-decoded AJAX fragment) -> {channel,
    messages, before_cursor, after_cursor, notice}. `notice` is the site's
    own empty-state line ("No posts found" on a search with no hits)."""
    soup = _soup(html)
    messages = [parse_message(node) for node in soup.select(".tgme_widget_message[data-post]")]
    before, after = _cursors(soup)
    return {
        "channel": parse_feed_header(soup),
        "messages": messages,
        "before_cursor": before,
        "after_cursor": after,
        "notice": _text(soup.select_one(".tme_no_messages_found")) or None,
    }


# ---- one message (the embed widget) --------------------------------------------------

def parse_embed(html):
    """A ?embed=1 page -> the message dict, or None when the widget renders
    an error block ("Post not found", "Channel with the username … not
    found"); embed_error(html) gives that text."""
    soup = _soup(html)
    node = soup.select_one(".tgme_widget_message[data-post]")
    if node is None:
        return None
    return parse_message(node)


def embed_error(html):
    soup = _soup(html)
    return _text(soup.select_one(".tgme_widget_message_error")) or None


# ---- the discussion widget -------------------------------------------------------------

def parse_comment(node):
    peer = _attr(node, "data-peer") or ""
    group_id = _int(peer[1:].split("_", 1)[0]) if peer.startswith("c") else None
    bubble = node.select_one(".tgme_widget_message_bubble")
    author = _author_block(bubble)
    name_node = author.select_one(".tgme_widget_message_author_name") if author is not None else None
    person = _person(name_node) or {"name": None, "username": None, "link": None}
    user_block = node.select_one(".tgme_widget_message_user")
    if person["link"] is None and user_block is not None:
        profile = user_block.find("a")
        person["link"] = _absolute(_attr(profile, "href"))
        person["username"] = _username_from_link(person["link"])
    person["photo"] = _photo_url(user_block)
    text_node = node.select_one(".tgme_widget_message_text.js-message_text")
    text = rich_text(text_node)
    links, mentions, hashtags = text_links(text_node, text["text"])
    date_anchor = node.select_one(".tgme_widget_message_date")
    time_node = date_anchor.find("time") if date_anchor is not None else None
    reply = node.select_one(".tgme_widget_message_reply.js-reply_to")
    reply_to = None
    if reply is not None:
        quote = reply.select_one(".js-message_reply_text")
        reply_to = {
            "id": _int(_attr(reply, "data-reply-to")),
            "author": _text(reply.select_one(".tgme_widget_message_author_name")) or None,
            "text": _text(quote) or None,
        }
    photos = [{"link": _absolute(_attr(photo, "href")), "source": _style_url(photo)}
              for photo in node.select(".tgme_widget_message_photo_wrap")
              if photo.find_parent(class_="tgme_widget_message_reply") is None]
    reactions = parse_reactions(node.select_one(".tgme_widget_message_reactions"))
    return {
        "id": _int(_attr(node, "data-post-id")),
        "link": _absolute(_attr(date_anchor, "href")),
        "discussion_group_id": group_id,
        "author": person,
        "date": _attr(time_node, "datetime"),
        "text": text["text"],
        "text_html": text["html"],
        "is_reply": reply_to is not None,
        "reply_to": reply_to,
        "photos": photos,
        "links": links,
        "mentions": mentions,
        "hashtags": hashtags,
        "reactions": reactions,
        "reactions_count": sum(r["count"] or 0 for r in reactions) if reactions else 0,
    }


def _authors_hidden(comments):
    """Telegram serves a repeat request of the same discussion page within
    ~60-90 s with every author stripped (no name, handle or avatar on any
    comment). A real page always carries display names."""
    return bool(comments) and all(c["author"]["name"] is None and c["author"]["photo"] is None
                                  for c in comments)


def parse_comments(html, api_payload=None):
    """A ?embed=1&discussion=1 page -> {is_available, total_count, comments,
    before_cursor, after_cursor, is_authors_hidden, notice}. With
    `api_payload` (the widget's loadComments JSON for an older page) the
    comments and cursors come from its comments_html and the total from
    its header. `notice` carries the widget's own line when there is
    nothing to show ("Discussion is not available at the moment." for a
    post without comments enabled, "Channel with the username @x not
    found" for an unknown channel)."""
    soup = _soup(html)
    notice = _text(soup.select_one(".tme_no_messages_found")) or None
    header = _text(soup.select_one(".tgme_post_discussion_header .js-header, .js-header"))
    if isinstance(api_payload, dict):
        soup = _soup(api_payload.get("comments_html") or "")
        header = _clean(api_payload.get("header_html")) or header
    match = _COMMENT_HEADER_RE.search(header or "")
    total = parse_number(match.group(1) + (match.group(2) or "")) if match else None
    if total is None and isinstance(api_payload, dict):
        total = _int(api_payload.get("comments_cnt"))
    comments = [parse_comment(node) for node in soup.select(".tgme_widget_message[data-post-id]")]
    before, after = _cursors(soup)
    available = notice is None or not notice.lower().startswith("discussion is not available")
    return {
        "is_available": available and not (notice or "").lower().startswith("channel with the username"),
        "total_count": total if total is not None else (0 if available and not comments else None),
        "comments": comments,
        "before_cursor": before,
        "after_cursor": after,
        "is_authors_hidden": _authors_hidden(comments),
        "notice": notice,
    }


# ---- entity previews (t.me/<username>, t.me/+hash) ---------------------------------------

def _page_description(page):
    node = page.select_one(".tgme_page_description") if page is not None else None
    if node is None:
        return {"text": None, "html": None}
    return rich_text(node)


def _preview_common(page):
    title = page.select_one(".tgme_page_title") if page is not None else None
    extras = [_text(extra) for extra in page.select(".tgme_page_extra")] if page is not None else []
    counts = {}
    for extra in extras:
        counts.update(parse_counts(extra))
    photo = page.select_one(".tgme_page_photo_image") if page is not None else None
    photo_src = _attr(photo, "src") if photo is not None and photo.name == "img" else _attr(photo.find("img") if photo is not None else None, "src")
    action = _text(page.select_one(".tgme_page_action a")) if page is not None else ""
    return {
        "title": _text(title.find("span") if title is not None and title.find("span") else title) or None,
        "is_verified": title is not None and title.select_one(".verified-icon") is not None,
        "photo": _absolute(photo_src) if photo_src and not photo_src.startswith("data:") else None,
        "description": _page_description(page),
        "extras": extras,
        "counts": counts,
        "action": action,
    }


def parse_preview(html, username):
    """t.me/<username> -> the entity record, or None when the page carries
    no title (an unknown username, or a user with no public profile: those
    two pages are identical)."""
    soup = _soup(html)
    page = soup.select_one(".tgme_page")
    common = _preview_common(page)
    if common["title"] is None:
        return None
    extras, counts, action = common["extras"], common["counts"], common["action"].lower()
    context = page.select_one(".tgme_page_context_link")
    has_feed = context is not None and (_attr(context, "href") or "").startswith("/s/")
    if "subscribers" in counts or has_feed:
        kind = "channel"
    elif "members" in counts or "online" in counts:
        kind = "group"
    elif "monthly_users" in counts or "bot" in action or "launch" in action:
        kind = "bot"
    else:
        kind = "user"
    handle = next((extra.lstrip("@") for extra in extras if extra.startswith("@")), None)
    return {
        "username": (handle or username or "").lower() or None,
        "link": channel_link((handle or username).lower()) if (handle or username) else None,
        "type": kind,
        "title": common["title"],
        "is_verified": common["is_verified"],
        "photo": common["photo"],
        "description": common["description"]["text"],
        "description_html": common["description"]["html"],
        "subscribers_count": counts.get("subscribers"),
        "members_count": counts.get("members"),
        "online_count": counts.get("online"),
        "monthly_users_count": counts.get("monthly_users"),
        "has_web_preview": has_feed,
        "feed_link": feed_link((handle or username).lower()) if has_feed and (handle or username) else None,
    }


def parse_invite(html, invite_hash):
    """t.me/+<hash> -> the invite record, or None when the hash is invalid /
    revoked (the generic "You are invited to a group chat" page)."""
    soup = _soup(html)
    page = soup.select_one(".tgme_page")
    common = _preview_common(page)
    if common["title"] is None:
        return None
    additional = _text(page.select_one(".tgme_page_additional")).lower()
    action = common["action"].lower()
    kind = "channel" if "channel" in action or "channel" in additional or "subscribers" in common["counts"] else "group"
    counts = common["counts"]
    return {
        "hash": invite_hash,
        "link": invite_link(invite_hash),
        "type": kind,
        "title": common["title"],
        "is_verified": common["is_verified"],
        "photo": common["photo"],
        "description": common["description"]["text"],
        "description_html": common["description"]["html"],
        "subscribers_count": counts.get("subscribers"),
        "members_count": counts.get("members"),
        "online_count": counts.get("online"),
    }


# ---- collectible gifts -----------------------------------------------------------------

def _meta(soup, prop):
    node = soup.find("meta", attrs={"property": prop})
    return _clean(node.get("content")) if node is not None else None


def parse_gift(html, slug):
    """t.me/nft/<slug> -> the collectible record, or None when the page is
    not a gift page (an unknown slug redirects to telegram.org)."""
    soup = _soup(html)
    page = soup.select_one(".tgme_page_gift")
    if page is None:
        return None
    rows = {}
    for row in page.select(".tgme_gift_table tr"):
        key = _text(row.find("th")).lower()
        cell = row.find("td")
        if key and cell is not None:
            rows[key] = cell

    def attribute(key):
        cell = rows.get(key)
        if cell is None:
            return None
        rarity = cell.find("mark")
        match = _PERCENT_RE.search(_text(rarity)) if rarity is not None else None
        name = _text(cell).replace(_text(rarity), "", 1).strip() if rarity is not None else _text(cell)
        return {"name": _clean(name), "rarity_percent": float(match.group(1)) if match else None}

    owner_cell = rows.get("owner")
    owner = None
    if owner_cell is not None:
        anchor = owner_cell.find("a")
        link = _absolute(_attr(anchor, "href")) if anchor is not None else None
        owner = {"name": _text(owner_cell) or None, "username": _username_from_link(link), "link": link}
    quantity = None
    if rows.get("quantity") is not None:
        numbers = [parse_number(part) for part in re.findall(r"\d[\d\s ,]*", _text(rows["quantity"]))]
        quantity = {"issued": numbers[0] if numbers else None, "total": numbers[1] if len(numbers) > 1 else None}
    og_title = _meta(soup, "og:title")
    number_label = _text(page.select_one(".tgme_gift_number_label"))
    number_match = re.search(r"#\s*(\d[\d\s ,]*)", number_label or og_title or "")
    collection, _, _ = (og_title or "").rpartition(" #")
    sticker = page.select_one("source[type='application/x-tgsticker']")
    description = page.select_one(".tgme_gift_description")
    return {
        "slug": slug,
        "link": gift_link(slug),
        "name": og_title,
        "collection": _clean(collection) or (slug.rsplit("-", 1)[0] if "-" in slug else None),
        "number": parse_number(number_match.group(1)) if number_match else None,
        "owner": owner,
        "model": attribute("model"),
        "backdrop": attribute("backdrop"),
        "symbol": attribute("symbol"),
        "quantity": quantity,
        "image": _meta(soup, "og:image"),
        "sticker_link": _absolute(_attr(sticker, "srcset")),
        "description": _clean((description.get_text("\n", strip=True).split("\n") or [None])[0]) if description is not None else None,
    }

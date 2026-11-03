"""Reference resolvers for /telegram/*: ONE param per input that accepts a
bare id OR any t.me link for the same record (tripadvisor QueryOrIdField
convention — never a sibling `url` / `id` pair). Resolvers raise ValueError
with a user-facing message (RefField turns it into a 400).

  channel   durov | @durov | https://t.me/durov | https://t.me/s/durov
            | https://t.me/s/durov?before=300 | https://t.me/durov/300 (the
            post's channel) | https://telegram.me/durov | t.me/boost/durov
            | tg://resolve?domain=durov
    -> "durov" (lower-cased: usernames are case-insensitive on t.me)

  message   durov/300 | @durov/300 | https://t.me/durov/300[?single]
            | https://t.me/s/durov/300 | https://t.me/durov/300?comment=5
            | tg://resolve?domain=durov&post=300
    -> "durov/300" (the channel username + the message id)
    Private links (t.me/c/<chat id>/<id>) need a logged-in member and are
    rejected with a message that says so.

  invite    7G7QpTO2PDE0YWE6 | +7G7QpTO2PDE0YWE6 | https://t.me/+7G7QpTO2PDE0YWE6
            | https://t.me/joinchat/7G7QpTO2PDE0YWE6 | tg://join?invite=…
    -> "7G7QpTO2PDE0YWE6" (the invite hash)

  gift      PlushPepe-1 | https://t.me/nft/PlushPepe-1 | tg://nft?slug=PlushPepe-1
    -> "PlushPepe-1" (the collectible slug: <Collection>-<number>)

Telegram public usernames are 5-32 characters of [A-Za-z0-9_] starting with
a letter; the pattern here allows 4+ so an old short name still resolves
and leaves the site to answer "not found".
"""
import re
from urllib.parse import parse_qs, urlparse

SITE = "https://t.me"

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
MESSAGE_ID_RE = re.compile(r"^[0-9]{1,12}$")
INVITE_HASH_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
GIFT_SLUG_RE = re.compile(r"^[A-Za-z0-9]+-[0-9]+$")

_TME_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me", "telegram.dog", "www.telegram.dog"}
_BARE_LINK_RE = re.compile(r"^(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)(?:[/?#]|$)", re.I)

# First path words of t.me that are features, not usernames.
_RESERVED = {
    "s", "c", "nft", "addstickers", "addemoji", "addtheme", "addlist", "joinchat", "boost",
    "proxy", "socks", "giftcode", "share", "iv", "m", "login", "contact", "setlanguage",
    "confirmphone", "bg", "invoice", "call", "vote", "blog", "faq", "apps", "privacy", "tos",
    "widgets", "dl", "home", "img", "js", "css", "api", "v", "premium_multigift",
}


def _as_url(value):
    """A pasted link (with or without a scheme) -> urlparse result, or None
    when the value is not a link at all."""
    if value.startswith(("http://", "https://", "//")):
        return urlparse(value if not value.startswith("//") else "https:" + value)
    if value.startswith("tg://"):
        return urlparse(value)
    if _BARE_LINK_RE.match(value):
        return urlparse("https://" + value)
    return None


def _tme_segments(url, what):
    """Path segments of a t.me / telegram.me link; ValueError for another host."""
    host = (url.hostname or "").lower()
    if host not in _TME_HOSTS:
        raise ValueError(f"Must be a t.me link or a bare {what}.")
    return [seg for seg in url.path.split("/") if seg]


def _username(value, what):
    name = value[1:] if value.startswith("@") else value
    if not USERNAME_RE.match(name) or name.lower() in _RESERVED:
        raise ValueError(f"Not a valid Telegram username for {what}: {value!r} "
                         "(letters, digits and underscores, starting with a letter).")
    return name.lower()


def _refuse_special(segments):
    """The t.me path words that are never a channel/message reference."""
    first = segments[0]
    if first.startswith("+") or first == "joinchat":
        raise ValueError("That is an invite link; use /telegram/invites/details for it.")
    if first == "c":
        raise ValueError("t.me/c/… links point into a private chat and only work for its "
                         "members; there is no public page to read.")
    if first == "nft":
        raise ValueError("That is a collectible gift link; use /telegram/gifts/details for it.")
    if first in ("addstickers", "addemoji", "addtheme", "proxy", "socks", "giftcode",
                 "share", "iv", "login", "setlanguage", "confirmphone", "bg", "invoice",
                 "addlist", "m"):
        raise ValueError(f"t.me/{first}/… links carry no channel or message.")


def resolve_channel(value):
    """Bare username, @username or any t.me link of a channel / group / bot /
    user (a post link resolves to its channel) -> the lower-cased username."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    url = _as_url(value)
    if url is None:
        return _username(value, "channel")
    if url.scheme == "tg":
        domain = parse_qs(url.query).get("domain", [""])[0]
        if url.netloc in ("resolve", "boost") and domain:
            return _username(domain, "channel")
        raise ValueError("Must be a tg://resolve?domain=<username> link, a t.me link or a username.")
    segments = _tme_segments(url, "username")
    if not segments:
        raise ValueError("Must be a t.me/<username> link, not the t.me homepage.")
    _refuse_special(segments)
    if segments[0] in ("s", "boost"):
        segments = segments[1:]
        if not segments:
            raise ValueError("Must be a t.me/s/<username> link.")
    return _username(segments[0], "channel")


def resolve_message(value):
    """"<username>/<id>" or any t.me post link -> "<username>/<id>"."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    url = _as_url(value)
    if url is None:
        username, _, msg_id = value.rpartition("/")
        if not username or not MESSAGE_ID_RE.match(msg_id):
            raise ValueError("Must be <channel>/<message id> (durov/300) or a t.me post link "
                             "(https://t.me/durov/300).")
        return f"{_username(username, 'message')}/{int(msg_id)}"
    if url.scheme == "tg":
        query = parse_qs(url.query)
        domain = query.get("domain", [""])[0]
        post = query.get("post", [""])[0]
        if url.netloc == "resolve" and domain and MESSAGE_ID_RE.match(post):
            return f"{_username(domain, 'message')}/{int(post)}"
        raise ValueError("Must be a tg://resolve?domain=<username>&post=<id> link, a t.me post "
                         "link or <channel>/<message id>.")
    segments = _tme_segments(url, "<channel>/<message id>")
    if not segments:
        raise ValueError("Must be a t.me/<channel>/<message id> link.")
    _refuse_special(segments)
    if segments[0] == "s":
        segments = segments[1:]
    if len(segments) < 2 or not MESSAGE_ID_RE.match(segments[1]):
        raise ValueError("Must be a t.me/<channel>/<message id> link (https://t.me/durov/300) "
                         "or <channel>/<message id>.")
    return f"{_username(segments[0], 'message')}/{int(segments[1])}"


def resolve_invite(value):
    """Bare hash, +hash, a t.me/+hash or t.me/joinchat/hash link, or a
    tg://join?invite=hash link -> the invite hash."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    url = _as_url(value)
    if url is None:
        candidate = value[1:] if value.startswith("+") else value
    elif url.scheme == "tg":
        candidate = parse_qs(url.query).get("invite", [""])[0] if url.netloc == "join" else ""
    else:
        segments = _tme_segments(url, "invite hash")
        if segments and segments[0].startswith("+"):
            candidate = segments[0][1:]
        elif len(segments) >= 2 and segments[0] == "joinchat":
            candidate = segments[1]
        else:
            candidate = ""
    if not INVITE_HASH_RE.match(candidate):
        raise ValueError("Must be an invite hash, +hash, or a t.me/+<hash> / t.me/joinchat/<hash> link.")
    return candidate


def resolve_gift(value):
    """Bare slug (PlushPepe-1), a t.me/nft/<slug> link or tg://nft?slug=…
    -> the slug."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    url = _as_url(value)
    if url is None:
        candidate = value
    elif url.scheme == "tg":
        candidate = parse_qs(url.query).get("slug", [""])[0] if url.netloc == "nft" else ""
    else:
        segments = _tme_segments(url, "gift slug")
        candidate = segments[1] if len(segments) >= 2 and segments[0] == "nft" else ""
    if not GIFT_SLUG_RE.match(candidate):
        raise ValueError("Must be a collectible gift slug like PlushPepe-1 or a "
                         "t.me/nft/<Collection>-<number> link.")
    return candidate


def split_message(ref):
    """"durov/300" -> ("durov", 300)."""
    username, _, msg_id = ref.rpartition("/")
    return username, int(msg_id)


def channel_link(username):
    return f"{SITE}/{username}"


def feed_link(username):
    return f"{SITE}/s/{username}"


def message_link(username, msg_id):
    return f"{SITE}/{username}/{msg_id}"


def invite_link(invite_hash):
    return f"{SITE}/+{invite_hash}"


def gift_link(slug):
    return f"{SITE}/nft/{slug}"

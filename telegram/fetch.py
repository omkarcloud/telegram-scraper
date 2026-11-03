"""Telegram transport: plain curl_cffi with browser-impersonated TLS on
t.me's public pages. No browser, no cookies, no tokens. Egress: the pod's
own IP (config.telegram_proxy(), knob TELEGRAM_EXIT) — every surface below
answered 200 from the pod's own Google Cloud address and from 2/2
datacenter and 2/2 US residential ports (pod probe 2026-11-03,
scrapers-patchright-depl-cb6ff6d5d-n8bjx; table in config.py). A retryable
failure drops the thread's session so the retry rides a fresh exit when
the knob is a proxied tier.

Six upstream surfaces, all open, all HTML:

  * PREVIEW  GET /<username>                        the entity page
  * FEED     GET /s/<username>[?before=|after=|q=]  20 channel messages
             (the same page the widget JS fetches as a JSON string with
             X-Requested-With; the full page carries the channel header,
             so the GET is used throughout)
  * MESSAGE  GET /<username>/<id>?embed=1&mode=tme  one message block
  * COMMENTS GET /<username>/<id>?embed=1&discussion=1&comments_limit=N
             the discussion widget's first (newest) page, with the hidden
             form (peer, top_msg_id, discussion_hash) and api_url the
             widget's JS pages with; older pages are what that JS sends:
             POST /api/method?api_hash=<page's>  method=loadComments&
             peer=&top_msg_id=&discussion_hash=&before_id=<comment id>
             -> JSON {ok, header_html, comments_html, comments_cnt}. A
             before_id on the page URL is served, but with every author
             stripped, so it is never used.
             Telegram strips authors (names, handles, avatars) from any
             REPEAT request of the same (post, cursor) within ~60-90 s,
             from any client or IP (probed 2026-11-03: first request
             authored, repeats anonymised, authored again after 90 s);
             the parser flags such a page and api.py does not cache it.
  * INVITE   GET /+<hash>
  * GIFT     GET /nft/<slug>                        (an unknown slug 302s
                                                    to telegram.org)

t.me answers HTTP 200 for everything it knows nothing about and says so
in the page, so NotFound is decided on the body (telegram/parsers.py has
the markers): no `tgme_page_title` on a preview, a feed that redirected
back to the preview page, an `err_message` embed block, a discussion
widget naming an unknown channel, an invite page without a title, a gift
request that left t.me.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  TelegramUpstreamError  transport failure / 5xx         — retryable
  TelegramBlocked        403 / 429                       — retryable
  TelegramBadRequest     upstream 400                    — never retried
  TelegramNotFound       unknown username / post / hash  — never retried
"""
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from telegram import parsers
from telegram.refs import SITE

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 30
# The discussion widget serves up to this many comments per page (probed
# 2026-11-03: comments_limit=100 returned 59 of 59 on tginfo/4430).
COMMENTS_PAGE_SIZE = 50

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "accept-language": egress.site_accept_language("telegram"),
    "upgrade-insecure-requests": "1",
}
API_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": egress.site_accept_language("telegram"),
    "x-requested-with": "XMLHttpRequest",
    "origin": SITE,
}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)


class TelegramUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class TelegramBlocked(TelegramUpstreamError, Blocked):
    """403 / 429 where a page was expected — retryable."""


class TelegramBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class TelegramNotFound(NotFound):
    """No public page for the reference — never retried."""


# One session per cheroot worker thread: a curl handle must not be shared
# across threads; the GETs are stateless so thread-lifetime sessions with
# keep-alive are enough.
_local = threading.local()


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = config.telegram_proxy()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers.update({"accept-language": egress.accept_language(proxy)})
        _local.session = sess
    return sess


def _drop_session():
    """Close the thread's session so a poisoned keep-alive connection (and
    its exit) dies."""
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _retrying(fn):
    """Run fn() under the shared retry policy (TelegramUpstreamError only;
    NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except TelegramUpstreamError as e:
            last = e
            _drop_session()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _classify(resp, label):
    if resp.status_code == 404:
        raise TelegramNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise TelegramBadRequest(resp.text[:200])
    if resp.status_code in (401, 403, 429):
        raise TelegramBlocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code != 200:
        raise TelegramUpstreamError(f"HTTP {resp.status_code} for {label}")
    return resp.text


def _get(path, label, params=None):
    """GET one t.me page; returns (text, final_url)."""
    url = SITE + path
    if params:
        url += "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})

    def once():
        try:
            resp = _session().get(url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT)
        except Exception as e:
            raise TelegramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label)
        if not text or "<html" not in text[:500].lower():
            raise TelegramUpstreamError(f"unexpected non-HTML response for {label}")
        return text, str(resp.url)
    return _retrying(once)


def _left_site(final_url):
    return (urlparse(final_url).hostname or "").lower() not in ("t.me", "telegram.me")


# ---- surfaces --------------------------------------------------------------------------

def fetch_preview(username):
    """t.me/<username> -> HTML. NotFound when the page carries no title: an
    unknown username, or a user who publishes no name (t.me renders the
    same "Send Message" page for both)."""
    text, _ = _get(f"/{username}", f"@{username}")
    if "tgme_page_title" not in text:
        raise TelegramNotFound(f"@{username} has no public Telegram page: unknown username, "
                               "or a user with no public profile")
    return text


def fetch_feed(username, before=None, after=None, query=None):
    """t.me/s/<username> -> HTML of one page of the channel's messages.
    NotFound when t.me sends the request back to the entity preview (not a
    channel, a channel with its web preview off, or an unknown username)."""
    params = {"before": before, "after": after, "q": query}
    text, final_url = _get(f"/s/{username}", f"@{username} feed", params)
    if not urlparse(final_url).path.startswith("/s/"):
        raise TelegramNotFound(f"@{username} has no public message feed: unknown username, "
                               "not a channel, or a channel whose web preview is off")
    return text


def fetch_embed(username, msg_id):
    """t.me/<username>/<id>?embed=1 -> HTML of the one-message widget.
    NotFound for the widget's own error block ("Post not found", "Channel
    with the username @x not found")."""
    text, _ = _get(f"/{username}/{msg_id}", f"message {username}/{msg_id}",
                   {"embed": "1", "mode": "tme"})
    error = parsers.embed_error(text)
    if error or "tgme_widget_message" not in text:
        detail = error or "no message block"
        raise TelegramNotFound(f"message {username}/{msg_id}: {detail}")
    return text


_API_URL_RE = re.compile(r'"api_url":"([^"]+)"')
_FORM_FIELD_RE = re.compile(r'<input[^>]*name="(peer|top_msg_id|discussion_hash)"[^>]*value="([^"]*)"')


def _load_comments(page_text, username, msg_id, before_id, label):
    """The widget's own loadComments call for the comments older than
    `before_id`, on the thread session that just loaded the page -> the
    JSON payload, or None when the page has no discussion form (comments
    disabled)."""
    api_match = _API_URL_RE.search(page_text)
    form = dict(_FORM_FIELD_RE.findall(page_text))
    if not api_match or not {"peer", "top_msg_id", "discussion_hash"} <= set(form):
        return None
    api_url = api_match.group(1).replace("\\/", "/")
    data = {"method": "loadComments", "peer": form["peer"], "top_msg_id": form["top_msg_id"],
            "discussion_hash": form["discussion_hash"], "before_id": str(before_id)}
    headers = {**API_HEADERS,
               "referer": f"{SITE}/{username}/{msg_id}?embed=1&discussion=1&comments_limit={COMMENTS_PAGE_SIZE}"}

    def once():
        try:
            resp = _session().post(api_url, data=data, headers=headers, timeout=PAGE_TIMEOUT)
        except Exception as e:
            raise TelegramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        _classify(resp, label)
        try:
            payload = resp.json()
        except Exception:
            raise TelegramUpstreamError(f"non-JSON loadComments response for {label}")
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise TelegramUpstreamError(f"loadComments refused for {label}: {str(payload)[:120]}")
        return payload
    return _retrying(once)


def fetch_comments(username, msg_id, before_id=None, limit=COMMENTS_PAGE_SIZE):
    """The discussion widget for a post -> (page HTML, loadComments JSON or
    None). The page is the newest `limit` comments (50 for the comments
    endpoint; messages/details asks for 1 — the header still carries the
    total, the page is 6 KB instead of 130 KB, and a different limit is a
    different key for Telegram's author-stripping window, so a details
    call never burns the comments page's authored copy); with `before_id`
    the JSON carries the 50 older ones (fetched right after the page, on
    the same session, as the widget's JS does). NotFound only when the
    widget names an unknown channel; a post without comments enabled is a
    valid page that the parser reports as unavailable."""
    label = f"comments of {username}/{msg_id}"
    text, _ = _get(f"/{username}/{msg_id}", label,
                   {"embed": "1", "discussion": "1", "comments_limit": limit})
    notice = parsers.parse_comments(text)["notice"] or ""
    if notice.lower().startswith("channel with the username"):
        raise TelegramNotFound(f"@{username} not found")
    payload = None
    if before_id is not None:
        payload = _load_comments(text, username, msg_id, before_id, f"{label} before {before_id}")
    return text, payload


def fetch_invite(invite_hash):
    """t.me/+<hash> -> HTML. NotFound when the hash is invalid, expired or
    revoked (the generic join page without a title)."""
    text, _ = _get(f"/+{invite_hash}", f"invite +{invite_hash}")
    if "tgme_page_title" not in text:
        raise TelegramNotFound(f"invite link +{invite_hash} is invalid, expired or revoked")
    return text


def fetch_gift(slug):
    """t.me/nft/<slug> -> HTML. NotFound when t.me redirects away (unknown
    collection or number)."""
    text, final_url = _get(f"/nft/{slug}", f"gift {slug}")
    if _left_site(final_url) or "tgme_page_gift" not in text:
        raise TelegramNotFound(f"collectible gift {slug} not found")
    return text

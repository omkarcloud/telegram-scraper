"""Egress helpers the scraper asks for: the Accept-Language header of a
session. The hosted API derives it from the country of the proxy exit it
leaves through; this open-source server runs direct (or through your own
TELEGRAM_PROXY), so it announces a plain English preference. t.me's pages
are the same in every language the header could ask for.
"""

DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def accept_language(proxy=None, country=None):
    """The Accept-Language for a session on `proxy` (ignored here)."""
    return DEFAULT_ACCEPT_LANGUAGE


def site_accept_language(site):
    """The Accept-Language for a site's module-level headers."""
    return DEFAULT_ACCEPT_LANGUAGE

"""Configuration for the Telegram Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT            port the API listens on (default 8000)
    TELEGRAM_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                    (default: none — direct). t.me's public pages answered 40
                    requests in 13 seconds from one IP without any throttling,
                    so you very likely don't need this. Set it only if you
                    start seeing failures at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

TELEGRAM_PROXY = os.environ.get("TELEGRAM_PROXY") or None


def telegram_proxy():
    """The proxy URL for one session (None = direct)."""
    return TELEGRAM_PROXY

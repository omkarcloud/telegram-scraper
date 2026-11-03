"""Response cache stand-in: the hosted API keeps parsed pages for a few
minutes; this open-source server fetches live on every call, so
`cached_call` simply runs the function.

    DontCache(data)   a result the scraper does not want kept (the hosted
                      API uses it for Telegram's author-stripped comment
                      pages); here it just unwraps to `data`
"""


class DontCache:
    def __init__(self, data):
        self.data = data


def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
    """Run fn(**data) and return its result (no caching here)."""
    result = fn(**data)
    if isinstance(result, DontCache):
        return result.data
    return result

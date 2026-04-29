"""Extractor base class + auto-registering subclass hook."""


class Extractor:
    """Abstract base. Subclasses auto-register via __init_subclass__."""

    NAME = ""
    ICON = ""
    COLOR = ""
    URL_PATTERNS = []
    _registry = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.NAME:
            Extractor._registry.append(cls)

    @classmethod
    def detect(cls, url):
        """Return an instance of the matching extractor, or None."""
        if not url or not isinstance(url, str):
            return None
        url = url.strip()
        if not url:
            return None
        for ext_cls in cls._registry:
            for pattern in ext_cls.URL_PATTERNS:
                try:
                    if pattern.match(url):
                        return ext_cls()
                except Exception:
                    continue
        return None

    @classmethod
    def all_names(cls):
        return [e.NAME for e in cls._registry]

    def resolve(self, url, log_fn=None):
        """Resolve a URL to a StreamInfo with qualities.
        Returns StreamInfo or None."""
        raise NotImplementedError

    def list_vods(self, url, log_fn=None, cursor=None):
        """List available VODs for a channel.

        Returns ``(list[VODInfo], next_cursor)`` where *next_cursor* is
        an opaque value to pass back for the next page, or ``None`` when
        there are no more results.  Legacy callers that only check for a
        list still work because the tuple is truthy when non-empty.
        """
        return [], None

    def supports_vod_listing(self):
        return False

    def supports_live_check(self):
        return False

    def check_live(self, url):
        """Check if channel is live. Returns bool or None."""
        return None

    def extract_channel_id(self, url):
        """Extract channel name/slug for folder naming."""
        return None

    def _log(self, log_fn, msg):
        if log_fn:
            log_fn(msg)

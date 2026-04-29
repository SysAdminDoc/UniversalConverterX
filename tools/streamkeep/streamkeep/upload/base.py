"""Upload destination base class + adapter registry (F68).

Each adapter subclasses ``UploadDestination`` and implements ``upload()``
and ``test_connection()``.  Subclasses auto-register via ``__init_subclass__``.
"""

class UploadDestination:
    """Abstract base for upload adapters."""

    NAME = ""
    _registry = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.NAME:
            UploadDestination._registry.append(cls)

    def __init__(self, config=None):
        self.config = config or {}

    def upload(self, file_path, metadata=None, progress_cb=None):
        """Upload *file_path* to the destination.

        *metadata* is an optional dict with title, channel, date, etc.
        *progress_cb* is called with ``(bytes_sent, total_bytes)`` or None.

        Returns ``(ok, message)``.
        """
        raise NotImplementedError

    def test_connection(self):
        """Test connectivity to the destination.

        Returns ``(ok, message)``.
        """
        raise NotImplementedError

    @classmethod
    def all_adapters(cls):
        return {c.NAME: c for c in cls._registry if c.NAME}

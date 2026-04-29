"""Extractor registry + concrete extractor classes.

Each concrete subclass auto-registers itself via `__init_subclass__`.
Importing this package imports every extractor module so the registry
is populated as a side effect — consumers only need
`from streamkeep.extractors import Extractor`.
"""

from .base import Extractor

# Importing each submodule triggers its subclass registration.
# Order matters: `YtDlpExtractor` is the catch-all fallback and must
# register last so platform-specific matchers get first chance at a URL.
from . import kick          # noqa: F401
from . import twitch        # noqa: F401
from . import rumble        # noqa: F401
from . import soundcloud    # noqa: F401
from . import reddit        # noqa: F401
from . import audius        # noqa: F401
from . import podcast       # noqa: F401
from . import ytdlp         # noqa: F401

from .kick import KickExtractor
from .twitch import TwitchExtractor
from .rumble import RumbleExtractor
from .soundcloud import SoundCloudExtractor
from .reddit import RedditExtractor
from .audius import AudiusExtractor
from .podcast import PodcastRSSExtractor
from .ytdlp import YtDlpExtractor

__all__ = [
    "Extractor",
    "KickExtractor",
    "TwitchExtractor",
    "RumbleExtractor",
    "SoundCloudExtractor",
    "RedditExtractor",
    "AudiusExtractor",
    "PodcastRSSExtractor",
    "YtDlpExtractor",
]

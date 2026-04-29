"""Background QThreads — detection, subtitles, encoding, scenes."""

# Sentinel string that every worker emits on cooperative cancellation and
# every controller slot compares against. Keep as a plain literal so tests
# that assert the exact message continue to match across releases.
WORKER_CANCELLED_MSG = "Cancelled."

from .detect_worker import DetectWorker
from .encode_worker import EncodeWorker
from .scene_worker import SceneWorker
from .subtitle_worker import SubtitleWorker

__all__ = [
    "DetectWorker",
    "EncodeWorker",
    "SceneWorker",
    "SubtitleWorker",
    "WORKER_CANCELLED_MSG",
]

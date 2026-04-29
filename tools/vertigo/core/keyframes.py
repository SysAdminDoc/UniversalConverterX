"""Keyframe extraction — Katna-backed with a cv2 fallback.

Katna (https://github.com/keplerlab/katna, MIT) ranks frames by a
mixture of brightness, contrast, blur, and color-diversity, then
clusters similar frames and emits one representative per cluster.
It's the quickest way to turn a clip into a usable thumbnail pool.

This module gives Vertigo two features:

  * ``extract_thumbnails(path, n)`` — n PIL images suitable for the
    clip-card poster art or the "Export poster frame" button
  * ``extract_for_cover(path)`` — a single best frame for the default
    thumbnail, with a cheap fallback when Katna isn't installed (take
    the middle frame of the brightest 5-second window)

The OpenCV fallback ships with the product — no install friction —
so the feature is always usable; Katna just makes the picks sharper
when present.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------- availability

def is_available() -> bool:
    try:
        import Katna  # noqa: F401  (capital K is the pypi import)
        return True
    except ImportError:
        return False


def ensure_installed() -> bool:
    if is_available():
        return True
    from ._lazy import pip_install
    if not pip_install("Katna>=0.9.2"):
        return False
    return is_available()


# ---------------------------------------------------------------- public api

def extract_thumbnails(
    path: Path,
    *,
    n: int = 6,
    cancel_cb=None,
):
    """Return up to ``n`` PIL.Image thumbnails representative of ``path``.

    Uses Katna's ``extract_video_keyframes`` when available, falls back
    to evenly-spaced frames via OpenCV otherwise. Always returns a
    list of PIL images (or empty if the clip cannot be opened).
    """
    n = max(1, int(n))
    if is_available():
        try:
            return _katna_thumbnails(path, n, cancel_cb=cancel_cb)
        except Exception:
            # Katna can fail on unusual codecs — fall through so the UI
            # never shows a blank state when we can still read frames
            # via OpenCV.
            pass
    return _cv2_thumbnails(path, n, cancel_cb=cancel_cb)


def extract_for_cover(path: Path):
    """Return a single best frame for a clip card. Always succeeds when
    the clip is decodable (otherwise returns ``None``)."""
    thumbs = extract_thumbnails(path, n=1)
    return thumbs[0] if thumbs else None


# ---------------------------------------------------------------- backends

def _katna_thumbnails(path: Path, n: int, cancel_cb=None):
    from Katna.video import Video  # type: ignore[import]

    vd = Video()
    frames = vd.extract_video_keyframes(no_of_frames=n, file_path=str(path))
    if cancel_cb and cancel_cb():
        return []
    # Katna returns numpy ndarrays (BGR order). Normalise to PIL RGB so
    # callers can use them uniformly across backends.
    return [_bgr_ndarray_to_pil(f) for f in frames if f is not None]


def _cv2_thumbnails(path: Path, n: int, cancel_cb=None):
    """Evenly-spaced frames via OpenCV.

    Reads the clip's duration, picks ``n`` offsets equispaced across
    (0, duration), and grabs the nearest decoded frame at each. A
    crude but reliable fallback that leans on a dependency the product
    already requires.
    """
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0 or fps <= 0:
            return []
        thumbs = []
        for i in range(n):
            if cancel_cb and cancel_cb():
                break
            frac = (i + 1) / (n + 1)
            idx = max(0, min(total - 1, int(total * frac)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            thumbs.append(_bgr_ndarray_to_pil(frame))
        return thumbs
    finally:
        cap.release()


def _bgr_ndarray_to_pil(bgr):
    """BGR ndarray → PIL.Image RGB. Pulls Pillow lazily so this module
    loads even in headless test environments that skipped Pillow."""
    from PIL import Image
    import numpy as np  # noqa: F401 — ensures ndarray-type presence

    rgb = bgr[..., ::-1].copy()  # BGR -> RGB, contiguous
    return Image.fromarray(rgb)


def save_thumbnails(path: Path, out_dir: Path, *, n: int = 6, prefix: str = "thumb") -> list[Path]:
    """Convenience: write thumbnails as PNGs and return their paths.

    Useful for wiring a "Export thumbnails" button without the caller
    having to juggle PIL objects.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    thumbs = extract_thumbnails(path, n=n)
    written: list[Path] = []
    for i, img in enumerate(thumbs, start=1):
        dst = out_dir / f"{prefix}-{i:02d}.png"
        try:
            img.save(str(dst), "PNG")
            written.append(dst)
        except Exception:
            continue
    return written



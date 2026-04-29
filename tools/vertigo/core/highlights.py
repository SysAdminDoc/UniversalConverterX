"""Video-highlight scoring — Lighthouse-driven or fallback heuristic.

Lighthouse (https://github.com/line/lighthouse, Apache-2.0) wraps 7
moment-retrieval / highlight-detection models (Moment-DETR, QD-DETR,
CG-DETR, TR-DETR, …) behind a single ``inference()`` call. Given a
video and an optional natural-language query it returns ranked
``(start, end, score)`` spans — the visual equivalent of Vertigo's
audio-only ``hook_score``.

This module exposes a single public function, ``score_spans(path,
query=None)``, that returns the top-N highlight candidates. When
Lighthouse isn't installed, the fallback ranks segments by Vertigo's
existing ``hook_score`` audio heuristic applied to a sliding window —
so the UI can always show "segments worth clipping" for the user to
pick from, with a degraded-but-usable quality when the heavy model
weights haven't been downloaded.

Licensing: Apache-2.0. The underlying model weights each carry their
own licence; check the Lighthouse README before commercial shipping.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WINDOW_SEC = 3.0
DEFAULT_TOP_N = 5


@dataclass(frozen=True)
class Highlight:
    start: float
    end: float
    score: float   # 0..1
    source: str    # "lighthouse" | "fallback"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


# ---------------------------------------------------------------- availability

def is_available() -> bool:
    try:
        import lighthouse  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_installed() -> bool:
    if is_available():
        return True
    # Lighthouse pulls a sizeable torch + transformers graph; we don't
    # auto-install it silently because the first run fetches ~1 GB of
    # model weights. Callers should route the user through a "download
    # highlight model?" confirmation before invoking this.
    from ._lazy import pip_install
    if not pip_install("lighthouse-ml>=0.4"):
        return False
    return is_available()


# ---------------------------------------------------------------- public api

def score_spans(
    path: Path,
    *,
    query: str | None = None,
    window_sec: float = DEFAULT_WINDOW_SEC,
    top_n: int = DEFAULT_TOP_N,
    cancel_cb=None,
) -> list[Highlight]:
    """Return the top-N candidate highlight windows for ``path``.

    ``query`` is optional — when present and Lighthouse is available, it
    steers moment retrieval toward the text description. Without
    Lighthouse we ignore the query and fall back to audio energy.
    """
    if is_available():
        try:
            return _score_with_lighthouse(
                path, query=query, window_sec=window_sec, top_n=top_n,
                cancel_cb=cancel_cb,
            )
        except Exception:
            # Any runtime failure in Lighthouse (missing weights, CUDA
            # mismatch, etc.) shouldn't stop the user — fall through to
            # the cheap heuristic.
            pass
    return _score_with_fallback(
        path, window_sec=window_sec, top_n=top_n, cancel_cb=cancel_cb
    )


# ---------------------------------------------------------------- lighthouse path

def _score_with_lighthouse(
    path: Path,
    *,
    query: str | None,
    window_sec: float,
    top_n: int,
    cancel_cb=None,
) -> list[Highlight]:
    import lighthouse

    # Lighthouse exposes inference functions that differ across versions;
    # we probe for the two most common shapes.
    runner = None
    for name in ("highlight_inference", "inference", "run"):
        runner = getattr(lighthouse, name, None)
        if callable(runner):
            break
    if runner is None:
        raise RuntimeError(
            "Lighthouse is installed but exposes no known inference entry "
            "point. Upgrade with `pip install -U lighthouse-ml`."
        )

    if cancel_cb and cancel_cb():
        return []

    # The result shape we accept: list[dict(start, end, score)] or
    # list[tuple(start, end, score)]. Anything else we normalise.
    raw = runner(str(path), query=query) if query else runner(str(path))
    spans: list[Highlight] = []
    for item in raw or []:
        try:
            if isinstance(item, dict):
                s, e, sc = float(item["start"]), float(item["end"]), float(item.get("score", 0.0))
            else:
                s, e, sc = float(item[0]), float(item[1]), float(item[2])
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        spans.append(Highlight(s, e, max(0.0, min(1.0, sc)), source="lighthouse"))

    spans.sort(key=lambda h: h.score, reverse=True)
    return spans[: max(1, int(top_n))]


# ---------------------------------------------------------------- fallback path

def _score_with_fallback(
    path: Path,
    *,
    window_sec: float,
    top_n: int,
    cancel_cb=None,
) -> list[Highlight]:
    """Sliding-window ``hook_score`` over the full clip.

    This gives the UI *something* to rank against when the heavy
    Lighthouse graph isn't present. We walk the timeline in strides of
    ``window_sec`` and score each window — exactly the contract
    Lighthouse honours, minus the visual-semantic signal.
    """
    from .hook_score import score_hook
    from .probe import probe

    try:
        info = probe(path)
    except Exception:
        return []
    if info.duration <= 0:
        return []

    # Each window is evaluated by running hook_score starting from that
    # offset. hook_score's ffmpeg pipeline already supports an -ss style
    # trim via ``window_sec``; but we need offset too, so we copy the
    # logic here with an -ss prefix for correctness.
    import shutil
    bin_path = shutil.which("ffmpeg")
    if not bin_path:
        return []

    spans: list[Highlight] = []
    t = 0.0
    stride = max(0.5, window_sec / 2.0)
    while t + 0.5 < info.duration:
        if cancel_cb and cancel_cb():
            break
        window_end = min(info.duration, t + window_sec)
        score = _hook_score_offset(
            path, start=t, window_sec=window_end - t, ffmpeg=bin_path
        )
        if score > 0:
            spans.append(
                Highlight(
                    start=t,
                    end=window_end,
                    score=min(1.0, score / 100.0),
                    source="fallback",
                )
            )
        t += stride

    spans.sort(key=lambda h: h.score, reverse=True)
    # Deduplicate overlapping high-score windows — pick the highest
    # scoring non-overlapping candidates, greedy.
    picked: list[Highlight] = []
    for cand in spans:
        if any(_overlaps(cand, p) for p in picked):
            continue
        picked.append(cand)
        if len(picked) >= max(1, int(top_n)):
            break
    # Return in timeline order for nicer UI.
    picked.sort(key=lambda h: h.start)
    return picked


def _hook_score_offset(path: Path, *, start: float, window_sec: float, ffmpeg: str) -> float:
    """Like hook_score, but starting at a given offset. Runs ffmpeg once
    per window; the whole function is <200 ms on a typical clip."""
    import struct
    cmd = [
        ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error",
        "-ss", f"{max(0.0, start):.3f}",
        "-t", f"{max(0.1, window_sec):.3f}",
        "-i", str(path),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=10, creationflags=_no_window_flags(),
        )
    except Exception:
        return 0.0
    raw = proc.stdout or b""
    n = len(raw) // 2
    if n == 0:
        return 0.0
    samples = list(struct.unpack(f"<{n}h", raw[: n * 2]))
    from .hook_score import _analyse
    vf, mve = _analyse(samples, sample_rate=16000)
    return 60.0 * vf + 40.0 * mve


def _overlaps(a: Highlight, b: Highlight) -> bool:
    return not (a.end <= b.start or b.end <= a.start)


# ---------------------------------------------------------------- helpers


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0

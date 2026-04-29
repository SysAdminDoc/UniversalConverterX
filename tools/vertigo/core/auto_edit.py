"""auto-editor interop — motion/audio-driven cut planning.

auto-editor (https://github.com/WyattBlue/auto-editor, Unlicense) is a
battle-tested CLI that trims boring sections out of a video using
audio-threshold, motion-detection, or a combination. We call it as a
subprocess with ``--export json`` and ingest the timeline it emits, so
the heavy lifting stays in an isolated, well-tested tool.

Vertigo consumes the result as a list of ``(start, end)`` spans — the
same shape the scene detector produces — so the rest of the pipeline
(trim timeline ticks, smart-track's scene-clamp logic, dry-run planner)
picks it up unchanged.

This module has no Python dependency: auto-editor is invoked as an
external executable. ``is_available()`` probes the PATH; if missing,
the UI should offer the install hint.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_AUDIO_THRESHOLD = 0.04      # RMS value auto-editor's 'audio' edit uses
DEFAULT_MARGIN_SEC = 0.20           # keep-edges padding around each cut


@dataclass(frozen=True)
class KeepSpan:
    start: float  # seconds, in the original timeline
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


# ---------------------------------------------------------------- availability

def is_available() -> bool:
    return shutil.which("auto-editor") is not None


def install_hint() -> str:
    return "pip install auto-editor  # or: pipx install auto-editor"


# ---------------------------------------------------------------- public api

def plan_cuts(
    path: Path,
    *,
    threshold: float = DEFAULT_AUDIO_THRESHOLD,
    margin_sec: float = DEFAULT_MARGIN_SEC,
    edit_method: str = "audio",
    cancel_cb=None,
) -> list[KeepSpan]:
    """Run auto-editor and return the keep-spans it proposes.

    ``edit_method`` is passed straight through to ``--edit``:
      * ``"audio"`` — silence threshold
      * ``"motion"`` — visual motion threshold
      * ``"(audio or motion)"`` — either triggers a keep

    Raises ``RuntimeError`` if auto-editor isn't on PATH.
    """
    if not is_available():
        raise RuntimeError(
            f"auto-editor was not found on PATH. Install with:\n"
            f"    {install_hint()}"
        )
    if not Path(path).exists():
        raise FileNotFoundError(path)
    if cancel_cb and cancel_cb():
        return []

    # auto-editor's JSON export writes a timeline file beside the input.
    # We write it into a tempdir so we don't pollute the user's folder
    # even if auto-editor crashes mid-run.
    with tempfile.TemporaryDirectory() as tmp:
        out_json = Path(tmp) / "timeline.json"
        cmd = [
            shutil.which("auto-editor") or "auto-editor",
            str(path),
            "--edit", _edit_arg(edit_method, threshold),
            "--margin", f"{max(0.0, margin_sec)}sec",
            "--export", "json",
            "--output", str(out_json),
            "--quiet",
            "--no-open",
        ]
        try:
            rc = subprocess.call(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=_no_window_flags(),
            )
        except Exception as e:
            raise RuntimeError(f"auto-editor failed to start: {e}") from e
        if rc != 0:
            raise RuntimeError(f"auto-editor exited {rc}")
        if cancel_cb and cancel_cb():
            return []
        if not out_json.exists():
            return []
        try:
            data = json.loads(out_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return _parse_timeline(data)


# ---------------------------------------------------------------- helpers

def _edit_arg(method: str, threshold: float) -> str:
    """Translate a ``(method, threshold)`` pair into auto-editor's
    ``--edit`` argument syntax.

    The tool uses a tiny expression DSL; we restrict ourselves to the
    three shapes Vertigo's UI will offer.
    """
    m = method.strip().lower()
    t = max(0.0, min(1.0, float(threshold)))
    if m == "audio":
        return f"audio:threshold={t:.4f}"
    if m == "motion":
        return f"motion:threshold={t:.4f}"
    # Fall through: accept a raw expression the caller built itself.
    return method


def _parse_timeline(data: dict) -> list[KeepSpan]:
    """Pick out the keep-spans regardless of auto-editor version.

    Recent releases emit {"chunks": [[start_frame, end_frame, speed], ...]}
    where speed 1.0 = keep, 99999 (or >1) = cut. Older ones use
    {"timeline": [{"start": s, "end": e, "speed": 1}]} form. Handle
    both.
    """
    fps = float(data.get("timeline_fps") or data.get("fps") or 30.0)

    chunks = data.get("chunks")
    if isinstance(chunks, list):
        spans: list[KeepSpan] = []
        for c in chunks:
            try:
                start_f, end_f, speed = float(c[0]), float(c[1]), float(c[2])
            except (IndexError, ValueError, TypeError):
                continue
            if speed != 1.0:
                continue
            spans.append(KeepSpan(start_f / fps, end_f / fps))
        return _merge_adjacent(spans)

    timeline = data.get("timeline")
    if isinstance(timeline, list):
        spans = []
        for t in timeline:
            if not isinstance(t, dict):
                continue
            speed = t.get("speed", 1.0)
            if speed and speed != 1.0:
                continue
            try:
                spans.append(KeepSpan(float(t["start"]), float(t["end"])))
            except (KeyError, ValueError, TypeError):
                continue
        return _merge_adjacent(spans)

    return []


def _merge_adjacent(spans: list[KeepSpan], gap_tol: float = 0.01) -> list[KeepSpan]:
    """Combine spans whose edges meet within ``gap_tol`` seconds."""
    if not spans:
        return []
    merged = [spans[0]]
    for s in spans[1:]:
        last = merged[-1]
        if s.start - last.end <= gap_tol:
            merged[-1] = KeepSpan(last.start, max(last.end, s.end))
        else:
            merged.append(s)
    return merged


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0

"""Resume sidecar — persists in-flight download state for crash-safe resume.

A sidecar file named `.streamkeep_resume.json` is written into each output
directory at download start, refreshed after each segment completes or on
cancel, and deleted when the download finishes cleanly. At app startup the
Download tab scans known output directories for orphan sidecars and shows
a "Resume N interrupted download(s)" banner.

Token-bearing playlist URLs (Kick m3u8 master, Twitch signed playback, etc.)
typically expire in ~24h. Before actually restarting a download the UI should
re-run the extractor for the source_url to refresh playlist_url — if the
segment list has shifted shape we fall back to a full restart.
"""

import json
import math
import os
from dataclasses import asdict
from datetime import datetime

from .models import ResumeState

SIDECAR_NAME = ".streamkeep_resume.json"
MAX_SIDECAR_BYTES = 1024 * 1024
MAX_SEGMENTS = 100000


def _sidecar_path(output_dir):
    return os.path.join(output_dir, SIDECAR_NAME)


def _normalize_output_dir(output_dir):
    path = str(output_dir or "").strip()
    if not path:
        return ""
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def _sanitize_timestamp(value):
    return str(value or "")[:64]


def _sanitize_text(value, max_len=2048):
    # Use explicit None check so falsy-but-valid values like 0 are preserved
    return str("" if value is None else value)[:max_len]


def _sanitize_segments(value):
    if not isinstance(value, (list, tuple)):
        return []
    cleaned = []
    for seg in value[:MAX_SEGMENTS]:
        if not isinstance(seg, (list, tuple)) or len(seg) < 4:
            continue
        try:
            idx = int(seg[0])
            start = float(seg[2])
            duration = float(seg[3])
        except (TypeError, ValueError):
            continue
        if idx < 0 or not math.isfinite(start) or not math.isfinite(duration) or duration < 0:
            continue
        cleaned.append([idx, _sanitize_text(seg[1], max_len=256), start, duration])
    return cleaned


def _sanitize_completed(value):
    if not isinstance(value, (list, tuple, set)):
        return []
    cleaned = []
    seen = set()
    for item in value:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx in seen:
            continue
        seen.add(idx)
        cleaned.append(idx)
    return cleaned


def _sanitize_resume_payload(data, output_dir):
    if not isinstance(data, dict):
        return None
    try:
        version = int(data.get("version", 1) or 1)
    except (TypeError, ValueError):
        version = 1
    return {
        "version": version,
        "created_at": _sanitize_timestamp(data.get("created_at", "")),
        "updated_at": _sanitize_timestamp(data.get("updated_at", "")),
        "source_url": _sanitize_text(data.get("source_url", "")),
        "platform": _sanitize_text(data.get("platform", ""), max_len=128),
        "title": _sanitize_text(data.get("title", ""), max_len=512),
        "channel": _sanitize_text(data.get("channel", ""), max_len=256),
        "playlist_url": _sanitize_text(data.get("playlist_url", "")),
        "format_type": _sanitize_text(data.get("format_type", "hls"), max_len=32) or "hls",
        "audio_url": _sanitize_text(data.get("audio_url", "")),
        "ytdlp_source": _sanitize_text(data.get("ytdlp_source", "")),
        "ytdlp_format": _sanitize_text(data.get("ytdlp_format", ""), max_len=128),
        "quality_name": _sanitize_text(data.get("quality_name", ""), max_len=128),
        "segments": _sanitize_segments(data.get("segments", [])),
        "completed": _sanitize_completed(data.get("completed", [])),
        "output_dir": _normalize_output_dir(output_dir),
        "expected_outfile": _sanitize_text(data.get("expected_outfile", "")),
    }


def save_resume_state(state):
    """Atomically write a ResumeState to its output directory.

    Silent on error — a resume sidecar is a nice-to-have, never a correctness
    requirement, so disk-full / permission errors must not block the actual
    download."""
    if not state or not state.output_dir:
        return
    state.output_dir = _normalize_output_dir(state.output_dir)
    try:
        os.makedirs(state.output_dir, exist_ok=True)
    except OSError:
        return
    state.updated_at = datetime.now().isoformat(timespec="seconds")
    if not state.created_at:
        state.created_at = state.updated_at
    try:
        payload = json.dumps(asdict(state), indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return
    path = _sidecar_path(state.output_dir)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            try:
                f.flush()
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def load_resume_state(output_dir):
    """Read a sidecar. Returns a ResumeState or None."""
    if not output_dir:
        return None
    normalized_output_dir = _normalize_output_dir(output_dir)
    path = _sidecar_path(normalized_output_dir)
    if not os.path.exists(path):
        return None
    try:
        if os.path.getsize(path) > MAX_SIDECAR_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    clean = _sanitize_resume_payload(data, normalized_output_dir)
    if clean is None:
        return None
    try:
        return ResumeState(**clean)
    except (TypeError, ValueError):
        return None


def clear_resume_state(output_dir):
    """Delete the sidecar. Safe to call if none exists."""
    if not output_dir:
        return
    path = _sidecar_path(_normalize_output_dir(output_dir))
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def scan_for_orphan_sidecars(roots):
    """Find resume sidecars under any of the given root directories whose
    download looks interrupted (no matching all-done marker, fewer completed
    segments than the original segment list, etc.).

    Returns a list of ResumeState, freshest first. Used by the startup banner.
    """
    found = []
    seen = set()
    for root in roots or []:
        if not root or not os.path.isdir(root):
            continue
        # Walk at most 3 levels deep — per-VOD output folders live directly
        # inside the user's Videos/Capture root; scanning a whole disk is a
        # non-goal and would be slow on big archives.
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
            if depth > 3:
                dirnames[:] = []
                continue
            if SIDECAR_NAME not in filenames:
                continue
            real = os.path.realpath(dirpath)
            if real in seen:
                continue
            seen.add(real)
            state = load_resume_state(dirpath)
            if state is None:
                continue
            total = len(state.segments or [])
            done = len(state.completed or [])
            if total and done >= total:
                # All segments completed but sidecar wasn't cleaned up —
                # finalize probably crashed. Treat as already-done and
                # ignore rather than offering to "resume" a completed job.
                continue
            found.append(state)
    found.sort(key=lambda s: s.updated_at or "", reverse=True)
    return found


def merge_completed(state, seg_idx):
    """Record a completed segment index. Idempotent.

    Uses a cached set for O(1) membership checks instead of the O(n) list
    scan that made long VODs (10k+ segments) quadratic.
    """
    if not state:
        return
    idx = int(seg_idx)
    # Lazily build a set cache from the authoritative list
    if not hasattr(state, "_completed_set") or state._completed_set is None:
        state._completed_set = set(state.completed)
    if idx in state._completed_set:
        return
    state._completed_set.add(idx)
    state.completed.append(idx)


def remaining_segments(state):
    """Return (seg_idx, label, start, duration) tuples that still need work.

    Tolerates segments stored either as lists (JSON round-trip) or tuples.
    """
    if not state:
        return []
    done = set(int(x) for x in (state.completed or []))
    out = []
    for seg in (state.segments or []):
        if not seg or len(seg) < 4:
            continue
        try:
            idx = int(seg[0])
            start = float(seg[2])
            duration = float(seg[3])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(duration) or duration < 0:
            continue
        if idx in done:
            continue
        out.append((idx, str(seg[1]), start, duration))
    return out

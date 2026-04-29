"""AI Auto-Highlight Generator — composite scoring from chat + audio + scenes (F57).

Combines chat spike detection (F8), audio peak analysis, and scene change
frequency into a per-window "interestingness" score.  Returns the top N
highlight moments as ``(start, end, score, reason)`` tuples.

All analysis is local — no cloud APIs needed.
"""

import array
import json
import math
import os

from PyQt6.QtCore import QThread, pyqtSignal


# ── Signal analysis helpers ─────────────────────────────────────────

def _load_chat_spikes(recording_dir, bucket_secs=30):
    """Load chat density per *bucket_secs* window from chat.jsonl."""
    jsonl = os.path.join(recording_dir, "chat.jsonl")
    if not os.path.isfile(jsonl):
        return {}
    from ..chat.spike_detect import detect_spikes
    spikes = detect_spikes(jsonl, bucket_secs=bucket_secs, min_std_dev=1.0)
    return {int(s["time"] // bucket_secs): s["score"] for s in spikes}


def _load_audio_peaks(recording_dir, bucket_secs=30):
    """Load audio peak energy per window from .waveform.bin cache."""
    # Find the waveform cache
    waveform = ""
    for fn in os.listdir(recording_dir):
        if fn.endswith(".waveform.bin"):
            waveform = os.path.join(recording_dir, fn)
            break
    if not waveform or not os.path.isfile(waveform):
        return {}
    try:
        with open(waveform, "rb") as f:
            data = f.read()
        # Waveform is int16 peaks, 8000 samples/sec — use array for fast bulk decode
        sample_rate = 8000
        samples_per_bucket = sample_rate * bucket_secs
        samples = array.array("h")
        samples.frombytes(data[:len(data) - len(data) % 2])
        n_samples = len(samples)
        peaks = {}
        for bucket_idx in range(n_samples // samples_per_bucket):
            lo = bucket_idx * samples_per_bucket
            hi = lo + samples_per_bucket
            chunk = samples[lo:hi]
            total = sum(v * v for v in chunk)
            rms = math.sqrt(total / max(len(chunk), 1))
            peaks[bucket_idx] = rms
        # Normalize to 0-1
        max_rms = max(peaks.values()) if peaks else 1.0
        if max_rms > 0:
            peaks = {k: v / max_rms for k, v in peaks.items()}
        return peaks
    except (OSError, ValueError):
        return {}


def _load_scene_changes(recording_dir, bucket_secs=30):
    """Load scene change density per window from storyboard cache."""
    storyboard = os.path.join(recording_dir, ".storyboard.json")
    if not os.path.isfile(storyboard):
        return {}
    try:
        with open(storyboard, "r", encoding="utf-8") as f:
            scenes = json.load(f)
        if not isinstance(scenes, list):
            return {}
        density = {}
        for sc in scenes:
            t = float(sc.get("time", sc.get("start", 0)))
            bucket = int(t // bucket_secs)
            density[bucket] = density.get(bucket, 0) + 1
        # Normalize
        max_d = max(density.values()) if density else 1
        if max_d > 0:
            density = {k: v / max_d for k, v in density.items()}
        return density
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


# ── Highlight detection ─────────────────────────────────────────────

def detect_highlights(recording_dir, *, top_n=10, bucket_secs=30,
                      min_gap_secs=60, weights=None):
    """Detect highlight moments in a recording.

    Returns a list of ``(start_secs, end_secs, score, reason)`` tuples,
    sorted by score descending, limited to *top_n*.

    *weights* is a dict ``{"chat": float, "audio": float, "scene": float}``
    defaulting to equal weights (1.0 each).
    """
    if weights is None:
        weights = {"chat": 1.0, "audio": 1.0, "scene": 1.0}

    chat = _load_chat_spikes(recording_dir, bucket_secs)
    audio = _load_audio_peaks(recording_dir, bucket_secs)
    scenes = _load_scene_changes(recording_dir, bucket_secs)

    # Determine the number of buckets from available data
    all_keys = set(chat) | set(audio) | set(scenes)
    if not all_keys:
        return []

    # Score each bucket
    scored = []
    for bucket_idx in sorted(all_keys):
        c = chat.get(bucket_idx, 0) * weights.get("chat", 1.0)
        a = audio.get(bucket_idx, 0) * weights.get("audio", 1.0)
        s = scenes.get(bucket_idx, 0) * weights.get("scene", 1.0)
        total = c + a + s

        # Build reason string
        reasons = []
        if c > 0.3:
            reasons.append("chat spike")
        if a > 0.5:
            reasons.append("audio peak")
        if s > 0.3:
            reasons.append("scene change")

        start = bucket_idx * bucket_secs
        end = start + bucket_secs
        scored.append((start, end, total, ", ".join(reasons) or "composite"))

    # Sort by score, highest first
    scored.sort(key=lambda x: -x[2])

    # Select top N with minimum gap
    selected = []
    for start, end, score, reason in scored:
        if score <= 0:
            continue
        # Check gap
        too_close = False
        for sel_start, sel_end, _, _ in selected:
            if abs(start - sel_start) < min_gap_secs:
                too_close = True
                break
        if too_close:
            continue
        selected.append((start, end, score, reason))
        if len(selected) >= top_n:
            break

    return selected


# ── Worker thread ───────────────────────────────────────────────────

class HighlightWorker(QThread):
    """Run highlight detection in the background."""

    done = pyqtSignal(list)   # list of (start, end, score, reason)
    log = pyqtSignal(str)

    def __init__(self, recording_dir, top_n=10, weights=None):
        super().__init__()
        self._dir = recording_dir
        self._top_n = top_n
        self._weights = weights

    def run(self):
        try:
            results = detect_highlights(
                self._dir,
                top_n=self._top_n,
                weights=self._weights,
            )
            self.log.emit(f"[HIGHLIGHT] Found {len(results)} highlight(s)")
            self.done.emit(results)
        except Exception as e:
            self.log.emit(f"[HIGHLIGHT] Error: {e}")
            self.done.emit([])

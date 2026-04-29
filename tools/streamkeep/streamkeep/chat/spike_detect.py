"""Chat-spike detection — bucket messages by time window and find density
spikes for clip-marker suggestions (F8).

Reads a `.chat.jsonl` file (one JSON object per line with at least a
``ts`` field) and returns a list of spike dicts::

    [{"time": 3600.0, "count": 42, "score": 3.1}, ...]

where *score* is the number of standard deviations above the rolling
average for that window.
"""

import json
import math
import os


def detect_spikes(jsonl_path, *, bucket_secs=10, min_std_dev=2.0,
                  rolling_window=30, start_ts=None):
    """Scan *jsonl_path* and return spike timestamps.

    Parameters
    ----------
    jsonl_path : str
        Path to a ``chat.jsonl`` file.
    bucket_secs : int
        Width of each time bucket in seconds (default 10).
    min_std_dev : float
        A bucket must be this many standard deviations above the rolling
        average to count as a spike (default 2.0).
    rolling_window : int
        Number of preceding buckets used for the rolling average (default 30).
    start_ts : float or None
        If set, message timestamps are made relative by subtracting this
        value.  If *None*, the first message's ``ts`` is used.

    Returns
    -------
    list[dict]
        Each dict has ``time`` (seconds), ``count`` (messages in that
        bucket), and ``score`` (std-dev above rolling mean).
    """
    if not jsonl_path or not os.path.isfile(jsonl_path):
        return []

    # Pass 1: collect timestamps
    timestamps = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ts = obj.get("ts")
                    if ts is not None:
                        timestamps.append(float(ts))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        return []

    if len(timestamps) < 2:
        return []

    timestamps.sort()
    if start_ts is None:
        start_ts = timestamps[0]

    # Pass 2: bucket into fixed-width windows
    max_rel = timestamps[-1] - start_ts
    n_buckets = max(1, int(math.ceil(max_rel / bucket_secs)) + 1)
    buckets = [0] * n_buckets
    for ts in timestamps:
        rel = ts - start_ts
        idx = int(rel / bucket_secs)
        if 0 <= idx < n_buckets:
            buckets[idx] += 1

    # Pass 3: rolling stats → spike detection
    spikes = []
    ring = []
    for i, count in enumerate(buckets):
        if ring:
            mean = sum(ring) / len(ring)
            variance = sum((x - mean) ** 2 for x in ring) / len(ring)
            std = math.sqrt(variance) if variance > 0 else 0
            if std > 0:
                score = (count - mean) / std
            else:
                score = 0.0 if count <= mean else float(min_std_dev + 1)
            if score >= min_std_dev and count > 1:
                spikes.append({
                    "time": i * bucket_secs,
                    "count": count,
                    "score": round(score, 2),
                })
        ring.append(count)
        if len(ring) > rolling_window:
            ring.pop(0)

    return spikes

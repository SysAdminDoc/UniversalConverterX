"""SponsorBlock integration — skip sponsors/intros/outros on YouTube (F58).

Uses the SHA256-prefix privacy API so the SponsorBlock server never knows
which exact video is being queried.

Categories: sponsor, selfpromo, interaction, intro, outro, preview,
music_offtopic, filler.

Usage::

    segments = fetch_segments("dQw4w9WgXcQ")
    # [{"start": 0.0, "end": 15.2, "category": "intro"}, ...]
"""

import hashlib
import json
import re
import urllib.parse

from ..http import curl

API_BASE = "https://sponsor.ajay.app"
CATEGORIES = [
    "sponsor", "selfpromo", "interaction", "intro", "outro",
    "preview", "music_offtopic", "filler",
]


def extract_video_id(url):
    """Extract YouTube video ID from a URL, or '' if not YouTube."""
    patterns = [
        r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    return ""


def fetch_segments(video_id, categories=None):
    """Fetch SponsorBlock segments for a YouTube video.

    Uses the SHA256 prefix lookup (first 4 hex chars) for privacy.

    Returns a list of dicts: ``[{start, end, category, uuid}, ...]``
    sorted by start time. Returns ``[]`` on error or no segments.
    """
    if not video_id or len(video_id) != 11:
        return []

    if categories is None:
        categories = list(CATEGORIES)

    # SHA256 prefix lookup — server returns all videos with matching prefix
    sha = hashlib.sha256(video_id.encode("utf-8")).hexdigest()
    prefix = sha[:4]
    cats_param = urllib.parse.quote(json.dumps(categories))

    url = f"{API_BASE}/api/skipSegments/{prefix}?categories={cats_param}"
    body = curl(url, timeout=10)
    if not body:
        return []

    try:
        results = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(results, list):
        return []

    # Find matching video in results
    segments = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        if entry.get("videoID") != video_id:
            continue
        for seg in entry.get("segments", []):
            if not isinstance(seg, dict):
                continue
            segment = seg.get("segment", [])
            if len(segment) < 2:
                continue
            segments.append({
                "start": float(segment[0]),
                "end": float(segment[1]),
                "category": seg.get("category", "sponsor"),
                "uuid": seg.get("UUID", ""),
            })

    segments.sort(key=lambda s: s["start"])
    return segments


def total_sponsor_time(segments):
    """Return total seconds of sponsor/skip content."""
    return sum(s["end"] - s["start"] for s in segments)


def segments_to_chapters(segments, total_duration=0):
    """Convert SponsorBlock segments to chapter markers.

    Returns a list of ``{title, start, end}`` dicts suitable for
    metadata chapter writing.
    """
    chapters = []
    for seg in segments:
        chapters.append({
            "title": f"[{seg['category']}]",
            "start": seg["start"],
            "end": seg["end"],
        })
    return chapters

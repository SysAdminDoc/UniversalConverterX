"""Clip Share via Local Web Gallery — serve shared recordings over HTTP (F69).

Extends the local web server with:
  GET /gallery       — browsable grid of shared recordings
  GET /share/{id}    — HTML page with embedded video player
  GET /media/{id}    — video file streaming with HTTP Range support

Only recordings explicitly marked as ``shared=True`` are accessible.
Share IDs are UUID-based for unguessable URLs.
"""

import mimetypes
import os
import uuid

from .theme import CAT

# In-memory registry of shared recordings.
# Populated from HistoryEntry objects that have shared=True + share_id.
_shared = {}   # share_id -> {"path": str, "title": str, "channel": str, "media": str}


def register_shared(share_id, path, title="", channel="", media=""):
    """Register a recording for sharing."""
    _shared[share_id] = {
        "path": path,
        "title": title,
        "channel": channel,
        "media": media,
    }


def unregister_shared(share_id):
    _shared.pop(share_id, None)


def generate_share_id():
    return uuid.uuid4().hex[:12]


def get_shared(share_id):
    return _shared.get(share_id)


def all_shared():
    return dict(_shared)


# ── HTML rendering ──────────────────────────────────────────────────

def render_gallery_html(base_url=""):
    """Render the gallery page HTML."""
    items_html = ""
    if not _shared:
        items_html = '<p style="color:#aaa;text-align:center;">No shared recordings.</p>'
    else:
        for sid, info in _shared.items():
            title = info.get("title", "Untitled")[:50]
            channel = info.get("channel", "")
            items_html += (
                f'<div class="card">'
                f'<a href="{base_url}/share/{sid}">'
                f'<div class="title">{_esc(title)}</div>'
                f'<div class="channel">{_esc(channel)}</div>'
                f'</a></div>\n'
            )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>StreamKeep Gallery</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body {{ background: {CAT['base']}; color: {CAT['text']}; font-family: system-ui; margin: 0; padding: 20px; }}
h1 {{ color: {CAT['blue']}; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }}
.card {{ background: {CAT['surface0']}; border-radius: 8px; padding: 16px; }}
.card a {{ color: {CAT['text']}; text-decoration: none; }}
.card:hover {{ background: {CAT['surface1']}; }}
.title {{ font-weight: bold; margin-bottom: 4px; }}
.channel {{ color: {CAT['subtext0']}; font-size: 0.9em; }}
</style></head><body>
<h1>StreamKeep Gallery</h1>
<div class="grid">{items_html}</div>
</body></html>"""


def render_share_html(share_id, base_url=""):
    """Render the player page for a shared recording."""
    info = _shared.get(share_id)
    if not info:
        return "<h1>Not Found</h1>"
    title = info.get("title", "Untitled")
    channel = info.get("channel", "")
    media_type = mimetypes.guess_type(info.get("media", ""))[0] or "video/mp4"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{_esc(title)} - StreamKeep</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body {{ background: {CAT['base']}; color: {CAT['text']}; font-family: system-ui; margin: 0; padding: 20px; }}
h1 {{ color: {CAT['blue']}; font-size: 1.4em; }}
h2 {{ color: {CAT['subtext0']}; font-size: 1em; font-weight: normal; }}
video {{ width: 100%; max-width: 1200px; border-radius: 8px; background: #000; }}
a {{ color: {CAT['blue']}; }}
</style></head><body>
<a href="{base_url}/gallery">&larr; Gallery</a>
<h1>{_esc(title)}</h1>
<h2>{_esc(channel)}</h2>
<video controls preload="metadata">
<source src="{base_url}/media/{share_id}" type="{_esc(media_type)}">
</video>
</body></html>"""


def find_media_file(recording_dir):
    """Find the first media file in a recording directory."""
    if not recording_dir or not os.path.isdir(recording_dir):
        return ""
    for fn in sorted(os.listdir(recording_dir)):
        if fn.lower().endswith((".mp4", ".mkv", ".webm", ".ts")) and not fn.startswith("."):
            return os.path.join(recording_dir, fn)
    return ""


def serve_media_range(media_path, range_header=None):
    """Serve a media file with HTTP Range support.

    Returns ``(data, status_code, headers_dict)`` or ``(None, 404, {})``.
    """
    if not media_path or not os.path.isfile(media_path):
        return None, 404, {}

    file_size = os.path.getsize(media_path)
    content_type = mimetypes.guess_type(media_path)[0] or "video/mp4"

    if range_header and range_header.startswith("bytes="):
        try:
            ranges = range_header[6:].split("-", 1)
            if not ranges or len(ranges) != 2:
                raise ValueError("invalid range")
            if not ranges[0]:
                suffix_len = int(ranges[1])
                if suffix_len <= 0:
                    raise ValueError("invalid suffix range")
                start = max(file_size - suffix_len, 0)
                end = file_size - 1
            else:
                start = int(ranges[0])
                end = int(ranges[1]) if ranges[1] else file_size - 1
            if start < 0 or start >= file_size or end < start:
                raise ValueError("range out of bounds")
        except (TypeError, ValueError):
            return None, 416, {
                "Content-Range": f"bytes */{file_size}",
                "Accept-Ranges": "bytes",
            }

        end = min(end, file_size - 1)
        length = end - start + 1

        with open(media_path, "rb") as f:
            f.seek(start)
            data = f.read(length)

        headers = {
            "Content-Type": content_type,
            "Content-Length": str(length),
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
        }
        return data, 206, headers
    else:
        # Cap non-Range reads to prevent OOM on multi-GB files. Clients that
        # need the full file should use Range requests (browsers/players do).
        _MAX_FULL_READ = 256 * 1024 * 1024  # 256 MB
        read_size = min(file_size, _MAX_FULL_READ)
        with open(media_path, "rb") as f:
            data = f.read(read_size)
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(read_size),
            "Accept-Ranges": "bytes",
        }
        if file_size > _MAX_FULL_READ:
            # Signal partial content so clients know to use Range requests
            headers["Content-Range"] = f"bytes 0-{read_size - 1}/{file_size}"
            return data, 206, headers
        return data, 200, headers


def _esc(s):
    """Basic HTML escape."""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

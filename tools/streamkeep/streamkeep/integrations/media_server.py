"""Media Server Auto-Import — copy/hardlink recordings into Plex/Jellyfin/Emby
library folders and trigger a library scan.

Naming template: ``{Channel}/Season {Year}/{Channel} - S{Year}E{Seq} - {Title}.ext``

Config keys (under ``config["media_server"]``):
    enabled, server_type (plex|jellyfin|emby), url, token, library_path, library_id
"""

import os
import shutil
import threading
import urllib.request
from datetime import datetime

from ..metadata import MetadataSaver

# Supported server types
SERVER_TYPES = ["plex", "jellyfin", "emby"]


def _safe_name(s, max_len=80):
    """Sanitize a string for use as a filesystem name."""
    if not s:
        return "Unknown"
    bad = '<>:"/\\|?*'
    out = "".join(c if c not in bad else "_" for c in s.strip())
    out = out[:max_len].rstrip(". ")  # trailing dots/spaces invalid on Windows
    return out or "Unknown"


def _next_episode(season_dir):
    """Scan *season_dir* and return the next episode number."""
    import re
    if not os.path.isdir(season_dir):
        return 1
    existing = []
    for f in os.listdir(season_dir):
        # Match S<digits>E<digits> pattern — avoids false hits on channel
        # names that contain the letter E (e.g. "Echo").
        m = re.search(r"S\d+E(\d+)", f, re.IGNORECASE)
        if m:
            existing.append(int(m.group(1)))
    return max(existing, default=0) + 1


def _find_video(out_dir):
    """Return the path to the largest video file in *out_dir*."""
    best, best_size = None, 0
    if not os.path.isdir(out_dir):
        return None
    for f in os.listdir(out_dir):
        if f.lower().endswith((".mp4", ".mkv", ".ts", ".webm", ".flv")):
            fp = os.path.join(out_dir, f)
            sz = os.path.getsize(fp)
            if sz > best_size:
                best, best_size = fp, sz
    return best


def import_to_media_server(config, out_dir, info=None, log_fn=None):
    """Copy/hardlink the recording into the media server library and trigger
    a library scan.  Runs in a daemon thread so the UI never blocks.

    *config* is the ``media_server`` sub-dict from the app config.
    """
    if not config or not config.get("enabled"):
        return
    library_path = (config.get("library_path") or "").strip()
    if not library_path or not os.path.isdir(library_path):
        if log_fn:
            log_fn("[MEDIA-SERVER] Library path does not exist — skipping import.")
        return

    def _run():
        try:
            _do_import(config, out_dir, info, log_fn)
        except Exception as e:
            if log_fn:
                log_fn(f"[MEDIA-SERVER] Import error: {e}")

    threading.Thread(target=_run, daemon=True).start()


def _do_import(config, out_dir, info, log_fn):
    video = _find_video(out_dir)
    if not video:
        if log_fn:
            log_fn("[MEDIA-SERVER] No video file found in output directory.")
        return

    library_path = config["library_path"].strip()
    channel = _safe_name(getattr(info, "channel", "") if info else "")
    title = _safe_name(
        (getattr(info, "title", "") if info else "") or os.path.basename(out_dir)
    )
    year = datetime.now().strftime("%Y")
    try:
        if info and getattr(info, "start_time", ""):
            year = info.start_time[:4]
    except Exception:
        pass

    # Build library structure: Channel/Season YYYY/
    season_dir = os.path.join(library_path, channel, f"Season {year}")
    os.makedirs(season_dir, exist_ok=True)

    ep_num = _next_episode(season_dir)
    ext = os.path.splitext(video)[1]
    dest_name = f"{channel} - S{year}E{ep_num:02d} - {title}{ext}"
    dest_path = os.path.join(season_dir, dest_name)

    # Try hardlink first, fall back to copy
    try:
        os.link(video, dest_path)
        if log_fn:
            log_fn(f"[MEDIA-SERVER] Hardlinked → {dest_path}")
    except OSError:
        shutil.copy2(video, dest_path)
        if log_fn:
            log_fn(f"[MEDIA-SERVER] Copied → {dest_path}")

    # Write NFO sidecar next to the imported file
    if info:
        nfo_base = os.path.splitext(dest_name)[0]
        MetadataSaver.write_nfo(season_dir, info, file_base=nfo_base)

    # Trigger library scan
    server_type = (config.get("server_type") or "").lower()
    url = (config.get("url") or "").strip().rstrip("/")
    token = (config.get("token") or "").strip()

    if not url or not token:
        if log_fn:
            log_fn("[MEDIA-SERVER] No server URL/token — skipping library scan.")
        return

    try:
        if server_type == "plex":
            _scan_plex(url, token, config.get("library_id", ""), log_fn)
        elif server_type in ("jellyfin", "emby"):
            _scan_jellyfin(url, token, log_fn)
        else:
            if log_fn:
                log_fn(f"[MEDIA-SERVER] Unknown server type: {server_type}")
    except Exception as e:
        if log_fn:
            log_fn(f"[MEDIA-SERVER] Scan trigger failed: {e}")


def _scan_plex(url, token, library_id, log_fn):
    """Plex: GET /library/sections/{id}/refresh?X-Plex-Token={token}"""
    section = library_id or "1"
    scan_url = f"{url}/library/sections/{section}/refresh?X-Plex-Token={token}"
    req = urllib.request.Request(scan_url, method="GET")
    with urllib.request.urlopen(req, timeout=15):
        pass
    if log_fn:
        log_fn(f"[MEDIA-SERVER] Plex library scan triggered (section {section}).")


def _scan_jellyfin(url, token, log_fn):
    """Jellyfin/Emby: POST /Library/Refresh with API key header."""
    scan_url = f"{url}/Library/Refresh"
    req = urllib.request.Request(scan_url, method="POST")
    req.add_header("X-Emby-Token", token)
    with urllib.request.urlopen(req, timeout=15):
        pass
    if log_fn:
        log_fn("[MEDIA-SERVER] Jellyfin/Emby library refresh triggered.")

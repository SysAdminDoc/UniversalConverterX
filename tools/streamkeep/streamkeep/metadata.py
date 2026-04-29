"""Metadata saver — writes metadata.json, chapters, NFO, and thumbnails."""

import json
import os
import subprocess
from datetime import datetime

from .paths import _CREATE_NO_WINDOW


class MetadataSaver:
    @staticmethod
    def save(output_dir, stream_info, vod_info=None):
        """Save metadata.json alongside downloads."""
        if stream_info is None or not output_dir:
            return
        if not os.path.isdir(output_dir):
            return
        meta = {
            "platform": getattr(stream_info, "platform", "") or "",
            "title": (
                getattr(stream_info, "title", "")
                or (getattr(vod_info, "title", "") if vod_info else "")
            ),
            "url": getattr(stream_info, "url", "") or "",
            "duration": getattr(stream_info, "duration_str", "") or "",
            "total_secs": getattr(stream_info, "total_secs", 0) or 0,
            "start_time": getattr(stream_info, "start_time", "") or "",
            "is_live": bool(getattr(stream_info, "is_live", False)),
            "qualities": [
                {
                    "name": q.name, "resolution": q.resolution,
                    "bandwidth": q.bandwidth, "format": q.format_type,
                }
                for q in (stream_info.qualities or [])
            ],
            "downloaded_at": datetime.now().isoformat(),
        }
        if vod_info:
            meta["vod_date"] = vod_info.date
            meta["vod_channel"] = vod_info.channel
            meta["vod_viewers"] = vod_info.viewers
        try:
            p = os.path.join(output_dir, "metadata.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        if stream_info.thumbnail_url:
            try:
                thumb_path = os.path.join(output_dir, "thumbnail.jpg")
                subprocess.run(
                    ["curl", "-s", "-L", "-o", thumb_path, stream_info.thumbnail_url],
                    timeout=15, creationflags=_CREATE_NO_WINDOW,
                )
            except Exception:
                pass

    @staticmethod
    def write_chapters(output_dir, stream_info, file_base=""):
        """Write {file_base}.chapters.txt and .chapters.json files if the
        stream has chapter metadata."""
        if not stream_info or not output_dir:
            return False
        if not os.path.isdir(output_dir):
            return False
        chapters = getattr(stream_info, "chapters", None) or []
        if not chapters:
            return False
        base = os.path.basename(file_base) if file_base else "chapters"
        try:
            txt_path = os.path.join(output_dir, f"{base}.chapters.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                for ch in chapters:
                    secs = int(ch.get("start", 0) or 0)
                    hh = secs // 3600
                    mm = (secs % 3600) // 60
                    ss = secs % 60
                    ts = f"{hh:02d}:{mm:02d}:{ss:02d}"
                    f.write(f"{ts} {ch.get('title', 'Chapter')}\n")
        except Exception:
            pass
        try:
            json_path = os.path.join(output_dir, f"{base}.chapters.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"chapters": chapters}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return True

    @staticmethod
    def _xml_escape(s):
        if not s:
            return ""
        return (
            str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    @staticmethod
    def write_nfo(output_dir, stream_info, vod_info=None, file_base=""):
        """Write a Kodi/Jellyfin/Plex-compatible .nfo file using the
        <movie> schema (most widely supported)."""
        if stream_info is None or not output_dir:
            return
        if not os.path.isdir(output_dir):
            return
        title = (
            (stream_info.title or (vod_info.title if vod_info else "")).strip()
            or "Untitled"
        )
        platform = stream_info.platform or ""
        channel = ""
        if vod_info and vod_info.channel:
            channel = vod_info.channel
        elif stream_info.channel:
            channel = stream_info.channel
        date_str = ""
        try:
            if stream_info.start_time:
                date_str = stream_info.start_time.split("T")[0]
            elif vod_info and vod_info.date:
                date_str = vod_info.date.split("T")[0].split(" ")[0]
        except Exception:
            pass
        runtime_min = int((stream_info.total_secs or 0) // 60)

        esc = MetadataSaver._xml_escape
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<movie>',
            f'  <title>{esc(title)}</title>',
            f'  <originaltitle>{esc(title)}</originaltitle>',
            f'  <studio>{esc(platform)}</studio>',
        ]
        if channel:
            lines.append(f'  <director>{esc(channel)}</director>')
            lines.append(f'  <credits>{esc(channel)}</credits>')
        if date_str:
            lines.append(f'  <premiered>{esc(date_str)}</premiered>')
            lines.append(f'  <year>{esc(date_str[:4])}</year>')
        if runtime_min > 0:
            lines.append(f'  <runtime>{runtime_min}</runtime>')
        if stream_info.url:
            lines.append(f'  <trailer>{esc(stream_info.url)}</trailer>')
        if stream_info.thumbnail_url:
            lines.append(f'  <thumb>{esc(stream_info.thumbnail_url)}</thumb>')
        lines.append(
            f'  <plot>Archived from {esc(platform)} on '
            f'{esc(datetime.now().strftime("%Y-%m-%d"))}.</plot>'
        )
        lines.append('</movie>')

        try:
            safe_base = os.path.basename(file_base) if file_base else ""
            nfo_path = os.path.join(
                output_dir,
                (safe_base + ".nfo") if safe_base else "movie.nfo",
            )
            with open(nfo_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass

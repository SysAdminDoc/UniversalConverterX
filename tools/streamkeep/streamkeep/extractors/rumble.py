"""Rumble — embed API extractor (HLS + direct MP4)."""

import re

from .. import CURL_UA
from ..http import curl, curl_json
from ..hls import parse_hls_duration
from ..models import QualityInfo, StreamInfo
from ..utils import fmt_duration
from .base import Extractor


class RumbleExtractor(Extractor):
    NAME = "Rumble"
    ICON = "R"
    COLOR = "green"
    URL_PATTERNS = [
        re.compile(r'(?:https?://)?(?:www\.)?rumble\.com/(v[a-z0-9]+)'),
        re.compile(r'(?:https?://)?(?:www\.)?rumble\.com/embed/(v[a-z0-9]+)'),
    ]

    def extract_channel_id(self, url):
        m = re.match(
            r'(?:https?://)?(?:www\.)?rumble\.com/(?:embed/)?(v[a-z0-9]+)',
            url.strip(),
        )
        return m.group(1) if m else None

    def _get_embed_id(self, url, log_fn=None):
        m = re.match(
            r'(?:https?://)?(?:www\.)?rumble\.com/embed/(v[a-z0-9]+)',
            url.strip(),
        )
        if m:
            return m.group(1)

        self._log(log_fn, "Fetching Rumble page to find embed ID...")
        body = curl(url, headers={"User-Agent": CURL_UA, "Accept": "text/html"})
        if body:
            m = re.search(r'embed/(v[a-z0-9]+)', body)
            if m:
                return m.group(1)
        return None

    def _extract_channel_from_data(self, data):
        if not isinstance(data, dict):
            return ""
        direct_keys = (
            "channel", "channel_name", "channel_slug", "author",
            "author_name", "creator", "creator_name", "username",
            "user_name", "owner", "publisher", "publisher_name",
        )
        for key in direct_keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for subkey in ("slug", "username", "name", "title"):
                    subval = value.get(subkey)
                    if isinstance(subval, str) and subval.strip():
                        return subval.strip()
        for key in ("author", "channel", "user", "owner", "publisher"):
            value = data.get(key)
            if isinstance(value, dict):
                for subkey in ("slug", "username", "name", "title"):
                    subval = value.get(subkey)
                    if isinstance(subval, str) and subval.strip():
                        return subval.strip()
        return ""

    def resolve(self, url, log_fn=None):
        embed_id = self._get_embed_id(url, log_fn)
        if not embed_id:
            self._log(log_fn, "Could not find Rumble embed ID")
            return None

        self._log(log_fn, f"Fetching Rumble video data: {embed_id}")
        data = curl_json(
            f"https://rumble.com/embedJS/u3/?request=video&ver=2&v={embed_id}",
            headers={"User-Agent": CURL_UA, "Referer": "https://rumble.com/"},
        )
        if not data or not isinstance(data, dict):
            self._log(log_fn, "Failed to fetch Rumble video data")
            return None

        info = StreamInfo(
            platform="Rumble",
            url=url,
            title=data.get("title", ""),
            channel=self._extract_channel_from_data(data),
            is_live=data.get("duration", 0) == 0,
        )

        ua = data.get("ua", {})

        hls = ua.get("hls", {})
        for key, val in hls.items():
            if isinstance(val, dict) and "url" in val:
                meta = val.get("meta", {})
                h = meta.get("h", "?")
                w = meta.get("w", "?")
                info.qualities.append(QualityInfo(
                    name=f"hls_{key}",
                    url=val["url"],
                    resolution=f"{w}x{h}" if w != "?" else "auto",
                    bandwidth=meta.get("bitrate", 0),
                    format_type="hls",
                ))

        mp4 = ua.get("mp4", {})
        for key, val in mp4.items():
            if isinstance(val, dict) and "url" in val:
                meta = val.get("meta", {})
                h = meta.get("h", "?")
                w = meta.get("w", "?")
                info.qualities.append(QualityInfo(
                    name=f"mp4_{key}",
                    url=val["url"],
                    resolution=f"{w}x{h}",
                    bandwidth=meta.get("bitrate", 0),
                    format_type="mp4",
                ))

        dur = data.get("duration", 0)
        if dur:
            info.total_secs = dur
            info.duration_str = fmt_duration(dur)
        elif info.is_live:
            info.duration_str = "Live"

        if info.total_secs == 0 and info.qualities:
            for q in info.qualities:
                if q.format_type == "hls":
                    sub = curl(q.url)
                    if sub:
                        ts, _, sc = parse_hls_duration(sub)
                        if ts > 0:
                            info.total_secs = ts
                            info.duration_str = fmt_duration(ts)
                            info.segment_count = sc
                            break

        self._log(
            log_fn,
            f"Rumble: {info.title}, {len(info.qualities)} qualities, "
            f"{info.duration_str}",
        )
        return info

"""Audius — public discovery API extractor."""

import re
import urllib.parse

from ..http import curl_json
from ..models import QualityInfo, StreamInfo
from ..utils import fmt_duration
from .base import Extractor


class AudiusExtractor(Extractor):
    NAME = "Audius"
    ICON = "A"
    COLOR = "mauve"
    URL_PATTERNS = [
        re.compile(
            r'(?:https?://)?(?:www\.)?audius\.co/'
            r'([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)'
        ),
    ]
    API_BASE = "https://discoveryprovider.audius.co/v1"

    def extract_channel_id(self, url):
        m = re.match(
            r'(?:https?://)?(?:www\.)?audius\.co/([a-zA-Z0-9_-]+)',
            url.strip(),
        )
        return m.group(1) if m else None

    def resolve(self, url, log_fn=None):
        self._log(log_fn, f"Resolving Audius: {url}")

        data = curl_json(
            f"{self.API_BASE}/resolve?url={urllib.parse.quote(url, safe='')}"
            f"&app_name=StreamKeep"
        )
        if not data or not data.get("data"):
            self._log(log_fn, "Failed to resolve Audius URL")
            return None

        track = data["data"]
        track_id = track.get("id", "")

        info = StreamInfo(
            platform="Audius",
            url=url,
            title=track.get("title", ""),
            channel=self.extract_channel_id(url) or "",
            total_secs=track.get("duration", 0),
        )
        info.duration_str = fmt_duration(info.total_secs)

        stream_url = f"{self.API_BASE}/tracks/{track_id}/stream?app_name=StreamKeep"
        info.qualities.append(QualityInfo(
            name="stream (mp3)", url=stream_url,
            resolution="audio", bandwidth=0, format_type="mp4",
        ))

        self._log(log_fn, f"Audius: {info.title}, {info.duration_str}")
        return info

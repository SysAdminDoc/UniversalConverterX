"""SoundCloud — API v2 resolve + progressive/HLS transcodings."""

import re
import urllib.parse

from .. import CURL_UA
from ..http import curl, curl_json
from ..models import QualityInfo, StreamInfo
from ..utils import fmt_duration
from .base import Extractor


class SoundCloudExtractor(Extractor):
    NAME = "SoundCloud"
    ICON = "S"
    COLOR = "peach"
    URL_PATTERNS = [
        re.compile(
            r'(?:https?://)?(?:www\.)?soundcloud\.com/'
            r'([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)'
        ),
        re.compile(
            r'(?:https?://)?(?:www\.)?soundcloud\.com/'
            r'([a-zA-Z0-9_-]+)/sets/([a-zA-Z0-9_-]+)'
        ),
    ]
    _client_id = None

    def extract_channel_id(self, url):
        m = re.match(
            r'(?:https?://)?(?:www\.)?soundcloud\.com/([a-zA-Z0-9_-]+)',
            url.strip(),
        )
        return m.group(1) if m else None

    def _get_client_id(self, log_fn=None):
        if self._client_id:
            return self._client_id
        self._log(log_fn, "Extracting SoundCloud client_id...")
        page = curl("https://soundcloud.com/", headers={"User-Agent": CURL_UA})
        if not page:
            return None
        scripts = re.findall(
            r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', page
        )
        for js_url in scripts:
            js = curl(js_url)
            if js:
                m = re.search(r'client_id:"([a-zA-Z0-9]+)"', js)
                if m:
                    SoundCloudExtractor._client_id = m.group(1)
                    self._log(log_fn, f"Got client_id: {self._client_id[:8]}...")
                    return self._client_id
        return None

    def resolve(self, url, log_fn=None):
        cid = self._get_client_id(log_fn)
        if not cid:
            self._log(log_fn, "Could not get SoundCloud client_id")
            return None

        self._log(log_fn, f"Resolving SoundCloud: {url}")
        data = curl_json(
            f"https://api-v2.soundcloud.com/resolve?"
            f"url={urllib.parse.quote(url, safe='')}&client_id={cid}"
        )
        if not data or not isinstance(data, dict):
            # client_id may have gone stale — clear and retry once
            if SoundCloudExtractor._client_id:
                self._log(log_fn, "SoundCloud resolve failed — refreshing client_id...")
                SoundCloudExtractor._client_id = None
                cid = self._get_client_id(log_fn)
                if cid:
                    data = curl_json(
                        f"https://api-v2.soundcloud.com/resolve?"
                        f"url={urllib.parse.quote(url, safe='')}&client_id={cid}"
                    )
            if not data or not isinstance(data, dict):
                self._log(log_fn, "Failed to resolve SoundCloud URL")
                return None

        info = StreamInfo(
            platform="SoundCloud",
            url=url,
            title=data.get("title", ""),
            channel=self.extract_channel_id(url) or "",
            total_secs=data.get("duration", 0) / 1000,
        )
        info.duration_str = fmt_duration(info.total_secs)

        for t in data.get("media", {}).get("transcodings", []):
            fmt = t.get("format", {})
            protocol = fmt.get("protocol", "")
            mime = fmt.get("mime_type", "")
            trans_url = t.get("url", "")
            if not trans_url:
                continue
            stream_data = curl_json(f"{trans_url}?client_id={cid}")
            if stream_data and stream_data.get("url"):
                ft = "mp4" if protocol == "progressive" else "hls"
                name = f"{protocol} ({mime.split('/')[-1].split(';')[0]})"
                info.qualities.append(QualityInfo(
                    name=name, url=stream_data["url"],
                    resolution="audio", bandwidth=0, format_type=ft,
                ))

        self._log(
            log_fn,
            f"SoundCloud: {info.title}, {len(info.qualities)} formats, "
            f"{info.duration_str}",
        )
        return info

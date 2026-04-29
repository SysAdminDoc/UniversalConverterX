"""Reddit — JSON API extractor (DASH + fallback MP4)."""

import re
import urllib.parse

from ..http import curl, curl_json
from ..models import QualityInfo, StreamInfo
from ..utils import fmt_duration
from .base import Extractor


class RedditExtractor(Extractor):
    NAME = "Reddit"
    ICON = "R"
    COLOR = "peach"
    URL_PATTERNS = [
        re.compile(
            r'(?:https?://)?(?:www\.|old\.)?reddit\.com/r/\w+/comments/\w+'
        ),
        re.compile(r'(?:https?://)?v\.redd\.it/\w+'),
    ]

    def extract_channel_id(self, url):
        m = re.search(r'/r/(\w+)(?:/comments/\w+)?', url)
        if m:
            return m.group(1)
        m = re.search(r'v\.redd\.it/(\w+)', url)
        return m.group(1) if m else None

    def resolve(self, url, log_fn=None):
        self._log(log_fn, f"Resolving Reddit: {url}")

        # Normalize v.redd.it URLs — follow redirect to find the post
        if "v.redd.it" in url:
            body = curl(url, headers={"User-Agent": "StreamKeep/2.0"})
            if body:
                m = re.search(r'reddit\.com/r/\w+/comments/\w+', body)
                if m:
                    url = "https://www." + m.group(0)

        parsed = urllib.parse.urlsplit(url.rstrip("/"))
        json_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path + ".json",
             parsed.query, parsed.fragment)
        )
        data = curl_json(json_url, headers={"User-Agent": "StreamKeep/2.0"})
        if not data or not isinstance(data, list) or len(data) == 0:
            self._log(log_fn, "Failed to fetch Reddit post data")
            return None

        post = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
        if not post.get("is_video"):
            self._log(log_fn, "Reddit post is not a video")
            return None

        rv = post.get("secure_media", {}).get("reddit_video", {})
        if not rv:
            rv = post.get("media", {}).get("reddit_video", {})
        if not rv:
            return None

        info = StreamInfo(
            platform="Reddit",
            url=url,
            title=post.get("title", ""),
            channel=str(post.get("subreddit") or self.extract_channel_id(url) or ""),
            total_secs=rv.get("duration", 0),
        )
        info.duration_str = fmt_duration(info.total_secs)

        fallback = rv.get("fallback_url", "")
        if fallback:
            h = rv.get("height", "?")
            info.qualities.append(QualityInfo(
                name=f"fallback ({h}p)", url=fallback,
                resolution=f"?x{h}", bandwidth=0, format_type="mp4",
            ))

        dash = rv.get("dash_url", "")
        if dash:
            info.qualities.insert(0, QualityInfo(
                name="DASH (best)", url=dash,
                resolution=f"{rv.get('width', '?')}x{rv.get('height', '?')}",
                bandwidth=rv.get("bitrate_kbps", 0) * 1000,
                format_type="hls",  # ffmpeg handles DASH via -i
            ))

        self._log(
            log_fn,
            f"Reddit: {info.title[:50]}, {len(info.qualities)} formats, "
            f"{info.duration_str}",
        )
        return info

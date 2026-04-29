"""Twitch — GraphQL + usher.ttvnw.net HLS extractor."""

import json
import re
import urllib.parse

from ..http import curl, curl_post_json
from ..hls import parse_hls_duration
from ..models import QualityInfo, StreamInfo, VODInfo
from ..utils import fmt_duration
from .base import Extractor


class TwitchExtractor(Extractor):
    NAME = "Twitch"
    ICON = "T"
    COLOR = "mauve"
    URL_PATTERNS = [
        re.compile(r'(?:https?://)?(?:www\.)?twitch\.tv/videos/(\d+)'),
        re.compile(r'(?:https?://)?(?:www\.)?twitch\.tv/([a-zA-Z0-9_]+)/?$'),
    ]
    CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
    # Set by Settings tab — download chat replay alongside Twitch VODs.
    # Named _enabled to avoid shadowing the download_chat() method below.
    download_chat_enabled = False

    def _gql(self, query, log_fn=None):
        return curl_post_json(
            "https://gql.twitch.tv/gql",
            {"query": query},
            headers={"Client-Id": self.CLIENT_ID},
        )

    def extract_channel_id(self, url):
        url = url.strip()
        m = re.match(r'(?:https?://)?(?:www\.)?twitch\.tv/videos/(\d+)', url)
        if m:
            return f"vod_{m.group(1)}"
        m = re.match(r'(?:https?://)?(?:www\.)?twitch\.tv/([a-zA-Z0-9_]+)/?$', url)
        if m:
            return m.group(1)
        return None

    def supports_vod_listing(self):
        return True

    def supports_live_check(self):
        return True

    def check_live(self, url):
        login = self.extract_channel_id(url)
        if not login or login.startswith("vod_"):
            return None
        data = self._gql(f'{{ user(login: "{login}") {{ stream {{ id type }} }} }}')
        if data and data.get("data", {}).get("user", {}).get("stream"):
            return data["data"]["user"]["stream"]["type"] == "live"
        return False

    def list_vods(self, url, log_fn=None, cursor=None):
        login = self.extract_channel_id(url)
        if not login or login.startswith("vod_"):
            return [], None
        page_label = f" (after {cursor[:12]}…)" if cursor else ""
        self._log(log_fn, f"Fetching VODs for Twitch channel: {login}{page_label}")

        after_clause = f', after: "{cursor}"' if cursor else ""
        data = self._gql(
            f'{{ user(login: "{login}") {{ displayName '
            f'videos(first: 20, type: ARCHIVE, sort: TIME{after_clause}) '
            f'{{ edges {{ node {{ '
            f'id title createdAt lengthSeconds viewCount '
            f'previewThumbnailURL(width: 320, height: 180) '
            f'}} cursor }} pageInfo {{ hasNextPage }} }} }} }}'
        )
        if not data:
            self._log(log_fn, "GraphQL request failed")
            return [], None

        user = data.get("data") or {}
        user = user.get("user") or {}
        videos = user.get("videos") or {}
        edges = videos.get("edges") or []
        page_info = videos.get("pageInfo") or {}
        vods = []
        last_cursor = None
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            vod_id = node.get("id")
            if not vod_id:
                continue  # Can't resolve later without an ID — skip.
            secs = node.get("lengthSeconds") or 0
            try:
                secs = int(secs)
            except (TypeError, ValueError):
                secs = 0
            vods.append(VODInfo(
                title=node.get("title") or "Untitled",
                date=node.get("createdAt") or "",
                source=vod_id,  # VOD ID — resolved to m3u8 in resolve()
                is_live=False,
                viewers=node.get("viewCount") or 0,
                duration=fmt_duration(secs) if secs else "",
                duration_ms=secs * 1000,
                platform="Twitch",
                channel=login,
            ))
            last_cursor = edge.get("cursor")
        self._log(log_fn, f"Found {len(vods)} VOD(s)")
        next_cursor = last_cursor if page_info.get("hasNextPage") else None
        return vods, next_cursor

    def _get_access_token(self, vod_id=None, channel=None, log_fn=None):
        """Get playback access token for a VOD or live channel."""
        if vod_id:
            data = self._gql(
                f'{{ videoPlaybackAccessToken(id: "{vod_id}", params: '
                f'{{ platform: "web", playerBackend: "mediaplayer", playerType: "site" }}) '
                f'{{ value signature }} }}'
            )
            token_key = "videoPlaybackAccessToken"
        else:
            data = self._gql(
                f'{{ streamPlaybackAccessToken(channelName: "{channel}", params: '
                f'{{ platform: "web", playerBackend: "mediaplayer", playerType: "site" }}) '
                f'{{ value signature }} }}'
            )
            token_key = "streamPlaybackAccessToken"

        if not data:
            return None, None
        tok = data.get("data", {}).get(token_key, {})
        return tok.get("value"), tok.get("signature")

    def resolve(self, url, log_fn=None):
        url = url.strip()
        m = re.match(r'(?:https?://)?(?:www\.)?twitch\.tv/videos/(\d+)', url)
        if m:
            return self._resolve_vod(m.group(1), log_fn)

        login = self.extract_channel_id(url)
        if not login:
            return None

        if self.check_live(url):
            return self._resolve_live(login, log_fn)

        return None  # UI handles VOD listing

    def _resolve_vod(self, vod_id, log_fn=None, channel=""):
        self._log(log_fn, f"Resolving Twitch VOD: {vod_id}")
        token, sig = self._get_access_token(vod_id=vod_id, log_fn=log_fn)
        if not token or not sig:
            self._log(log_fn, "Failed to get access token")
            return None

        m3u8_url = (
            f"https://usher.ttvnw.net/vod/{vod_id}.m3u8"
            f"?client_id={self.CLIENT_ID}"
            f"&token={urllib.parse.quote(token)}"
            f"&sig={sig}"
            f"&allow_source=true&allow_audio_only=true"
        )
        body = curl(m3u8_url)
        if not body or not body.startswith("#EXTM3U"):
            self._log(log_fn, "Failed to fetch m3u8 playlist")
            return None

        info = StreamInfo(platform="Twitch", url=m3u8_url, is_master=True, channel=channel or "")
        info.qualities = []
        res, bw, name = "?", 0, "unknown"
        for line in body.splitlines():
            if line.startswith("#EXT-X-MEDIA"):
                nm = re.search(r'NAME="([^"]+)"', line)
                if nm:
                    name = nm.group(1)
            elif line.startswith("#EXT-X-STREAM-INF"):
                attrs = line.split(":", 1)[1]
                res_m = re.search(r'RESOLUTION=(\d+x\d+)', attrs)
                bw_m = re.search(r'BANDWIDTH=(\d+)', attrs)
                res = res_m.group(1) if res_m else "?"
                bw = int(bw_m.group(1)) if bw_m else 0
            elif line.startswith("http"):
                info.qualities.append(QualityInfo(
                    name=name, url=line.strip(), resolution=res,
                    bandwidth=bw, format_type="hls",
                ))

        if info.qualities:
            sub = curl(info.qualities[0].url)
            if sub:
                info.total_secs, info.start_time, info.segment_count = parse_hls_duration(sub)
                # Twitch VODs may not have TOTAL-SECS — sum EXTINF instead.
                # Tolerate malformed tokens (e.g. live-edit playlists mid-rewrite).
                if info.total_secs == 0:
                    total = 0.0
                    for mm in re.finditer(r'#EXTINF:([\d.]+)', sub):
                        try:
                            total += float(mm.group(1))
                        except ValueError:
                            continue
                    info.total_secs = total

        info.duration_str = fmt_duration(info.total_secs)
        self._log(log_fn, f"Twitch VOD: {info.duration_str}, {len(info.qualities)} qualities")
        return info

    def _resolve_live(self, login, log_fn=None):
        self._log(log_fn, f"Resolving Twitch live stream: {login}")
        token, sig = self._get_access_token(channel=login, log_fn=log_fn)
        if not token or not sig:
            self._log(log_fn, "Failed to get access token")
            return None

        m3u8_url = (
            f"https://usher.ttvnw.net/api/channel/hls/{login}.m3u8"
            f"?client_id={self.CLIENT_ID}"
            f"&token={urllib.parse.quote(token)}"
            f"&sig={sig}"
            f"&allow_source=true&allow_audio_only=true&fast_bread=true"
        )
        body = curl(m3u8_url)
        if not body or not body.startswith("#EXTM3U"):
            self._log(log_fn, "Failed to fetch live m3u8")
            return None

        info = StreamInfo(
            platform="Twitch",
            url=m3u8_url,
            is_master=True,
            is_live=True,
            channel=login,
        )
        info.qualities = []
        res, bw, name = "?", 0, "unknown"
        for line in body.splitlines():
            if line.startswith("#EXT-X-MEDIA"):
                nm = re.search(r'NAME="([^"]+)"', line)
                if nm:
                    name = nm.group(1)
            elif line.startswith("#EXT-X-STREAM-INF"):
                attrs = line.split(":", 1)[1]
                res_m = re.search(r'RESOLUTION=(\d+x\d+)', attrs)
                bw_m = re.search(r'BANDWIDTH=(\d+)', attrs)
                res = res_m.group(1) if res_m else "?"
                bw = int(bw_m.group(1)) if bw_m else 0
            elif line.startswith("http"):
                info.qualities.append(QualityInfo(
                    name=name, url=line.strip(), resolution=res,
                    bandwidth=bw, format_type="hls",
                ))

        info.duration_str = "Live"
        self._log(log_fn, f"Twitch live: {len(info.qualities)} qualities")
        return info

    def download_chat(self, vod_id, output_path, log_fn=None, progress_cb=None):
        """Download the full chat replay for a VOD. Writes two files:
          {output_path}.chat.json  — raw GraphQL comment data
          {output_path}.chat.txt   — human-readable [MM:SS] user: message
        Returns (total_comments, None) on success or (0, error_str)."""
        headers = {"Client-Id": self.CLIENT_ID, "Content-Type": "application/json"}
        all_comments = []
        cursor = None
        offset_seconds = 0
        page = 0
        QUERY_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"

        while True:
            if cursor:
                variables = {"videoID": str(vod_id), "cursor": cursor}
            else:
                variables = {"videoID": str(vod_id), "contentOffsetSeconds": offset_seconds}
            payload = [{
                "operationName": "VideoCommentsByOffsetOrCursor",
                "variables": variables,
                "extensions": {
                    "persistedQuery": {"version": 1, "sha256Hash": QUERY_HASH}
                },
            }]
            data = curl_post_json("https://gql.twitch.tv/gql", payload, headers=headers)
            if not data or not isinstance(data, list) or not data:
                return 0, "Empty response from Twitch"
            video = data[0].get("data", {}).get("video") or {}
            comments = video.get("comments") or {}
            edges = comments.get("edges", [])
            if not edges:
                break
            for e in edges:
                node = e.get("node") or {}
                all_comments.append(node)
            page += 1
            if progress_cb:
                progress_cb(len(all_comments))
            self._log(log_fn, f"  [CHAT] Page {page}: {len(all_comments)} comments so far")
            page_info = comments.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = edges[-1].get("cursor") if edges[-1].get("cursor") else None
            if not cursor:
                last_offset = edges[-1].get("node", {}).get("contentOffsetSeconds", 0)
                if last_offset <= offset_seconds:
                    break
                offset_seconds = last_offset + 1
                cursor = None
            if len(all_comments) > 500000:  # safety cap
                self._log(log_fn, "  [CHAT] Hit 500k cap — stopping")
                break

        try:
            json_path = output_path + ".chat.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"vod_id": vod_id, "comments": all_comments}, f,
                          ensure_ascii=False, indent=2)
        except Exception as e:
            return 0, f"Write JSON failed: {e}"

        try:
            txt_path = output_path + ".chat.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                for node in all_comments:
                    secs = int(node.get("contentOffsetSeconds", 0) or 0)
                    hh = secs // 3600
                    mm = (secs % 3600) // 60
                    ss = secs % 60
                    ts = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
                    user = (node.get("commenter") or {}).get("displayName", "?")
                    fragments = (node.get("message") or {}).get("fragments") or []
                    msg = "".join(fr.get("text", "") for fr in fragments)
                    f.write(f"[{ts}] {user}: {msg}\n")
        except Exception as e:
            self._log(log_fn, f"  [CHAT] Text export failed: {e}")

        return len(all_comments), None

"""Deleted VOD Recovery — reconstruct CDN URLs for expired / deleted Twitch VODs.

Approach:
  1. Scrape TwitchTracker for stream metadata (stream ID + timestamps) given
     a channel name + date range.
  2. Construct CDN URL candidates using known Twitch VOD URL patterns.
  3. Test candidates with HEAD requests to see if segments are still cached.
  4. Return valid M3U8 URLs that can be fed to the normal download pipeline.

CDN URL format (may rotate):
  https://d1m7jfoe9zdc1j.cloudfront.net/{hash}_{channel}_{stream_id}_{timestamp}/
    chunked/index-dvr.m3u8

The hash is SHA1(f"{channel}_{stream_id}_{timestamp}") truncated to 20 chars.
"""

import hashlib
import re
import urllib.request
import urllib.error

from ..models import QualityInfo, StreamInfo


# Known Twitch CDN domains — Twitch rotates these periodically.
CDN_DOMAINS = [
    "https://d1m7jfoe9zdc1j.cloudfront.net",
    "https://d2nvs31859zcd8.cloudfront.net",
    "https://d2aba1wr3818hz.cloudfront.net",
    "https://dqrpb9wgowsf5.cloudfront.net",
    "https://ds0h3roq6wcgc.cloudfront.net",
    "https://dgeft87wbj63p.cloudfront.net",
]

QUALITIES = ["chunked", "720p60", "720p30", "480p30", "360p30", "160p30"]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _compute_hash(channel, stream_id, timestamp):
    """Compute the CDN path hash."""
    body = f"{channel}_{stream_id}_{timestamp}"
    return hashlib.sha1(body.encode()).hexdigest()[:20]


def _head_check(url, timeout=8):
    """Return True if the URL responds with 200 or 206."""
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", _UA)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status in (200, 206)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def _scrape_twitchtracker(channel, year, month, log_fn=None):
    """Scrape TwitchTracker for stream IDs in a given month.

    Returns list of dicts: [{stream_id, timestamp, date_str, title}]
    """
    url = f"https://twitchtracker.com/{channel}/streams/{year}/{month:02d}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        if log_fn:
            log_fn(f"[RECOVER] Failed to fetch TwitchTracker: {e}")
        return []

    streams = []
    # TwitchTracker embeds stream IDs in links like /streams/{stream_id}
    for m in re.finditer(
        r'/streams/(\d{8,})"[^>]*>.*?'
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})',
        html, re.DOTALL,
    ):
        sid = m.group(1)
        date_str = m.group(2).strip()
        streams.append({
            "stream_id": sid,
            "date_str": date_str,
        })

    # Also try sullygnome pattern as fallback
    if not streams:
        for m in re.finditer(r'data-sid="(\d+)".*?data-date="([^"]+)"', html, re.DOTALL):
            streams.append({
                "stream_id": m.group(1),
                "date_str": m.group(2).strip(),
            })

    if log_fn:
        log_fn(f"[RECOVER] Found {len(streams)} stream(s) on TwitchTracker for {channel} ({year}-{month:02d})")
    return streams


def _unix_timestamp_variants(date_str):
    """Generate plausible Unix timestamps from a date string.

    TwitchTracker dates are approximate — we try a range of offsets.
    """
    import datetime
    ts_list = []
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(date_str, fmt).replace(
                tzinfo=datetime.timezone.utc
            )
            base = int(dt.timestamp())
            # Try the exact time and +/- 1 hour in 10-minute increments
            for offset in range(-3600, 3600 + 1, 600):
                ts_list.append(base + offset)
            return ts_list
        except ValueError:
            continue
    return ts_list


def recover_vod(channel, stream_id, timestamp, log_fn=None):
    """Try CDN domains * qualities for a single stream. Returns list of valid M3U8 URLs."""
    channel_lower = channel.lower().strip()
    h = _compute_hash(channel_lower, stream_id, timestamp)
    found = []
    for domain in CDN_DOMAINS:
        for quality in QUALITIES:
            url = (
                f"{domain}/{h}_{channel_lower}_{stream_id}_{timestamp}"
                f"/{quality}/index-dvr.m3u8"
            )
            if _head_check(url):
                if log_fn:
                    log_fn(f"[RECOVER] HIT: {quality} @ {domain}")
                found.append(url)
                break  # Found on this domain, skip lower qualities
    return found


def recover_channel_vods(channel, year, month, log_fn=None, progress_fn=None):
    """Full recovery pipeline: scrape tracker -> brute-force CDN -> return StreamInfo list."""
    streams = _scrape_twitchtracker(channel, year, month, log_fn)
    if not streams:
        return []

    results = []
    total = len(streams)
    for i, s in enumerate(streams):
        if progress_fn:
            progress_fn(int((i / total) * 100), f"Testing stream {s['stream_id']}...")

        timestamps = _unix_timestamp_variants(s.get("date_str", ""))
        for ts in timestamps:
            urls = recover_vod(channel, s["stream_id"], ts, log_fn)
            if urls:
                # Use the highest quality (first hit)
                info = StreamInfo(
                    platform="twitch",
                    channel=channel,
                    title=f"Recovered VOD — {s.get('date_str', 'unknown date')}",
                    url=urls[0],
                    qualities=[
                        QualityInfo(name="recovered", url=u, format_type="hls")
                        for u in urls
                    ],
                )
                results.append(info)
                break  # Found a working timestamp for this stream

    if progress_fn:
        progress_fn(100, f"Done — {len(results)} recoverable VOD(s)")
    return results

"""HLS m3u8 parsing."""

import re
from urllib.parse import urljoin

from .models import QualityInfo


def parse_hls_master(body, base_url):
    """Parse an HLS master playlist into a list of QualityInfo."""
    qualities = []
    res, bw = "?", 0
    # urljoin expects a resource URL, not a directory. If base_url looks
    # like a directory (no trailing file), append a / so relative variants
    # resolve under it instead of replacing the last segment.
    if base_url and not base_url.endswith("/") and "/" in base_url.split("://", 1)[-1]:
        tail = base_url.rsplit("/", 1)[-1]
        if "." not in tail:
            base_url = base_url + "/"
    for line in body.splitlines():
        if line.startswith("#EXT-X-STREAM-INF"):
            attrs = line.split(":", 1)[1]
            res_m = re.search(r'RESOLUTION=(\d+x\d+)', attrs)
            bw_m = re.search(r'BANDWIDTH=(\d+)', attrs)
            res = res_m.group(1) if res_m else "?"
            bw = int(bw_m.group(1)) if bw_m else 0
        elif not line.startswith("#") and line.strip():
            q_url = line.strip()
            if not q_url.startswith("http"):
                q_url = urljoin(base_url, q_url)
            # Human-facing name: last path component, fall back to resolution.
            tail = q_url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            name = tail or res or "stream"
            qualities.append(QualityInfo(
                name=name, url=q_url, resolution=res,
                bandwidth=bw, format_type="hls",
            ))
    return qualities


def parse_hls_duration(body):
    """Parse HLS playlist for duration metadata.
    Returns (total_secs, start_time, segment_count)."""
    total_secs = 0.0
    start_time = ""
    m = re.search(r'TOTAL-SECS[=:](\d+\.?\d*)', body)
    if m:
        total_secs = float(m.group(1))
    m2 = re.search(r'PROGRAM-DATE-TIME:(.+)', body)
    if m2:
        start_time = m2.group(1).strip()
    seg_count = len(re.findall(r'#EXTINF:', body))
    return total_secs, start_time, seg_count

"""DASH/MPD manifest parser — static VOD manifests (F50).

Parses MPEG-DASH Media Presentation Description (MPD) XML into
``QualityInfo`` entries.  Handles ``SegmentTemplate`` (pattern-based
URLs) and ``SegmentList`` (explicit URL lists) addressing.

Only **static** MPD manifests (``type="static"``) are supported.
Dynamic/live MPD is deferred.  DRM-protected content (``ContentProtection``
elements) is detected and skipped with a warning.
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET

from .http import curl
from .models import QualityInfo

# MPD namespace — most manifests use this, but some omit it
_MPD_NS = "urn:mpeg:dash:schema:mpd:2011"
_NS = {"mpd": _MPD_NS}


def parse_mpd(url, log_fn=None):
    """Fetch and parse a DASH MPD manifest.

    Returns a list of ``QualityInfo`` entries, or an empty list on error.
    """
    body = curl(url, timeout=15)
    if not body:
        if log_fn:
            log_fn("[DASH] Failed to fetch MPD manifest.")
        return []

    return parse_mpd_xml(body, url, log_fn)


def parse_mpd_xml(xml_text, base_url, log_fn=None):
    """Parse MPD XML text into ``QualityInfo`` entries."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        if log_fn:
            log_fn(f"[DASH] MPD parse error: {e}")
        return []

    # Detect namespace — some manifests don't declare it
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    mpd_type = root.attrib.get("type", "static")
    if mpd_type != "static":
        if log_fn:
            log_fn(f"[DASH] Dynamic MPD (type={mpd_type}) not yet supported.")
        return []

    # Parse total duration from mediaPresentationDuration (ISO 8601)
    total_secs = _parse_duration(root.attrib.get("mediaPresentationDuration", ""))

    qualities = []
    base_dir = base_url.rsplit("/", 1)[0] + "/" if "/" in base_url else base_url

    for period in _findall(root, "Period", ns):
        for adapt_set in _findall(period, "AdaptationSet", ns):
            mime = adapt_set.attrib.get("mimeType", "")
            content_type = adapt_set.attrib.get("contentType", "")

            # Check for DRM
            if _findall(adapt_set, "ContentProtection", ns):
                if log_fn:
                    log_fn("[DASH] Skipping DRM-protected AdaptationSet.")
                continue

            for rep in _findall(adapt_set, "Representation", ns):
                rid = rep.attrib.get("id", "")
                width = int(rep.attrib.get("width", 0) or 0)
                height = int(rep.attrib.get("height", 0) or 0)
                bandwidth = int(rep.attrib.get("bandwidth", 0) or 0)
                # Determine if this is video or audio
                is_video = "video" in (mime or content_type).lower()
                is_audio = "audio" in (mime or content_type).lower()

                # Build quality name
                if is_video and height:
                    name = f"{height}p"
                    if bandwidth:
                        name += f" ({bandwidth // 1000}kbps)"
                elif is_audio:
                    name = f"audio {bandwidth // 1000}kbps" if bandwidth else "audio"
                else:
                    name = f"rep-{rid}" if rid else f"{bandwidth // 1000}kbps"

                # Resolve the playback URL
                rep_url = ""

                # SegmentTemplate
                seg_tmpl = _find(rep, "SegmentTemplate", ns)
                if seg_tmpl is None:
                    seg_tmpl = _find(adapt_set, "SegmentTemplate", ns)
                if seg_tmpl is not None:
                    # For ffmpeg, the MPD URL itself is the best input
                    # (ffmpeg's DASH demuxer resolves templates internally)
                    rep_url = base_url

                # BaseURL
                base_el = _find(rep, "BaseURL", ns)
                if base_el is not None and base_el.text:
                    rep_url = urllib.parse.urljoin(base_dir, base_el.text.strip())

                # SegmentList
                seg_list = _find(rep, "SegmentList", ns)
                if seg_list is not None:
                    # For ffmpeg, the MPD URL is the input
                    rep_url = base_url

                if not rep_url:
                    rep_url = base_url

                resolution = f"{width}x{height}" if width and height else ""

                qi = QualityInfo(
                    name=name,
                    url=rep_url,
                    resolution=resolution,
                    bandwidth=bandwidth,
                    format_type="dash",
                )
                qualities.append(qi)

    # Sort: video first (highest resolution), then audio
    qualities.sort(key=lambda q: (
        0 if "audio" not in q.name.lower() else 1,
        -(q.bandwidth or 0),
    ))

    if log_fn:
        log_fn(f"[DASH] Parsed {len(qualities)} quality/ies from MPD "
               f"(duration: {total_secs:.0f}s).")

    return qualities


# ── XML helpers (namespace-agnostic) ────────────────────────────────

def _findall(parent, tag, ns):
    """Find child elements with or without namespace."""
    results = parent.findall(f"{ns}{tag}") if ns else parent.findall(tag)
    if not results and ns:
        results = parent.findall(tag)
    if not results:
        results = parent.findall(f"{{*}}{tag}")
    return results


def _find(parent, tag, ns):
    """Find first child element with or without namespace."""
    results = _findall(parent, tag, ns)
    return results[0] if results else None


def _parse_duration(iso_str):
    """Parse ISO 8601 duration (e.g. ``PT1H23M45.6S``) to seconds."""
    if not iso_str:
        return 0
    m = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?",
        iso_str,
    )
    if not m:
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    secs = float(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + secs

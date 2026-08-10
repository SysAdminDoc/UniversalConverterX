"""DASH/MPD manifest parsing for VOD and bounded live recordings.

The parser keeps the existing ``QualityInfo`` contract used by StreamKeep,
but also records the small amount of MPD timing metadata needed to make a
dynamic presentation safe to record.  A dynamic MPD is accepted only when
its representations expose segment addressing through ``SegmentTemplate``
or ``SegmentList``; a bare ``BaseURL`` is not enough to safely follow a live
window.
"""

from dataclasses import dataclass
import re
import urllib.parse
import xml.etree.ElementTree as ET

from .http import curl
from .models import QualityInfo

# MPD namespace — most manifests use this, but some omit it
_MPD_NS = "urn:mpeg:dash:schema:mpd:2011"
_NS = {"mpd": _MPD_NS}


@dataclass(frozen=True)
class DashManifestInfo:
    """Timing and capability metadata extracted from an MPD root."""

    is_dynamic: bool = False
    total_secs: float = 0.0
    minimum_update_period_secs: float = 0.0
    time_shift_buffer_depth_secs: float = 0.0
    segment_duration_secs: float = 0.0
    usable_representation_count: int = 0
    unsupported_reason: str = ""


def parse_mpd(url, log_fn=None):
    """Fetch and parse a DASH MPD manifest.

    Returns a list of ``QualityInfo`` entries, or an empty list on error.
    Dynamic entries carry their recording metadata on the quality object so
    callers that use the historical list-only API can still opt into bounded
    recording without a second manifest request.
    """
    body = curl(url, timeout=15)
    if not body:
        if log_fn:
            log_fn("[DASH] Failed to fetch MPD manifest.")
        return []

    qualities, _manifest = parse_mpd_xml_details(body, url, log_fn)
    return qualities


def parse_mpd_xml(xml_text, base_url, log_fn=None):
    """Parse MPD XML text into ``QualityInfo`` entries."""
    qualities, _manifest = parse_mpd_xml_details(xml_text, base_url, log_fn)
    return qualities


def parse_mpd_xml_details(xml_text, base_url, log_fn=None):
    """Parse MPD XML and return ``(qualities, manifest_metadata)``.

    This is intentionally separate from :func:`parse_mpd_xml` so existing
    integrations that expect a plain list remain source-compatible.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        if log_fn:
            log_fn(f"[DASH] MPD parse error: {e}")
        return [], DashManifestInfo(unsupported_reason=f"invalid MPD XML: {e}")

    # Detect namespace — some manifests don't declare it
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    mpd_type = (root.attrib.get("type", "static") or "static").lower()
    if mpd_type not in ("static", "dynamic"):
        reason = f"unsupported MPD type '{mpd_type}'"
        if log_fn:
            log_fn(f"[DASH] {reason}; no files will be written.")
        return [], DashManifestInfo(unsupported_reason=reason)

    is_dynamic = mpd_type == "dynamic"
    total_secs = _parse_duration(root.attrib.get("mediaPresentationDuration", ""))
    minimum_update_period = _parse_duration(
        root.attrib.get("minimumUpdatePeriod", "")
    )
    time_shift_buffer_depth = _parse_duration(
        root.attrib.get("timeShiftBufferDepth", "")
    )

    qualities = []
    base_dir = base_url.rsplit("/", 1)[0] + "/" if "/" in base_url else base_url
    unsupported_dynamic = []

    for period in _findall(root, "Period", ns):
        for adapt_set in _findall(period, "AdaptationSet", ns):
            adapt_mime = adapt_set.attrib.get("mimeType", "")
            adapt_content_type = adapt_set.attrib.get("contentType", "")

            # Check for DRM
            if _findall(adapt_set, "ContentProtection", ns):
                if log_fn:
                    log_fn("[DASH] Skipping DRM-protected AdaptationSet.")
                continue

            for rep in _findall(adapt_set, "Representation", ns):
                rid = rep.attrib.get("id", "")
                mime = rep.attrib.get("mimeType", adapt_mime)
                content_type = rep.attrib.get("contentType", adapt_content_type)
                width = _safe_int(rep.attrib.get("width", 0))
                height = _safe_int(rep.attrib.get("height", 0))
                bandwidth = _safe_int(rep.attrib.get("bandwidth", 0))

                # Determine if this is video or audio
                media_kind = (mime or content_type).lower()
                is_video = "video" in media_kind
                is_audio = "audio" in media_kind

                # Build quality name
                if is_video and height:
                    name = f"{height}p"
                    if bandwidth:
                        name += f" ({bandwidth // 1000}kbps)"
                elif is_audio:
                    name = f"audio {bandwidth // 1000}kbps" if bandwidth else "audio"
                else:
                    name = f"rep-{rid}" if rid else f"{bandwidth // 1000}kbps"

                # Representation-level values override inherited values. The
                # Period fallback covers valid manifests that put addressing
                # at the Period level rather than on the AdaptationSet.
                seg_tmpl = _first_present(
                    _find(rep, "SegmentTemplate", ns),
                    _find(adapt_set, "SegmentTemplate", ns),
                    _find(period, "SegmentTemplate", ns),
                )
                seg_list = _first_present(
                    _find(rep, "SegmentList", ns),
                    _find(adapt_set, "SegmentList", ns),
                    _find(period, "SegmentList", ns),
                )

                if is_dynamic and seg_tmpl is None and seg_list is None:
                    reason = (
                        f"representation {rid or name} has no SegmentTemplate "
                        "or SegmentList addressing"
                    )
                    unsupported_dynamic.append(reason)
                    if log_fn:
                        log_fn(f"[DASH] Unsupported dynamic representation: {reason}.")
                    continue

                # For ffmpeg, the MPD URL itself is the best input: its DASH
                # demuxer resolves templates and follows manifest updates.
                rep_url = base_url
                base_el = _first_present(
                    _find(rep, "BaseURL", ns), _find(adapt_set, "BaseURL", ns)
                )
                if base_el is not None and base_el.text:
                    rep_url = urllib.parse.urljoin(base_dir, base_el.text.strip())

                segment_duration = _segment_duration(
                    _first_present(seg_tmpl, seg_list), ns
                )
                qi = QualityInfo(
                    name=name,
                    url=rep_url,
                    resolution=f"{width}x{height}" if width and height else "",
                    bandwidth=bandwidth,
                    format_type="dash",
                    is_dynamic=is_dynamic,
                    segment_duration_secs=segment_duration,
                    minimum_update_period_secs=minimum_update_period,
                    time_shift_buffer_depth_secs=time_shift_buffer_depth,
                    manifest_duration_secs=total_secs,
                )
                qualities.append(qi)

    # Sort: video first (highest resolution), then audio
    qualities.sort(key=lambda q: (
        0 if "audio" not in q.name.lower() else 1,
        -(q.bandwidth or 0),
    ))

    manifest = DashManifestInfo(
        is_dynamic=is_dynamic,
        total_secs=total_secs,
        minimum_update_period_secs=minimum_update_period,
        time_shift_buffer_depth_secs=time_shift_buffer_depth,
        segment_duration_secs=max(
            (q.segment_duration_secs for q in qualities), default=0.0
        ),
        usable_representation_count=len(qualities),
        unsupported_reason=(
            "dynamic MPD has no usable SegmentTemplate or SegmentList representations"
            + (f" ({unsupported_dynamic[0]})" if unsupported_dynamic else "")
            if is_dynamic and not qualities
            else ""
        ),
    )

    if not qualities and log_fn:
        if manifest.unsupported_reason:
            log_fn(f"[DASH] {manifest.unsupported_reason}; no files will be written.")
        else:
            log_fn("[DASH] MPD contains no usable representations.")
    elif log_fn:
        if is_dynamic:
            interval = f", refresh: {minimum_update_period:.1f}s" if minimum_update_period else ""
            log_fn(
                f"[DASH] Parsed {len(qualities)} dynamic quality/ies "
                f"(bounded recording required{interval})."
            )
        else:
            log_fn(
                f"[DASH] Parsed {len(qualities)} quality/ies "
                f"(duration: {total_secs:.0f}s)."
            )

    return qualities, manifest


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


def _first_present(*elements):
    """Return the first non-None XML element (Element truthiness is child-based)."""
    for element in elements:
        if element is not None:
            return element
    return None


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _segment_duration(element, ns):
    """Return a SegmentTemplate/SegmentList's nominal duration in seconds."""
    if element is None:
        return 0.0
    timescale = max(1, _safe_int(element.attrib.get("timescale", 1)))
    duration = _safe_int(element.attrib.get("duration", 0))
    if duration > 0:
        return duration / timescale

    timeline = _find(element, "SegmentTimeline", ns)
    if timeline is not None:
        first = _find(timeline, "S", ns)
        if first is not None:
            duration = _safe_int(first.attrib.get("d", 0))
            if duration > 0:
                return duration / timescale
    return 0.0


def _parse_duration(iso_str):
    """Parse ISO 8601 duration (e.g. ``PT1H23M45.6S``) to seconds."""
    if not iso_str:
        return 0.0
    m = re.match(
        r"^P(?:(\d+(?:\.\d+)?)D)?T(?:(\d+(?:\.\d+)?)H)?"
        r"(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?$",
        str(iso_str).strip(),
    )
    if not m:
        return 0.0
    days = float(m.group(1) or 0)
    hours = float(m.group(2) or 0)
    minutes = float(m.group(3) or 0)
    secs = float(m.group(4) or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + secs

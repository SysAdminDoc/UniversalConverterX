"""Platform subtitle download + format normalization (F59).

Downloads platform-provided subtitles/closed captions alongside the video.
For yt-dlp-based downloads, passes ``--write-subs --sub-langs`` flags.
For native extractors, provides subtitle discovery + download helpers.

Normalizes TTML/SBV/VTT to SRT for maximum player compatibility.
"""

import os
import re


# ── Format conversion ───────────────────────────────────────────────

def vtt_to_srt(vtt_text):
    """Convert WebVTT text to SRT format."""
    lines = vtt_text.strip().splitlines()
    # Skip WEBVTT header
    start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("WEBVTT"):
            start = i + 1
            continue
        if line.strip() == "" and i <= start:
            start = i + 1
            continue
        break

    srt_lines = []
    cue_idx = 1
    i = start
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            # Timestamp line: convert . to , for SRT
            ts_line = line.replace(".", ",")
            # Remove VTT position/alignment metadata after timestamp
            ts_line = re.sub(r"([\d:,]+\s*-->\s*[\d:,]+).*", r"\1", ts_line)
            srt_lines.append(str(cue_idx))
            srt_lines.append(ts_line)
            i += 1
            # Collect text lines until blank
            text_lines = []
            while i < len(lines) and lines[i].strip():
                # Strip VTT tags like <c> </c> <v Name>
                cleaned = re.sub(r"<[^>]+>", "", lines[i])
                text_lines.append(cleaned)
                i += 1
            srt_lines.extend(text_lines)
            srt_lines.append("")
            cue_idx += 1
        else:
            i += 1

    return "\n".join(srt_lines)


def ttml_to_srt(ttml_text):
    """Convert TTML/DFXP XML to SRT format (basic conversion)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(ttml_text)
    except ET.ParseError:
        return ""

    # Find all <p> elements (TTML paragraphs)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    paragraphs = root.iter(f"{ns}p") if ns else root.iter("p")

    srt_lines = []
    cue_idx = 1
    for p in paragraphs:
        begin = p.attrib.get("begin", "")
        end = p.attrib.get("end", p.attrib.get("dur", ""))
        if not begin:
            continue
        text = "".join(p.itertext()).strip()
        if not text:
            continue

        # Convert TTML time format (HH:MM:SS.mmm or ticks) to SRT
        begin_srt = _ttml_time_to_srt(begin)
        end_srt = _ttml_time_to_srt(end)
        if not begin_srt or not end_srt:
            continue

        srt_lines.append(str(cue_idx))
        srt_lines.append(f"{begin_srt} --> {end_srt}")
        srt_lines.append(text)
        srt_lines.append("")
        cue_idx += 1

    return "\n".join(srt_lines)


def _ttml_time_to_srt(t):
    """Convert TTML time (HH:MM:SS.mmm or SS.mmm) to SRT format (HH:MM:SS,mmm)."""
    if not t:
        return ""
    # Already in HH:MM:SS.mmm format
    m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})\.?(\d{0,3})", t)
    if m:
        h, mi, s, ms = m.group(1), m.group(2), m.group(3), m.group(4) or "000"
        return f"{int(h):02d}:{mi}:{s},{ms:0<3}"
    # Seconds format
    m = re.match(r"(\d+\.?\d*)", t)
    if m:
        total = float(m.group(1))
        h = int(total) // 3600
        mi = (int(total) % 3600) // 60
        s = int(total) % 60
        ms = int((total % 1) * 1000)
        return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"
    return ""


# ── Subtitle file management ───────────────────────────────────────

def save_subtitle(output_dir, content, lang="en", fmt="srt"):
    """Save subtitle content to a file alongside the recording.

    Returns the written file path, or '' on error.
    """
    if not content or not output_dir:
        return ""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"subtitles.{lang}.{fmt}"
    path = os.path.join(output_dir, filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except OSError:
        return ""


def find_subtitles(recording_dir):
    """Find all subtitle files in a recording directory.

    Returns list of ``(path, lang, fmt)`` tuples.
    """
    if not recording_dir or not os.path.isdir(recording_dir):
        return []
    results = []
    for fn in os.listdir(recording_dir):
        fl = fn.lower()
        if fl.endswith((".srt", ".vtt", ".ass", ".sub")):
            # Try to extract language code from filename
            # e.g., "video.en.srt", "subtitles.es.vtt"
            parts = fn.rsplit(".", 2)
            lang = parts[-2] if len(parts) >= 3 and len(parts[-2]) <= 5 else ""
            fmt = fl.rsplit(".", 1)[-1]
            results.append((os.path.join(recording_dir, fn), lang, fmt))
    return results


def normalize_to_srt(file_path):
    """Convert a subtitle file to SRT format if needed. Returns SRT text."""
    if not file_path or not os.path.isfile(file_path):
        return ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return ""

    fl = file_path.lower()
    if fl.endswith(".vtt"):
        return vtt_to_srt(content)
    if fl.endswith((".ttml", ".dfxp", ".xml")):
        return ttml_to_srt(content)
    if fl.endswith(".srt"):
        return content
    return content


# ── yt-dlp subtitle flags ──────────────────────────────────────────

def ytdlp_sub_args(enabled=True, langs="en"):
    """Return yt-dlp command-line args for subtitle download.

    *langs* is a comma-separated language list (e.g., ``"en,es,ja"``).
    """
    if not enabled:
        return []
    args = [
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", langs or "en",
        "--convert-subs", "srt",
    ]
    return args

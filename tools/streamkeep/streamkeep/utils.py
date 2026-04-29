"""Pure utility functions — no Qt imports, safe for any module to use."""

import os
import re
import shutil
import sys
from pathlib import Path


def free_space_bytes(path):
    """Return free bytes on the disk containing `path`, or None on error.

    Walks up the path if needed (the target dir may not exist yet)."""
    if not path:
        return None
    probe = path
    for _ in range(6):
        try:
            return shutil.disk_usage(probe).free
        except (FileNotFoundError, OSError, ValueError):
            parent = os.path.dirname(probe)
            if not parent or parent == probe:
                return None
            probe = parent
    return None


def estimate_download_bytes(stream_info):
    """Rough estimate of total download size from a StreamInfo, based on
    manifest bandwidth × total_secs × 1.05 container overhead. Returns
    None when we can't make a meaningful guess (no duration / no
    bandwidth). Picks the highest bandwidth quality — matches the UI's
    default selection."""
    if not stream_info:
        return None
    total_secs = float(getattr(stream_info, "total_secs", 0) or 0)
    if total_secs <= 0:
        return None
    qualities = getattr(stream_info, "qualities", None) or []
    bandwidths = [int(getattr(q, "bandwidth", 0) or 0) for q in qualities]
    bw = max(bandwidths) if bandwidths else 0
    if bw <= 0:
        return None
    return int((bw / 8.0) * total_secs * 1.05)


DEFAULT_FOLDER_TEMPLATE = "{channel}/{date} - {title}"
DEFAULT_FILE_TEMPLATE = "{title}"


def fmt_duration(secs):
    """Format seconds as Xh Ym Zs."""
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def fmt_size(b):
    """Format bytes as a human-readable string."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def safe_filename(s, max_len=60):
    """Sanitize a string for use as a filename. Strips invalid chars,
    control chars, trailing dots/spaces (invalid on Windows), template
    braces left behind by render_template fallbacks, and truncates."""
    if not s:
        return ""
    # Drop NT-invalid chars, control chars, and {} left over from templates.
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f{}]', '', s)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    reserved = (
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"
    # Truncate, then re-strip trailing whitespace/dots exposed by the cut.
    cleaned = cleaned[:max_len].rstrip(". ")
    return cleaned or "download"


def safe_path_component(s, max_len=80):
    """Sanitize a path component (filename or folder name)."""
    return safe_filename(s, max_len=max_len) or "download"


def user_videos_dir():
    """Return the current user's Videos folder (platform-specific).
    On Windows queries SHGetKnownFolderPath for FOLDERID_Videos to honor
    redirected / OneDrive-mapped profiles. Falls back to ~/Videos (Linux,
    Windows default) or ~/Movies (macOS)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            FOLDERID_Videos = _GUID(
                0x18989B1D, 0x99B5, 0x455B,
                (ctypes.c_ubyte * 8)(0x84, 0x1C, 0xAB, 0x7C, 0x74, 0xE4, 0xDD, 0xFC),
            )
            SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
            SHGetKnownFolderPath.argtypes = [
                ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
                ctypes.POINTER(ctypes.c_wchar_p),
            ]
            SHGetKnownFolderPath.restype = ctypes.HRESULT
            out_ptr = ctypes.c_wchar_p()
            hr = SHGetKnownFolderPath(
                ctypes.byref(FOLDERID_Videos), 0, 0, ctypes.byref(out_ptr)
            )
            if hr == 0 and out_ptr.value:
                result = Path(out_ptr.value)
                ctypes.windll.ole32.CoTaskMemFree(out_ptr)
                return result
        except Exception:
            pass
        return Path.home() / "Videos"
    if sys.platform == "darwin":
        return Path.home() / "Movies"
    # Linux / BSD: honor XDG_VIDEOS_DIR
    xdg_config = Path.home() / ".config" / "user-dirs.dirs"
    try:
        if xdg_config.exists():
            text = xdg_config.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'XDG_VIDEOS_DIR\s*=\s*"(.+)"', text)
            if m:
                path = m.group(1).replace("$HOME", str(Path.home()))
                return Path(path)
    except Exception:
        pass
    return Path.home() / "Videos"


def default_output_dir():
    """Default root directory for new downloads: <User Videos>/StreamKeep."""
    return user_videos_dir() / "StreamKeep"


def render_template(template, context):
    """Render a filename template. Each path segment is sanitized
    separately so that '{channel}/{title}' produces a valid nested path.
    Returns a list of path components (to be joined with os.path.join)."""
    if not template:
        return []
    result = []
    for segment in template.split("/"):
        if not segment.strip():
            continue
        try:
            rendered = segment.format(**context)
        except (KeyError, IndexError, ValueError):
            def safe_sub(m):
                key = m.group(1)
                return str(context.get(key, "")) or m.group(0)
            rendered = re.sub(r'\{(\w+)\}', safe_sub, segment)
        rendered = safe_path_component(rendered)
        if rendered:
            result.append(rendered)
    return result


def build_template_context(stream_info, vod_info=None):
    """Build the variable dict for template rendering.
    Variables: {title}, {channel}, {platform}, {date}, {year}, {month},
    {day}, {id}, {quality}, {ext}"""
    from datetime import datetime as _dt
    now = _dt.now()
    title = (stream_info.title if stream_info else "") or (
        vod_info.title if vod_info else "") or "download"
    channel = ""
    if vod_info and vod_info.channel:
        channel = vod_info.channel
    elif stream_info and stream_info.channel:
        channel = stream_info.channel
    date_str = ""
    try:
        if stream_info and stream_info.start_time:
            dt = _dt.fromisoformat(stream_info.start_time.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        elif vod_info and vod_info.date:
            raw = vod_info.date.replace("T", " ").split(".")[0].split("+")[0]
            dt = _dt.fromisoformat(raw[:19])
            date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    if not date_str:
        date_str = now.strftime("%Y-%m-%d")
    year, month, day = date_str.split("-") if "-" in date_str else ("", "", "")
    return {
        "title": title,
        "channel": channel or "unknown",
        "platform": stream_info.platform if stream_info else "",
        "date": date_str,
        "year": year,
        "month": month,
        "day": day,
        "id": "",
        "quality": "",
        "ext": "mp4",
    }


def scan_browser_cookies():
    """Scan for installed browsers with cookie stores.
    Returns list of (display_name, ytdlp_name, path)."""
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    browsers = [
        ("Chrome", "chrome", [
            os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cookies"),
            os.path.join(local, "Google", "Chrome", "User Data", "Default", "Network", "Cookies"),
        ]),
        ("Chromium", "chromium", [
            os.path.join(local, "Chromium", "User Data", "Default", "Cookies"),
            os.path.join(local, "Chromium", "User Data", "Default", "Network", "Cookies"),
        ]),
        ("Firefox", "firefox", [
            os.path.join(roaming, "Mozilla", "Firefox", "Profiles"),
        ]),
        ("Edge", "edge", [
            os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cookies"),
            os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Network", "Cookies"),
        ]),
        ("Brave", "brave", [
            os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Cookies"),
            os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Network", "Cookies"),
        ]),
        ("Opera", "opera", [
            os.path.join(roaming, "Opera Software", "Opera Stable", "Cookies"),
            os.path.join(roaming, "Opera Software", "Opera Stable", "Network", "Cookies"),
        ]),
        ("Opera GX", "opera", [
            os.path.join(roaming, "Opera Software", "Opera GX Stable", "Cookies"),
            os.path.join(roaming, "Opera Software", "Opera GX Stable", "Network", "Cookies"),
        ]),
        ("Vivaldi", "vivaldi", [
            os.path.join(local, "Vivaldi", "User Data", "Default", "Cookies"),
            os.path.join(local, "Vivaldi", "User Data", "Default", "Network", "Cookies"),
        ]),
        ("LibreWolf", "firefox", [
            os.path.join(roaming, "librewolf", "Profiles"),
        ]),
        ("Waterfox", "firefox", [
            os.path.join(roaming, "Waterfox", "Profiles"),
        ]),
    ]
    found = []
    seen_ytdlp = set()
    for display, ytdlp_name, paths in browsers:
        for p in paths:
            if os.path.exists(p):
                actual_ytdlp = ytdlp_name
                if ytdlp_name == "firefox" and display != "Firefox":
                    if os.path.isdir(p):
                        for entry in os.listdir(p):
                            profile_dir = os.path.join(p, entry)
                            if os.path.isdir(profile_dir) and os.path.exists(
                                os.path.join(profile_dir, "cookies.sqlite")
                            ):
                                actual_ytdlp = f"firefox:{profile_dir}"
                                break
                key = actual_ytdlp if actual_ytdlp.startswith("firefox:") else ytdlp_name
                if key not in seen_ytdlp:
                    found.append((display, actual_ytdlp, p))
                    seen_ytdlp.add(key)
                break
    return found

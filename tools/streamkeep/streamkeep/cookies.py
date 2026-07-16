"""Browser cookie import — extract cookies to Netscape cookies.txt (F47).

Supports Chrome, Firefox, Edge, Brave, Chromium, Vivaldi, LibreWolf.
Uses ``rookiepy`` (preferred) or ``browser_cookie3`` for decryption.
Falls back to manual cookies.txt import.

The exported file lives at ``%APPDATA%/StreamKeep/cookies.txt`` and is
referenced by ``http._build_curl_cmd()`` and ``DownloadWorker`` (yt-dlp
``--cookies``).

Cookies are encrypted at rest with current-user DPAPI and application-specific
entropy. Legacy plaintext and DPAPI1 stores are migrated when read. yt-dlp
can't read encrypted cookies, so :func:`cookies_file_path` decrypts to a
process-private temp file and registers an ``atexit`` cleanup.
"""

import atexit
import os
import tempfile
import time

from .paths import CONFIG_DIR
from . import dpapi

COOKIES_FILE = CONFIG_DIR / "cookies.txt"

# Track the per-process plaintext temp file (when encryption is in use). One
# per process; cleaned up on interpreter exit.
_DECRYPTED_TEMP: str | None = None


def _cleanup_decrypted_temp() -> None:
    global _DECRYPTED_TEMP
    if _DECRYPTED_TEMP and os.path.isfile(_DECRYPTED_TEMP):
        try:
            os.unlink(_DECRYPTED_TEMP)
        except OSError:
            pass
    _DECRYPTED_TEMP = None


atexit.register(_cleanup_decrypted_temp)

# Domains we care about — filter to reduce file size and surface area
PLATFORM_DOMAINS = {
    ".twitch.tv", ".kick.com", ".youtube.com", ".google.com",
    ".rumble.com", ".soundcloud.com", ".reddit.com",
}


def cookies_file_path():
    """Return the path to the Netscape cookies.txt, or '' if none exists.

    When the on-disk file is DPAPI-encrypted (current default on Windows),
    decrypts to a process-private temp file under ``%TEMP%`` and returns the
    temp path. Subsequent calls in the same process reuse the temp file. The
    temp file is unlinked on interpreter exit via :mod:`atexit`.

    Legacy plaintext files are encrypted before use. If DPAPI protection is
    unavailable, no plaintext path is returned.
    """
    global _DECRYPTED_TEMP

    if not (COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0):
        return ""

    try:
        raw = COOKIES_FILE.read_bytes()
    except OSError:
        return ""

    if not dpapi.is_encrypted(raw):
        try:
            _write_encrypted_or_plain(raw)
            raw = COOKIES_FILE.read_bytes()
            _cleanup_decrypted_temp()
        except (dpapi.DpapiUnavailable, OSError):
            return ""

    # Encrypted blob — decrypt to a per-process temp file. Reuse if we
    # already decrypted this process.
    if _DECRYPTED_TEMP and os.path.isfile(_DECRYPTED_TEMP):
        return _DECRYPTED_TEMP

    try:
        plaintext = dpapi.decrypt(raw)
    except (dpapi.DpapiUnavailable, OSError, ValueError):
        # Best-effort: if decrypt fails (re-imaged host, GPO restrictions),
        # treat as no cookies rather than crash the sidecar pipeline.
        return ""

    if dpapi.is_legacy(raw):
        try:
            _write_encrypted_or_plain(plaintext)
        except (dpapi.DpapiUnavailable, OSError):
            # DPAPI1 is still encrypted, so migration can safely wait.
            pass

    fd, tmp_path = tempfile.mkstemp(prefix="streamkeep_cookies_", suffix=".txt")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(plaintext)
    except OSError:
        try: os.unlink(tmp_path)
        except OSError: pass
        return ""

    _DECRYPTED_TEMP = tmp_path
    return tmp_path


def cookies_file_age_secs():
    """Return seconds since the cookies file was last written, or -1."""
    try:
        return int(time.time() - COOKIES_FILE.stat().st_mtime)
    except (OSError, ValueError):
        return -1


def import_from_browser(browser_name):
    """Extract cookies from *browser_name* and write cookies.txt.

    *browser_name* is one of the yt-dlp-style names: chrome, firefox,
    edge, brave, chromium, vivaldi, opera.

    Returns ``(ok, message)`` tuple.
    """
    cj = None

    # Prefer rookiepy — lighter, better maintained
    try:
        import rookiepy
        load_fn = getattr(rookiepy, browser_name, None)
        if load_fn is not None:
            cj = load_fn(domains=list(PLATFORM_DOMAINS))
    except Exception:
        cj = None

    # Fallback to browser_cookie3
    if cj is None:
        try:
            import browser_cookie3 as bc3
            load_fn = getattr(bc3, browser_name, None)
            if load_fn is not None:
                jar = load_fn()
                cj = [
                    {
                        "domain": c.domain,
                        "name": c.name,
                        "value": c.value,
                        "path": c.path or "/",
                        "expires": int(c.expires or 0),
                        "secure": bool(c.secure),
                        "http_only": c.has_nonstandard_attr("httponly") if hasattr(c, "has_nonstandard_attr") else False,
                    }
                    for c in jar
                    if any(c.domain.endswith(d) or d.endswith(c.domain) for d in PLATFORM_DOMAINS)
                ]
        except Exception as e:
            return False, f"Failed to load cookies from {browser_name}: {e}"

    if cj is None:
        return False, (
            f"No cookie loader found for '{browser_name}'. "
            "Install rookiepy (`pip install rookiepy`) or browser_cookie3."
        )

    return _write_cookies(cj, browser_name)


def import_from_file(source_path):
    """Copy a Netscape cookies.txt file into the config dir.

    Returns ``(ok, message)``.
    """
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return False, f"Failed to read {source_path}: {e}"

    # Basic validation — Netscape format starts with comments or domain lines
    lines = [ln for ln in content.strip().splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return False, "File appears empty (no cookie lines found)."
    # Check that lines have ~7 tab-separated fields
    valid = sum(1 for ln in lines if len(ln.split("\t")) >= 6)
    if valid < 1:
        return False, "File doesn't look like Netscape cookies.txt format (expected tab-separated fields)."

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _write_encrypted_or_plain(content.encode("utf-8"))
    except (dpapi.DpapiUnavailable, OSError) as e:
        return False, f"Failed to protect or write cookies: {e}"
    _cleanup_decrypted_temp()  # invalidate any stale process-cached plaintext

    return True, f"Imported {valid} cookie(s) from file."


def clear_cookies():
    """Delete the cookies.txt file (and any process-cached plaintext temp)."""
    try:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()
        _cleanup_decrypted_temp()
        return True, "Cookies cleared."
    except OSError as e:
        return False, f"Failed to clear cookies: {e}"


def _write_encrypted_or_plain(payload: bytes) -> None:
    """Atomically replace the cookie store with entropy-bound DPAPI data.

    Protection completes before the destination is touched, so a DPAPI or
    filesystem failure cannot replace an existing encrypted store with
    plaintext or a partial file.
    """
    protected = dpapi.encrypt(payload, description="UCX-StreamKeep cookies")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="cookies_", suffix=".tmp", dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(protected)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, COOKIES_FILE)
    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass


def is_storage_encrypted() -> bool:
    """Return True if the on-disk cookies file is DPAPI-encrypted.

    Used by the StreamKeep settings UI to display "Encrypted at rest" vs
    "Plaintext (legacy)". Returns False when no cookies are stored.
    """
    if not COOKIES_FILE.is_file():
        return False
    try:
        head = COOKIES_FILE.open("rb").read(
            max(len(dpapi.MAGIC), len(dpapi.LEGACY_MAGIC))
        )
    except OSError:
        return False
    return dpapi.is_encrypted(head)


def _write_cookies(cookie_list, source):
    """Write a list of cookie dicts to Netscape cookies.txt."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File",
             f"# Exported by StreamKeep from {source}",
             ""]
    count = 0

    for c in cookie_list:
        # rookiepy returns dicts; browser_cookie3 returns our own dicts
        domain = c.get("domain", "") if isinstance(c, dict) else ""
        if not domain:
            continue

        domain = _sanitize_cookie_field(domain)
        name = _sanitize_cookie_field(c.get("name", ""))
        value = _sanitize_cookie_field(c.get("value", ""))
        path = _sanitize_cookie_field(c.get("path", "/") or "/")
        if not domain or not name:
            continue
        expires = int(c.get("expires", 0) or 0)
        secure = "TRUE" if c.get("secure", False) else "FALSE"

        # Netscape format: domain  include_subdomains  path  secure  expires  name  value
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        lines.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
        count += 1

    if count == 0:
        return False, f"No relevant cookies found in {source} for supported platforms."

    try:
        _write_encrypted_or_plain(("\n".join(lines) + "\n").encode("utf-8"))
    except (dpapi.DpapiUnavailable, OSError) as e:
        return False, f"Failed to protect or write cookies: {e}"
    _cleanup_decrypted_temp()  # invalidate stale plaintext temp

    return True, f"Exported {count} cookie(s) from {source}."


def _sanitize_cookie_field(value):
    """Strip control characters that would corrupt Netscape cookie rows."""
    # Remove NUL bytes and all C0 control chars (0x00-0x1F) except space
    cleaned = str(value or "")
    cleaned = "".join(c if c >= " " or c == "\t" else " " for c in cleaned)
    cleaned = cleaned.replace("\t", " ")
    return " ".join(cleaned.split())

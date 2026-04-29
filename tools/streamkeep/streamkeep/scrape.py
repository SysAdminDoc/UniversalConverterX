"""Webpage scraping helpers — regex-based + headless Playwright.

Used by the FetchWorker when a URL doesn't match any extractor: try to
find embedded media links or platform URLs on the page. Kept separate
from the extractors because these are generic URL sniffers, not
platform-specific parsers.
"""

import os
import re
import sys
import urllib.parse

from . import CURL_UA
from .http import curl, http_interrupted, http_probe, run_capture_interruptible
from .models import QualityInfo, StreamInfo


# Module-level flag so we only probe the Playwright browser install once.
# None = not checked yet; True = ready; False = failed (will retry after
# _PLAYWRIGHT_RETRY_AFTER seconds in case the user installs it mid-session).
_PLAYWRIGHT_READY = None
_PLAYWRIGHT_LAST_CHECK = 0.0
_PLAYWRIGHT_RETRY_AFTER = 300  # 5 minutes


def _cancelled(checker=None):
    if checker is not None:
        try:
            if checker():
                return True
        except Exception:
            pass
    return http_interrupted()


def ensure_playwright_browser(log_fn=None, should_cancel=None):
    """Check that Playwright is importable AND has a Chromium install.
    Attempts `playwright install chromium` on first use. Returns True
    if the browser is ready to use."""
    global _PLAYWRIGHT_READY, _PLAYWRIGHT_LAST_CHECK
    if _PLAYWRIGHT_READY is True:
        return True
    # Allow retry after cooldown so a mid-session install can succeed
    if _PLAYWRIGHT_READY is False:
        import time as _time
        if _time.time() - _PLAYWRIGHT_LAST_CHECK < _PLAYWRIGHT_RETRY_AFTER:
            return False
    import time as _time
    _PLAYWRIGHT_LAST_CHECK = _time.time()
    if _cancelled(should_cancel):
        return False
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        if log_fn:
            log_fn("[HEADLESS] Playwright not installed — falling back to regex scraper.")
        _PLAYWRIGHT_READY = False
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if _cancelled(should_cancel):
                _PLAYWRIGHT_READY = False
                return False
            browser = p.chromium.launch(headless=True)
            browser.close()
        _PLAYWRIGHT_READY = True
        return True
    except Exception as e:
        err_str = str(e)
        # `sys.executable` in a frozen PyInstaller exe is the exe itself,
        # so `sys.executable -m playwright install chromium` would
        # re-launch StreamKeep.exe in a loop. Skip the auto-install path
        # when frozen and just surface the failure — the user must install
        # Playwright browsers manually in that case.
        _frozen = getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")
        if (
            not _frozen
            and ("Executable doesn't exist" in err_str or "playwright install" in err_str)
        ):
            if _cancelled(should_cancel):
                _PLAYWRIGHT_READY = False
                return False
            if log_fn:
                log_fn("[HEADLESS] Installing Chromium for Playwright (one-time, ~120MB)...")
            result = run_capture_interruptible(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                timeout=300,
            )
            if result.interrupted or _cancelled(should_cancel):
                _PLAYWRIGHT_READY = False
                return False
            if result.returncode != 0:
                if log_fn:
                    install_err = (
                        result.stderr.strip().split("\n")[-1]
                        if result.stderr else result.error or "Unknown error"
                    )
                    log_fn(f"[HEADLESS] Install failed: {install_err}")
                _PLAYWRIGHT_READY = False
                return False
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    if _cancelled(should_cancel):
                        _PLAYWRIGHT_READY = False
                        return False
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                _PLAYWRIGHT_READY = True
                return True
            except Exception as retry_err:
                if log_fn:
                    log_fn(f"[HEADLESS] Still can't launch after install: {retry_err}")
                _PLAYWRIGHT_READY = False
                return False
        if log_fn:
            log_fn(
                f"[HEADLESS] Launch failed: {err_str[:120]}"
                + (" (frozen build — install Playwright browsers manually)"
                   if _frozen else "")
            )
        _PLAYWRIGHT_READY = False
        return False


def scrape_media_links_headless(page_url, log_fn=None, max_links=100,
                                wait_seconds=8, should_cancel=None):
    """Load a page in a headless Chromium browser and capture any network
    requests that look like media streams. Catches lazy-loaded players
    that the regex scraper can't see."""
    if not ensure_playwright_browser(log_fn, should_cancel=should_cancel):
        return []
    if _cancelled(should_cancel):
        return []

    media_ext_re = re.compile(
        r'\.(mp4|webm|mkv|mov|mp3|m4a|ogg|flac|wav|m3u8|mpd|ts|aac|opus)'
        r'(?:\?|$|/)',
        re.IGNORECASE,
    )
    media_ct_prefixes = (
        "video/", "audio/", "application/vnd.apple.mpegurl",
        "application/x-mpegurl", "application/dash+xml",
    )

    captured = []
    seen = set()

    def add(u, hint):
        if _cancelled(should_cancel):
            return
        if not u or u in seen:
            return
        if len(captured) >= max_links:
            return
        lower = u.lower()
        if any(x in lower for x in (
            "/ads/", "doubleclick", "analytics",
            "telemetry", "/ping", "googlevideo.com/ptracking",
        )):
            return
        seen.add(u)
        captured.append((u, hint))

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if _cancelled(should_cancel):
                return []
            browser = p.chromium.launch(
                headless=True,
                args=["--mute-audio", "--no-sandbox"],
            )
            context = None
            page = None
            try:
                context = browser.new_context(
                    user_agent=CURL_UA,
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()

                def on_request(req):
                    if _cancelled(should_cancel):
                        return
                    u = req.url
                    rtype = req.resource_type
                    if rtype in ("media", "xhr", "fetch"):
                        if media_ext_re.search(u):
                            add(u, f"headless {rtype}")
                            return
                    if media_ext_re.search(u):
                        add(u, "headless url-ext")

                def on_response(resp):
                    if _cancelled(should_cancel):
                        return
                    try:
                        ct = (resp.headers.get("content-type", "") or "").lower()
                    except Exception:
                        return
                    if any(ct.startswith(prefix) for prefix in media_ct_prefixes):
                        add(resp.url, f"headless {ct.split(';')[0]}")

                page.on("request", on_request)
                page.on("response", on_response)

                if log_fn:
                    log_fn(f"[HEADLESS] Loading {page_url[:80]} (up to {wait_seconds}s)")
                try:
                    nav_timeout = max(4000, min(12000, int((wait_seconds + 2) * 1000)))
                    page.goto(page_url, wait_until="domcontentloaded", timeout=nav_timeout)
                except Exception as nav_err:
                    if log_fn:
                        log_fn(f"[HEADLESS] Navigation warning: {str(nav_err)[:80]}")
                if _cancelled(should_cancel):
                    return captured

                try:
                    page.evaluate("""
                        const v = document.querySelector('video');
                        if (v) v.scrollIntoView({behavior:'instant',block:'center'});
                    """)
                except Exception:
                    pass
                if _cancelled(should_cancel):
                    return captured

                try:
                    for sel in [
                        "button[aria-label*='play' i]", ".play-button",
                        ".vjs-big-play-button", "button.ytp-large-play-button",
                        ".plyr__control--overlaid",
                    ]:
                        if _cancelled(should_cancel):
                            return captured
                        try:
                            page.locator(sel).first.click(timeout=500)
                            break
                        except Exception:
                            continue
                except Exception:
                    pass

                try:
                    remaining_ms = max(0, int(wait_seconds * 1000))
                    while remaining_ms > 0:
                        if _cancelled(should_cancel):
                            return captured
                        step = min(250, remaining_ms)
                        page.wait_for_timeout(step)
                        remaining_ms -= step
                except Exception:
                    pass
            finally:
                try:
                    if page is not None:
                        page.close()
                except Exception:
                    pass
                try:
                    if context is not None:
                        context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        if log_fn:
            log_fn(f"[HEADLESS] Error: {str(e)[:120]}")
        return []

    if log_fn:
        log_fn(f"[HEADLESS] Captured {len(captured)} media request(s)")
    return captured


def scrape_media_links(page_url, log_fn=None, max_links=100):
    """Fetch a webpage and extract URLs that look like media or embeddable
    streams. Returns a de-duplicated list of (url, hint) tuples.

    Conservative: looks for explicit media files (mp4/mp3/m3u8), common
    streaming hosts, and iframe embeds. Does NOT execute JavaScript."""
    headers = {
        "User-Agent": CURL_UA,
        "Accept": "text/html,application/xhtml+xml",
    }
    body = curl(page_url, headers=headers, timeout=20) or ""
    if not body:
        return []
    found = []
    seen = set()

    def add(url, hint):
        if not url or url in seen:
            return
        if len(found) >= max_links:
            return
        seen.add(url)
        found.append((url, hint))

    media_re = re.compile(
        r'https?://[^\s"\'<>]+\.(?:mp4|webm|mkv|mov|mp3|m4a|ogg|flac|wav|m3u8|mpd|ts)'
        r'(?:\?[^\s"\'<>]*)?',
        re.IGNORECASE,
    )
    for m in media_re.finditer(body):
        add(m.group(0), "direct media")

    host_re = re.compile(
        r'https?://(?:www\.)?'
        r'(?:youtube\.com/(?:watch|shorts|embed)/[^\s"\'<>]+'
        r'|youtu\.be/[^\s"\'<>]+'
        r'|twitch\.tv/(?:videos/)?[a-zA-Z0-9_]+'
        r'|kick\.com/[a-zA-Z0-9_-]+(?:/videos/\d+)?'
        r'|rumble\.com/v[a-z0-9]+[^\s"\'<>]*'
        r'|soundcloud\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+'
        r'|reddit\.com/r/\w+/comments/\w+[^\s"\'<>]*'
        r'|vimeo\.com/\d+'
        r'|dailymotion\.com/video/[a-zA-Z0-9]+'
        r'|bitchute\.com/video/[a-zA-Z0-9]+'
        r'|odysee\.com/@[^\s"\'<>]+'
        r')',
        re.IGNORECASE,
    )
    for m in host_re.finditer(body):
        url = m.group(0).rstrip('.,;)')
        add(url, "platform link")

    iframe_re = re.compile(
        r'<iframe[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE,
    )
    for m in iframe_re.finditer(body):
        src = m.group(1)
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith("http"):
            continue
        if any(x in src.lower() for x in (
            "youtube", "vimeo", "twitch", "kick", "rumble",
            "dailymotion", "bitchute", "odysee",
        )):
            add(src, "iframe embed")

    if log_fn:
        log_fn(f"[SCRAPE] Found {len(found)} candidate link(s) in {page_url}")
    return found


def detect_direct_media(url, log_fn=None):
    """Sniff a URL via HEAD request. Returns StreamInfo if it's a direct
    media file, else None."""
    MEDIA_TYPES = {
        "video/mp4": "mp4", "video/webm": "mp4", "video/x-matroska": "mp4",
        "video/quicktime": "mp4", "video/x-msvideo": "mp4", "video/x-flv": "mp4",
        "audio/mpeg": "mp4", "audio/mp3": "mp4", "audio/mp4": "mp4",
        "audio/ogg": "mp4", "audio/flac": "mp4", "audio/wav": "mp4",
        "audio/x-wav": "mp4", "audio/aac": "mp4",
        "application/vnd.apple.mpegurl": "hls", "audio/mpegurl": "hls",
        "application/x-mpegurl": "hls", "application/dash+xml": "dash",
        # Note: application/octet-stream is intentionally excluded — it
        # matches any binary file (exe, zip, etc.) and would false-positive.
        # Direct media URLs are caught earlier by extension matching.
    }
    MEDIA_EXTS = {
        ".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".wmv",
        ".mp3", ".m4a", ".ogg", ".flac", ".wav", ".aac", ".opus",
        ".m3u8", ".mpd", ".ts",
    }

    parsed = urllib.parse.urlparse(url)

    def infer_channel(parsed_url):
        parts = [p for p in parsed_url.path.strip("/").split("/") if p]
        if len(parts) < 2:
            return ""
        lead = parts[0].strip()
        if not lead or lead.isdigit():
            return ""
        return lead

    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in MEDIA_EXTS:
        # DASH MPD manifest — parse into proper qualities (F50)
        if ext == ".mpd":
            from .dash import parse_mpd
            if log_fn:
                log_fn(f"DASH manifest detected: {url}")
            qualities = parse_mpd(url, log_fn=log_fn)
            if qualities:
                info = StreamInfo(
                    platform="Direct",
                    url=url,
                    title=parsed.path.split("/")[-1],
                    channel=infer_channel(parsed),
                    qualities=qualities,
                )
                return info
        fmt = "hls" if ext == ".m3u8" else "mp4"
        if log_fn:
            log_fn(f"Direct media URL detected by extension: {ext}")
        info = StreamInfo(
            platform="Direct",
            url=url,
            title=parsed.path.split("/")[-1],
            channel=infer_channel(parsed),
        )
        info.qualities.append(QualityInfo(name=f"direct ({ext})", url=url, format_type=fmt))
        return info

    try:
        probe = http_probe(url, headers={"User-Agent": CURL_UA}, timeout=10)
        ct = probe.get("content_type", "")
        final_url = probe.get("final_url") or url
        final_parsed = urllib.parse.urlparse(final_url)
        final_ext = os.path.splitext(final_parsed.path)[1].lower()
        if final_ext in MEDIA_EXTS:
            if final_ext == ".mpd":
                from .dash import parse_mpd
                if log_fn:
                    log_fn(f"DASH manifest detected after probe redirect: {final_url}")
                qualities = parse_mpd(final_url, log_fn=log_fn)
                if qualities:
                    return StreamInfo(
                        platform="Direct",
                        url=final_url,
                        title=os.path.basename(final_parsed.path) or parsed.path.split("/")[-1],
                        channel=infer_channel(final_parsed) or infer_channel(parsed),
                        qualities=qualities,
                    )
            fmt = "hls" if final_ext == ".m3u8" else "mp4"
            if log_fn:
                log_fn(f"Direct media URL detected after probe redirect: {final_ext}")
            info = StreamInfo(
                platform="Direct",
                url=final_url,
                title=os.path.basename(final_parsed.path) or parsed.path.split("/")[-1],
                channel=infer_channel(final_parsed) or infer_channel(parsed),
            )
            info.qualities.append(
                QualityInfo(name=f"direct ({final_ext})", url=final_url, format_type=fmt)
            )
            return info

        if ct in MEDIA_TYPES:
            fmt = MEDIA_TYPES[ct]
            title = os.path.basename(final_parsed.path) or parsed.path.split("/")[-1]
            if log_fn:
                log_fn(f"Direct media URL detected: {ct}")
            info = StreamInfo(
                platform="Direct",
                url=final_url,
                title=title,
                channel=infer_channel(final_parsed) or infer_channel(parsed),
            )
            info.qualities.append(
                QualityInfo(name=f"direct ({ct})", url=final_url, format_type=fmt)
            )
            return info
    except Exception:
        pass

    return None

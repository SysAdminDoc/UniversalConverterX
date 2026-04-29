"""Proxy pool with per-platform routing (F49).

Replaces the single ``NATIVE_PROXY`` global with a pool of proxy entries,
each assigned to specific platforms.  ``resolve_proxy(url)`` returns the
best proxy URL for a given target, or ``""`` for direct connection.

Pool entries are persisted in ``config["proxy_pool"]`` as a list of dicts::

    [
        {"url": "socks5://us.proxy:1080", "platforms": ["twitch", "kick"],
         "enabled": true, "label": "US proxy"},
        {"url": "http://de.proxy:8080", "platforms": ["youtube"],
         "enabled": true, "label": "DE proxy"},
    ]

An empty ``platforms`` list means "all platforms" (global fallback).
"""

import os
import re
import subprocess

from .paths import _CREATE_NO_WINDOW

_pool = []   # list of dicts: url, platforms, enabled, label, last_health_ms
_fallback = ""  # legacy single proxy (backward compat)

# Platform detection from URL domain
_PLATFORM_PATTERNS = {
    "twitch": re.compile(r"twitch\.tv|twitchcdn|jtvnw\.net", re.I),
    "kick": re.compile(r"kick\.com", re.I),
    "youtube": re.compile(r"youtube\.com|googlevideo\.com|ytimg\.com|youtu\.be", re.I),
    "rumble": re.compile(r"rumble\.com", re.I),
    "soundcloud": re.compile(r"soundcloud\.com|sndcdn\.com", re.I),
    "reddit": re.compile(r"reddit\.com|redd\.it|redditmedia\.com", re.I),
}


def set_pool(entries):
    """Replace the proxy pool.  *entries* is a list of dicts."""
    global _pool
    _pool = [
        {
            "url": str(e.get("url", "")),
            "platforms": [
                str(p).strip().lower()
                for p in (e.get("platforms", []) or [])
                if str(p).strip()
            ],
            "enabled": bool(e.get("enabled", True)),
            "label": str(e.get("label", "")),
            "last_health_ms": int(e.get("last_health_ms", -1)),
        }
        for e in entries
        if e.get("url")
    ]


def get_pool():
    """Return a copy of the current pool."""
    return list(_pool)


def set_fallback(url):
    """Set a legacy single-proxy fallback (backward compat)."""
    global _fallback
    _fallback = url or ""


def resolve_proxy(target_url):
    """Return the best proxy URL for *target_url*, or ``""`` for direct.

    Selection priority:
    1. Enabled entries whose ``platforms`` list matches the target domain
    2. Enabled entries with empty ``platforms`` (global catch-all)
    3. Legacy ``_fallback``
    4. ``""`` (direct)
    """
    platform = _detect_platform(target_url)

    # First pass: platform-specific proxies
    for entry in _pool:
        if not entry["enabled"] or not entry["url"]:
            continue
        if entry["platforms"] and platform and platform in entry["platforms"]:
            return entry["url"]

    # Second pass: catch-all proxies (empty platforms list)
    for entry in _pool:
        if not entry["enabled"] or not entry["url"]:
            continue
        if not entry["platforms"]:
            return entry["url"]

    return _fallback


def _detect_platform(url):
    """Detect the platform from a URL domain."""
    if not url:
        return ""
    for name, pattern in _PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return ""


def health_check(proxy_url, test_url="https://httpbin.org/ip", timeout=10):
    """Test a proxy by curling *test_url* through it.

    Returns ``(ok, latency_ms)`` — latency is round-trip in milliseconds,
    or -1 on failure.
    """
    if not proxy_url:
        return False, -1
    cmd = [
        "curl", "-s", "-o", os.devnull, "-w", "%{time_total}",
        "-x", proxy_url,
        "--connect-timeout", str(min(timeout, 10)),
        "--max-time", str(timeout),
        test_url,
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout + 2,
            creationflags=_CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            secs = float(r.stdout.decode("utf-8", errors="replace").strip())
            return True, int(secs * 1000)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return False, -1


def health_check_all(test_url="https://httpbin.org/ip", timeout=10):
    """Run health checks on all enabled pool entries. Updates
    ``last_health_ms`` in-place. Returns list of ``(label_or_url, ok, ms)``."""
    results = []
    for entry in _pool:
        if not entry["enabled"] or not entry["url"]:
            continue
        ok, ms = health_check(entry["url"], test_url, timeout)
        entry["last_health_ms"] = ms if ok else -1
        label = entry["label"] or entry["url"]
        results.append((label, ok, ms))
    return results

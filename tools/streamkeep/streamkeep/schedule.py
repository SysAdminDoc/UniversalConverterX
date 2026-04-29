"""Stream schedule fetcher — retrieves upcoming schedules from Twitch
for monitored channels and caches the results.

Uses the Twitch GQL API (same as the extractor) so no OAuth token
is needed.  Schedule data is cached per-channel in ``config["schedules"]``.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone

from .http import curl_post_json

_SAFE_LOGIN = re.compile(r'^[a-zA-Z0-9_]{1,50}$')

_TWITCH_GQL = "https://gql.twitch.tv/gql"
_TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_CACHE_TTL = 1800  # 30 minutes


def fetch_twitch_schedule(channel_login, log_fn=None):
    """Fetch upcoming scheduled streams for a Twitch channel.

    Returns a list of dicts: ``[{title, start_iso, end_iso, category, channel}]``
    """
    if not _SAFE_LOGIN.match(channel_login):
        if log_fn:
            log_fn(f"[SCHEDULE] Invalid channel login: {channel_login!r}")
        return []

    query = """
    {
      user(login: "%s") {
        channel {
          schedule {
            segments(first: 20) {
              edges {
                node {
                  title
                  startAt
                  endAt
                  categories { name }
                }
              }
            }
          }
        }
      }
    }
    """ % channel_login

    try:
        resp = curl_post_json(
            _TWITCH_GQL,
            {"query": query},
            extra_headers={"Client-ID": _TWITCH_CLIENT_ID},
        )
        data = json.loads(resp) if isinstance(resp, str) else resp
    except Exception as e:
        if log_fn:
            log_fn(f"[SCHEDULE] Failed to fetch schedule for {channel_login}: {e}")
        return []

    segments = []
    try:
        edges = data["data"]["user"]["channel"]["schedule"]["segments"]["edges"]
        for edge in edges:
            node = edge["node"]
            cats = node.get("categories") or []
            segments.append({
                "title": node.get("title") or "",
                "start_iso": node.get("startAt") or "",
                "end_iso": node.get("endAt") or "",
                "category": cats[0]["name"] if cats else "",
                "channel": channel_login,
            })
    except (KeyError, TypeError, IndexError):
        pass
    return segments


def refresh_schedules(monitor_entries, cache, log_fn=None):
    """Refresh cached schedules for all Twitch monitor entries.

    *cache* is ``config["schedules"]`` — mutated in place.
    Returns the updated cache dict.
    """
    now = time.time()
    for entry in monitor_entries:
        platform = getattr(entry, "platform", "") or ""
        if platform.lower() != "twitch":
            continue
        channel_id = getattr(entry, "channel_id", "") or ""
        if not channel_id:
            continue
        cached = cache.get(channel_id, {})
        if now - cached.get("fetched_at", 0) < _CACHE_TTL:
            continue
        segs = fetch_twitch_schedule(channel_id, log_fn=log_fn)
        cache[channel_id] = {
            "fetched_at": now,
            "segments": segs,
        }
    return cache


def get_all_segments(cache):
    """Flatten cached schedules into a single sorted list of segments."""
    out = []
    for _ch, data in (cache or {}).items():
        for seg in data.get("segments", []):
            out.append(seg)
    out.sort(key=lambda s: s.get("start_iso", ""))
    return out


def get_week_segments(cache, start_of_week=None):
    """Return segments for a 7-day window starting from *start_of_week*
    (defaults to the current Monday).

    Returns a list of ``(day_index_0_mon, hour_float, segment_dict)`` tuples.
    """
    if start_of_week is None:
        today = datetime.now(timezone.utc).date()
        start_of_week = today - timedelta(days=today.weekday())

    end = start_of_week + timedelta(days=7)
    result = []
    for seg in get_all_segments(cache):
        iso = seg.get("start_iso", "")
        if not iso:
            continue
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            local = dt.astimezone()  # convert to local timezone
            seg_date = local.date()
        except (ValueError, TypeError):
            continue
        if seg_date < start_of_week or seg_date >= end:
            continue
        day_idx = (seg_date - start_of_week).days
        hour_frac = local.hour + local.minute / 60.0
        result.append((day_idx, hour_frac, seg))
    return result

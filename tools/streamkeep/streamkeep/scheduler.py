"""Download speed scheduler — time-of-day bandwidth rules (F51).

Defines day/night/weekend speed tiers. A 60-second timer checks the
current time and updates the active speed limit. New downloads read
``get_active_limit()`` instead of the static config value.

Config schema::

    "speed_schedule": {
        "enabled": true,
        "day_start": 8,       # 08:00
        "day_end": 23,        # 23:00
        "day_limit": "2M",    # day limit (ffmpeg -maxrate format)
        "night_limit": "",    # night = unlimited
        "weekend_limit": ""   # weekends = unlimited (Sat/Sun)
    }
"""

from datetime import datetime


_schedule = {
    "enabled": False,
    "day_start": 8,
    "day_end": 23,
    "day_limit": "2M",
    "night_limit": "",
    "weekend_limit": "",
}

_static_limit = ""  # global fallback from config["rate_limit"]


def configure(schedule_dict, static_limit=""):
    """Load schedule config.  *static_limit* is the global rate_limit."""
    global _static_limit
    if isinstance(schedule_dict, dict):
        for k in list(_schedule):
            if k in schedule_dict:
                _schedule[k] = schedule_dict[k]
    _static_limit = static_limit or ""


def get_schedule():
    """Return a copy of the current schedule config."""
    return dict(_schedule)


def get_active_limit():
    """Return the speed limit that should be applied right now.

    Returns the appropriate limit string (``"2M"``, ``"500K"``, ``""`` for
    unlimited) based on the current time and schedule.

    If the schedule is disabled, returns the static global limit.
    """
    if not _schedule.get("enabled"):
        return _static_limit

    now = datetime.now()
    weekday = now.weekday()  # 0=Mon ... 6=Sun

    # Weekend override (Saturday=5, Sunday=6)
    if weekday >= 5:
        wl = _schedule.get("weekend_limit", "")
        if wl:
            return wl
        # If weekend_limit is empty, fall through to day/night logic

    hour = now.hour
    day_start = int(_schedule.get("day_start", 8) or 8)
    day_end = int(_schedule.get("day_end", 23) or 23)

    if day_start <= hour < day_end:
        return _schedule.get("day_limit", "") or _static_limit
    else:
        return _schedule.get("night_limit", "") or _static_limit

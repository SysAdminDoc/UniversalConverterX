"""Channel Statistics & Growth Trends — monitor poll logging + aggregation (F66).

Logs status transitions (live/offline) per monitored channel to a
``channel_polls`` table in library.db.  Aggregation queries provide
streams-per-week, average duration, and top game/category stats.

Usage::

    from streamkeep.channel_stats import log_transition, get_channel_stats
    log_transition("xqc", "twitch", "live", viewers=45000, title="Just Chatting")
    stats = get_channel_stats("xqc", weeks=8)
"""

import sqlite3
import time
from datetime import datetime, timedelta

from .paths import CONFIG_DIR

DB_PATH = CONFIG_DIR / "library.db"


def _ensure_table():
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS channel_polls (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                platform   TEXT NOT NULL DEFAULT '',
                timestamp  REAL NOT NULL,
                status     TEXT NOT NULL DEFAULT 'unknown',
                viewers    INTEGER NOT NULL DEFAULT 0,
                title      TEXT NOT NULL DEFAULT '',
                game       TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_cp_channel ON channel_polls(channel_id);
            CREATE INDEX IF NOT EXISTS idx_cp_ts ON channel_polls(timestamp);
        """)
        db.commit()
        db.close()
    except Exception:
        pass


def log_transition(channel_id, platform, status, *, viewers=0, title="", game=""):
    """Log a status transition (live->offline or offline->live).

    Should only be called on actual state changes, not every poll.
    """
    _ensure_table()
    try:
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
        db.execute(
            "INSERT INTO channel_polls (channel_id, platform, timestamp, status, viewers, title, game) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (channel_id, platform, time.time(), status, viewers, title[:200], game[:100]),
        )
        db.commit()
        db.close()
    except Exception:
        pass


def get_channel_stats(channel_id, weeks=8):
    """Aggregate stats for a channel over the last *weeks* weeks.

    Returns a dict::

        {
            "streams_total": int,
            "streams_per_week": float,
            "avg_duration_mins": float,
            "top_games": [(game, count), ...],
            "weekly_counts": [(week_label, count), ...],  # for sparkline
            "last_live": str,  # ISO timestamp or ""
        }
    """
    _ensure_table()
    cutoff = time.time() - weeks * 7 * 86400
    try:
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
        rows = db.execute(
            "SELECT timestamp, status, viewers, title, game FROM channel_polls "
            "WHERE channel_id=? AND timestamp>=? ORDER BY timestamp ASC",
            (channel_id, cutoff),
        ).fetchall()
        db.close()
    except Exception:
        rows = []

    if not rows:
        return {
            "streams_total": 0,
            "streams_per_week": 0,
            "avg_duration_mins": 0,
            "top_games": [],
            "weekly_counts": [],
            "last_live": "",
        }

    # Count stream sessions (each live->offline pair is one stream)
    sessions = []
    live_start = None
    live_game = ""
    for ts, status, viewers, title, game in rows:
        if status == "live" and live_start is None:
            live_start = ts
            live_game = game or ""
        elif status == "offline" and live_start is not None:
            sessions.append({
                "start": live_start,
                "end": ts,
                "duration": ts - live_start,
                "game": live_game,
            })
            live_start = None
            live_game = ""

    streams_total = len(sessions)
    streams_per_week = streams_total / max(weeks, 1)

    avg_duration = 0
    if sessions:
        avg_duration = sum(s["duration"] for s in sessions) / len(sessions) / 60

    # Top games
    from collections import Counter
    game_counts = Counter(s["game"] for s in sessions if s["game"])
    top_games = game_counts.most_common(5)

    # Weekly counts for sparkline
    now = datetime.now()
    weekly = {}
    for i in range(weeks):
        week_start = now - timedelta(weeks=weeks - i)
        label = week_start.strftime("%m/%d")
        weekly[label] = 0
    for s in sessions:
        d = datetime.fromtimestamp(s["start"])
        week_offset = (now - d).days // 7
        if 0 <= week_offset < weeks:
            label = (now - timedelta(weeks=week_offset)).strftime("%m/%d")
            if label in weekly:
                weekly[label] += 1
    weekly_counts = list(weekly.items())

    # Last live timestamp
    last_live = ""
    live_rows = [r for r in rows if r[1] == "live"]
    if live_rows:
        last_live = datetime.fromtimestamp(live_rows[-1][0]).isoformat(timespec="minutes")

    return {
        "streams_total": streams_total,
        "streams_per_week": round(streams_per_week, 1),
        "avg_duration_mins": round(avg_duration, 0),
        "top_games": top_games,
        "weekly_counts": weekly_counts,
        "last_live": last_live,
    }


def get_all_channel_summaries(weeks=4):
    """Return a dict of channel_id -> summary stats for all tracked channels."""
    _ensure_table()
    try:
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
        channels = db.execute(
            "SELECT DISTINCT channel_id FROM channel_polls"
        ).fetchall()
        db.close()
    except Exception:
        return {}
    return {ch[0]: get_channel_stats(ch[0], weeks) for ch in channels}

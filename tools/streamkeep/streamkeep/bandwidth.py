"""Bandwidth Usage Tracker — daily/monthly byte totals with optional caps (F64).

Singleton tracker incremented by download workers via ``add_bytes()``.
Persists daily totals to the SQLite library.db. Status bar shows running
total; optional caps pause the queue on threshold.

Usage::

    from streamkeep.bandwidth import tracker
    tracker.add_bytes(1024 * 1024)  # 1 MB
    print(tracker.today_bytes, tracker.month_bytes)
"""

import sqlite3
import threading
from datetime import date

from .paths import CONFIG_DIR

DB_PATH = CONFIG_DIR / "library.db"
_lock = threading.Lock()


class BandwidthTracker:
    """Tracks cumulative bytes transferred, persisted per-day in SQLite."""

    def __init__(self):
        self._today_bytes = 0
        self._today_key = ""
        self._daily_cap = 0        # bytes, 0 = unlimited
        self._monthly_cap = 0      # bytes, 0 = unlimited
        self._cap_action = "warn"  # "warn" | "pause"
        self._cap_hit = False
        self._ensure_table()
        self._load_today()

    def _ensure_table(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
            db.execute("""
                CREATE TABLE IF NOT EXISTS bandwidth_daily (
                    day   TEXT PRIMARY KEY,
                    bytes INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.commit()
            db.close()
        except Exception:
            pass

    def _load_today(self):
        key = date.today().isoformat()
        self._today_key = key
        try:
            db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
            row = db.execute(
                "SELECT bytes FROM bandwidth_daily WHERE day=?", (key,)
            ).fetchone()
            db.close()
            self._today_bytes = row[0] if row else 0
        except Exception:
            self._today_bytes = 0

    def configure(self, daily_cap_gb=0, monthly_cap_gb=0, action="warn"):
        self._daily_cap = int(daily_cap_gb * 1024 * 1024 * 1024)
        self._monthly_cap = int(monthly_cap_gb * 1024 * 1024 * 1024)
        self._cap_action = action

    def add_bytes(self, n):
        """Record *n* bytes transferred. Thread-safe."""
        if n <= 0:
            return
        with _lock:
            key = date.today().isoformat()
            if key != self._today_key:
                self._persist()
                self._today_key = key
                self._today_bytes = 0
                self._cap_hit = False
            self._today_bytes += n

    def flush(self):
        """Persist current totals to DB."""
        with _lock:
            self._persist()

    def _persist(self):
        try:
            db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
            db.execute(
                "INSERT OR REPLACE INTO bandwidth_daily (day, bytes) VALUES (?, ?)",
                (self._today_key, self._today_bytes),
            )
            db.commit()
            db.close()
        except Exception:
            pass

    @property
    def today_bytes(self):
        return self._today_bytes

    @property
    def month_bytes(self):
        """Sum of all days in the current month."""
        month_prefix = date.today().strftime("%Y-%m")
        try:
            db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
            row = db.execute(
                "SELECT COALESCE(SUM(bytes), 0) FROM bandwidth_daily WHERE day LIKE ?",
                (month_prefix + "%",),
            ).fetchone()
            db.close()
            return (row[0] if row else 0) + self._today_bytes
        except Exception:
            return self._today_bytes

    @property
    def daily_cap_exceeded(self):
        if self._daily_cap <= 0:
            return False
        return self._today_bytes >= self._daily_cap

    @property
    def monthly_cap_exceeded(self):
        if self._monthly_cap <= 0:
            return False
        return self.month_bytes >= self._monthly_cap

    @property
    def cap_action(self):
        return self._cap_action

    def format_today(self):
        """Return human-readable today's usage string."""
        return _fmt(self._today_bytes)

    def format_month(self):
        """Return human-readable month's usage string."""
        return _fmt(self.month_bytes)

    def daily_history(self, days=30):
        """Return list of (day_str, bytes) for the last N days."""
        try:
            db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=5)
            rows = db.execute(
                "SELECT day, bytes FROM bandwidth_daily ORDER BY day DESC LIMIT ?",
                (days,),
            ).fetchall()
            db.close()
            return [(r[0], r[1]) for r in reversed(rows)]
        except Exception:
            return []


def _fmt(n):
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


# Module-level singleton
tracker = BandwidthTracker()

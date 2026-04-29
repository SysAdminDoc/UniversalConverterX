"""SQLite library database — history, monitor channels, download queue.

Replaces the list-of-dicts sections of config.json with properly indexed
SQLite tables.  Config.json retains only user preferences and UI state.

Database lives at ``%APPDATA%/StreamKeep/library.db`` (or ``data/library.db``
in portable mode).  WAL journal, ``check_same_thread=False`` so worker
threads can read.  All writes go through module-level functions that
serialise behind a lock.

Schema version is stored in ``PRAGMA user_version`` and bumped on each
migration so future schema changes are orderly.
"""

import json
import sqlite3
import threading

from .paths import CONFIG_DIR

DB_PATH = CONFIG_DIR / "library.db"
SCHEMA_VERSION = 1

_write_lock = threading.Lock()


# ── Connection management ───────────────────────────────────────────

def _connect(readonly=False):
    """Return a connection.  Caller is responsible for closing."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,
        timeout=10,
    )
    db.row_factory = sqlite3.Row
    if not readonly:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    """Create tables if they don't exist.  Idempotent."""
    db = _connect()
    try:
        v = db.execute("PRAGMA user_version").fetchone()[0]
        if v < SCHEMA_VERSION:
            _apply_schema(db)
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.commit()
    finally:
        db.close()


def _apply_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT NOT NULL DEFAULT '',
            platform            TEXT NOT NULL DEFAULT '',
            title               TEXT NOT NULL DEFAULT '',
            channel             TEXT NOT NULL DEFAULT '',
            quality             TEXT NOT NULL DEFAULT '',
            size                TEXT NOT NULL DEFAULT '',
            path                TEXT NOT NULL DEFAULT '',
            url                 TEXT NOT NULL DEFAULT '',
            favorite            INTEGER NOT NULL DEFAULT 0,
            watched             INTEGER NOT NULL DEFAULT 0,
            watch_position_secs REAL    NOT NULL DEFAULT 0.0,
            bookmarks           TEXT    NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_history_platform ON history(platform);
        CREATE INDEX IF NOT EXISTS idx_history_channel  ON history(channel);
        CREATE INDEX IF NOT EXISTS idx_history_date     ON history(date);
        CREATE INDEX IF NOT EXISTS idx_history_url      ON history(url);

        CREATE TABLE IF NOT EXISTS monitor_channels (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            url                         TEXT NOT NULL UNIQUE,
            platform                    TEXT NOT NULL DEFAULT '',
            channel_id                  TEXT NOT NULL DEFAULT '',
            interval_secs               INTEGER NOT NULL DEFAULT 120,
            auto_record                 INTEGER NOT NULL DEFAULT 0,
            subscribe_vods              INTEGER NOT NULL DEFAULT 0,
            archive_ids                 TEXT    NOT NULL DEFAULT '[]',
            override_output_dir         TEXT    NOT NULL DEFAULT '',
            override_quality_pref       TEXT    NOT NULL DEFAULT '',
            override_filename_template  TEXT    NOT NULL DEFAULT '',
            schedule_start_hhmm         TEXT    NOT NULL DEFAULT '',
            schedule_end_hhmm           TEXT    NOT NULL DEFAULT '',
            schedule_days_mask          INTEGER NOT NULL DEFAULT 0,
            retention_keep_last         INTEGER NOT NULL DEFAULT 0,
            filter_keywords             TEXT    NOT NULL DEFAULT '',
            override_pp_preset          TEXT    NOT NULL DEFAULT '',
            auto_upgrade                INTEGER NOT NULL DEFAULT 0,
            min_upgrade_quality         TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS download_queue (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            position INTEGER NOT NULL DEFAULT 0,
            data     TEXT    NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_queue_pos ON download_queue(position);
    """)


# ── History CRUD ────────────────────────────────────────────────────

def load_history():
    """Return all history entries as a list of dicts, oldest-first."""
    db = _connect(readonly=True)
    try:
        rows = db.execute(
            "SELECT * FROM history ORDER BY id ASC"
        ).fetchall()
        return [_row_to_history_dict(r) for r in rows]
    finally:
        db.close()


def save_history_entry(entry_dict):
    """Insert a single history entry. Returns the new row id."""
    with _write_lock:
        db = _connect()
        try:
            cur = db.execute("""
                INSERT INTO history
                    (date, platform, title, channel, quality, size, path, url,
                     favorite, watched, watch_position_secs, bookmarks)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                str(entry_dict.get("date", "")),
                str(entry_dict.get("platform", "")),
                str(entry_dict.get("title", "")),
                str(entry_dict.get("channel", "")),
                str(entry_dict.get("quality", "")),
                str(entry_dict.get("size", "")),
                str(entry_dict.get("path", "")),
                str(entry_dict.get("url", "")),
                int(bool(entry_dict.get("favorite", False))),
                int(bool(entry_dict.get("watched", False))),
                float(entry_dict.get("watch_position_secs", 0) or 0),
                json.dumps(entry_dict.get("bookmarks", []) or []),
            ))
            db.commit()
            return cur.lastrowid
        finally:
            db.close()


def update_history_entry(entry_id, fields):
    """Update specific fields on a history row by id.

    *fields* is a dict of column_name -> value.  Only known columns
    are applied (unknown keys are silently ignored).
    """
    allowed = {
        "date", "platform", "title", "channel", "quality", "size",
        "path", "url", "favorite", "watched", "watch_position_secs",
        "bookmarks",
    }
    parts = []
    vals = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "bookmarks":
            v = json.dumps(v if isinstance(v, list) else [])
        elif k in ("favorite", "watched"):
            v = int(bool(v))
        elif k == "watch_position_secs":
            v = float(v or 0)
        else:
            v = str(v)
        parts.append(f"{k}=?")
        vals.append(v)
    if not parts:
        return
    vals.append(int(entry_id))
    with _write_lock:
        db = _connect()
        try:
            db.execute(
                f"UPDATE history SET {', '.join(parts)} WHERE id=?",
                vals,
            )
            db.commit()
        finally:
            db.close()


def delete_history_entries(entry_ids):
    """Delete history rows by id list."""
    if not entry_ids:
        return
    with _write_lock:
        db = _connect()
        try:
            placeholders = ",".join("?" for _ in entry_ids)
            db.execute(
                f"DELETE FROM history WHERE id IN ({placeholders})",
                [int(i) for i in entry_ids],
            )
            db.commit()
        finally:
            db.close()


def clear_history():
    """Delete all history entries."""
    with _write_lock:
        db = _connect()
        try:
            db.execute("DELETE FROM history")
            db.commit()
        finally:
            db.close()


def history_count():
    """Return total number of history entries."""
    db = _connect(readonly=True)
    try:
        return db.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    finally:
        db.close()


# ── Monitor channels CRUD ──────────────────────────────────────────

def load_monitor_channels():
    """Return all monitor channels as a list of dicts."""
    db = _connect(readonly=True)
    try:
        rows = db.execute(
            "SELECT * FROM monitor_channels ORDER BY id ASC"
        ).fetchall()
        return [_row_to_monitor_dict(r) for r in rows]
    finally:
        db.close()


def save_monitor_channel(entry_dict):
    """Insert or replace a monitor channel (keyed by url). Returns row id."""
    with _write_lock:
        db = _connect()
        try:
            cur = db.execute("""
                INSERT OR REPLACE INTO monitor_channels
                    (url, platform, channel_id, interval_secs, auto_record,
                     subscribe_vods, archive_ids,
                     override_output_dir, override_quality_pref,
                     override_filename_template,
                     schedule_start_hhmm, schedule_end_hhmm, schedule_days_mask,
                     retention_keep_last, filter_keywords, override_pp_preset,
                     auto_upgrade, min_upgrade_quality)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                str(entry_dict.get("url", "")),
                str(entry_dict.get("platform", "")),
                str(entry_dict.get("channel_id", "")),
                int(entry_dict.get("interval_secs", 120) or 120),
                int(bool(entry_dict.get("auto_record", False))),
                int(bool(entry_dict.get("subscribe_vods", False))),
                json.dumps(entry_dict.get("archive_ids", []) or []),
                str(entry_dict.get("override_output_dir", "") or ""),
                str(entry_dict.get("override_quality_pref", "") or ""),
                str(entry_dict.get("override_filename_template", "") or ""),
                str(entry_dict.get("schedule_start_hhmm", "") or ""),
                str(entry_dict.get("schedule_end_hhmm", "") or ""),
                int(entry_dict.get("schedule_days_mask", 0) or 0),
                int(entry_dict.get("retention_keep_last", 0) or 0),
                str(entry_dict.get("filter_keywords", "") or ""),
                str(entry_dict.get("override_pp_preset", "") or ""),
                int(bool(entry_dict.get("auto_upgrade", False))),
                str(entry_dict.get("min_upgrade_quality", "") or ""),
            ))
            db.commit()
            return cur.lastrowid
        finally:
            db.close()


def save_all_monitor_channels(entries_dicts):
    """Replace all monitor channels atomically."""
    with _write_lock:
        db = _connect()
        try:
            db.execute("DELETE FROM monitor_channels")
            for d in entries_dicts:
                db.execute("""
                    INSERT INTO monitor_channels
                        (url, platform, channel_id, interval_secs, auto_record,
                         subscribe_vods, archive_ids,
                         override_output_dir, override_quality_pref,
                         override_filename_template,
                         schedule_start_hhmm, schedule_end_hhmm,
                         schedule_days_mask, retention_keep_last,
                         filter_keywords, override_pp_preset,
                         auto_upgrade, min_upgrade_quality)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(d.get("url", "")),
                    str(d.get("platform", "")),
                    str(d.get("channel_id", "")),
                    int(d.get("interval_secs", 120) or 120),
                    int(bool(d.get("auto_record", False))),
                    int(bool(d.get("subscribe_vods", False))),
                    json.dumps(d.get("archive_ids", []) or []),
                    str(d.get("override_output_dir", "") or ""),
                    str(d.get("override_quality_pref", "") or ""),
                    str(d.get("override_filename_template", "") or ""),
                    str(d.get("schedule_start_hhmm", "") or ""),
                    str(d.get("schedule_end_hhmm", "") or ""),
                    int(d.get("schedule_days_mask", 0) or 0),
                    int(d.get("retention_keep_last", 0) or 0),
                    str(d.get("filter_keywords", "") or ""),
                    str(d.get("override_pp_preset", "") or ""),
                    int(bool(d.get("auto_upgrade", False))),
                    str(d.get("min_upgrade_quality", "") or ""),
                ))
            db.commit()
        finally:
            db.close()


def delete_monitor_channel(url):
    """Remove a monitor channel by URL."""
    with _write_lock:
        db = _connect()
        try:
            db.execute("DELETE FROM monitor_channels WHERE url=?", (url,))
            db.commit()
        finally:
            db.close()


# ── Download queue CRUD ─────────────────────────────────────────────

def load_queue():
    """Return all queue items as a list of dicts, ordered by position."""
    db = _connect(readonly=True)
    try:
        rows = db.execute(
            "SELECT data FROM download_queue ORDER BY position ASC"
        ).fetchall()
        items = []
        for r in rows:
            try:
                items.append(json.loads(r[0]))
            except (json.JSONDecodeError, TypeError):
                pass
        return items
    finally:
        db.close()


def save_queue(items):
    """Replace the entire queue atomically.  Each item is a dict."""
    with _write_lock:
        db = _connect()
        try:
            db.execute("DELETE FROM download_queue")
            for i, item in enumerate(items):
                db.execute(
                    "INSERT INTO download_queue (position, data) VALUES (?,?)",
                    (i, json.dumps(item, ensure_ascii=False)),
                )
            db.commit()
        finally:
            db.close()


# ── Row conversion helpers ──────────────────────────────────────────

def _row_to_history_dict(row):
    d = dict(row)
    d["favorite"] = bool(d.get("favorite", 0))
    d["watched"] = bool(d.get("watched", 0))
    d["watch_position_secs"] = float(d.get("watch_position_secs", 0) or 0)
    try:
        d["bookmarks"] = json.loads(d.get("bookmarks", "[]") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["bookmarks"] = []
    return d


def _row_to_monitor_dict(row):
    d = dict(row)
    d["auto_record"] = bool(d.get("auto_record", 0))
    d["subscribe_vods"] = bool(d.get("subscribe_vods", 0))
    d["auto_upgrade"] = bool(d.get("auto_upgrade", 0))
    try:
        d["archive_ids"] = json.loads(d.get("archive_ids", "[]") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["archive_ids"] = []
    return d


# ── Migration from config.json ──────────────────────────────────────

def migrate_from_config(cfg):
    """One-time migration: move history, monitor_channels, and download_queue
    from the JSON config dict into SQLite.  Returns True if migration ran,
    False if already done or nothing to migrate.

    The caller should remove the migrated keys from cfg and re-save it
    so they don't persist in JSON.
    """
    if not any(k in cfg for k in ("history", "monitor_channels", "download_queue")):
        return False

    init_db()
    db = _connect(readonly=True)
    try:
        existing_history = db.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        existing_channels = db.execute("SELECT COUNT(*) FROM monitor_channels").fetchone()[0]
        existing_queue = db.execute("SELECT COUNT(*) FROM download_queue").fetchone()[0]
    finally:
        db.close()

    if existing_history > 0 or existing_channels > 0 or existing_queue > 0:
        # DB already has data — don't re-migrate.  Strip keys from config.
        for k in ("history", "monitor_channels", "download_queue"):
            cfg.pop(k, None)
        return False

    # Migrate history
    history = cfg.get("history", [])
    if isinstance(history, list):
        with _write_lock:
            db = _connect()
            try:
                for h in history:
                    if not isinstance(h, dict):
                        continue
                    db.execute("""
                        INSERT INTO history
                            (date, platform, title, channel, quality, size,
                             path, url, favorite, watched,
                             watch_position_secs, bookmarks)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        str(h.get("date", "")),
                        str(h.get("platform", "")),
                        str(h.get("title", "")),
                        str(h.get("channel", "")),
                        str(h.get("quality", "")),
                        str(h.get("size", "")),
                        str(h.get("path", "")),
                        str(h.get("url", "")),
                        int(bool(h.get("favorite", False))),
                        int(bool(h.get("watched", False))),
                        float(h.get("watch_position_secs", 0) or 0),
                        json.dumps(h.get("bookmarks", []) or []),
                    ))
                db.commit()
            finally:
                db.close()

    # Migrate monitor channels
    channels = cfg.get("monitor_channels", [])
    if isinstance(channels, list):
        entries = []
        for ch in channels:
            if not isinstance(ch, dict) or "url" not in ch:
                continue
            entries.append({
                "url": ch.get("url", ""),
                "platform": ch.get("platform", ""),
                "channel_id": ch.get("channel_id", ""),
                "interval_secs": ch.get("interval", 120),
                "auto_record": ch.get("auto_record", False),
                "subscribe_vods": ch.get("subscribe_vods", False),
                "archive_ids": ch.get("archive_ids", []),
                "override_output_dir": ch.get("override_output_dir", ""),
                "override_quality_pref": ch.get("override_quality_pref", ""),
                "override_filename_template": ch.get("override_filename_template", ""),
                "schedule_start_hhmm": ch.get("schedule_start_hhmm", ""),
                "schedule_end_hhmm": ch.get("schedule_end_hhmm", ""),
                "schedule_days_mask": ch.get("schedule_days_mask", 0),
                "retention_keep_last": ch.get("retention_keep_last", 0),
                "filter_keywords": ch.get("filter_keywords", ""),
                "override_pp_preset": ch.get("override_pp_preset", ""),
                "auto_upgrade": ch.get("auto_upgrade", False),
                "min_upgrade_quality": ch.get("min_upgrade_quality", ""),
            })
        if entries:
            save_all_monitor_channels(entries)

    # Migrate download queue
    queue = cfg.get("download_queue", [])
    if isinstance(queue, list) and queue:
        save_queue(queue)

    # Strip migrated keys so they don't persist in JSON
    for k in ("history", "monitor_channels", "download_queue"):
        cfg.pop(k, None)

    return True

"""Full-text transcript search — SQLite FTS5 index over generated
transcripts (.srt, .vtt, .transcript.json).

The index lives in ``%APPDATA%/StreamKeep/search.db``.  Each row stores
a recording path, text segment, and start/end timestamps in seconds.
"""

import json
import os
import re
import sqlite3
import threading

from .paths import CONFIG_DIR

DB_PATH = CONFIG_DIR / "search.db"
SCHEMA_VERSION = 2
_SCHEMA_LOCK = threading.Lock()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    with _SCHEMA_LOCK:
        _ensure_schema(db)
    return db


def _ensure_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS search_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transcript_segments (
            rowid          INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_path TEXT NOT NULL,
            text           TEXT NOT NULL,
            start_sec      REAL NOT NULL DEFAULT 0,
            end_sec        REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ts_path ON transcript_segments(recording_path);
        CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
            recording_path, text, start_sec, end_sec,
            content='transcript_segments',
            content_rowid='rowid'
        );
        CREATE TRIGGER IF NOT EXISTS transcript_segments_ai AFTER INSERT ON transcript_segments BEGIN
            INSERT INTO transcript_fts(rowid, recording_path, text, start_sec, end_sec)
            VALUES (new.rowid, new.recording_path, new.text, new.start_sec, new.end_sec);
        END;
        CREATE TRIGGER IF NOT EXISTS transcript_segments_ad AFTER DELETE ON transcript_segments BEGIN
            INSERT INTO transcript_fts(transcript_fts, rowid, recording_path, text, start_sec, end_sec)
            VALUES ('delete', old.rowid, old.recording_path, old.text, old.start_sec, old.end_sec);
        END;
        CREATE TRIGGER IF NOT EXISTS transcript_segments_au AFTER UPDATE ON transcript_segments BEGIN
            INSERT INTO transcript_fts(transcript_fts, rowid, recording_path, text, start_sec, end_sec)
            VALUES ('delete', old.rowid, old.recording_path, old.text, old.start_sec, old.end_sec);
            INSERT INTO transcript_fts(rowid, recording_path, text, start_sec, end_sec)
            VALUES (new.rowid, new.recording_path, new.text, new.start_sec, new.end_sec);
        END;
    """)
    row = db.execute(
        "SELECT value FROM search_meta WHERE key = 'schema_version'"
    ).fetchone()
    try:
        current_version = int(row[0]) if row else 0
    except (TypeError, ValueError):
        current_version = 0
    if current_version < SCHEMA_VERSION:
        db.execute("INSERT INTO transcript_fts(transcript_fts) VALUES('rebuild')")
        db.execute(
            "INSERT OR REPLACE INTO search_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        db.commit()


def _parse_srt(path):
    """Parse an .srt file into segments: [(start_sec, end_sec, text)]."""
    segments = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return segments

    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        ts_line = lines[1]
        m = re.match(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            ts_line,
        )
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = " ".join(lines[2:]).strip()
        if text:
            segments.append((start, end, text))
    return segments


def _parse_vtt(path):
    """Parse a .vtt file into segments."""
    segments = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return segments

    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = re.match(
                r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*"
                r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})",
                line,
            )
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                text = " ".join(lines[i + 1:]).strip()
                if text:
                    segments.append((start, end, text))
                break
    return segments


def _parse_transcript_json(path):
    """Parse a .transcript.json file."""
    segments = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return segments

    items = data if isinstance(data, list) else data.get("segments", [])
    if not isinstance(items, list):
        return segments
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text", "").strip()
        try:
            start = float(item.get("start", 0) or 0)
            end = float(item.get("end", start + 1) or (start + 1))
        except (TypeError, ValueError):
            continue
        if text:
            segments.append((start, end, text))
    return segments


def index_recording(recording_path):
    """Index all transcript files found in a recording directory.

    Runs in the calling thread. Safe to call multiple times — removes
    old entries before re-indexing.
    """
    if not recording_path:
        return 0

    all_segments = []
    db = _connect()
    try:
        db.execute(
            "DELETE FROM transcript_segments WHERE recording_path = ?",
            (recording_path,),
        )
        if os.path.isdir(recording_path):
            for fname in os.listdir(recording_path):
                fpath = os.path.join(recording_path, fname)
                fl = fname.lower()
                if fl.endswith(".srt"):
                    all_segments.extend(_parse_srt(fpath))
                elif fl.endswith(".vtt"):
                    all_segments.extend(_parse_vtt(fpath))
                elif fl.endswith(".transcript.json"):
                    all_segments.extend(_parse_transcript_json(fpath))
            if all_segments:
                db.executemany(
                    "INSERT INTO transcript_segments (recording_path, text, start_sec, end_sec) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (recording_path, text, start, end)
                        for start, end, text in all_segments
                    ],
                )
        db.commit()
    finally:
        db.close()
    return len(all_segments)


def search_transcripts(query, limit=100):
    """Search indexed transcripts. Returns list of dicts:
    ``[{recording_path, text, start_sec, end_sec}]``
    """
    query = str(query or "").strip()
    if not query:
        return []
    try:
        limit = max(1, int(limit or 100))
    except (TypeError, ValueError):
        limit = 100
    db = _connect()
    try:
        rows = db.execute(
            "SELECT s.recording_path, s.text, s.start_sec, s.end_sec "
            "FROM transcript_fts f "
            "JOIN transcript_segments s ON s.rowid = f.rowid "
            "WHERE transcript_fts MATCH ? "
            "ORDER BY bm25(transcript_fts), s.rowid "
            "LIMIT ?",
            (query, limit),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        db.close()
    return [
        {"recording_path": r[0], "text": r[1], "start_sec": r[2], "end_sec": r[3]}
        for r in rows
    ]


def index_all_async(history, log_fn=None):
    """Index all recordings in history in a background thread."""
    def _run():
        total = 0
        for h in history:
            path = getattr(h, "path", "") or ""
            if path and os.path.isdir(path):
                n = index_recording(path)
                total += n
        if log_fn:
            log_fn(f"[SEARCH] Indexed {total} transcript segments across {len(history)} recordings.")
    threading.Thread(target=_run, daemon=True).start()

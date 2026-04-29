"""Tag system — SQLite-backed many-to-many tags for recordings.

Tags are stored in ``%APPDATA%/StreamKeep/tags.db`` (separate from the
JSON config to avoid bloat).  Two categories: *system* tags (auto-generated
from metadata) and *user* tags (manually assigned).

Smart collections are JSON rule sets stored in ``config["collections"]``.
"""

import sqlite3

from .paths import CONFIG_DIR

DB_PATH = CONFIG_DIR / "tags.db"

# Duration bucket boundaries in seconds
_DURATION_BUCKETS = [
    (3600, "short (<1h)"),
    (7200, "medium (1-2h)"),
    (14400, "long (2-4h)"),
    (999999, "marathon (4h+)"),
]


def _connect():
    """Open (and initialize if needed) the tags database."""
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tags (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            kind    TEXT NOT NULL DEFAULT 'user',
            UNIQUE(name, kind)
        );
        CREATE TABLE IF NOT EXISTS recording_tags (
            recording_path TEXT NOT NULL,
            tag_id         INTEGER NOT NULL REFERENCES tags(id),
            PRIMARY KEY (recording_path, tag_id)
        );
        CREATE INDEX IF NOT EXISTS idx_rt_path ON recording_tags(recording_path);
        CREATE INDEX IF NOT EXISTS idx_rt_tag  ON recording_tags(tag_id);
    """)
    return db


def get_or_create_tag(db, name, kind="user"):
    """Return the tag ID, creating the tag if it doesn't exist."""
    row = db.execute(
        "SELECT id FROM tags WHERE name=? AND kind=?", (name, kind)
    ).fetchone()
    if row:
        return row[0]
    cur = db.execute(
        "INSERT INTO tags (name, kind) VALUES (?, ?)", (name, kind)
    )
    db.commit()
    return cur.lastrowid


def tag_recording(db, path, tag_name, kind="user"):
    """Add a tag to a recording (by path)."""
    tag_id = get_or_create_tag(db, tag_name, kind)
    try:
        db.execute(
            "INSERT OR IGNORE INTO recording_tags (recording_path, tag_id) VALUES (?, ?)",
            (path, tag_id),
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass


def untag_recording(db, path, tag_name, kind="user"):
    """Remove a tag from a recording."""
    row = db.execute(
        "SELECT id FROM tags WHERE name=? AND kind=?", (tag_name, kind)
    ).fetchone()
    if row:
        db.execute(
            "DELETE FROM recording_tags WHERE recording_path=? AND tag_id=?",
            (path, row[0]),
        )
        db.commit()


def get_tags_for_recording(db, path):
    """Return list of ``(tag_name, kind)`` for a recording."""
    rows = db.execute("""
        SELECT t.name, t.kind FROM tags t
        JOIN recording_tags rt ON rt.tag_id = t.id
        WHERE rt.recording_path = ?
        ORDER BY t.kind, t.name
    """, (path,)).fetchall()
    return [(r[0], r[1]) for r in rows]


def get_all_tags(db):
    """Return all tags as ``[(name, kind, count)]``."""
    rows = db.execute("""
        SELECT t.name, t.kind, COUNT(rt.recording_path) AS cnt
        FROM tags t LEFT JOIN recording_tags rt ON rt.tag_id = t.id
        GROUP BY t.id ORDER BY t.kind, t.name
    """).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def get_recordings_by_tag(db, tag_name):
    """Return list of recording paths that have the given tag."""
    rows = db.execute("""
        SELECT rt.recording_path FROM recording_tags rt
        JOIN tags t ON t.id = rt.tag_id
        WHERE t.name = ?
    """, (tag_name,)).fetchall()
    return [r[0] for r in rows]


def auto_tag_recording(db, path, info=None, vod_info=None):
    """Generate system tags for a recording based on metadata."""
    if not path:
        return

    # Platform tag
    platform = getattr(info, "platform", "") if info else ""
    if platform:
        tag_recording(db, path, f"platform:{platform}", kind="system")

    # Channel tag
    channel = ""
    if vod_info and getattr(vod_info, "channel", ""):
        channel = vod_info.channel
    elif info and getattr(info, "channel", ""):
        channel = info.channel
    if channel:
        tag_recording(db, path, f"channel:{channel}", kind="system")

    # Resolution tag
    if info:
        for q in (info.qualities or []):
            res = getattr(q, "resolution", "") or ""
            if "1080" in res:
                tag_recording(db, path, "res:1080p", kind="system")
                break
            elif "720" in res:
                tag_recording(db, path, "res:720p", kind="system")
                break
            elif "480" in res:
                tag_recording(db, path, "res:480p", kind="system")
                break

    # Duration bucket
    total_secs = getattr(info, "total_secs", 0) if info else 0
    if total_secs and total_secs > 0:
        for threshold, label in _DURATION_BUCKETS:
            if total_secs < threshold:
                tag_recording(db, path, f"duration:{label}", kind="system")
                break

    # Live tag
    if info and getattr(info, "is_live", False):
        tag_recording(db, path, "type:live", kind="system")
    else:
        tag_recording(db, path, "type:vod", kind="system")


# ── Smart Collections ────────────────────────────────────────────────

def evaluate_collection(rule, history):
    """Evaluate a smart collection rule against history entries.

    A *rule* is a dict: ``{field, op, value}``.
    Supported fields: platform, channel, quality, title, watched, favorite.
    Supported ops: eq, ne, contains, gt, lt.

    Returns matching HistoryEntry objects.
    """
    results = []
    field = rule.get("field", "")
    op = rule.get("op", "eq")
    value = rule.get("value", "")

    for h in history:
        entry_val = str(getattr(h, field, "") or "").lower()
        cmp_val = str(value).lower()

        if op == "eq" and entry_val == cmp_val:
            results.append(h)
        elif op == "ne" and entry_val != cmp_val:
            results.append(h)
        elif op == "contains" and cmp_val in entry_val:
            results.append(h)
        elif op == "gt":
            try:
                if float(entry_val) > float(cmp_val):
                    results.append(h)
            except (ValueError, TypeError):
                pass
        elif op == "lt":
            try:
                if float(entry_val) < float(cmp_val):
                    results.append(h)
            except (ValueError, TypeError):
                pass
    return results


def evaluate_collection_rules(rules, history, logic="and"):
    """Evaluate multiple rules with AND/OR logic."""
    if not rules:
        return list(history)
    if logic == "or":
        seen = set()
        results = []
        for rule in rules:
            for h in evaluate_collection(rule, history):
                hid = id(h)
                if hid not in seen:
                    seen.add(hid)
                    results.append(h)
        return results
    else:  # AND
        result_set = None
        for rule in rules:
            matches = set(id(h) for h in evaluate_collection(rule, history))
            if result_set is None:
                result_set = matches
            else:
                result_set &= matches
        if result_set is None:
            return list(history)
        return [h for h in history if id(h) in result_set]

"""Platform Account Manager — credential store for authenticated APIs (F48).

Stores per-platform auth tokens/keys in the SQLite library.db with mandatory,
entropy-bound DPAPI encryption. Legacy base64 and plaintext values remain
readable so they can be replaced, but new writes fail closed.

Supported platforms and their credential types:
  - Twitch:  OAuth token (for Schedule API, subscriber VODs)
  - YouTube: API key (for Data API quota management)
  - Kick:    Session token (for authenticated API)
  - Generic: Custom header key-value pairs per domain
"""

import base64
import json
import sqlite3
import threading

from . import dpapi
from .paths import CONFIG_DIR

DB_PATH = CONFIG_DIR / "library.db"
_WRITE_LOCK = threading.Lock()


# ── Encryption helpers ──────────────────────────────────────────────

def _encrypt(plaintext):
    """Encrypt *plaintext* using the shared entropy-bound DPAPI helper."""
    if not plaintext:
        return ""
    return dpapi.encrypt_text(plaintext, description="UCX-StreamKeep account")


def _decrypt(stored):
    """Decrypt a value produced by ``_encrypt()``."""
    if not stored:
        return ""
    if dpapi.is_encrypted_text(stored):
        try:
            return dpapi.decrypt_text(stored)
        except (dpapi.DpapiUnavailable, OSError, UnicodeDecodeError, ValueError):
            return ""
    if stored.startswith("b64:"):
        try:
            return base64.b64decode(stored[4:]).decode("utf-8")
        except Exception:
            pass
    # Raw plaintext fallback (legacy or migration)
    return stored


# ── Database operations ─────────────────────────────────────────────

def _ensure_table():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    db.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            platform    TEXT PRIMARY KEY,
            credential  TEXT NOT NULL DEFAULT '',
            extra       TEXT NOT NULL DEFAULT '{}'
        )
    """)
    db.commit()
    db.close()


def get_credential(platform):
    """Return the decrypted credential for *platform*, or ''."""
    _ensure_table()
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    try:
        row = db.execute(
            "SELECT credential FROM accounts WHERE platform=?", (platform,)
        ).fetchone()
        if row:
            return _decrypt(row[0])
        return ""
    finally:
        db.close()


def set_credential(platform, value):
    """Store an encrypted credential and return ``(succeeded, message)``.

    Encryption happens before the database transaction, so a DPAPI failure
    leaves any previously stored credential untouched.
    """
    _ensure_table()
    try:
        enc = _encrypt(value)
    except (dpapi.DpapiUnavailable, OSError) as exc:
        return False, f"Credential was not saved because DPAPI protection failed: {exc}"
    with _WRITE_LOCK:
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
        try:
            db.execute(
                "INSERT INTO accounts (platform, credential, extra) VALUES (?,?,?) "
                "ON CONFLICT(platform) DO UPDATE SET credential=excluded.credential",
                (platform, enc, "{}"),
            )
            db.commit()
        finally:
            db.close()
    return True, "Credential saved with DPAPI protection."


def delete_credential(platform):
    """Remove the credential for *platform*."""
    _ensure_table()
    with _WRITE_LOCK:
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
        try:
            db.execute("DELETE FROM accounts WHERE platform=?", (platform,))
            db.commit()
        finally:
            db.close()


def list_platforms():
    """Return a list of platforms that have stored credentials."""
    _ensure_table()
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    try:
        rows = db.execute("SELECT platform FROM accounts ORDER BY platform").fetchall()
        return [r[0] for r in rows]
    finally:
        db.close()


def get_extra(platform):
    """Return the JSON extra data dict for *platform*."""
    _ensure_table()
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    try:
        row = db.execute(
            "SELECT extra FROM accounts WHERE platform=?", (platform,)
        ).fetchone()
        if row:
            try:
                return json.loads(row[0] or "{}")
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    finally:
        db.close()


def set_extra(platform, data):
    """Store extra JSON data alongside a credential."""
    _ensure_table()
    payload = json.dumps(data, ensure_ascii=False)
    with _WRITE_LOCK:
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
        try:
            db.execute(
                "INSERT INTO accounts (platform, credential, extra) VALUES (?,?,?) "
                "ON CONFLICT(platform) DO UPDATE SET extra=excluded.extra",
                (platform, "", payload),
            )
            db.commit()
        finally:
            db.close()


# ── Platform-specific helpers ───────────────────────────────────────

PLATFORMS = {
    "twitch": {
        "label": "Twitch",
        "hint": "OAuth token (from Twitch developer console)",
        "header_name": "Authorization",
        "header_prefix": "Bearer ",
    },
    "youtube": {
        "label": "YouTube",
        "hint": "API key (from Google Cloud Console)",
        "header_name": "",
        "header_prefix": "",
    },
    "kick": {
        "label": "Kick",
        "hint": "Session token (from browser cookies)",
        "header_name": "Authorization",
        "header_prefix": "Bearer ",
    },
}


def get_auth_header(platform):
    """Return a ``{header_name: header_value}`` dict for *platform*,
    or ``{}`` if no credential is stored."""
    info = PLATFORMS.get(platform, {})
    if not info or not info.get("header_name"):
        return {}
    cred = get_credential(platform)
    if not cred:
        return {}
    prefix = info.get("header_prefix", "")
    return {info["header_name"]: prefix + cred}


def credential_status(platform):
    """Return a status string: 'authenticated', 'none', or 'unknown'."""
    cred = get_credential(platform)
    if not cred:
        return "none"
    return "authenticated"

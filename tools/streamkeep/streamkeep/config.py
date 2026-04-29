"""Config persistence + rotating log file.

Free-form JSON dict for now. A typed dataclass wrapper lands in Phase 3b.
"""

import json
import os
import threading
from datetime import datetime

from .paths import CONFIG_DIR, CONFIG_FILE, LOG_FILE, LOG_FILE_BACKUP, LOG_FILE_MAX_BYTES

# Serializes config writes and log rotation across threads (QTimer polling,
# clipboard monitor, download workers) so two writers can't corrupt the file.
_SAVE_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()


def load_config():
    """Load the config JSON.

    Falls back to the last-known-good ``config.json.bak`` if the primary
    file is missing or corrupted. Returns ``{}`` on any unrecoverable error.
    """
    for candidate in (
        CONFIG_FILE,
        CONFIG_FILE.with_suffix(".json.bak"),
    ):
        try:
            if not candidate.exists():
                continue
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def save_config(cfg):
    """Persist the config dict atomically. Silent on error.

    Writes to `config.json.tmp` then renames into place so a mid-write
    crash leaves the previous config intact. Also rotates a last-known-good
    sibling `config.json.bak` before each successful replace.
    """
    with _SAVE_LOCK:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            payload = json.dumps(cfg, indent=2, ensure_ascii=False)
            # Write + fsync so a power loss doesn't leave a zero-byte tmp.
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except (OSError, AttributeError):
                    pass
            # Keep a one-deep backup before the atomic replace.
            if CONFIG_FILE.exists():
                try:
                    bak = CONFIG_FILE.with_suffix(".json.bak")
                    if bak.exists():
                        bak.unlink()
                    CONFIG_FILE.replace(bak)
                except OSError:
                    pass
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            # Best-effort cleanup of stale tmp on failure.
            try:
                tmp = CONFIG_FILE.with_suffix(".json.tmp")
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def write_log_line(msg):
    """Append a timestamped line to the rotating log file.
    Rotates streamkeep.log -> streamkeep.log.1 when it exceeds the cap."""
    with _LOG_LOCK:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            try:
                if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_FILE_MAX_BYTES:
                    if LOG_FILE_BACKUP.exists():
                        try:
                            LOG_FILE_BACKUP.unlink()
                        except OSError:
                            pass
                    try:
                        LOG_FILE.rename(LOG_FILE_BACKUP)
                    except (FileNotFoundError, OSError):
                        pass
            except OSError:
                pass
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

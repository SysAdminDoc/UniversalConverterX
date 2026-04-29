"""Auto-cleanup lifecycle policies — time-based, size-based, and favorites-exempt
retention rules for recordings.

Lifecycle evaluation always uses ``send2trash`` (recycle bin) — never
permanent delete.  A cleanup preview must be shown before execution.

Config keys (under ``config["lifecycle"]``):
    enabled, max_days (0=disabled), max_total_gb (0=disabled),
    delete_watched (bool), favorites_exempt (bool)
"""

import os
import time

DEFAULT_POLICY = {
    "enabled": False,
    "max_days": 0,
    "max_total_gb": 0,
    "delete_watched": False,
    "favorites_exempt": True,
}


def _normalize_path(path):
    path = str(path or "").strip()
    if not path:
        return ""
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def _dir_size_bytes(path):
    """Total size in bytes of all files in *path* (non-recursive top-level)."""
    total = 0
    try:
        for f in os.scandir(path):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def removal_real_paths(removals):
    """Return the normalized real paths represented by a cleanup list."""
    paths = set()
    for h, _reason in removals or []:
        real_path = _normalize_path(getattr(h, "path", "") or "")
        if real_path:
            paths.add(real_path)
    return paths


def evaluate_cleanup(history, policy, output_dirs=None):
    """Return a list of ``(HistoryEntry, reason)`` tuples that should be
    cleaned up according to *policy*.

    Does NOT perform any deletion — call ``execute_cleanup()`` for that.
    ``output_dirs`` is an optional set/list of directories to consider;
    if None, all history entries are evaluated.
    """
    if not policy or not policy.get("enabled"):
        return []

    now = time.time()
    max_days = int(policy.get("max_days", 0) or 0)
    max_gb = float(policy.get("max_total_gb", 0) or 0)
    delete_watched = bool(policy.get("delete_watched"))
    fav_exempt = bool(policy.get("favorites_exempt", True))
    output_dirs = {_normalize_path(p) for p in (output_dirs or []) if p}

    candidates_by_path = {}
    total_bytes = 0

    for h in history:
        path = getattr(h, "path", "") or ""
        if not path:
            continue
        real_path = _normalize_path(path)
        if not real_path:
            continue
        if output_dirs and real_path not in output_dirs:
            continue
        candidate = candidates_by_path.get(real_path)
        if candidate is None:
            entry_bytes = _dir_size_bytes(path) if os.path.isdir(path) else 0
            candidate = {
                "entry": h,
                "path": path,
                "real_path": real_path,
                "size": entry_bytes,
                "favorite": False,
                "watched": False,
            }
            candidates_by_path[real_path] = candidate
            total_bytes += entry_bytes
        candidate["favorite"] = candidate["favorite"] or bool(getattr(h, "favorite", False))
        candidate["watched"] = candidate["watched"] or bool(getattr(h, "watched", False))

    candidates = []
    for candidate in candidates_by_path.values():
        if fav_exempt and candidate["favorite"]:
            continue
        candidates.append(candidate)

    to_remove = []
    scheduled_paths = set()

    # Rule 1: max age
    if max_days > 0:
        cutoff = now - max_days * 86400
        for candidate in candidates:
            h = candidate["entry"]
            path = candidate["path"]
            real_path = candidate["real_path"]
            if not path or not os.path.isdir(path):
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime < cutoff and real_path not in scheduled_paths:
                to_remove.append((h, f"older than {max_days} days"))
                scheduled_paths.add(real_path)

    # Rule 2: delete watched
    if delete_watched:
        for candidate in candidates:
            h = candidate["entry"]
            real_path = candidate["real_path"]
            if candidate["watched"] and real_path not in scheduled_paths:
                to_remove.append((h, "watched"))
                scheduled_paths.add(real_path)

    # Rule 3: max total size — remove oldest watched first, then oldest
    if max_gb > 0:
        max_bytes = max_gb * 1024 ** 3
        if total_bytes > max_bytes:
            excess = total_bytes - max_bytes
            # Sort candidates by oldest mtime first
            sized = []
            for candidate in candidates:
                h = candidate["entry"]
                sz = candidate["size"]
                real_path = candidate["real_path"]
                if real_path in scheduled_paths:
                    continue  # already slated
                path = candidate["path"]
                try:
                    mtime = os.path.getmtime(path) if path else 0
                except OSError:
                    mtime = 0
                watched_rank = 0 if candidate["watched"] else 1
                sized.append((watched_rank, mtime, h, sz, real_path))
            sized.sort()  # watched first, then oldest first
            freed = 0
            for _watched_rank, _mt, h, sz, real_path in sized:
                if freed >= excess:
                    break
                to_remove.append((h, f"storage exceeds {max_gb:.0f} GB"))
                scheduled_paths.add(real_path)
                freed += sz

    return to_remove


def execute_cleanup(removals, log_fn=None):
    """Send each recording directory in *removals* to the recycle bin.

    *removals* is the list returned by ``evaluate_cleanup()``.
    Returns the count of successfully recycled recordings.
    """
    try:
        from send2trash import send2trash as _send2trash
    except ImportError:
        if log_fn:
            log_fn(
                "[LIFECYCLE] send2trash not installed — refusing to delete. "
                "Install with: pip install send2trash"
            )
        return 0

    removed = 0
    seen_paths = set()
    for h, reason in removals:
        path = getattr(h, "path", "") or ""
        if not path or not os.path.isdir(path):
            continue
        real_path = _normalize_path(path)
        if real_path in seen_paths:
            continue
        seen_paths.add(real_path)
        try:
            _send2trash(path)
            removed += 1
            if log_fn:
                log_fn(f"[LIFECYCLE] Recycled: {os.path.basename(path)} ({reason})")
        except Exception as e:
            if log_fn:
                log_fn(f"[LIFECYCLE] Failed to recycle {path}: {e}")
    return removed

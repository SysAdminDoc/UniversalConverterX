"""Storage scanner — walks the output tree, groups by platform/channel,
computes sizes, feeds the Storage tab.

Read-only. Deletion is handled in the UI via send2trash so the user sees a
confirm dialog and the deletion is recycle-bin-first (never permanent).
"""

import json
import os
from dataclasses import dataclass, field


# Metadata sidecars written by streamkeep.metadata.MetadataSaver live next
# to the media file. When present they carry platform/channel authoritatively
# and we prefer them over directory-name heuristics.
METADATA_SIDECAR = "metadata.json"
MEDIA_EXTS = {
    ".mp4", ".mkv", ".webm", ".mov", ".ts", ".avi", ".flv",
    ".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".aac",
}


@dataclass
class StorageFile:
    path: str = ""
    size: int = 0
    mtime: float = 0.0


@dataclass
class StorageGroup:
    """One leaf group — typically a VOD folder: a collection of media files
    plus optional sidecars with shared metadata."""
    dir_path: str = ""
    title: str = ""
    platform: str = ""
    channel: str = ""
    files: list = field(default_factory=list)   # list[StorageFile]
    total_size: int = 0
    newest_mtime: float = 0.0


@dataclass
class StorageScan:
    total_size: int = 0
    total_files: int = 0
    by_platform: dict = field(default_factory=dict)   # platform -> total_size
    by_channel: dict = field(default_factory=dict)    # "platform/channel" -> total_size
    groups: list = field(default_factory=list)        # list[StorageGroup]


def _read_sidecar(dir_path):
    path = os.path.join(dir_path, METADATA_SIDECAR)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _platform_from_path(dir_path, root):
    """Best-effort platform inference from a subdirectory path when no
    metadata.json is present. Falls back to 'Unknown'."""
    rel = os.path.relpath(dir_path, root) if root else dir_path
    head = rel.split(os.sep, 1)[0].lower() if rel else ""
    for p in ("kick", "twitch", "rumble", "youtube", "soundcloud", "reddit"):
        if p in head:
            return p.capitalize()
    return "Unknown"


def scan_storage(root, max_depth=3):
    """Walk `root` and return a StorageScan. Skips hidden dirs and dot-files."""
    scan = StorageScan()
    if not root or not os.path.isdir(root):
        return scan
    base_depth = root.rstrip(os.sep).count(os.sep)
    # group_key -> StorageGroup
    groups = {}
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        # Prune hidden / dot subdirs to keep the scan cheap on big archives.
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        media_here = [
            fn for fn in filenames
            if os.path.splitext(fn)[1].lower() in MEDIA_EXTS
            and not fn.startswith(".")
        ]
        if not media_here:
            continue
        meta = _read_sidecar(dirpath)
        platform = str(meta.get("platform") or _platform_from_path(dirpath, root)) or "Unknown"
        channel = str(meta.get("channel") or os.path.basename(os.path.dirname(dirpath))) or "Unknown"
        title = str(meta.get("title") or os.path.basename(dirpath))
        group = groups.get(dirpath)
        if group is None:
            group = StorageGroup(
                dir_path=dirpath, title=title,
                platform=platform, channel=channel,
            )
            groups[dirpath] = group
        for fn in media_here:
            path = os.path.join(dirpath, fn)
            try:
                st = os.stat(path)
            except OSError:
                continue
            sf = StorageFile(path=path, size=st.st_size, mtime=st.st_mtime)
            group.files.append(sf)
            group.total_size += sf.size
            if sf.mtime > group.newest_mtime:
                group.newest_mtime = sf.mtime
            scan.total_size += sf.size
            scan.total_files += 1
            scan.by_platform[platform] = scan.by_platform.get(platform, 0) + sf.size
            ck = f"{platform}/{channel}"
            scan.by_channel[ck] = scan.by_channel.get(ck, 0) + sf.size
    # Sort groups by newest mtime descending — what the user most recently
    # wrote shows up first.
    scan.groups = sorted(
        groups.values(), key=lambda g: g.newest_mtime, reverse=True
    )
    return scan

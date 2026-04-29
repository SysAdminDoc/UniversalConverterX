"""Recording Notes & Annotations — .notes.md sidecars (F71).

Saves free-form Markdown notes alongside recordings. Auto-generates a
template on first open. Indexed for search via the global search bar (F45).

Usage::

    text = load_notes("/path/to/recording/")
    save_notes("/path/to/recording/", "My notes here")
"""

import os
from datetime import datetime


NOTES_FILENAME = ".notes.md"


def notes_path(recording_dir):
    """Return the .notes.md path for a recording directory."""
    if not recording_dir:
        return ""
    return os.path.join(recording_dir, NOTES_FILENAME)


def load_notes(recording_dir):
    """Load notes for a recording. Returns '' if none exist."""
    path = notes_path(recording_dir)
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def save_notes(recording_dir, text):
    """Save notes to .notes.md. Returns True on success."""
    path = notes_path(recording_dir)
    if not path:
        return False
    try:
        os.makedirs(recording_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except OSError:
        return False


def delete_notes(recording_dir):
    """Delete .notes.md if it exists."""
    path = notes_path(recording_dir)
    if path and os.path.isfile(path):
        try:
            os.unlink(path)
            return True
        except OSError:
            pass
    return False


def has_notes(recording_dir):
    """Check if a recording has notes."""
    path = notes_path(recording_dir)
    return bool(path and os.path.isfile(path) and os.path.getsize(path) > 0)


def generate_template(title="", channel="", platform="", date="",
                      quality="", duration=""):
    """Generate a template for new notes."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {title or 'Untitled Recording'}",
        "",
    ]
    meta = []
    if channel:
        meta.append(f"- **Channel:** {channel}")
    if platform:
        meta.append(f"- **Platform:** {platform}")
    if date:
        meta.append(f"- **Date:** {date}")
    if quality:
        meta.append(f"- **Quality:** {quality}")
    if duration:
        meta.append(f"- **Duration:** {duration}")
    if meta:
        lines.extend(meta)
        lines.append("")

    lines.extend([
        "## Notes",
        "",
        f"*Created {now}*",
        "",
        "<!-- Add your notes below -->",
        "",
        "",
    ])
    return "\n".join(lines)


def search_notes(recording_dirs, query):
    """Search notes content across multiple recording directories.

    Returns list of ``(recording_dir, matching_line)`` tuples.
    """
    if not query:
        return []
    query_lower = query.lower()
    results = []
    for d in recording_dirs:
        text = load_notes(d)
        if not text:
            continue
        for line in text.splitlines():
            if query_lower in line.lower():
                results.append((d, line.strip()))
                break  # one match per recording
    return results

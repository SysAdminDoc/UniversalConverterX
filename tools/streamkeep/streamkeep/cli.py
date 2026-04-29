"""CLI / headless mode for StreamKeep (F42).

Provides ``--url``, ``--server``, and ``--list-extractors`` subcommands.
Uses QCoreApplication (no display server required) so existing QThread-based
workers and pyqtSignal infrastructure work without modification.

Usage::

    python StreamKeep.py --url URL [--quality best|1080p|720p|...] [--output DIR]
    python StreamKeep.py --server [--port PORT] [--bind 0.0.0.0]
    python StreamKeep.py --list-extractors
"""

import argparse
import os
import sys

# QCoreApplication drives the event loop without requiring a display
# server.  This lets us reuse QThread workers and pyqtSignal infra.
from PyQt6.QtCore import QCoreApplication

from . import VERSION
from .config import load_config, write_log_line
from .extractors.base import Extractor as _ExtBase
from .paths import _CREATE_NO_WINDOW
from . import db as _db


def _print_progress(text):
    """Overwrite the current console line with *text*."""
    cols = os.get_terminal_size(fallback=(80, 24)).columns
    sys.stdout.write("\r" + text[:cols].ljust(cols) + "\r")
    sys.stdout.flush()


def _print_line(text):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _check_ffmpeg():
    import subprocess
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return False


# ── --url handler ───────────────────────────────────────────────────

def _run_download(args):
    """Resolve *args.url* and download it."""
    if not _check_ffmpeg():
        print("Error: ffmpeg not found in PATH.")
        sys.exit(1)

    app = QCoreApplication(sys.argv)
    _db.init_db()

    from .workers import FetchWorker, DownloadWorker

    cfg = load_config()
    output_dir = args.output or cfg.get("output_dir", "")
    if not output_dir:
        from .utils import default_output_dir
        output_dir = default_output_dir()

    quality_pref = (args.quality or "best").lower()

    _print_line(f"StreamKeep v{VERSION} (CLI)")
    _print_line(f"URL:     {args.url}")
    _print_line(f"Output:  {output_dir}")
    _print_line(f"Quality: {quality_pref}")
    _print_line("")

    state = {"phase": "fetch", "info": None, "exit_code": 0, "fw": None, "dw": None}

    # ── Fetch ──
    fw = FetchWorker(args.url)
    state["fw"] = fw  # prevent GC while event loop runs

    def on_fetch_done(info):
        state["info"] = info
        state["phase"] = "download"
        _print_line(
            f"Resolved: {info.platform} / {info.channel} / {info.title}"
        )
        _print_line(
            f"Duration: {info.duration_str or 'live'}  |  "
            f"Qualities: {len(info.qualities)}"
        )
        if not info.qualities:
            _print_line("Error: No downloadable qualities found.")
            state["exit_code"] = 1
            app.quit()
            return

        # Pick quality
        qi = _pick_quality(info.qualities, quality_pref)
        _print_line(f"Selected: {qi.name} ({qi.resolution or qi.format_type})")
        _print_line("")

        # Build segments
        from .hls import parse_hls_playlist
        segments = []
        if qi.format_type == "hls" and qi.url:
            segments = parse_hls_playlist(qi.url)
        if not segments:
            segments = [(0, info.title or "stream", 0, info.total_secs)]

        # Start download
        dw = DownloadWorker(qi.url, segments, output_dir, qi.format_type)
        dw.audio_url = qi.audio_url
        dw.ytdlp_source = qi.ytdlp_source
        dw.ytdlp_format = qi.ytdlp_format
        if args.rate_limit:
            dw.rate_limit = args.rate_limit
        state["dw"] = dw  # prevent GC while event loop runs

        dw.progress.connect(lambda si, pct, txt: _print_progress(
            f"[{pct:3d}%] {txt}"
        ))
        dw.log.connect(lambda msg: write_log_line(msg))
        dw.error.connect(lambda si, msg: _print_line(f"Error: {msg}"))
        dw.segment_done.connect(lambda si, path: _print_line(
            f"  segment {si} done"
        ))
        dw.all_done.connect(lambda: _on_download_done(state, app, output_dir))
        dw.start()

    def on_fetch_error(msg):
        _print_line(f"Fetch error: {msg}")
        state["exit_code"] = 1
        app.quit()

    fw.finished.connect(on_fetch_done)
    fw.error.connect(on_fetch_error)
    fw.log.connect(lambda msg: write_log_line(msg))
    _print_line("Fetching...")
    fw.start()

    ret = app.exec() or state["exit_code"]
    # Wait for any in-flight workers to finish before exit
    for key in ("fw", "dw"):
        w = state.get(key)
        if w is not None and w.isRunning():
            w.wait(3000)
    sys.exit(ret)


def _on_download_done(state, app, output_dir):
    _print_progress("")
    _print_line(f"\nDownload complete -> {output_dir}")
    app.quit()


def _pick_quality(qualities, pref):
    """Pick a quality entry matching *pref*."""
    if not qualities:
        return None
    pref = pref.lower().strip()
    if pref in ("best", "source", "highest", ""):
        return qualities[0]
    if pref == "lowest":
        return qualities[-1]
    # Try matching by name (e.g. "1080p", "720p")
    for q in qualities:
        if pref in (q.name or "").lower() or pref in (q.resolution or "").lower():
            return q
    # Fallback to best
    return qualities[0]


# ── --server handler ────────────────────────────────────────────────

def _run_server(args):
    """Start the REST API / web remote server headlessly."""
    app = QCoreApplication(sys.argv)
    _db.init_db()

    from .local_server import LocalCompanionServer

    bind_lan = args.bind == "0.0.0.0"
    server = LocalCompanionServer(bind_lan=bind_lan)
    if args.port:
        server.port = int(args.port)

    # In server-only mode, received URLs are just logged
    server.url_received.connect(
        lambda url, action: _print_line(f"[{action}] {url}")
    )
    server.start()

    _print_line(f"StreamKeep v{VERSION} — server mode")
    _print_line(f"Listening on {'0.0.0.0' if bind_lan else '127.0.0.1'}:{server.port}")
    _print_line(f"Token: {server.token}")
    _print_line(f"Web UI: http://{'0.0.0.0' if bind_lan else '127.0.0.1'}:{server.port}/")
    _print_line("Press Ctrl+C to stop.")

    sys.exit(app.exec())


# ── --list-extractors ───────────────────────────────────────────────

def _list_extractors():
    """Print all registered extractors and exit."""
    # Import all extractors so they auto-register
    __import__("streamkeep.extractors")
    _print_line(f"StreamKeep v{VERSION} — supported platforms:")
    _print_line("")
    for cls in _ExtBase._registry:
        patterns = ", ".join(
            getattr(p, "pattern", str(p)) for p in cls.URL_PATTERNS[:3]
        )
        _print_line(f"  {cls.NAME:<16s}  {patterns}")
    _print_line(f"\n  ({len(_ExtBase._registry)} extractors registered)")


# ── Entry point ─────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="StreamKeep",
        description=f"StreamKeep v{VERSION} — multi-platform stream/VOD downloader",
    )
    p.add_argument("--version", action="version", version=f"StreamKeep v{VERSION}")

    sub = p.add_subparsers(dest="command")

    # -- download --
    dl = sub.add_parser("download", aliases=["dl"], help="Download a URL")
    dl.add_argument("url", help="URL to download")
    dl.add_argument("-q", "--quality", default="best",
                    help="Quality preference: best, 1080p, 720p, 480p, lowest")
    dl.add_argument("-o", "--output", default="",
                    help="Output directory (default: config or ~/Videos/StreamKeep)")
    dl.add_argument("--rate-limit", default="",
                    help="Bandwidth limit (e.g. 5M, 500K)")

    # -- server --
    srv = sub.add_parser("server", help="Start REST API / web remote UI")
    srv.add_argument("--port", type=int, default=0,
                     help="Port to bind (default: random)")
    srv.add_argument("--bind", default="127.0.0.1",
                     help="Bind address (127.0.0.1 or 0.0.0.0)")

    # -- list-extractors --
    sub.add_parser("extractors", help="List supported platforms")

    # Legacy flat args for backward compat
    p.add_argument("--url", dest="legacy_url", default="",
                   help=argparse.SUPPRESS)
    p.add_argument("--server", dest="legacy_server", action="store_true",
                   help=argparse.SUPPRESS)
    p.add_argument("--list-extractors", dest="legacy_list", action="store_true",
                   help=argparse.SUPPRESS)

    return p


def run_cli(argv=None):
    """Parse args and dispatch to the appropriate handler."""
    p = build_parser()
    args = p.parse_args(argv)

    # Handle legacy flat args
    if args.legacy_list:
        _list_extractors()
        sys.exit(0)
    if args.legacy_server:
        args.command = "server"
        if not hasattr(args, "port"):
            args.port = 0
        if not hasattr(args, "bind"):
            args.bind = "127.0.0.1"
    if args.legacy_url:
        args.command = "download"
        args.url = args.legacy_url
        if not hasattr(args, "quality"):
            args.quality = "best"
        if not hasattr(args, "output"):
            args.output = ""
        if not hasattr(args, "rate_limit"):
            args.rate_limit = ""

    if args.command in ("download", "dl"):
        _run_download(args)
    elif args.command == "server":
        _run_server(args)
    elif args.command == "extractors":
        _list_extractors()
    else:
        p.print_help()
        sys.exit(0)


def has_cli_args():
    """Return True if sys.argv contains CLI subcommands or legacy flags."""
    if len(sys.argv) <= 1:
        return False
    cli_triggers = {
        "download", "dl", "server", "extractors",
        "--url", "--server", "--list-extractors", "--version", "--help", "-h",
    }
    return any(arg in cli_triggers for arg in sys.argv[1:])

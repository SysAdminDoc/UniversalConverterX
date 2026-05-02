"""StreamKeep sidecar — NDJSON CLI shim for the UCX Downloader module.

v2.1 scope: yt-dlp covers 1000+ sites out of the box (YouTube, Twitch VODs,
Vimeo, X/Twitter, Facebook, Instagram, Reddit, podcasts, direct URLs, etc.).
StreamKeep's native Kick/Rumble/SoundCloud extractors are deferred to v2.2+
when we wire them in via the existing streamkeep package.

Contract: see ../README.md (sidecar contract) and ../../README.md (parent).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    yt_dlp = None  # surface a clean error from main()


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_ffmpeg() -> str | None:
    here = Path(__file__).resolve().parent
    for c in [os.environ.get("FFMPEG_PATH"), shutil.which("ffmpeg"),
              str(here / "ffmpeg.exe"), str(here.parent / "_bin" / "ffmpeg.exe")]:
        if c and Path(c).is_file():
            return c
    return None


# ─── Probe ───────────────────────────────────────────────────────────────────

def op_probe(args: argparse.Namespace) -> int:
    if yt_dlp is None:
        return fail("missing_yt_dlp", "yt-dlp is not installed in the sidecar runtime.")
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(args.url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        return fail("probe_failed", str(exc))
    except Exception as exc:  # pylint: disable=broad-except
        return fail("probe_failed", f"{type(exc).__name__}: {exc}")

    if not info:
        return fail("probe_failed", "yt-dlp returned no info.")

    # Trim formats to the essentials so the C# host can render a quality picker.
    formats = []
    for f in (info.get("formats") or []):
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution"),
            "height": f.get("height"),
            "fps": f.get("fps"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "tbr": f.get("tbr"),
        })

    emit("complete", probe={
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "extractor": info.get("extractor"),
        "extractor_key": info.get("extractor_key"),
        "thumbnail": info.get("thumbnail"),
        "is_live": info.get("is_live", False),
        "webpage_url": info.get("webpage_url"),
        "formats": formats,
    })
    return 0


# ─── Download ────────────────────────────────────────────────────────────────

class _ProgressBridge:
    """yt-dlp progress_hook that translates dict events to NDJSON."""

    def __init__(self) -> None:
        self.last_pct = -1.0
        self.output_path: str | None = None

    def __call__(self, d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100.0) if total else 0.0
            if pct - self.last_pct < 0.5:
                return
            self.last_pct = pct
            speed = d.get("speed")
            eta = d.get("eta")
            stage = "downloading"
            if d.get("fragment_index") is not None:
                stage = f"fragment {d['fragment_index']}/{d.get('fragment_count', '?')}"
            emit("progress",
                 percent=round(pct, 1),
                 stage=stage,
                 eta_seconds=int(eta) if isinstance(eta, (int, float)) else None,
                 speed_bps=int(speed) if isinstance(speed, (int, float)) else None,
                 downloaded_bytes=done,
                 total_bytes=total or None)
        elif status == "finished":
            self.output_path = d.get("filename")
            emit("log", level="info", message=f"Downloaded → {self.output_path}")
        elif status == "error":
            emit("log", level="error", message=d.get("error") or "Unknown yt-dlp error")


def op_download(args: argparse.Namespace) -> int:
    if yt_dlp is None:
        return fail("missing_yt_dlp", "yt-dlp is not installed in the sidecar runtime.")

    ffmpeg = find_ffmpeg()
    if not ffmpeg and args.merge:
        emit("log", level="warn", message="FFmpeg not found — separate audio/video streams won't be merged.")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    bridge = _ProgressBridge()

    fmt = args.format
    if args.audio_only:
        fmt = "bestaudio/best"

    ydl_opts: dict = {
        "outtmpl": str(output_dir / "%(title)s [%(id)s].%(ext)s"),
        "format": fmt,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "progress_hooks": [bridge],
        "merge_output_format": args.merge_format if args.merge else None,
    }
    if ffmpeg:
        ydl_opts["ffmpeg_location"] = ffmpeg
    if args.audio_only:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": args.audio_codec,
            "preferredquality": str(args.audio_quality),
        }]
    if args.subtitles:
        ydl_opts["writesubtitles"] = True
        ydl_opts["subtitleslangs"] = ["en", "all"] if args.subtitles == "all" else [args.subtitles]
        ydl_opts["embedsubtitles"] = args.embed_subtitles

    # SponsorBlock — yt-dlp natively supports this. The postprocessor reaches
    # out to api.sponsor.ajay.app for segment data; only fires when the user
    # explicitly opts in via the flag. Charter-aligned per the user-initiated
    # network policy in ROADMAP.md (Items 7/45/48 share that pattern).
    if args.sponsorblock:
        cats = {c.strip() for c in (args.sponsorblock_categories or "").split(",") if c.strip()}
        if not cats:
            cats = {"sponsor", "selfpromo", "interaction"}  # safe default
        if args.sponsorblock == "remove":
            ydl_opts["sponsorblock_remove"] = cats
            emit("log", level="info",
                 message=f"SponsorBlock: removing categories {sorted(cats)}")
        else:  # "mark"
            ydl_opts["sponsorblock_mark"] = cats
            emit("log", level="info",
                 message=f"SponsorBlock: marking categories as chapters {sorted(cats)}")

    emit("progress", percent=0, stage="resolving", eta_seconds=None)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            rc = ydl.download([args.url])
    except yt_dlp.utils.DownloadError as exc:
        return fail("download_failed", str(exc))
    except Exception as exc:  # pylint: disable=broad-except
        return fail("download_failed", f"{type(exc).__name__}: {exc}")

    if rc != 0:
        return fail("yt_dlp_nonzero", f"yt-dlp returned {rc}")

    if not bridge.output_path or not Path(bridge.output_path).is_file():
        # Find the most-recent file in output_dir as a fallback.
        candidates = sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            bridge.output_path = str(candidates[0])

    size = Path(bridge.output_path).stat().st_size if bridge.output_path else 0
    emit("complete", output=bridge.output_path, size_bytes=size)
    return 0


# ─── Entry ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="streamkeep-sidecar",
                                description="UCX StreamKeep sidecar — yt-dlp-backed downloader with NDJSON progress.")
    sub = p.add_subparsers(dest="op", required=True)

    probe = sub.add_parser("probe", help="Probe a URL (no download) and emit metadata + format list")
    probe.add_argument("--url", required=True)

    dl = sub.add_parser("download", help="Download a URL")
    dl.add_argument("--url", required=True)
    dl.add_argument("--output-dir", required=True)
    dl.add_argument("--format", default="bv*+ba/b",
                    help="yt-dlp format selector (default: best video + best audio merged, or fallback to best combined)")
    dl.add_argument("--merge", action="store_true",
                    help="Merge separate video/audio streams via ffmpeg")
    dl.add_argument("--merge-format", default="mp4")
    dl.add_argument("--audio-only", action="store_true")
    dl.add_argument("--audio-codec", default="mp3")
    dl.add_argument("--audio-quality", type=int, default=192)
    dl.add_argument("--subtitles", help="Subtitle language ('en', 'all', or a 2-letter code)")
    dl.add_argument("--embed-subtitles", action="store_true")
    dl.add_argument("--sponsorblock",
                    choices=["mark", "remove"],
                    help="Apply SponsorBlock segments to the download — 'mark' adds chapter markers, "
                         "'remove' cuts the segments out of the final file. Requires network access to "
                         "api.sponsor.ajay.app via yt-dlp's built-in postprocessor.")
    dl.add_argument("--sponsorblock-categories", dest="sponsorblock_categories",
                    default="sponsor,selfpromo,interaction",
                    help="Comma-separated SponsorBlock categories to mark/remove "
                         "(default: sponsor,selfpromo,interaction). Available: "
                         "sponsor, selfpromo, interaction, intro, outro, preview, music_offtopic, filler.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "download":
            return op_download(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

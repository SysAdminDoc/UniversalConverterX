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
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    yt_dlp = None  # surface a clean error from main()


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
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


def _tool_candidates(name: str, env_name: str) -> list[str | None]:
    suffix = ".exe" if os.name == "nt" else ""
    exe_name = name + suffix
    here = Path(__file__).resolve().parent
    frozen_dir = Path(sys.executable).resolve().parent
    tools_bin = os.environ.get("UCX_TOOLS_BIN")
    return [
        os.environ.get(env_name),
        str(Path(tools_bin) / exe_name) if tools_bin else None,
        str(frozen_dir / exe_name),
        str(here / exe_name),
        str(here.parent / "bin" / exe_name),
        str(here.parent / "_bin" / exe_name),
        shutil.which(name),
    ]


def _find_tool(name: str, env_name: str) -> str | None:
    for candidate in _tool_candidates(name, env_name):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def find_ytdlp() -> str | None:
    """Locate the managed portable yt-dlp update before the embedded fallback."""
    return _find_tool("yt-dlp", "UCX_YTDLP_PATH")


def find_deno() -> str | None:
    return _find_tool("deno", "UCX_DENO_PATH")


def _hidden_process_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _parse_version(value: str) -> tuple[int, ...] | None:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)+)(?!\d)", value or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def deno_runtime_status() -> dict:
    """Return a stable health payload for yt-dlp's recommended EJS runtime."""
    path = find_deno()
    if not path:
        return {
            "runtime": "deno",
            "active": False,
            "path": None,
            "version": None,
            "minimum_version": "2.3.0",
            "detail": "Deno is not installed. Install it from Downloader health or Settings > Converter Tools for full YouTube format extraction.",
        }

    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            creationflags=_hidden_process_flags(),
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        parsed = _parse_version(output)
        version = ".".join(str(part) for part in parsed) if parsed else None
        active = proc.returncode == 0 and parsed is not None and parsed >= (2, 3, 0)
        detail = (
            f"Deno {version} is active for yt-dlp EJS challenges."
            if active
            else f"Deno {version or 'unknown'} is unsupported; update to 2.3.0 or newer."
        )
        return {
            "runtime": "deno",
            "active": active,
            "path": path,
            "version": version,
            "minimum_version": "2.3.0",
            "detail": detail,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "runtime": "deno",
            "active": False,
            "path": path,
            "version": None,
            "minimum_version": "2.3.0",
            "detail": f"Deno was found but could not be verified: {exc}",
        }


def emit_runtime_status() -> dict:
    status = deno_runtime_status()
    emit("runtime_status", **status, yt_dlp_backend="portable" if find_ytdlp() else "embedded")
    if not status["active"]:
        emit("log", level="warn", message=status["detail"])
    return status


def _cookie_file() -> str | None:
    try:
        from streamkeep import cookies
        path = cookies.cookies_file_path()
        return path if path and Path(path).is_file() else None
    except (ImportError, OSError):
        return None


def _configure_python_ytdlp(options: dict, runtime: dict) -> None:
    if runtime["active"]:
        options["js_runtimes"] = {"deno": {"path": runtime["path"]}}
    cookie_file = _cookie_file()
    if cookie_file:
        options["cookiefile"] = cookie_file


def _external_base_args(runtime: dict) -> list[str]:
    args = ["--ignore-config", "--no-update", "--color", "never"]
    if runtime["active"]:
        args.extend(["--js-runtimes", f"deno:{runtime['path']}"])
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        args.extend(["--ffmpeg-location", ffmpeg])
    cookie_file = _cookie_file()
    if cookie_file:
        args.extend(["--cookies", cookie_file])
    return args


def _external_probe(executable: str, url: str, runtime: dict) -> tuple[dict | None, str | None]:
    cmd = [executable, *_external_base_args(runtime), "--dump-single-json",
           "--skip-download", "--no-playlist", "--no-warnings", "--", url]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            creationflags=_hidden_process_flags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"Could not run managed yt-dlp: {exc}"
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout or f"yt-dlp exited {proc.returncode}").strip()
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"Managed yt-dlp returned invalid metadata: {exc}"


# ─── Probe ───────────────────────────────────────────────────────────────────

def op_probe(args: argparse.Namespace) -> int:
    runtime = emit_runtime_status()
    portable_ytdlp = find_ytdlp()
    if yt_dlp is None and portable_ytdlp is None:
        return fail("missing_yt_dlp", "yt-dlp is not installed in the sidecar runtime.")
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if portable_ytdlp:
        info, error = _external_probe(portable_ytdlp, args.url, runtime)
        if error:
            return fail("probe_failed", error)
    else:
        _configure_python_ytdlp(ydl_opts, runtime)
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
        "js_runtime": runtime,
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


def _external_download(executable: str, args: argparse.Namespace, runtime: dict) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = "bestaudio/best" if args.audio_only else args.format
    cmd = [
        executable,
        *_external_base_args(runtime),
        "--newline",
        "--progress",
        "--no-playlist",
        "--no-simulate",
        "--progress-template",
        "download:__UCX_PROGRESS__:%(progress._percent_str)s|%(progress.eta)s|%(progress.speed)s",
        "--print",
        "after_move:__UCX_OUTPUT__:%(filepath)s",
        "--output",
        str(output_dir / "%(title)s [%(id)s].%(ext)s"),
        "--format",
        fmt,
    ]
    if args.merge:
        cmd.extend(["--merge-output-format", args.merge_format])
    if args.audio_only:
        cmd.extend(["--extract-audio", "--audio-format", args.audio_codec,
                    "--audio-quality", f"{args.audio_quality}K"])
    if args.subtitles:
        langs = "en,all" if args.subtitles == "all" else args.subtitles
        cmd.extend(["--write-subs", "--sub-langs", langs])
        if args.embed_subtitles:
            cmd.append("--embed-subs")
    if args.sponsorblock:
        categories = args.sponsorblock_categories or "sponsor,selfpromo,interaction"
        option = "--sponsorblock-remove" if args.sponsorblock == "remove" else "--sponsorblock-mark"
        cmd.extend([option, categories])
    cmd.extend(["--", args.url])

    emit("progress", percent=0, stage="resolving", eta_seconds=None)
    output_path = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_hidden_process_flags(),
        )
    except OSError as exc:
        return fail("download_failed", f"Could not run managed yt-dlp: {exc}")

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if line.startswith("__UCX_OUTPUT__:"):
            output_path = line.removeprefix("__UCX_OUTPUT__:").strip()
            continue
        if line.startswith("__UCX_PROGRESS__:"):
            parts = line.removeprefix("__UCX_PROGRESS__:").split("|")
            try:
                percent = float(parts[0].strip().rstrip("%"))
            except (ValueError, IndexError):
                percent = 0.0
            try:
                eta = int(parts[1])
            except (ValueError, IndexError):
                eta = None
            emit("progress", percent=percent, stage="downloading", eta_seconds=eta)
            continue
        if line:
            level = "warn" if "WARNING" in line.upper() else "info"
            emit("log", level=level, message=line[:4096])

    return_code = process.wait()
    if return_code != 0:
        return fail("yt_dlp_nonzero", f"yt-dlp returned {return_code}")

    if not output_path or not Path(output_path).is_file():
        candidates = sorted(
            (path for path in output_dir.iterdir() if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        output_path = str(candidates[0]) if candidates else None
    if not output_path:
        return fail("download_failed", "yt-dlp completed without reporting an output file.")

    emit("complete", output=output_path, size_bytes=Path(output_path).stat().st_size)
    return 0


def op_download(args: argparse.Namespace) -> int:
    runtime = emit_runtime_status()
    portable_ytdlp = find_ytdlp()
    if portable_ytdlp:
        return _external_download(portable_ytdlp, args, runtime)
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
    _configure_python_ytdlp(ydl_opts, runtime)
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


# ─── Cookies ─────────────────────────────────────────────────────────────────
#
# UCX-side cookie management surface for ROADMAP Item 9 (UI completion). The
# at-rest DPAPI encryption layer was shipped in iter-3 inside the streamkeep
# package; these ops expose that machinery to the C# DownloaderPage so the
# user can import / clear / inspect cookies without leaving UCX.

SUPPORTED_BROWSERS = (
    "chrome", "firefox", "edge", "brave", "chromium", "vivaldi",
    "opera", "librewolf", "safari",
)


def _emit_cookie_status(action: str | None = None, message: str | None = None) -> None:
    """Common ``cookie_status`` event emit.

    Reports whether a cookies file is present, whether the on-disk format is
    DPAPI-encrypted, the staleness in seconds, and the last user-visible
    action ("imported" / "cleared" / etc). The C# UI keys off these fields to
    populate the Cookie Auth card.
    """
    try:
        from streamkeep import cookies as ck
    except ImportError as exc:
        emit("cookie_status", present=False, encrypted=False, age_seconds=-1,
             action=action, message=message or f"streamkeep package missing: {exc}",
             ok=False)
        return

    path = ck.cookies_file_path()
    present = bool(path)
    age = ck.cookies_file_age_secs() if present else -1
    encrypted = ck.is_storage_encrypted() if present else False
    emit("cookie_status",
         present=present,
         encrypted=encrypted,
         age_seconds=age,
         action=action,
         message=message,
         ok=True)


def op_cookies_status(_args: argparse.Namespace) -> int:
    _emit_cookie_status()
    emit("complete", output="", size_bytes=0)
    return 0


def op_cookies_import(args: argparse.Namespace) -> int:
    try:
        from streamkeep import cookies as ck
    except ImportError as exc:
        return fail("missing_streamkeep", f"streamkeep package missing: {exc}")

    if args.file:
        ok, msg = ck.import_from_file(args.file)
    else:
        if args.browser not in SUPPORTED_BROWSERS:
            return fail("unknown_browser",
                        f"Browser '{args.browser}' not supported. "
                        f"Pick one of: {', '.join(SUPPORTED_BROWSERS)}.")
        ok, msg = ck.import_from_browser(args.browser)

    _emit_cookie_status(action="imported" if ok else "import_failed", message=msg)
    if not ok:
        return fail("import_failed", msg)
    emit("complete", output="", size_bytes=0)
    return 0


def op_cookies_clear(_args: argparse.Namespace) -> int:
    try:
        from streamkeep import cookies as ck
    except ImportError as exc:
        return fail("missing_streamkeep", f"streamkeep package missing: {exc}")

    ok, msg = ck.clear_cookies()
    _emit_cookie_status(action="cleared" if ok else "clear_failed", message=msg)
    if not ok:
        return fail("clear_failed", msg)
    emit("complete", output="", size_bytes=0)
    return 0


# ─── Entry ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="streamkeep-sidecar",
                                description="UCX StreamKeep sidecar — yt-dlp-backed downloader with NDJSON progress.")
    sub = p.add_subparsers(dest="op", required=True)

    probe = sub.add_parser("probe", help="Probe a URL (no download) and emit metadata + format list")
    probe.add_argument("--url", required=True)

    sub.add_parser("runtime-status", help="Report yt-dlp, Deno, and EJS runtime readiness")

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

    sub.add_parser("cookies-status",
                   help="Report current cookie store state (presence, DPAPI encryption, staleness).")

    ci = sub.add_parser("cookies-import",
                        help="Import cookies from an installed browser (or a Netscape cookies.txt file).")
    src = ci.add_mutually_exclusive_group(required=True)
    src.add_argument("--browser", choices=SUPPORTED_BROWSERS,
                     help="Browser name to extract cookies from (uses rookiepy / browser_cookie3).")
    src.add_argument("--file", help="Path to a Netscape cookies.txt to import directly.")

    sub.add_parser("cookies-clear",
                   help="Delete the on-disk cookies store (and any process-cached plaintext temp).")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "runtime-status":
            emit_runtime_status()
            emit("complete", output="", size_bytes=0)
            return 0
        if args.op == "download":
            return op_download(args)
        if args.op == "cookies-status":
            return op_cookies_status(args)
        if args.op == "cookies-import":
            return op_cookies_import(args)
        if args.op == "cookies-clear":
            return op_cookies_clear(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

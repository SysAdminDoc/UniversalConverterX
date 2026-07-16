"""DVD ripper sidecar — read an unprotected DVD VIDEO_TS structure and
convert a title to MP4/MKV via FFmpeg.

Scope (deliberately narrow, no DRM circumvention):
  * Reads a VIDEO_TS folder (a mounted, menu-free, non-commercial disc/ISO).
  * Groups VOB parts by title set (VTS_NN_1.VOB, VTS_NN_2.VOB, ...) and
    concatenates them with FFmpeg's `concat:` protocol.
  * CSS-encrypted commercial discs are NOT decrypted; when the VOBs cannot be
    read as MPEG-2 program streams the sidecar fails with a `drm_or_unreadable`
    error instead of producing garbage.

Operations:
  probe   Enumerate ripable titles in a VIDEO_TS folder -> `title` events.
  rip     Concatenate one title's VOBs and encode to MP4/MKV.

Requires FFmpeg + FFprobe (managed/bundled). Pure stdlib otherwise.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, probe_media, run_ffmpeg


_VOB_RE = re.compile(r"^VTS_(\d{2})_(\d+)\.VOB$", re.IGNORECASE)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def resolve_video_ts(raw: str) -> Path | None:
    """Accept a VIDEO_TS folder, its parent, or a drive root and return the
    VIDEO_TS directory that actually holds the VOBs."""
    p = Path(raw)
    if not p.exists():
        return None
    if p.is_file():
        p = p.parent
    candidates = [p]
    if p.name.upper() != "VIDEO_TS":
        candidates.append(p / "VIDEO_TS")
    for candidate in candidates:
        if candidate.is_dir() and any(_VOB_RE.match(f.name) for f in candidate.iterdir()):
            return candidate
    return None


def enumerate_titles(video_ts: Path) -> dict[int, list[Path]]:
    """Map title-set number -> ordered list of playable VOB parts.

    Part 0 (VTS_NN_0.VOB) is the menu/navigation VOB and is skipped; only
    content parts (>= 1) are ripped."""
    titles: dict[int, list[tuple[int, Path]]] = {}
    for f in sorted(video_ts.iterdir()):
        m = _VOB_RE.match(f.name)
        if not m:
            continue
        title = int(m.group(1))
        part = int(m.group(2))
        if part < 1:
            continue
        titles.setdefault(title, []).append((part, f))
    ordered: dict[int, list[Path]] = {}
    for title, parts in titles.items():
        parts.sort(key=lambda pair: pair[0])
        ordered[title] = [path for _, path in parts]
    return ordered


def concat_spec(vobs: list[Path]) -> str:
    return "concat:" + "|".join(str(v) for v in vobs)


def op_probe(args: argparse.Namespace) -> int:
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")
    video_ts = resolve_video_ts(args.input)
    if video_ts is None:
        return fail("missing_input",
                    f"No VIDEO_TS with VOB files found at: {args.input}")

    titles = enumerate_titles(video_ts)
    if not titles:
        return fail("no_titles", "No ripable titles (VTS_NN_1.VOB) were found.")

    readable = 0
    for title in sorted(titles):
        vobs = titles[title]
        info = probe_media(ffprobe, vobs[0])
        if not info or not info.get("streams"):
            emit("title", index=title, readable=False,
                 parts=len(vobs), duration_seconds=None,
                 message="Unreadable — likely CSS-protected or damaged.")
            continue
        # Sum the per-part durations for a whole-title estimate.
        total = 0.0
        for vob in vobs:
            part_info = probe_media(ffprobe, vob)
            try:
                total += float(part_info.get("format", {}).get("duration", 0) or 0)
            except (TypeError, ValueError):
                pass
        has_video = any(s.get("codec_type") == "video" for s in info.get("streams", []))
        readable += 1
        emit("title", index=title, readable=True, parts=len(vobs),
             duration_seconds=round(total, 3) if total > 0 else None,
             has_video=has_video,
             size_bytes=sum(v.stat().st_size for v in vobs))

    if readable == 0:
        return fail("drm_or_unreadable",
                    "No title could be read as an MPEG-2 program stream. "
                    "Commercial CSS-encrypted discs are not supported.")
    emit("complete", output=str(video_ts), size_bytes=0, count=readable)
    return 0


def _encode_args(mode: str, crf: int) -> list[str]:
    if mode == "copy":
        # MPEG-2 video + AC-3 audio remux straight into MKV.
        return ["-c", "copy"]
    if mode == "h265":
        return ["-c:v", "libx265", "-crf", str(crf), "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k"]
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]


def op_rip(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")

    video_ts = resolve_video_ts(args.input)
    if video_ts is None:
        return fail("missing_input",
                    f"No VIDEO_TS with VOB files found at: {args.input}")

    titles = enumerate_titles(video_ts)
    if args.title not in titles:
        return fail("bad_title",
                    f"Title {args.title} not found. Available: {sorted(titles) or 'none'}.")
    vobs = titles[args.title]

    info = probe_media(ffprobe, vobs[0])
    if not info or not info.get("streams"):
        return fail("drm_or_unreadable",
                    f"Title {args.title} could not be read as MPEG-2. "
                    "Commercial CSS-encrypted discs are not supported.")

    duration = 0.0
    for vob in vobs:
        part_info = probe_media(ffprobe, vob)
        try:
            duration += float(part_info.get("format", {}).get("duration", 0) or 0)
        except (TypeError, ValueError):
            pass

    out_path = Path(args.output)
    if args.mode == "copy" and out_path.suffix.lower() not in (".mkv", ".vob", ".mpg"):
        emit("log", level="warn",
             message="Stream-copy works best into .mkv; the container may reject MPEG-2 otherwise.")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-fflags", "+genpts",
        "-i", concat_spec(vobs),
        *_encode_args(args.mode, args.crf),
        str(out_path),
    ]
    emit("progress", percent=0, stage=f"rip title {args.title}", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, f"rip title {args.title}")
    if rc != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        return fail("ffmpeg_failed", f"Rip failed (exit {rc}).")

    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         title=args.title, mode=args.mode)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dvdrip-sidecar",
        description="Rip an unprotected DVD VIDEO_TS title to MP4/MKV.")
    sub = p.add_subparsers(dest="op", required=True)

    probe = sub.add_parser("probe", help="List ripable titles in a VIDEO_TS folder")
    probe.add_argument("--input", required=True,
                       help="VIDEO_TS folder (or its parent / mounted drive root)")

    rip = sub.add_parser("rip", help="Rip one title to a video file")
    rip.add_argument("--input", required=True)
    rip.add_argument("--output", required=True)
    rip.add_argument("--title", type=int, required=True, help="Title-set number (see probe)")
    rip.add_argument("--mode", choices=["h264", "h265", "copy"], default="h264",
                     help="h264/h265 re-encode, or stream-copy into MKV (default h264)")
    rip.add_argument("--crf", type=int, default=20, help="CRF when re-encoding (default 20)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "rip":
            return op_rip(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:  # noqa: BLE001 — surface any failure as NDJSON
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

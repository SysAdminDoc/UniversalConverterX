"""Legacy / proprietary video format sidecar (extends `videopro`).

For obscure / legacy video containers and codecs, FFmpeg's demuxer
catalog covers most of them — but they need explicit codec / pixel-fmt
hints to decode reliably. This sidecar wraps those edge cases:

  * RealVideo (.rm / .rmvb) — RealMedia v1/v2/v3
  * Bink Video (.bik / .bk2) — RAD Game Tools
  * Smacker (.smk / .smkv2) — RAD Game Tools (older)
  * OGG Media (.ogm) — pre-Matroska
  * DivX (.divx) — explicit DivX 3/4/5 stream
  * Microsoft Video 1 (.avi MS-CRAM)
  * Cinepak (.avi cvid)
  * Indeo (.avi IV31/IV32/IV41/IV50)

Operations:
  legacy-to-mp4   Auto-detect legacy video and remux/transcode -> MP4 H.264.
  legacy-info     ffprobe-style probe of legacy video -> JSON.

Requires `ffmpeg` + `ffprobe` on PATH.
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
import shutil
import subprocess
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".exe")


def op_legacy_info(args: argparse.Namespace) -> int:
    cli = _which("ffprobe")
    if not cli: return fail("missing_dep", "ffprobe not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"video file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        cmd = [cli, "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", str(src)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=120)
        except Exception as ex:
            return fail("probe_failed", f"{src.name}: {ex}")
        if proc.returncode != 0:
            return fail("probe_failed",
                        f"{src.name}: ffprobe exit {proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()}")
        out_path = out_dir / (src.stem + ".info.json")
        out_path.write_text(proc.stdout, encoding="utf-8")
        try:
            data = json.loads(proc.stdout)
            fmt = data.get("format", {})
            streams = data.get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"),
                          {})
            emit("legacy_video",
                 input=str(src), output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 format="json", source="ffprobe",
                 codec=video.get("codec_name", ""),
                 width=video.get("width", 0),
                 height=video.get("height", 0),
                 duration_s=float(fmt.get("duration", 0) or 0))
        except Exception:
            emit("legacy_video",
                 input=str(src), output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 format="json", source="ffprobe")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_legacy_to_mp4(args: argparse.Namespace) -> int:
    cli = _which("ffmpeg")
    if not cli: return fail("missing_dep", "ffmpeg not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"video file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".mp4")
        cmd = [cli, "-y", "-hide_banner", "-loglevel", "warning",
               "-i", str(src),
               "-c:v", "libx264", "-preset", args.preset,
               "-crf", str(args.crf),
               "-c:a", "aac", "-b:a", "192k",
               "-pix_fmt", "yuv420p",
               str(out_path)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=3600)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: ffmpeg exit {proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()}")
        emit("legacy_video",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="mp4-h264", source=src.suffix.lstrip("."))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vidlegacy-sidecar",
                                description="Legacy video format conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    li = sub.add_parser("legacy-info", help="ffprobe-style legacy video probe")
    li.add_argument("--input", nargs="+", required=True)
    li.add_argument("--output-dir", required=True, dest="output_dir")

    lc = sub.add_parser("legacy-to-mp4", help="Auto-detect legacy and -> MP4 H.264")
    lc.add_argument("--input", nargs="+", required=True)
    lc.add_argument("--output-dir", required=True, dest="output_dir")
    lc.add_argument("--preset", default="medium",
                    choices=["ultrafast", "superfast", "veryfast", "faster",
                              "fast", "medium", "slow", "slower", "veryslow"])
    lc.add_argument("--crf", type=int, default=23)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "legacy-info":   return op_legacy_info(args)
        if args.op == "legacy-to-mp4": return op_legacy_to_mp4(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

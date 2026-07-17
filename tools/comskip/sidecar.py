"""Offline Comskip wrapper for non-destructive commercial detection.

The wrapper never downloads Comskip. Supply a user-provisioned binary, or use
the pinned GPL-reviewed build recipe in this directory. Every analysis keeps
the source untouched and emits JSON, EDL, and FFmetadata chapter artifacts;
an optional FFmpeg export writes atomically to a separate destination.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, probe_media


MAX_EDL_BYTES = 10_000_000
MAX_RANGES = 10_000
PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def find_comskip(explicit: str | None = None) -> str | None:
    here = Path(__file__).resolve().parent
    runtime = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else here
    candidates = [
        explicit,
        os.environ.get("COMSKIP_PATH"),
        shutil.which("comskip"),
        str(runtime / "comskip.exe"),
        str(runtime / "comskip"),
        str(runtime.parent / "_bin" / "comskip.exe"),
        str(here / "comskip.exe"),
        str(here.parent / "_bin" / "comskip.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def parse_edl(path: Path) -> list[dict]:
    if not path.is_file():
        raise ValueError("Comskip did not produce an EDL file.")
    if path.stat().st_size > MAX_EDL_BYTES:
        raise ValueError(f"EDL exceeds {MAX_EDL_BYTES} bytes.")
    ranges: list[dict] = []
    last_end = 0.0
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"Invalid EDL line {line_number}: expected start end action.")
        try:
            start = float(parts[0])
            end = float(parts[1])
            action = int(parts[2])
        except ValueError as exc:
            raise ValueError(f"Invalid EDL line {line_number}: non-numeric value.") from exc
        if not (0 <= start < end) or start < last_end - 0.001:
            raise ValueError(f"Invalid EDL line {line_number}: ranges must be positive and ordered.")
        if action == 0:
            ranges.append({"start": round(start, 6), "end": round(end, 6), "action": "commercial"})
            last_end = end
        if len(ranges) > MAX_RANGES:
            raise ValueError(f"EDL contains more than {MAX_RANGES} commercial ranges.")
    return ranges


def keep_ranges(commercials: list[dict], duration: float) -> list[dict]:
    if duration <= 0:
        return []
    keep: list[dict] = []
    cursor = 0.0
    for item in commercials:
        start = max(0.0, min(duration, float(item["start"])))
        end = max(start, min(duration, float(item["end"])))
        if start > cursor + 0.001:
            keep.append({"start": round(cursor, 6), "end": round(start, 6)})
        cursor = max(cursor, end)
    if cursor < duration - 0.001:
        keep.append({"start": round(cursor, 6), "end": round(duration, 6)})
    return keep


def _run_comskip(command: list[str]) -> tuple[int, list[str]]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    )
    transcript: list[str] = []
    last_percent = -1.0
    assert process.stdout is not None
    try:
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            transcript.append(line)
            match = PERCENT_RE.search(line)
            if match:
                percent = max(0.0, min(99.0, float(match.group(1))))
                if percent >= last_percent + 1:
                    last_percent = percent
                    emit("progress", percent=round(percent, 1), stage="detecting commercials", eta_seconds=None)
            elif len(transcript) <= 20:
                emit("log", level="info", message=line[:500])
    finally:
        process.stdout.close()
        process.wait()
    return process.returncode, transcript


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{os.getpid()}{destination.suffix}")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_ffmetadata(commercials: list[dict]) -> str:
    lines = [";FFMETADATA1"]
    for index, item in enumerate(commercials, 1):
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={round(float(item['start']) * 1000)}",
            f"END={round(float(item['end']) * 1000)}",
            f"title=Commercial {index}",
        ]
    return "\n".join(lines) + "\n"


def _export_clean(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    commercials: list[dict],
    has_audio: bool,
) -> tuple[bool, str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.stem}.{os.getpid()}{output_path.suffix}")
    try:
        if not commercials:
            shutil.copyfile(input_path, temporary)
        else:
            cuts = "+".join(
                f"between(t\\,{float(item['start']):.6f}\\,{float(item['end']):.6f})"
                for item in commercials
            )
            keep_expression = f"not({cuts})"
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path),
                "-map", "0:v:0", "-vf", f"select='{keep_expression}',setpts=N/FRAME_RATE/TB",
                "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            ]
            if has_audio:
                command += [
                    "-map", "0:a:0?", "-af", f"aselect='{keep_expression}',asetpts=N/SR/TB",
                    "-c:a", "aac", "-b:a", "192k",
                ]
            else:
                command += ["-an"]
            command += [str(temporary)]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60 * 60,
                creationflags=_creation_flags(),
            )
            if result.returncode != 0:
                diagnostic = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
                return False, diagnostic[-2_000:]
        os.replace(temporary, output_path)
        return True, ""
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        temporary.unlink(missing_ok=True)


def op_probe(args: argparse.Namespace) -> int:
    binary = find_comskip(args.comskip)
    if not binary:
        return fail("missing_comskip", "Comskip is not installed. Provide --comskip or set COMSKIP_PATH.")
    result = subprocess.run(
        [binary, "--help"], capture_output=True, text=True, timeout=15,
        encoding="utf-8", errors="replace", creationflags=_creation_flags())
    first = next((line.strip() for line in (result.stdout + result.stderr).splitlines() if line.strip()), "unknown")
    emit("complete", available=result.returncode in (0, 1), path=binary, version=first[:200])
    return 0


def op_analyze(args: argparse.Namespace) -> int:
    binary = find_comskip(args.comskip)
    if not binary:
        return fail("missing_comskip", "Comskip is not installed. Provide --comskip or set COMSKIP_PATH.")
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    output_path = Path(args.output).resolve()
    if output_path.suffix.lower() != ".json":
        return fail("invalid_output", "Analysis output must end with .json.")
    ini_path = Path(args.ini).resolve() if args.ini else Path(__file__).resolve().parent / "comskip.ini"
    if not ini_path.is_file():
        return fail("missing_ini", f"Comskip INI not found: {ini_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=".ucx-comskip-", dir=output_path.parent))
    output_name = re.sub(r"[^A-Za-z0-9._-]+", "_", output_path.stem)[:120] or "comskip"
    try:
        command = [
            binary,
            "--ini", str(ini_path),
            "--output", str(work_dir),
            "--output-filename", output_name,
        ]
        if args.threads:
            command += ["--threads", str(args.threads)]
        command += [str(input_path)]
        emit("progress", percent=0, stage="detecting commercials", eta_seconds=None)
        return_code, transcript = _run_comskip(command)
        if return_code != 0:
            for line in transcript[-10:]:
                emit("log", level="error", message=line[:500])
            return fail("comskip_failed", f"Comskip exited with code {return_code}.")

        edl_candidates = [work_dir / f"{output_name}.edl", *sorted(work_dir.glob("*.edl"))]
        edl_source = next((candidate for candidate in edl_candidates if candidate.is_file()), None)
        if edl_source is None:
            return fail("missing_edl", "Comskip completed without producing an EDL file.")
        try:
            commercials = parse_edl(edl_source)
        except ValueError as exc:
            return fail("invalid_edl", str(exc))

        ffprobe = find_ffprobe(Path(__file__).resolve().parent)
        media = probe_media(ffprobe, input_path) if ffprobe else None
        try:
            duration = float((media or {}).get("format", {}).get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0 and commercials:
            duration = max(float(item["end"]) for item in commercials)
        has_audio = any(stream.get("codec_type") == "audio" for stream in (media or {}).get("streams", []))

        edl_output = output_path.with_suffix(".edl")
        chapters_output = output_path.with_suffix(".ffmeta")
        _atomic_copy(edl_source, edl_output)
        _atomic_write_text(chapters_output, build_ffmetadata(commercials))
        report = {
            "schemaVersion": 1,
            "input": str(input_path),
            "sourceModified": False,
            "durationSeconds": round(duration, 6),
            "commercialRanges": commercials,
            "keepRanges": keep_ranges(commercials, duration),
            "edl": str(edl_output),
            "chapters": str(chapters_output),
            "cleanExport": str(Path(args.export_clean).resolve()) if args.export_clean else None,
        }
        _atomic_write_text(output_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

        if args.export_clean:
            ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
            if not ffmpeg:
                return fail("missing_ffmpeg", "Report was saved, but FFmpeg is required for --export-clean.")
            emit("progress", percent=99, stage="exporting keep ranges", eta_seconds=None)
            succeeded, diagnostic = _export_clean(
                ffmpeg, input_path, Path(args.export_clean).resolve(), commercials, has_audio)
            if not succeeded:
                return fail("export_failed", f"Report was saved, but clean export failed: {diagnostic}")

        emit("progress", percent=100, stage="complete", eta_seconds=0)
        emit("complete", output=str(output_path), edl=str(edl_output), chapters=str(chapters_output),
             commercial_count=len(commercials), clean_export=report["cleanExport"])
        return 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comskip-sidecar", description="Offline commercial detection with EDL/chapter reports.")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    probe_parser = subparsers.add_parser("probe", help="Report local Comskip readiness")
    probe_parser.add_argument("--comskip", help="Explicit Comskip executable")
    probe_parser.set_defaults(func=op_probe)

    analyze = subparsers.add_parser("analyze", help="Analyze a local recording without modifying it")
    analyze.add_argument("--input", required=True)
    analyze.add_argument("--output", required=True, help="Atomic JSON report path; .edl/.ffmeta are written beside it")
    analyze.add_argument("--ini", help="Reviewed Comskip INI; defaults to the bundled offline profile")
    analyze.add_argument("--comskip", help="Explicit Comskip executable")
    analyze.add_argument("--threads", type=int, choices=range(1, 65), metavar="1..64")
    analyze.add_argument("--export-clean", help="Optional separate media output with commercial ranges removed")
    analyze.set_defaults(func=op_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as exc:
        return fail("unhandled", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())

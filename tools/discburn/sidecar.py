"""Windows optical-disc image and burn sidecar.

Data CD/DVD images and physical writes use the inbox IMAPI2 COM APIs. DVD-Video
mode transcodes each title with managed FFmpeg, authors VIDEO_TS with dvdauthor,
then hands that tree to the same IMAPI2 image/write path. Blu-ray authoring is
deliberately outside this sidecar because the former tsMuxeR dependency is no
longer maintained.
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
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LABEL_RE = re.compile(r"[^A-Z0-9_]+")


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def normalize_label(value: str) -> str:
    label = _LABEL_RE.sub("_", value.strip().upper()).strip("_")
    return (label or "UNIVERSAL_X")[:32]


def find_powershell() -> str | None:
    if os.name != "nt":
        return None
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe")


def find_dvdauthor() -> str | None:
    configured = os.environ.get("UCX_DVDAUTHOR")
    candidates = [
        configured,
        str(Path(__file__).resolve().parent / "dvdauthor.exe"),
        str(Path(__file__).resolve().parent.parent / "_bin" / "dvdauthor.exe"),
        shutil.which("dvdauthor"),
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


def run_imapi(
    operation: str,
    *,
    source: Path | None = None,
    output: Path | None = None,
    label: str = "UNIVERSAL_X",
    media: str = "dvd",
    layout: str = "data",
    recorder: str | None = None,
) -> tuple[dict | None, str | None]:
    powershell = find_powershell()
    if not powershell:
        return None, "Windows PowerShell with IMAPI2 is required."
    helper = Path(__file__).resolve().parent / "imapi.ps1"
    command = [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper),
        "-Operation",
        operation,
        "-VolumeLabel",
        normalize_label(label),
        "-Media",
        media,
        "-Layout",
        layout,
    ]
    if source is not None:
        command += ["-SourcePath", str(source)]
    if output is not None:
        command += ["-OutputPath", str(output)]
    if recorder:
        command += ["-RecorderId", recorder]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60 * 60,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return None, "IMAPI2 did not finish within one hour."
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "IMAPI2 failed").strip()
        return None, detail[-2000:]
    try:
        line = next(line for line in reversed(result.stdout.splitlines()) if line.strip())
        return json.loads(line), None
    except (StopIteration, json.JSONDecodeError) as exc:
        return None, f"IMAPI2 returned an invalid response: {exc}"


def op_drives(_args: argparse.Namespace) -> int:
    result, error = run_imapi("drives")
    if error:
        return fail("imapi_unavailable", error)
    for drive in result.get("drives", []):
        emit("drive", **drive)
    emit("complete", output="", size_bytes=0, count=len(result.get("drives", [])))
    return 0


def _validate_source_folder(raw: str) -> Path | None:
    source = Path(raw).resolve()
    return source if source.is_dir() else None


def _image_or_burn_data(args: argparse.Namespace, operation: str) -> int:
    source = _validate_source_folder(args.input)
    if source is None:
        return fail("missing_input", f"Data-disc source folder not found: {args.input}")
    output = Path(args.output).resolve() if operation == "image" else None
    emit("progress", percent=0, stage="building image", eta_seconds=None)
    result, error = run_imapi(
        operation,
        source=source,
        output=output,
        label=args.label,
        media=args.media,
        layout="data",
        recorder=getattr(args, "recorder", None),
    )
    if error:
        return fail("imapi_failed", error)
    emit("progress", percent=100, stage="complete", eta_seconds=0)
    if output is not None:
        emit("complete", output=str(output), size_bytes=output.stat().st_size)
    else:
        emit("complete", output=result.get("recorderId", ""), size_bytes=0)
    return 0


def op_image_data(args: argparse.Namespace) -> int:
    return _image_or_burn_data(args, "image")


def op_burn_data(args: argparse.Namespace) -> int:
    return _image_or_burn_data(args, "burn")


def _run_tool(command: list[str], stage: str) -> str | None:
    emit("log", level="info", message=stage)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout or f"{stage} failed").strip()
    return detail[-3000:]


def _author_dvd(inputs: list[str], standard: str, destination: Path) -> str | None:
    ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
    if not ffmpeg:
        return "FFmpeg not found. Provision the managed FFmpeg tool, then retry."
    dvdauthor = find_dvdauthor()
    if not dvdauthor:
        return (
            "dvdauthor not found. Provision a Windows dvdauthor build beside the "
            "discburn sidecar or set UCX_DVDAUTHOR, then retry."
        )
    sources = [Path(item).resolve() for item in inputs]
    missing = next((path for path in sources if not path.is_file()), None)
    if missing:
        return f"DVD-Video source file not found: {missing}"

    destination.mkdir(parents=True, exist_ok=True)
    authored = destination / "authored"
    authored.mkdir()
    streams: list[Path] = []
    total = len(sources)
    target = "ntsc-dvd" if standard == "ntsc" else "pal-dvd"
    for index, source in enumerate(sources, 1):
        stream = destination / f"title-{index:02d}.mpg"
        emit("progress", percent=(index - 1) * 75 / total,
             stage=f"transcoding title {index}/{total}", eta_seconds=None)
        error = _run_tool(
            [
                str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
                "-target", target, str(stream),
            ],
            f"FFmpeg DVD transcode for {source.name}",
        )
        if error:
            return error
        streams.append(stream)

    root = ET.Element("dvdauthor", {"dest": str(authored)})
    ET.SubElement(root, "vmgm")
    title_set = ET.SubElement(root, "titleset")
    titles = ET.SubElement(title_set, "titles")
    for stream in streams:
        pgc = ET.SubElement(titles, "pgc")
        ET.SubElement(pgc, "vob", {"file": str(stream)})
    xml_path = destination / "dvdauthor.xml"
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    emit("progress", percent=80, stage="authoring VIDEO_TS", eta_seconds=None)
    error = _run_tool([dvdauthor, "-x", str(xml_path)], "dvdauthor VIDEO_TS authoring")
    if error:
        return error
    video_ts = authored / "VIDEO_TS"
    if not video_ts.is_dir() or not any(video_ts.glob("*.IFO")):
        return "dvdauthor completed without producing a VIDEO_TS structure."
    return None


def _image_or_burn_dvd(args: argparse.Namespace, operation: str) -> int:
    with tempfile.TemporaryDirectory(prefix="ucx-discburn-") as temp:
        workspace = Path(temp)
        error = _author_dvd(args.input, args.standard, workspace)
        if error:
            code = "missing_dependency" if "not found" in error.lower() else "dvd_author_failed"
            return fail(code, error)
        output = Path(args.output).resolve() if operation == "image" else None
        emit("progress", percent=90, stage="building DVD-Video image", eta_seconds=None)
        result, error = run_imapi(
            operation,
            source=workspace / "authored",
            output=output,
            label=args.label,
            media="dvd",
            layout="dvd-video",
            recorder=getattr(args, "recorder", None),
        )
        if error:
            return fail("imapi_failed", error)
        emit("progress", percent=100, stage="complete", eta_seconds=0)
        if output is not None:
            emit("complete", output=str(output), size_bytes=output.stat().st_size)
        else:
            emit("complete", output=result.get("recorderId", ""), size_bytes=0)
    return 0


def op_image_dvd(args: argparse.Namespace) -> int:
    return _image_or_burn_dvd(args, "image")


def op_burn_dvd(args: argparse.Namespace) -> int:
    return _image_or_burn_dvd(args, "burn")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("drives", help="List IMAPI2-compatible optical recorders")

    for name in ("image-data", "burn-data"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True, help="Source folder")
        command.add_argument("--media", choices=("cd", "dvd"), default="dvd")
        command.add_argument("--label", default="UNIVERSAL_X")
        if name == "image-data":
            command.add_argument("--output", required=True, help="Destination ISO")
        else:
            command.add_argument("--recorder", help="IMAPI2 recorder ID; defaults to first")

    for name in ("image-dvd", "burn-dvd"):
        command = sub.add_parser(name)
        command.add_argument("--input", action="append", required=True,
                             help="Video title; repeat for additional titles")
        command.add_argument("--standard", choices=("ntsc", "pal"), default="ntsc")
        command.add_argument("--label", default="UNIVERSAL_X")
        if name == "image-dvd":
            command.add_argument("--output", required=True, help="Destination ISO")
        else:
            command.add_argument("--recorder", help="IMAPI2 recorder ID; defaults to first")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    handlers = {
        "drives": op_drives,
        "image-data": op_image_data,
        "burn-data": op_burn_data,
        "image-dvd": op_image_dvd,
        "burn-dvd": op_burn_dvd,
    }
    try:
        return handlers[args.op](args)
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as exc:
        return fail("unexpected", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())

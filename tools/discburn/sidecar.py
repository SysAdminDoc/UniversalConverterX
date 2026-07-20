"""Windows optical-disc image and burn sidecar.

Data CD/DVD/Blu-ray images and physical writes use the inbox IMAPI2 COM APIs.
DVD-Video mode transcodes each title with managed FFmpeg and authors VIDEO_TS
with dvdauthor. Single-title Blu-ray mode transcodes to a conservative H.264 +
AC-3 profile, authors an inspectable BDMV tree with a pinned or explicitly
provisioned tsMuxeR runtime, and hands that tree to the same IMAPI2 boundary.
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
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, probe_media


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


def find_tsmuxer(configured: str | None = None) -> str | None:
    candidates = [
        configured,
        os.environ.get("UCX_TSMUXER"),
        str(Path(__file__).resolve().parent / "tsMuxeR.exe"),
        str(Path(__file__).resolve().parent.parent / "_bin" / "tsMuxeR.exe"),
        shutil.which("tsMuxeR"),
        shutil.which("tsmuxer"),
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
    timeout=600)
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


_BDMV_REQUIRED = (
    ("BDMV/index.bdmv", b"INDX"),
    ("BDMV/MovieObject.bdmv", b"MOBJ"),
    ("BDMV/PLAYLIST/00000.mpls", b"MPLS"),
    ("BDMV/CLIPINF/00000.clpi", b"HDMV"),
    ("BDMV/STREAM/00000.m2ts", None),
    ("BDMV/BACKUP/index.bdmv", b"INDX"),
    ("BDMV/BACKUP/MovieObject.bdmv", b"MOBJ"),
    ("BDMV/BACKUP/PLAYLIST/00000.mpls", b"MPLS"),
    ("BDMV/BACKUP/CLIPINF/00000.clpi", b"HDMV"),
)


def inspect_bdmv(root: Path) -> tuple[dict | None, str | None]:
    files: list[dict] = []
    for relative, signature in _BDMV_REQUIRED:
        path = root / Path(relative)
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            return None, f"Blu-ray authoring did not produce {relative}."
        if signature is not None and path.read_bytes()[:4] != signature:
            return None, f"Blu-ray authoring produced an invalid {relative} signature."
        files.append({"path": relative, "sizeBytes": path.stat().st_size})
    stream = root / "BDMV" / "STREAM" / "00000.m2ts"
    with stream.open("rb") as handle:
        header = handle.read(5)
    if len(header) < 5 or header[4] != 0x47:
        return None, "Blu-ray transport stream does not begin with an M2TS sync byte."
    return {"schemaVersion": 1, "files": files}, None


def _author_bluray(
    raw_input: str,
    destination: Path,
    configured_tsmuxer: str | None = None,
) -> tuple[dict | None, str | None]:
    source = Path(raw_input).resolve()
    if not source.is_file():
        return None, f"Blu-ray source file not found: {source}"
    if destination.exists():
        return None, f"BDMV output already exists; choose a new folder: {destination}"
    ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    if not ffmpeg or not ffprobe:
        return None, "Managed FFmpeg and FFprobe are required for Blu-ray authoring."
    tsmuxer = find_tsmuxer(configured_tsmuxer)
    if not tsmuxer:
        return None, (
            "tsMuxeR 2.7.0 is not installed. Run build-runtime.ps1 with explicit "
            "Apache-2.0 acceptance, place tsMuxeR.exe beside the sidecar, or set UCX_TSMUXER."
        )
    media = probe_media(ffprobe, source)
    if media is None or not any(item.get("codec_type") == "video" for item in media.get("streams", [])):
        return None, f"Blu-ray source does not contain a readable video stream: {source}"
    has_audio = any(item.get("codec_type") == "audio" for item in media.get("streams", []))

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.partial-{os.getpid()}")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        with tempfile.TemporaryDirectory(prefix="ucx-bluray-") as temp:
            workspace = Path(temp)
            prepared = workspace / "title.mkv"
            command = [
                str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
            ]
            if not has_audio:
                command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            command += [
                "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-r", "24000/1001", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p",
                "-g", "24", "-keyint_min", "24", "-sc_threshold", "0",
                "-c:a", "ac3", "-b:a", "448k", "-ar", "48000", "-ac", "2", "-shortest",
                str(prepared),
            ]
            emit("progress", percent=0, stage="transcoding Blu-ray title", eta_seconds=None)
            error = _run_tool(command, f"FFmpeg Blu-ray transcode for {source.name}")
            if error:
                return None, error

            portable = str(prepared).replace("\\", "/")
            metadata = workspace / "title.meta"
            metadata.write_text(
                "MUXOPT --blu-ray --vbr --auto-chapters=5\n"
                f"V_MPEG4/ISO/AVC, {portable}, track=1\n"
                f"A_AC3, {portable}, track=2\n",
                encoding="utf-8",
            )
            emit("progress", percent=80, stage="authoring BDMV", eta_seconds=None)
            error = _run_tool([tsmuxer, str(metadata), str(staging)], "tsMuxeR BDMV authoring")
            if error:
                return None, error
            inspection, error = inspect_bdmv(staging)
            if error:
                return None, error
            os.replace(staging, destination)
            assert inspection is not None
            inspection["output"] = str(destination)
            return inspection, None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def op_author_bluray(args: argparse.Namespace) -> int:
    destination = Path(args.output).resolve()
    inspection, error = _author_bluray(args.input, destination, args.tsmuxer)
    if error:
        code = "missing_dependency" if "required" in error.lower() or "not installed" in error.lower() else "bluray_author_failed"
        return fail(code, error)
    emit("progress", percent=100, stage="complete", eta_seconds=0)
    emit("complete", output=str(destination), size_bytes=0, bdmv=inspection)
    return 0


def _image_or_burn_bluray(args: argparse.Namespace, operation: str) -> int:
    output = Path(args.output).resolve() if operation == "image" else None
    if args.bdmv_output:
        bdmv_output = Path(args.bdmv_output).resolve()
    elif output is not None:
        bdmv_output = output.with_name(f"{output.stem}_BDMV")
    else:
        return fail("missing_output", "--bdmv-output is required when burning a Blu-ray disc.")
    inspection, error = _author_bluray(args.input, bdmv_output, args.tsmuxer)
    if error:
        code = "missing_dependency" if "required" in error.lower() or "not installed" in error.lower() else "bluray_author_failed"
        return fail(code, error)
    emit("progress", percent=92, stage="building Blu-ray image" if output else "burning Blu-ray", eta_seconds=None)
    result, error = run_imapi(
        operation,
        source=bdmv_output,
        output=output,
        label=args.label,
        media="bluray",
        layout="bdmv",
        recorder=getattr(args, "recorder", None),
    )
    if error:
        return fail("imapi_failed", error)
    emit("progress", percent=100, stage="complete", eta_seconds=0)
    if output is not None:
        emit("complete", output=str(output), size_bytes=output.stat().st_size,
             bdmv_output=str(bdmv_output), bdmv=inspection)
    else:
        emit("complete", output=result.get("recorderId", ""), size_bytes=0,
             bdmv_output=str(bdmv_output), bdmv=inspection)
    return 0


def op_image_bluray(args: argparse.Namespace) -> int:
    return _image_or_burn_bluray(args, "image")


def op_burn_bluray(args: argparse.Namespace) -> int:
    return _image_or_burn_bluray(args, "burn")


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

    author = sub.add_parser("author-bluray", help="Create an inspectable single-title BDMV folder")
    author.add_argument("--input", required=True, help="Source video title")
    author.add_argument("--output", required=True, help="Destination folder containing BDMV")
    author.add_argument("--tsmuxer", help="Explicit tsMuxeR 2.7.0 executable")

    for name in ("image-bluray", "burn-bluray"):
        command = sub.add_parser(name)
        command.add_argument("--input", required=True, help="Source video title")
        command.add_argument("--bdmv-output", help="Persistent destination folder containing BDMV")
        command.add_argument("--tsmuxer", help="Explicit tsMuxeR 2.7.0 executable")
        command.add_argument("--label", default="UNIVERSAL_X")
        if name == "image-bluray":
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
        "author-bluray": op_author_bluray,
        "image-bluray": op_image_bluray,
        "burn-bluray": op_burn_bluray,
    }
    try:
        return handlers[args.op](args)
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as exc:
        return fail("unexpected", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())

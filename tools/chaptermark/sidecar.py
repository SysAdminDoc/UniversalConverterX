"""ChapterMark sidecar -- exact-PTS chapter editing for MKV / MP4 / MOV.

The sidecar reads and imports chapter markers without reducing their integer
PTS/time-base representation to floating point. MKV writes use MKVToolNix
97+; other supported containers use FFmpeg stream copy with a per-chapter
FFMETADATA time base. Every mux is verified before atomic promotion.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, find_tool


MAX_CHAPTERS = 10_000
MAX_CHAPTER_FILE_BYTES = 2 * 1024 * 1024
NANOSECONDS = 1_000_000_000
_SIMPLE_START = re.compile(r"^CHAPTER(\d+)=([0-9:.]+)\s*$", re.IGNORECASE)
_SIMPLE_TITLE = re.compile(r"^CHAPTER(\d+)NAME=(.*)$", re.IGNORECASE)
_TIMESTAMP = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.(\d{1,9}))?$")


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


def progress(percent: float, stage: str = "") -> None:
    emit("progress", percent=round(percent, 1), stage=stage)


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _parse_time_base(value: object) -> tuple[int, int]:
    text = str(value or "1/1000")
    match = re.fullmatch(r"(\d+)/(\d+)", text)
    if not match:
        raise ValueError(f"Invalid chapter time base: {text!r}")
    numerator, denominator = int(match.group(1)), int(match.group(2))
    if numerator <= 0 or denominator <= 0 or numerator > 1_000_000_000 or denominator > 10**15:
        raise ValueError(f"Chapter time base is outside supported bounds: {text!r}")
    reduced = Fraction(numerator, denominator)
    return reduced.numerator, reduced.denominator


def _parse_decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} is not a valid number") from None
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _decimal_to_pts(value: Decimal, numerator: int, denominator: int) -> int:
    scaled = value * Decimal(denominator) / Decimal(numerator)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _fraction_to_pts(value: Fraction, numerator: int, denominator: int) -> int:
    scaled = value / Fraction(numerator, denominator)
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    return quotient + (1 if remainder * 2 >= scaled.denominator else 0)


def _seconds(chapter: dict, key: str) -> Fraction:
    return Fraction(
        int(chapter[f"{key}_pts"]) * int(chapter["time_base_num"]),
        int(chapter["time_base_den"]),
    )


def _decimal_text(value: Fraction) -> str:
    decimal = Decimal(value.numerator) / Decimal(value.denominator)
    text = format(decimal.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP), "f")
    return text.rstrip("0").rstrip(".") or "0"


def _normalize_chapters(raw: object, total_duration: Decimal = Decimal(0)) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("chapters JSON must be a top-level list")
    if len(raw) > MAX_CHAPTERS:
        raise ValueError(f"chapter list exceeds the {MAX_CHAPTERS} item limit")

    normalized: list[dict] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Chapter {index} is not an object")

        has_exact_start = item.get("start_pts") is not None
        if has_exact_start:
            numerator, denominator = _parse_time_base(item.get("time_base"))
            try:
                start_pts = int(item["start_pts"])
            except (TypeError, ValueError):
                raise ValueError(f"Chapter {index} has an invalid start_pts") from None
        else:
            start_value = item.get("start", item.get("start_seconds"))
            if start_value is None:
                raise ValueError(f"Chapter {index} is missing its start time")
            numerator, denominator = 1, NANOSECONDS
            start_pts = _decimal_to_pts(
                _parse_decimal(start_value, f"Chapter {index} start"), numerator, denominator)

        if item.get("end_pts") is not None:
            try:
                end_pts: int | None = int(item["end_pts"])
            except (TypeError, ValueError):
                raise ValueError(f"Chapter {index} has an invalid end_pts") from None
        else:
            end_value = item.get("end", item.get("end_seconds"))
            end_pts = None if end_value in (None, "") else _decimal_to_pts(
                _parse_decimal(end_value, f"Chapter {index} end"), numerator, denominator)

        if start_pts < 0:
            raise ValueError(f"Chapter {index} starts before zero")
        title = str(item.get("title", "") or f"Chapter {index}")
        if len(title) > 1024:
            raise ValueError(f"Chapter {index} title exceeds 1024 characters")
        if "\0" in title:
            raise ValueError(f"Chapter {index} title contains a null character")

        normalized.append({
            "start_pts": start_pts,
            "end_pts": end_pts,
            "time_base_num": numerator,
            "time_base_den": denominator,
            "title": title,
        })

    normalized.sort(key=lambda chapter: _seconds(chapter, "start"))
    previous_start: Fraction | None = None
    duration_fraction = Fraction(total_duration) if total_duration > 0 else Fraction(0)
    for index, chapter in enumerate(normalized):
        start = _seconds(chapter, "start")
        if previous_start is not None and start <= previous_start:
            raise ValueError("Chapter start times must be strictly increasing")
        previous_start = start

        if chapter["end_pts"] is None:
            if index + 1 < len(normalized):
                target_end = _seconds(normalized[index + 1], "start")
            elif duration_fraction > start:
                target_end = duration_fraction
            else:
                target_end = start + 1
            chapter["end_pts"] = _fraction_to_pts(
                target_end, chapter["time_base_num"], chapter["time_base_den"])

        if _seconds(chapter, "end") <= start:
            raise ValueError(f"Chapter {index + 1} end must be after its start")

    return normalized


def _event_fields(chapter: dict, index: int) -> dict:
    start = _seconds(chapter, "start")
    end = _seconds(chapter, "end")
    return {
        "id": index,
        "start": float(start),
        "end": float(end),
        "start_text": _decimal_text(start),
        "end_text": _decimal_text(end),
        "start_pts": chapter["start_pts"],
        "end_pts": chapter["end_pts"],
        "time_base": f"{chapter['time_base_num']}/{chapter['time_base_den']}",
        "title": chapter["title"],
    }


def _emit_chapters(chapters: list[dict]) -> None:
    for index, chapter in enumerate(chapters):
        emit("chapter", **_event_fields(chapter, index))


def _load_json(path: Path) -> object:
    if not path.is_file():
        raise ValueError(f"Chapter file not found: {path}")
    if path.stat().st_size > MAX_CHAPTER_FILE_BYTES:
        raise ValueError("Chapter file exceeds the 2 MB safety limit")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not parse chapter JSON: {exc}") from exc


def _probe_duration(ffprobe: str, path: Path) -> Decimal:
    result = _run([
        ffprobe, "-v", "quiet", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], 30)
    try:
        return Decimal(result.stdout.strip()) if result.returncode == 0 else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _probe_chapters(ffprobe: str, path: Path) -> list[dict]:
    result = _run([
        ffprobe, "-v", "quiet", "-show_chapters", "-print_format", "json", str(path),
    ], 60)
    if result.returncode != 0:
        raise ValueError(f"ffprobe exited {result.returncode}: {result.stderr.strip()[:300]}")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse ffprobe chapter JSON: {exc}") from exc

    raw = []
    for index, chapter in enumerate(payload.get("chapters") or []):
        raw.append({
            "start_pts": chapter.get("start", 0),
            "end_pts": chapter.get("end", 0),
            "time_base": chapter.get("time_base", "1/1000"),
            "title": (chapter.get("tags") or {}).get("title") or f"Chapter {index + 1}",
        })
    return _normalize_chapters(raw)


def op_read(args: argparse.Namespace) -> int:
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    if ffprobe is None:
        return fail("missing_ffprobe", "FFprobe is required to read chapter markers.")
    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")

    progress(10.0, "probing exact chapter timestamps")
    try:
        chapters = _probe_chapters(ffprobe, source)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return fail("ffprobe_failed", str(exc))
    _emit_chapters(chapters)
    output_value = getattr(args, "output", None)
    if output_value:
        output = Path(output_value)
        staged: Path | None = None
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            staged = output.with_name(f".{output.stem}.ucx-{uuid.uuid4().hex}{output.suffix}")
            staged.write_text(_json_export(chapters), encoding="utf-8")
            os.replace(staged, output)
        except OSError as exc:
            return fail("export_failed", f"Could not export chapter JSON: {exc}")
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
    progress(100.0, "done")
    emit(
        "complete", count=len(chapters),
        output=str(output_value or ""),
        size_bytes=Path(output_value).stat().st_size if output_value else 0)
    return 0


def _timestamp_from_pts(pts: int, numerator: int, denominator: int) -> str:
    nanoseconds = Fraction(pts * numerator * NANOSECONDS, denominator)
    if nanoseconds.denominator != 1:
        raise ValueError(
            f"Timestamp {pts} at {numerator}/{denominator} cannot be represented exactly in Matroska nanoseconds")
    total_ns = nanoseconds.numerator
    seconds, fraction = divmod(total_ns, NANOSECONDS)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{fraction:09d}"


def _build_matroska_xml(chapters: list[dict]) -> bytes:
    root = ET.Element("Chapters")
    edition = ET.SubElement(root, "EditionEntry")
    for chapter in chapters:
        atom = ET.SubElement(edition, "ChapterAtom")
        ET.SubElement(atom, "ChapterTimeStart").text = _timestamp_from_pts(
            chapter["start_pts"], chapter["time_base_num"], chapter["time_base_den"])
        ET.SubElement(atom, "ChapterTimeEnd").text = _timestamp_from_pts(
            chapter["end_pts"], chapter["time_base_num"], chapter["time_base_den"])
        display = ET.SubElement(atom, "ChapterDisplay")
        ET.SubElement(display, "ChapterString").text = chapter["title"]
        ET.SubElement(display, "ChapterLanguage").text = "und"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _escape_ffmetadata(value: str) -> str:
    return (value.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\r", "")
            .replace("=", "\\=")
            .replace(";", "\\;")
            .replace("#", "\\#"))


def _build_ffmetadata(chapters: list[dict]) -> str:
    lines = [";FFMETADATA1\n"]
    for chapter in chapters:
        lines.extend([
            "[CHAPTER]\n",
            f"TIMEBASE={chapter['time_base_num']}/{chapter['time_base_den']}\n",
            f"START={chapter['start_pts']}\n",
            f"END={chapter['end_pts']}\n",
            f"title={_escape_ffmetadata(chapter['title'])}\n",
        ])
    return "".join(lines)


def _parse_timestamp(value: str) -> int:
    match = _TIMESTAMP.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid chapter timestamp: {value!r}")
    hours, minutes, seconds = (int(match.group(i)) for i in range(1, 4))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid chapter timestamp: {value!r}")
    fraction = (match.group(4) or "").ljust(9, "0")
    return ((hours * 3600 + minutes * 60 + seconds) * NANOSECONDS) + int(fraction or 0)


def _parse_matroska_xml(text: str) -> list[dict]:
    if re.search(r"<!ENTITY|<!DOCTYPE[^>]*\[", text, re.IGNORECASE):
        raise ValueError("Matroska chapter XML must not contain entity declarations or an internal DTD subset")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse Matroska chapter XML: {exc}") from exc

    raw = []
    for index, atom in enumerate(root.findall(".//ChapterAtom"), 1):
        start = atom.findtext("ChapterTimeStart")
        if not start:
            raise ValueError(f"Chapter {index} is missing ChapterTimeStart")
        end = atom.findtext("ChapterTimeEnd")
        title = atom.findtext("./ChapterDisplay/ChapterString") or f"Chapter {index}"
        raw.append({
            "start_pts": _parse_timestamp(start),
            "end_pts": _parse_timestamp(end) if end else None,
            "time_base": f"1/{NANOSECONDS}",
            "title": title,
        })
    return _normalize_chapters(raw)


def _parse_simple_chapters(text: str) -> list[dict]:
    starts: dict[int, str] = {}
    titles: dict[int, str] = {}
    for line in text.splitlines():
        start_match = _SIMPLE_START.match(line)
        if start_match:
            starts[int(start_match.group(1))] = start_match.group(2)
            continue
        title_match = _SIMPLE_TITLE.match(line)
        if title_match:
            titles[int(title_match.group(1))] = title_match.group(2)
    if not starts:
        raise ValueError("No CHAPTERxx timestamp pairs were found")
    raw = [{
        "start_pts": _parse_timestamp(starts[key]),
        "time_base": f"1/{NANOSECONDS}",
        "title": titles.get(key) or f"Chapter {index}",
    } for index, key in enumerate(sorted(starts), 1)]
    return _normalize_chapters(raw)


def _load_chapter_file(path: Path) -> list[dict]:
    if not path.is_file():
        raise ValueError(f"Chapter file not found: {path}")
    if path.stat().st_size > MAX_CHAPTER_FILE_BYTES:
        raise ValueError("Chapter file exceeds the 2 MB safety limit")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Could not read chapter file: {exc}") from exc
    stripped = text.lstrip()
    if path.suffix.lower() == ".json" or stripped.startswith("["):
        try:
            return _normalize_chapters(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse chapter JSON: {exc}") from exc
    if path.suffix.lower() == ".xml" or stripped.startswith("<"):
        return _parse_matroska_xml(text)
    return _parse_simple_chapters(text)


def op_import(args: argparse.Namespace) -> int:
    try:
        chapters = _load_chapter_file(Path(args.input))
    except ValueError as exc:
        return fail("import_failed", str(exc))
    _emit_chapters(chapters)
    emit("complete", count=len(chapters))
    return 0


def _json_export(chapters: list[dict]) -> str:
    rows = []
    for chapter in chapters:
        start, end = _seconds(chapter, "start"), _seconds(chapter, "end")
        rows.append({
            "start": _decimal_text(start),
            "end": _decimal_text(end),
            "start_pts": chapter["start_pts"],
            "end_pts": chapter["end_pts"],
            "time_base": f"{chapter['time_base_num']}/{chapter['time_base_den']}",
            "title": chapter["title"],
        })
    return json.dumps(rows, ensure_ascii=False, indent=2) + "\n"


def _simple_export(chapters: list[dict]) -> str:
    lines = []
    for index, chapter in enumerate(chapters, 1):
        if "\n" in chapter["title"] or "\r" in chapter["title"]:
            raise ValueError("Simple chapter text cannot encode multiline titles; export JSON or XML instead")
        start_ms = _seconds(chapter, "start") * 1000
        if start_ms.denominator != 1:
            raise ValueError("Simple chapter text cannot preserve sub-millisecond PTS; export JSON or XML instead")
        total_ms = start_ms.numerator
        seconds, milliseconds = divmod(total_ms, 1000)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        lines.extend([
            f"CHAPTER{index:02d}={hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}\n",
            f"CHAPTER{index:02d}NAME={chapter['title']}\n",
        ])
    return "".join(lines)


def op_export(args: argparse.Namespace) -> int:
    try:
        chapters = _normalize_chapters(_load_json(Path(args.chapters_json)))
        output = Path(args.output)
        suffix = output.suffix.lower()
        if suffix == ".xml":
            payload = _build_matroska_xml(chapters)
        elif suffix in {".txt", ".ogm"}:
            payload = _simple_export(chapters).encode("utf-8")
        else:
            payload = _json_export(chapters).encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        staged = output.with_name(f".{output.stem}.ucx-{uuid.uuid4().hex}{output.suffix}")
        staged.write_bytes(payload)
        os.replace(staged, output)
    except (OSError, ValueError) as exc:
        return fail("export_failed", str(exc))
    emit("complete", output=str(output), size_bytes=output.stat().st_size, chapters_written=len(chapters))
    return 0


def _mkvmerge_major(mkvmerge: str) -> tuple[int | None, str]:
    try:
        result = _run([mkvmerge, "--version"], 20)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    banner = (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr).strip() else ""
    match = re.search(r"\bmkvmerge\s+v(\d+)(?:\.\d+)*", banner, re.IGNORECASE)
    return (int(match.group(1)) if match else None), banner


def _same_chapters(expected: list[dict], actual: list[dict]) -> bool:
    if len(expected) != len(actual):
        return False
    return all(
        _seconds(left, "start") == _seconds(right, "start")
        and _seconds(left, "end") == _seconds(right, "end")
        and left["title"] == right["title"]
        for left, right in zip(expected, actual)
    )


def op_write(args: argparse.Namespace) -> int:
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    if ffprobe is None:
        return fail("missing_ffprobe", "FFprobe is required to verify chapter timestamps after muxing.")
    source = Path(args.input)
    output = Path(args.output)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")
    if output.exists() and output.is_dir():
        return fail("invalid_output", f"Output is a directory: {output}")

    try:
        duration = _probe_duration(ffprobe, source)
        chapters = _normalize_chapters(_load_json(Path(args.chapters_json)), duration)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return fail("invalid_chapters", str(exc))

    if output.suffix.lower() != ".mkv" and chapters and _seconds(chapters[0], "start") != 0:
        return fail(
            "invalid_chapters",
            "MP4/MOV chapter tables must start at zero for exact PTS preservation; add a zero-time first chapter.")

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(f".{output.stem}.ucx-{uuid.uuid4().hex}{output.suffix}")
    metadata_path: Path | None = None
    try:
        if output.suffix.lower() == ".mkv":
            mkvmerge = find_tool(
                "mkvmerge", env_var="MKVMERGE_PATH", anchor=Path(__file__).resolve().parent)
            if mkvmerge is None:
                return fail(
                    "missing_mkvmerge",
                    "MKV chapter writes require MKVToolNix 97 or newer; install mkvmerge or set MKVMERGE_PATH.")
            major, banner = _mkvmerge_major(mkvmerge)
            if major is None:
                return fail("mkvmerge_version_unknown", f"Could not verify MKVToolNix version: {banner}")
            if major < 97:
                return fail("outdated_mkvmerge", f"MKVToolNix 97+ is required; detected: {banner}")

            command = [mkvmerge, "-o", str(staged)]
            if chapters:
                with tempfile.NamedTemporaryFile("wb", suffix=".xml", delete=False) as temp:
                    temp.write(_build_matroska_xml(chapters))
                    metadata_path = Path(temp.name)
                command += ["--chapters", str(metadata_path)]
            else:
                command += ["--no-chapters"]
            command += [str(source)]
            muxer = f"MKVToolNix {major}"
            success_codes = {0, 1}  # mkvmerge uses 1 for successful completion with warnings.
        else:
            ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
            if ffmpeg is None:
                return fail("missing_ffmpeg", "FFmpeg is required to write MP4/MOV chapter markers.")
            with tempfile.NamedTemporaryFile("w", suffix=".ffmeta", delete=False, encoding="utf-8") as temp:
                temp.write(_build_ffmetadata(chapters))
                metadata_path = Path(temp.name)
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-f", "ffmetadata", "-i", str(metadata_path),
                "-map", "0", "-map_metadata", "0", "-map_chapters", "1",
                "-codec", "copy", str(staged),
            ]
            muxer = "FFmpeg"
            success_codes = {0}

        progress(35.0, f"muxing chapters with {muxer}")
        result = _run(command, 1800)
        if result.returncode not in success_codes:
            for line in (result.stderr or result.stdout).splitlines()[-15:]:
                log("error", line)
            return fail("mux_failed", f"{muxer} exited {result.returncode}")
        if result.returncode == 1:
            for line in (result.stdout + "\n" + result.stderr).splitlines()[-10:]:
                if line.strip():
                    log("warning", line)
        if not staged.is_file() or staged.stat().st_size <= 0:
            return fail("output_missing", f"{muxer} did not produce a non-empty output")

        progress(85.0, "verifying exact chapter timestamps")
        actual = _probe_chapters(ffprobe, staged)
        if not _same_chapters(chapters, actual):
            return fail(
                "verification_failed",
                "The muxed chapter table did not preserve every title and exact PTS; the output was not promoted.")
        os.replace(staged, output)
        progress(100.0, "done")
        emit(
            "complete", output=str(output), size_bytes=output.stat().st_size,
            chapters_written=len(chapters), muxer=muxer, exact_pts_verified=True)
        return 0
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return fail("write_failed", str(exc))
    finally:
        if metadata_path is not None:
            metadata_path.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaptermark-sidecar",
        description="Read, import, export, and mux exact-PTS MKV/MP4 chapters.",
    )
    sub = parser.add_subparsers(dest="op", required=True)

    read = sub.add_parser("read", help="Read chapters from a media file")
    read.add_argument("--input", required=True)
    read.add_argument("--output", help="Optional exact chapter JSON export path")

    import_cmd = sub.add_parser("import", help="Import JSON, Matroska XML, or simple chapter text")
    import_cmd.add_argument("--input", required=True)

    export_cmd = sub.add_parser("export", help="Export reviewed chapters to JSON, XML, or simple text")
    export_cmd.add_argument("--chapters-json", required=True)
    export_cmd.add_argument("--output", required=True)

    write = sub.add_parser("write", help="Replace a media file's chapter table without re-encoding")
    write.add_argument("--input", required=True)
    write.add_argument("--output", required=True)
    write.add_argument("--chapters-json", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "read":
            return op_read(args)
        if args.op == "import":
            return op_import(args)
        if args.op == "export":
            return op_export(args)
        if args.op == "write":
            return op_write(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user")
    except Exception as exc:  # pylint: disable=broad-except
        return fail("unhandled", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())

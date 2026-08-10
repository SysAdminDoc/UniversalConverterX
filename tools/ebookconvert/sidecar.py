"""eBook converter sidecar -- thin NDJSON wrapper around Calibre's
`ebook-convert` CLI.

Supported formats (Calibre handles dozens; common ones surfaced in UI):
  EPUB, MOBI, AZW3, PDF, FB2, LIT, LRF, PDB, RTF, TXT, HTML, HTMLZ, DOCX, ODT,
  CBZ, CBR (read-only). EPUB↔KEPUB is handled locally; it does not require
  Calibre or a Kobo plugin.

Frozen-guard: pure Python shim, no third-party deps.
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
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_calibre() -> str | None:
    env = os.environ.get("CALIBRE_PATH")
    if env and Path(env).is_file():
        return env
    for name in ("ebook-convert.exe", "ebook-convert"):
        hit = shutil.which(name)
        if hit:
            return hit
    candidates = [
        r"C:\Program Files\Calibre2\ebook-convert.exe",
        r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
        r"C:\Program Files\Calibre\ebook-convert.exe",
        # Co-located portable bundle
        str(Path(__file__).resolve().parent / "Calibre" / "ebook-convert.exe"),
    ]
    if os.name != "nt":
        candidates += [
            "/usr/bin/ebook-convert",
            "/usr/local/bin/ebook-convert",
            "/Applications/calibre.app/Contents/MacOS/ebook-convert",
        ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


KNOWN_FORMATS = [
    "epub", "mobi", "azw3", "pdf", "fb2", "lit", "lrf", "pdb",
    "rtf", "txt", "html", "htmlz", "docx", "odt", "cbz", "kepub",
]

_KEPUB_SUFFIX = ".kepub.epub"
_KOBO_SPAN_CLASS = "kobospan"
_XHTML_EXTENSIONS = {".xhtml", ".html", ".htm"}
_SKIP_KEPUB_NODES = {"head", "script", "style", "pre", "code"}
_KINDLE_PROTECTED_EXTENSIONS = {
    ".azw", ".azw3", ".azw4", ".kf8", ".kfx", ".mobi", ".tpz",
}
_KINDLE_PROTECTION_MARKERS = (
    b"drmion",
    b"drm",
    b"voucher",
    b"rights.xml",
    b"encryption.xml",
    b"kindle:drm",
)


# Calibre prints lines like "10% Initial output" -- catch the leading percent.
_PCT_RE = re.compile(r"^\s*(\d{1,3})%")


def build_calibre_environment(job_dir: Path) -> dict[str, str]:
    """Return an isolated Calibre environment with no user-installed plugins."""
    env = os.environ.copy()
    for unsafe_name in ("CALIBRE_DEVELOP_FROM", "PYTHONHOME", "PYTHONPATH"):
        env.pop(unsafe_name, None)

    directories = {
        "CALIBRE_CONFIG_DIRECTORY": job_dir / "config",
        "CALIBRE_CACHE_DIRECTORY": job_dir / "cache",
        "CALIBRE_TEMP_DIR": job_dir / "temp",
    }
    for name, directory in directories.items():
        directory.mkdir(parents=True, exist_ok=True)
        env[name] = str(directory)

    # An empty per-job config directory prevents discovery of user-installed
    # plugins. ebook-convert has no supported global --ignore-plugins switch.
    env["CALIBRE_ALLOW_PYTHON_TEMPLATES"] = "0"
    return env


def promote_output(staged_path: Path, destination: Path) -> None:
    """Validate a staged output before atomically replacing the destination."""
    if staged_path.is_symlink() or not staged_path.is_file():
        raise RuntimeError("Calibre did not produce a regular output file")
    if staged_path.stat().st_size == 0:
        raise RuntimeError("Calibre produced an empty output file")
    os.replace(staged_path, destination)


def _is_kepub_filename(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(_KEPUB_SUFFIX) or name.endswith(".kepub")


def _kepub_output_name(source: Path, target: str) -> str:
    name = source.name
    lowered = name.lower()
    if target == "kepub":
        if lowered.endswith(_KEPUB_SUFFIX):
            return name
        if lowered.endswith(".kepub"):
            return name + ".epub"
        if lowered.endswith(".epub"):
            return name[:-len(".epub")] + _KEPUB_SUFFIX
        return source.stem + _KEPUB_SUFFIX

    if lowered.endswith(_KEPUB_SUFFIX):
        return name[:-len(_KEPUB_SUFFIX)] + ".epub"
    if lowered.endswith(".kepub"):
        return name[:-len(".kepub")] + ".epub"
    return source.stem + ".epub"


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _xml_namespace(tag: str) -> str:
    if isinstance(tag, str) and tag.startswith("{") and "}" in tag:
        return tag[1:tag.index("}")]
    return ""


def _is_kobo_span(element: ET.Element) -> bool:
    classes = (element.attrib.get("class") or "").split()
    return _xml_local_name(element.tag) == "span" and any(
        value.lower() == _KOBO_SPAN_CLASS for value in classes)


def _make_kobo_span(namespace: str, text: str, sequence: list[int]) -> ET.Element:
    sequence[0] += 1
    tag = f"{{{namespace}}}span" if namespace else "span"
    span = ET.Element(tag, {
        "class": "koboSpan",
        "id": f"kobo.{sequence[0]}.1",
    })
    span.text = text
    return span


def _wrap_kobo_text(parent: ET.Element, namespace: str, sequence: list[int]) -> None:
    if _xml_local_name(parent.tag) in _SKIP_KEPUB_NODES or _is_kobo_span(parent):
        return

    text = parent.text
    parent.text = None
    if text is not None and text.strip():
        parent.insert(0, _make_kobo_span(namespace, text, sequence))
    elif text is not None:
        parent.text = text

    index = 0
    while index < len(parent):
        child = parent[index]
        if not _is_kobo_span(child):
            _wrap_kobo_text(child, namespace, sequence)
        tail = child.tail
        child.tail = None
        if tail is not None and tail.strip():
            parent.insert(index + 1, _make_kobo_span(namespace, tail, sequence))
            index += 1
        else:
            child.tail = tail
        index += 1


def _append_parent_text(parent: ET.Element, index: int, text: str) -> None:
    if not text:
        return
    if index == 0:
        parent.text = (parent.text or "") + text
    else:
        previous = parent[index - 1]
        previous.tail = (previous.tail or "") + text


def _unwrap_kobo_text(parent: ET.Element) -> None:
    index = 0
    while index < len(parent):
        child = parent[index]
        if _is_kobo_span(child):
            prefix = child.text or ""
            tail = child.tail or ""
            children = list(child)
            parent.remove(child)
            _append_parent_text(parent, index, prefix)
            for offset, grandchild in enumerate(children):
                parent.insert(index + offset, grandchild)
            if children:
                last = parent[index + len(children) - 1]
                last.tail = (last.tail or "") + tail
                for grandchild in children:
                    _unwrap_kobo_text(grandchild)
                index += len(children)
            else:
                _append_parent_text(parent, index, tail)
            continue

        _unwrap_kobo_text(child)
        index += 1


def _transform_xhtml(data: bytes, to_kepub: bool, sequence: list[int]) -> bytes:
    root = ET.fromstring(data, parser=ET.XMLParser())
    body = next((element for element in root.iter()
                 if _xml_local_name(element.tag) == "body"), None)
    if body is None:
        return data

    namespace = _xml_namespace(root.tag)
    if to_kepub:
        _wrap_kobo_text(body, namespace, sequence)
    else:
        _unwrap_kobo_text(body)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _validate_zip_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        raise ValueError(f"unsafe EPUB member rejected: {name!r}")
    if any(part == ".." for part in normalized.split("/")):
        raise ValueError(f"unsafe EPUB member rejected: {name!r}")
    return normalized


def _rewrite_epub(src: Path, destination: Path, to_kepub: bool) -> None:
    with zipfile.ZipFile(str(src), "r") as archive:
        entries: dict[str, bytes] = {}
        for info in archive.infolist():
            name = _validate_zip_member(info.filename)
            if name in entries:
                raise ValueError(f"duplicate EPUB member: {name}")
            entries[name] = archive.read(info)

    mimetype = entries.get("mimetype")
    if mimetype != b"application/epub+zip":
        raise ValueError("input is not a valid EPUB/KEPUB archive (mimetype missing)")

    sequence = [0]
    transformed: dict[str, bytes] = {}
    for name, data in entries.items():
        if Path(name).suffix.lower() in _XHTML_EXTENSIONS:
            transformed[name] = _transform_xhtml(data, to_kepub, sequence)
        else:
            transformed[name] = data

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".ucx-kepub-", suffix=".epub", dir=destination.parent,
            delete=False,
        ) as raw:
            temporary = Path(raw.name)
        with zipfile.ZipFile(str(temporary), "w") as output:
            output.writestr("mimetype", transformed["mimetype"],
                            compress_type=zipfile.ZIP_STORED)
            for name, data in transformed.items():
                if name == "mimetype":
                    continue
                output.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _protected_kindle_reason(path: Path) -> str | None:
    extension = path.suffix.lower()
    if extension not in _KINDLE_PROTECTED_EXTENSIONS:
        return None
    if extension == ".kfx":
        return ("KFX input is refused by the DRM-free workflow; UCX does not include "
                "DeDRM and will not bypass Kindle DRM. Provide a DRM-free export.")
    try:
        with path.open("rb") as stream:
            sample = stream.read(4 * 1024 * 1024).lower()
    except OSError as ex:
        return f"Could not inspect Kindle input for DRM protection: {ex}"
    if any(marker in sample for marker in _KINDLE_PROTECTION_MARKERS):
        return ("Protected Kindle input detected; UCX does not include DeDRM and "
                "will not bypass DRM. Provide a DRM-free export.")
    return None


def op_kepub_convert(args: argparse.Namespace, inputs: list[Path], target: str) -> int:
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(inputs)
    outputs: list[Path] = []
    emit("progress", percent=0, stage="kepub", eta_seconds=None)
    for index, src in enumerate(inputs):
        if target == "kepub" and src.suffix.lower() not in {".epub", ".kepub"}:
            return fail("invalid_kepub_source",
                        f"{src.name}: KEPUB input must be an EPUB archive.")
        out_path = out_dir / _kepub_output_name(src, target)
        try:
            _rewrite_epub(src, out_path, to_kepub=target == "kepub")
        except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as ex:
            return fail("kepub_failed", f"{src.name}: {ex}")
        outputs.append(out_path)
        emit("ebook", input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size, format=target, source="kepub")
        emit("progress", percent=round((index + 1) / total * 100, 1),
             stage=f"{index + 1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir),
         size_bytes=sum(path.stat().st_size for path in outputs), count=total)
    return 0


def op_convert(args: argparse.Namespace) -> int:
    target = args.format.lower().lstrip(".")
    if not re.fullmatch(r"[a-z0-9]{1,16}", target):
        return fail("invalid_format", "Target format must be a simple extension token")
    if target not in KNOWN_FORMATS:
        emit("log", level="warn",
             message=f"Format '{target}' is not in the curated list; Calibre "
                     "may still accept it.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"eBook(s) not found: {missing}")

    for src in inputs:
        reason = _protected_kindle_reason(src)
        if reason is not None:
            return fail("protected_input", f"{src.name}: {reason}")

    if target == "kepub":
        return op_kepub_convert(args, inputs, target)
    if getattr(args, "from_kepub", False):
        if target != "epub" or not all(_is_kepub_filename(src) for src in inputs):
            return fail("invalid_kepub_source",
                        "--from-kepub requires KEPUB input and an EPUB target.")
        return op_kepub_convert(args, inputs, target)
    if target == "epub" and all(_is_kepub_filename(src) for src in inputs):
        return op_kepub_convert(args, inputs, target)
    if target == "epub" and any(_is_kepub_filename(src) for src in inputs):
        return fail("mixed_kepub_batch",
                    "KEPUB and ordinary EPUB inputs cannot share one batch; run them separately.")

    calibre = find_calibre()
    if not calibre:
        return fail(
            "missing_calibre",
            "Calibre's ebook-convert.exe not found. Install Calibre "
            "(https://calibre-ebook.com/download) or set $env:CALIBRE_PATH.")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    emit("log", level="info",
         message=f"Convert {total} eBook(s) -> .{target} via Calibre")
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    started = time.monotonic()
    outputs: list[Path] = []
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + target)
        with tempfile.TemporaryDirectory(prefix="ucx-ebook-") as job_dir_raw:
            job_dir = Path(job_dir_raw)
            input_dir = job_dir / "input"
            output_dir = job_dir / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            # Copy the source into the job root so HTML and archive parsers cannot
            # traverse sibling files beside the user's original document.
            staged_input = input_dir / src.name
            staged_output = output_dir / (src.stem + "." + target)
            shutil.copyfile(src.resolve(), staged_input)

            cmd = [calibre, str(staged_input), str(staged_output)]
            if args.title:    cmd += ["--title", args.title]
            if args.authors:  cmd += ["--authors", args.authors]
            if args.language: cmd += ["--language", args.language]

            proc = subprocess.Popen(
                cmd,
                cwd=job_dir,
                env=build_calibre_environment(job_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = raw.rstrip()
                    if not line:
                        continue
                    m = _PCT_RE.match(line)
                    if m:
                        inner = float(m.group(1))
                        # Combine inner-file progress with batch progress so the UI
                        # bar moves smoothly across the whole queue.
                        overall = (i + inner / 100.0) / total * 100.0
                        elapsed = time.monotonic() - started
                        local = overall / 100.0
                        eta = (elapsed / local - elapsed) if local > 0.01 else None
                        emit("progress",
                             percent=round(overall, 1),
                             stage=f"{i + 1}/{total}: {line}",
                             eta_seconds=int(eta) if eta and eta < 86400 else None)
                    else:
                        emit("log", level="info", message=line)
            finally:
                proc.wait()

            if proc.returncode != 0:
                return fail("calibre_failed",
                            f"ebook-convert exited {proc.returncode} on {src.name}")
            try:
                promote_output(staged_output, out_path)
            except RuntimeError as ex:
                return fail("output_invalid", f"{ex} for {src.name}")

        emit("ebook",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, source="calibre")
        outputs.append(out_path)

    total_size = sum(path.stat().st_size for path in outputs)
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ebookconvert-sidecar",
                                description="eBook conversion via Calibre.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert", help="Convert one or more eBooks")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="Target: " + " | ".join(KNOWN_FORMATS))
    cv.add_argument("--title", help="Override book title metadata")
    cv.add_argument("--authors", help='Override author(s) metadata (e.g. "Asimov, Isaac")')
    cv.add_argument("--language", help="Override language metadata (e.g. en, fr)")
    cv.add_argument("--from-kepub", action="store_true",
                    help="Require KEPUB input and use the local reverse transformer")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":
            return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

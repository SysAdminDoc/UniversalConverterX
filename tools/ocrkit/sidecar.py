"""Unified offline OCR router for mixed image and PDF batches."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit


IMAGE_EXTENSIONS = {
    ".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".jp2", ".png", ".pnm",
    ".tif", ".tiff", ".webp",
}


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def locate_engine(name: str) -> list[str] | None:
    roots: list[Path] = []
    configured = os.environ.get("UCX_TOOLS_DIR")
    if configured:
        roots.append(Path(configured))
    here = _runtime_dir()
    roots.append(here.parent)
    tools_root = next(
        (candidate for candidate in (here, *here.parents) if candidate.name.lower() == "tools"),
        None,
    )
    if tools_root is not None:
        roots.append(tools_root)

    for root in roots:
        tool = root / name
        for executable in (tool / f"{name}.exe", tool / "dist" / f"{name}.exe"):
            if executable.is_file():
                return [str(executable)]
        source = tool / "sidecar.py"
        if source.is_file() and not getattr(sys, "frozen", False):
            return [sys.executable, str(source)]
    return None


def run_child(
    command_prefix: list[str],
    arguments: list[str],
    *,
    start_percent: float,
    end_percent: float,
) -> tuple[bool, str | None]:
    process = subprocess.Popen(
        [*command_prefix, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    error_message: str | None = None
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            emit("log", level="info", message=line[-1000:])
            continue
        name = event.pop("event", "log")
        if name == "complete":
            continue
        if name == "progress":
            local = max(0.0, min(100.0, float(event.get("percent", 0)))) / 100.0
            event["percent"] = round(start_percent + local * (end_percent - start_percent), 1)
        if name == "error":
            error_message = str(event.get("message") or event.get("code") or "OCR child failed")
        emit(name, **event)
    return_code = process.wait()
    if return_code != 0 and error_message is None:
        error_message = f"OCR child exited with code {return_code}"
    return return_code == 0, error_message


def probe_child(command_prefix: list[str]) -> bool:
    try:
        result = subprocess.run(
            [*command_prefix, "probe"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for line in reversed((result.stdout or "").splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") in {"backend", "complete"} and "available" in event:
            return result.returncode == 0 and bool(event["available"])
    return False


def op_probe(_: argparse.Namespace) -> int:
    engines: dict[str, bool] = {}
    for name in ("ocr", "pdfocr"):
        command = locate_engine(name)
        engines[name] = command is not None and probe_child(command)
    emit("backend", available=all(engines.values()), engines=engines)
    emit("complete", output="", size_bytes=0, available=all(engines.values()))
    return 0 if all(engines.values()) else 1


def op_recognize(args: argparse.Namespace) -> int:
    inputs = [Path(value) for value in args.input]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        return fail("missing_input", f"OCR input(s) not found: {missing}")
    unsupported = [str(path) for path in inputs if path.suffix.lower() not in IMAGE_EXTENSIONS | {".pdf"}]
    if unsupported:
        return fail("unsupported_input", f"Unsupported OCR input type(s): {unsupported}")

    images = [path for path in inputs if path.suffix.lower() in IMAGE_EXTENSIONS]
    pdfs = [path for path in inputs if path.suffix.lower() == ".pdf"]
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    groups = [("ocr", images), ("pdfocr", pdfs)]
    active = [(name, paths) for name, paths in groups if paths]
    emit(
        "log", level="info",
        message=f"Unified OCR: {len(images)} image(s), {len(pdfs)} PDF(s), language={args.lang}",
    )

    for index, (engine, paths) in enumerate(active):
        prefix = locate_engine(engine)
        if prefix is None:
            return fail("missing_engine", f"Required OCR engine is not installed: {engine}")
        child_args = [
            "recognize", "--input", *[str(path) for path in paths],
            "--output-dir", str(output), "--lang", args.lang,
        ]
        if engine == "ocr":
            child_args += ["--format", args.image_format, "--psm", str(args.psm)]
        else:
            child_args += ["--output-type", args.pdf_output_type]
            if args.deskew:
                child_args.append("--deskew")
            if args.rotate_pages:
                child_args.append("--rotate-pages")
            if args.clean:
                child_args.append("--clean")
            if args.skip_text:
                child_args.append("--skip-text")
        start = index / len(active) * 100.0
        end = (index + 1) / len(active) * 100.0
        success, error = run_child(prefix, child_args, start_percent=start, end_percent=end)
        if not success:
            return fail(f"{engine}_failed", error or f"{engine} failed")

    emit("complete", output=str(output), size_bytes=0, count=len(inputs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocrkit-sidecar",
        description="Unified offline image and searchable-PDF OCR.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe", help="Check image and PDF OCR child engines.")
    recognize = sub.add_parser("recognize", help="OCR a mixed image/PDF batch.")
    recognize.add_argument("--input", nargs="+", required=True)
    recognize.add_argument("--output-dir", required=True, dest="output_dir")
    recognize.add_argument("--lang", default="eng")
    recognize.add_argument("--image-format", choices=["txt", "hocr", "pdf", "tsv", "alto"], default="txt")
    recognize.add_argument("--psm", type=int, choices=range(0, 14), default=3)
    recognize.add_argument("--pdf-output-type", choices=["pdf", "pdfa", "pdfa-1", "pdfa-2", "pdfa-3"], default="pdfa-2")
    recognize.add_argument("--deskew", action=argparse.BooleanOptionalAction, default=True)
    recognize.add_argument("--rotate-pages", action=argparse.BooleanOptionalAction, default=True)
    recognize.add_argument("--clean", action="store_true")
    recognize.add_argument("--skip-text", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "recognize":
            return op_recognize(args)
        return fail("unknown_op", f"Unknown operation: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

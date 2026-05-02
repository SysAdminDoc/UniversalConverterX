"""exiftool-meta sidecar — read/write/clear EXIF / XMP / IPTC / GPS tags.

ROADMAP Item 12. Wraps the upstream `exiftool` Perl CLI (Phil Harvey,
Artistic License) which understands 100+ image / video / RAW / sidecar
formats and is the de-facto reference implementation for photographic
metadata round-tripping.

Subcommands:
  read           Emit the full tag dictionary for one or more files.
  write          Set tags on one or more files (-tag=value).
  clear          Remove all metadata or a specific tag group.
  template       Apply a JSON metadata template to every input.
  rotate-orient  Rewrite physical orientation while preserving rotation tags.
  probe          Report whether exiftool is on PATH and its version.

Standard NDJSON contract: progress / log / complete / error events on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ── NDJSON helpers ───────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


# ── exiftool discovery ───────────────────────────────────────────────────────

def _find_exiftool() -> str | None:
    candidates: list[str | None] = [
        os.environ.get("EXIFTOOL_PATH"),
        shutil.which("exiftool"),
    ]
    here = Path(__file__).resolve().parent
    candidates += [
        str(here / "exiftool.exe"),
        str(here / "exiftool"),
        str(here.parent / "_bin" / "exiftool.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _require_exiftool() -> str:
    binary = _find_exiftool()
    if not binary:
        emit("error", code="missing_exiftool",
             message=("exiftool is not installed. Drop exiftool.exe next to this "
                      "sidecar or under tools/_bin/, or install it from "
                      "exiftool.org. Bundled portable build is recommended."))
        sys.exit(1)
    return binary


# ── Ops ──────────────────────────────────────────────────────────────────────

def op_read(args: argparse.Namespace) -> int:
    binary = _require_exiftool()
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"File(s) not found: {missing}")

    cmd = [binary, "-j", "-G", "-charset", "UTF8"]
    if args.tag_group:
        cmd += [f"-{args.tag_group}:all"]
    cmd += [str(p) for p in inputs]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        for ln in (proc.stderr or "").splitlines()[-15:]:
            log("error", ln)
        return fail("read_failed", f"exiftool exited {proc.returncode}")

    try:
        records = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as ex:
        return fail("parse_failed", f"Could not parse exiftool JSON: {ex}")

    total = len(records)
    for i, rec in enumerate(records):
        path = rec.get("SourceFile", str(inputs[i] if i < len(inputs) else ""))
        emit("metadata_record",
             path=path,
             tag_count=len([k for k in rec if k != "SourceFile"]),
             tags=rec)
        emit("progress", percent=round((i + 1) / max(total, 1) * 100, 1),
             stage=f"read {i+1}/{total}", eta_seconds=None)

    emit("complete", output="", size_bytes=0, count=total)
    return 0


def op_write(args: argparse.Namespace) -> int:
    binary = _require_exiftool()
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"File(s) not found: {missing}")
    if not args.set:
        return fail("bad_arg", "write requires at least one --set TAG=value.")

    set_args: list[str] = []
    for kv in args.set:
        if "=" not in kv:
            return fail("bad_arg", f"--set expects TAG=value, got '{kv}'")
        # exiftool accepts either `-Author=value` or `-XMP:Subject=value` —
        # pass through verbatim so callers retain group qualification.
        tag, value = kv.split("=", 1)
        set_args.append(f"-{tag.strip()}={value}")

    cmd = [binary, "-charset", "UTF8"]
    if not args.preserve_backup:
        cmd.append("-overwrite_original")
    cmd += set_args
    cmd += [str(p) for p in inputs]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        for ln in (proc.stderr or "").splitlines()[-15:]:
            log("error", ln)
        return fail("write_failed", f"exiftool exited {proc.returncode}")

    total = len(inputs)
    for i, p in enumerate(inputs):
        emit("metadata_record",
             path=str(p),
             updated=[kv.split("=", 1)[0].strip() for kv in args.set])
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"wrote {i+1}/{total}", eta_seconds=None)

    if proc.stdout:
        log("info", proc.stdout.strip().splitlines()[-1])
    emit("complete", output="", size_bytes=0, count=total)
    return 0


def op_clear(args: argparse.Namespace) -> int:
    binary = _require_exiftool()
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"File(s) not found: {missing}")

    cmd = [binary, "-charset", "UTF8"]
    if not args.preserve_backup:
        cmd.append("-overwrite_original")
    if args.tag_group:
        cmd += [f"-{args.tag_group}:all="]
    else:
        cmd += ["-all="]
    cmd += [str(p) for p in inputs]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        for ln in (proc.stderr or "").splitlines()[-15:]:
            log("error", ln)
        return fail("clear_failed", f"exiftool exited {proc.returncode}")

    total = len(inputs)
    for i, p in enumerate(inputs):
        emit("metadata_record",
             path=str(p),
             cleared=args.tag_group or "all")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"cleared {i+1}/{total}", eta_seconds=None)

    if proc.stdout:
        log("info", proc.stdout.strip().splitlines()[-1])
    emit("complete", output="", size_bytes=0, count=total)
    return 0


def op_template(args: argparse.Namespace) -> int:
    """Apply a JSON metadata template to every input. The template is a JSON
    object whose keys are exiftool tag names (with optional group prefix) and
    values are the desired tag content. Useful for batch-stamping a folder
    of photos with a copyright / artist / location set."""
    binary = _require_exiftool()
    template_path = Path(args.template)
    if not template_path.is_file():
        return fail("missing_template", f"Template file not found: {args.template}")
    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        return fail("bad_template", f"Template is not valid JSON: {ex}")
    if not isinstance(template, dict) or not template:
        return fail("bad_template", "Template must be a non-empty JSON object.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"File(s) not found: {missing}")

    cmd = [binary, "-charset", "UTF8"]
    if not args.preserve_backup:
        cmd.append("-overwrite_original")
    for tag, value in template.items():
        cmd.append(f"-{tag}={value}")
    cmd += [str(p) for p in inputs]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        for ln in (proc.stderr or "").splitlines()[-15:]:
            log("error", ln)
        return fail("template_failed", f"exiftool exited {proc.returncode}")

    total = len(inputs)
    for i, p in enumerate(inputs):
        emit("metadata_record",
             path=str(p),
             template=str(template_path),
             updated=list(template.keys()))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"stamped {i+1}/{total}", eta_seconds=None)

    if proc.stdout:
        log("info", proc.stdout.strip().splitlines()[-1])
    emit("complete", output="", size_bytes=0, count=total)
    return 0


def op_rotate_orient(args: argparse.Namespace) -> int:
    """Apply an explicit Orientation tag value (1..8) without rewriting pixel
    data. Useful when a camera tagged the file but image viewers ignore the
    tag — paired with a viewer-side rotate this normalises the library."""
    binary = _require_exiftool()
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"File(s) not found: {missing}")

    if args.orientation not in range(1, 9):
        return fail("bad_arg", f"--orientation must be 1..8, got {args.orientation}.")

    cmd = [binary, "-charset", "UTF8"]
    if not args.preserve_backup:
        cmd.append("-overwrite_original")
    cmd += [f"-Orientation={args.orientation}", "-n"]
    cmd += [str(p) for p in inputs]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        for ln in (proc.stderr or "").splitlines()[-15:]:
            log("error", ln)
        return fail("rotate_failed", f"exiftool exited {proc.returncode}")

    total = len(inputs)
    for i, p in enumerate(inputs):
        emit("metadata_record", path=str(p), orientation=args.orientation)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"rotated {i+1}/{total}", eta_seconds=None)
    emit("complete", output="", size_bytes=0, count=total)
    return 0


def op_probe(_args: argparse.Namespace) -> int:
    binary = _find_exiftool()
    if not binary:
        log("warn", "exiftool is not on PATH and not bundled.")
        emit("complete", output="", size_bytes=0,
             exiftool_path=None, exiftool_version=None)
        return 0
    try:
        result = subprocess.run([binary, "-ver"],
                                capture_output=True, text=True, timeout=15)
        version = (result.stdout or result.stderr or "").strip()
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"
    log("info", f"exiftool at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         exiftool_path=binary, exiftool_version=version)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="exiftool-meta-sidecar",
                                description="EXIF / XMP / IPTC / GPS metadata read+write+clear via exiftool.")
    sub = p.add_subparsers(dest="op", required=True)

    r = sub.add_parser("read", help="Emit the full tag dictionary for one or more files.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--tag-group", default=None, dest="tag_group",
                   help="Optional group filter (EXIF, XMP, IPTC, GPS, ICC_Profile, …).")

    w = sub.add_parser("write", help="Set tags on one or more files.")
    w.add_argument("--input", nargs="+", required=True)
    w.add_argument("--set", action="append", required=True,
                   help="Repeatable TAG=value (e.g. --set Artist=\"Jane\" --set XMP:Subject=Photo).")
    w.add_argument("--preserve-backup", action="store_true", dest="preserve_backup",
                   help="Keep exiftool's _original backup file (default removes it).")

    c = sub.add_parser("clear", help="Remove all metadata or a specific tag group.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--tag-group", default=None, dest="tag_group",
                   help="Optional group filter (EXIF, XMP, IPTC, …). Omit to clear everything.")
    c.add_argument("--preserve-backup", action="store_true", dest="preserve_backup")

    t = sub.add_parser("template",
                       help="Apply a JSON metadata template to every input.")
    t.add_argument("--input", nargs="+", required=True)
    t.add_argument("--template", required=True,
                   help="Path to a JSON object whose keys are tag names and values are the desired content.")
    t.add_argument("--preserve-backup", action="store_true", dest="preserve_backup")

    o = sub.add_parser("rotate-orient",
                       help="Set the EXIF Orientation tag without re-encoding pixels.")
    o.add_argument("--input", nargs="+", required=True)
    o.add_argument("--orientation", required=True, type=int,
                   help="1=normal / 2=mirror H / 3=180° / 4=mirror V / 5=mirror H+90° CW / 6=90° CW / 7=mirror H+90° CCW / 8=90° CCW")
    o.add_argument("--preserve-backup", action="store_true", dest="preserve_backup")

    sub.add_parser("probe", help="Report whether exiftool is installed and its version.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "read":          return op_read(args)
        if args.op == "write":         return op_write(args)
        if args.op == "clear":         return op_clear(args)
        if args.op == "template":      return op_template(args)
        if args.op == "rotate-orient": return op_rotate_orient(args)
        if args.op == "probe":         return op_probe(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

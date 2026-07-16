"""Archive sidecar -- NDJSON wrapper around 7-Zip's `7z.exe`.

Read formats: 7z, zip, rar, tar, gz, bz2, xz, iso, cab, lzma, ar, lzh, msi
Write formats: 7z, zip, tar, gz, bz2, xz, lzma, wim
(7-Zip cannot WRITE rar -- the rar format is non-free; we only extract it.)

Frozen-guard: pure-Python wrapper, no pip calls -- the contract test passes
because no subprocess pip pattern exists in this file at all.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_7z() -> str | None:
    env = os.environ.get("SEVENZIP_PATH")
    if env and Path(env).is_file():
        return env
    for name in ("7z.exe", "7z", "7zz"):
        hit = shutil.which(name)
        if hit:
            return hit
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        # Co-located portable install
        str(Path(__file__).resolve().parent / "7-Zip" / "7z.exe"),
    ]
    if os.name != "nt":
        candidates += ["/usr/bin/7z", "/usr/local/bin/7z", "/opt/homebrew/bin/7z"]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


# 7z prints progress as ' 12%' or ' 12% 23 - some/file.ext' when run with -bsp1.
_PCT_RE = re.compile(r"(\d{1,3})%")
_ZONE_IDENTIFIER_SUFFIX = ":Zone.Identifier"
_MAX_ZONE_IDENTIFIER_BYTES = 64 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def read_zone_identifier(path: Path) -> bytes | None:
    """Read a Windows Mark-of-the-Web stream, or None when not present."""
    if os.name != "nt":
        return None
    try:
        with open(str(path) + _ZONE_IDENTIFIER_SUFFIX, "rb") as stream:
            data = stream.read(_MAX_ZONE_IDENTIFIER_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(data) > _MAX_ZONE_IDENTIFIER_BYTES:
        raise ValueError("Zone.Identifier exceeds the 64 KiB safety limit")
    return data


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(stat, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def collect_regular_files(root: Path) -> list[Path]:
    """Collect extracted files without following symlinks or junctions."""
    files: list[Path] = []
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for directory in list(directories):
            candidate = current_path / directory
            if _is_link_or_reparse_point(candidate):
                raise RuntimeError(f"Archive produced a link or reparse point: {candidate.name}")
        for name in names:
            candidate = current_path / name
            if _is_link_or_reparse_point(candidate):
                raise RuntimeError(f"Archive produced a link or reparse point: {candidate.name}")
            if candidate.is_file():
                files.append(candidate)
    return files


def apply_zone_identifier(files: list[Path], zone_data: bytes | None) -> int:
    """Apply Mark-of-the-Web to regular staging files before promotion."""
    if zone_data is None:
        return 0
    for path in files:
        with open(str(path) + _ZONE_IDENTIFIER_SUFFIX, "wb") as stream:
            stream.write(zone_data)
            stream.flush()
            os.fsync(stream.fileno())
    return len(files)


def promote_extracted_tree(staging: Path, destination: Path, files: list[Path]) -> None:
    """Promote a validated extraction tree only after 7-Zip fully succeeds."""
    for directory in sorted(
            (path for path in staging.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts)):
        relative = directory.relative_to(staging)
        target = destination / relative
        if target.exists() and not target.is_dir():
            raise RuntimeError(f"Cannot replace file with extracted directory: {relative}")
        target.mkdir(parents=True, exist_ok=True)

    for path in files:
        relative = path.relative_to(staging)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.is_dir():
            raise RuntimeError(f"Cannot replace directory with extracted file: {relative}")
        os.replace(path, target)


def _stream_7z(cmd: list[str], stage: str) -> int:
    """Run a 7z command, parse percent progress, surface log lines."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    started = time.monotonic()
    last_pct = -1.0
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            m = _PCT_RE.search(line)
            if m:
                pct = float(m.group(1))
                if pct - last_pct >= 0.5:
                    last_pct = pct
                    elapsed = time.monotonic() - started
                    local = pct / 100.0
                    eta = (elapsed / local - elapsed) if local > 0.01 else None
                    emit("progress",
                         percent=round(pct, 1), stage=stage,
                         eta_seconds=int(eta) if eta and eta < 86400 else None)
                continue
            # Surface 7z's textual output as info-log so the UI can show it.
            emit("log", level="info", message=line)
    finally:
        proc.wait()
    return proc.returncode


def op_pack(args: argparse.Namespace) -> int:
    sevenz = find_7z()
    if not sevenz:
        return fail("missing_7zip",
                    "7-Zip not found. Install from https://www.7-zip.org/ or "
                    "set $env:SEVENZIP_PATH.")

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        return fail("missing_input", f"Input(s) not found: {missing}")

    fmt = (args.format or out.suffix.lstrip(".") or "7z").lower()
    if fmt not in {"7z", "zip", "tar", "gz", "bz2", "xz", "lzma", "wim"}:
        return fail("bad_format",
                    f"7-Zip cannot write '{fmt}'. Use 7z / zip / tar / gz / bz2 / xz / lzma / wim.")

    # 7z 'a' (add). -bso1 routes std streams to stdout; -bsp1 progress to stdout
    # so we can parse it; -mx<level> sets compression level.
    cmd: list[str] = [sevenz, "a",
                      "-bso1", "-bsp1", "-bse2",
                      f"-mx{int(args.level)}",
                      "-y",
                      f"-t{fmt}", str(out)]
    if args.password:
        cmd.append(f"-p{args.password}")
        if fmt == "7z":
            cmd.append("-mhe")  # encrypt headers too on 7z
    cmd.extend(str(p) for p in inputs)

    emit("log", level="info",
         message=f"Pack {len(inputs)} item(s) -> {out.name} ({fmt}, level {args.level})")
    emit("progress", percent=0, stage="pack", eta_seconds=None)
    rc = _stream_7z(cmd, "pack")
    if rc != 0:
        return fail("sevenzip_failed", f"7z exited with code {rc}")
    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")
    emit("complete", output=str(out), size_bytes=out.stat().st_size,
         input_count=len(inputs))
    return 0


def op_unpack(args: argparse.Namespace) -> int:
    sevenz = find_7z()
    if not sevenz:
        return fail("missing_7zip",
                    "7-Zip not found. Install from https://www.7-zip.org/ or "
                    "set $env:SEVENZIP_PATH.")

    src = Path(args.input).resolve()
    if not src.is_file():
        return fail("missing_input", f"Archive not found: {args.input}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        zone_data = read_zone_identifier(src)
    except (OSError, ValueError) as ex:
        return fail("motw_read_failed", f"Could not read archive Mark-of-the-Web: {ex}")

    emit("log", level="info",
         message=f"Unpack {src.name} -> {out_dir}")
    emit("progress", percent=0, stage="unpack", eta_seconds=None)

    with tempfile.TemporaryDirectory(
            prefix=".ucx-archive-", dir=out_dir.parent) as staging_raw:
        staging = Path(staging_raw)
        # 7z 'x' preserves directory structure. Extract into a private staging
        # tree so failed jobs never leave partial or unmarked destination files.
        cmd: list[str] = [sevenz, "x",
                          "-bso1", "-bsp1", "-bse2",
                          "-y", "-aoa",
                          f"-o{staging}",
                          str(src)]
        if args.password:
            cmd.append(f"-p{args.password}")

        rc = _stream_7z(cmd, "unpack")
        if rc != 0:
            return fail("sevenzip_failed", f"7z exited with code {rc}")

        try:
            files = collect_regular_files(staging)
            marked = apply_zone_identifier(files, zone_data)
            promote_extracted_tree(staging, out_dir, files)
        except (OSError, RuntimeError) as ex:
            return fail("unsafe_extraction", f"Extraction was not promoted: {ex}")

    extracted = len(files)
    total_size = sum(
        (out_dir / path.relative_to(staging)).stat().st_size
        for path in files)
    if marked:
        emit("log", level="info",
             message=f"Preserved Mark-of-the-Web on {marked} extracted file(s)")
    emit("complete", output=str(out_dir),
         size_bytes=total_size, file_count=extracted)
    return 0


def op_list(args: argparse.Namespace) -> int:
    """Enumerate files inside an archive without extracting. Emits an
    `archive_entry` event per item."""
    sevenz = find_7z()
    if not sevenz:
        return fail("missing_7zip", "7-Zip not found.")
    src = Path(args.input).resolve()
    if not src.is_file():
        return fail("missing_input", f"Archive not found: {args.input}")

    cmd = [sevenz, "l", "-slt", str(src)]
    if args.password:
        cmd.append(f"-p{args.password}")
    proc = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        for ln in (proc.stderr or proc.stdout).splitlines()[-5:]:
            emit("log", level="error", message=ln)
        return fail("sevenzip_failed", f"7z exited with code {proc.returncode}")

    # 7z -slt outputs blocks of "Key = Value" pairs separated by blank lines.
    block: dict[str, str] = {}
    count = 0
    for line in proc.stdout.splitlines():
        if not line.strip():
            if "Path" in block and block.get("Folder", "-") != "+":
                count += 1
                emit("archive_entry",
                     path=block.get("Path", ""),
                     size=int(block.get("Size", "0") or 0),
                     packed_size=int(block.get("Packed Size", "0") or 0),
                     modified=block.get("Modified", ""))
            block = {}
            continue
        if " = " in line:
            k, v = line.split(" = ", 1)
            block[k.strip()] = v.strip()
    if "Path" in block and block.get("Folder", "-") != "+":
        count += 1
        emit("archive_entry",
             path=block.get("Path", ""),
             size=int(block.get("Size", "0") or 0),
             packed_size=int(block.get("Packed Size", "0") or 0),
             modified=block.get("Modified", ""))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, file_count=count)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="archive-sidecar",
                                description="Archive operations via 7-Zip.")
    sub = p.add_subparsers(dest="op", required=True)

    pk = sub.add_parser("pack", help="Create an archive from input files / folders")
    pk.add_argument("--input", nargs="+", required=True,
                    help="Files / folders to compress.")
    pk.add_argument("--output", required=True,
                    help="Output archive path. Format inferred from extension if --format omitted.")
    pk.add_argument("--format", help="7z | zip | tar | gz | bz2 | xz | lzma | wim")
    pk.add_argument("--level", type=int, default=5,
                    help="Compression level 0 (store) - 9 (ultra). Default 5.")
    pk.add_argument("--password", help="Optional archive password.")

    un = sub.add_parser("unpack", help="Extract an archive")
    un.add_argument("--input", required=True)
    un.add_argument("--output-dir", required=True, dest="output_dir")
    un.add_argument("--password", help="Archive password if encrypted.")

    ls = sub.add_parser("list", help="List files inside an archive without extracting")
    ls.add_argument("--input", required=True)
    ls.add_argument("--password", help="Archive password if encrypted.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "pack":   return op_pack(args)
        if args.op == "unpack": return op_unpack(args)
        if args.op == "list":   return op_list(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

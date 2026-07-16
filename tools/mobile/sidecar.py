"""Mobile-device backup sidecar.

Decode iTunes / Finder iOS backups (Manifest.plist + Manifest.db SQLite +
domain-hashed files) and Android adb backups (.ab — DEFLATE-compressed
tar with optional AES encryption header) into a navigable tree.

Operations:
  itunes-list    Inventory an iTunes backup directory -> JSON.
  itunes-extract Restore named-file paths from an iTunes backup tree.
  ab-to-tar      Android adb backup (.ab) -> plain tar.

iOS backup files are named by SHA-1(domain + "-" + relativePath); the
Manifest.db SQLite database maps those hashes back to original paths.
adb backup is a DEFLATE stream wrapped by a small text header
("ANDROID BACKUP\n<version>\n<compression>\n<encryption>\n").
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── iTunes / Finder iOS backup ─────────────────────────────────────────

def _itunes_inventory(backup_dir: Path) -> list[dict]:
    db = backup_dir / "Manifest.db"
    if not db.is_file():
        raise FileNotFoundError(f"Manifest.db missing in {backup_dir}")
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT fileID, domain, relativePath, flags FROM Files"
        ).fetchall()
    finally:
        conn.close()
    return [{"fileID": r[0], "domain": r[1], "relativePath": r[2], "flags": r[3]}
            for r in rows]


def op_itunes_list(args: argparse.Namespace) -> int:
    src = Path(args.backup_dir)
    if not src.is_dir(): return fail("missing_input", f"Backup dir not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        items = _itunes_inventory(src)
    except Exception as ex:
        return fail("parse_failed", f"{src.name}: {ex}")
    out_path = out_dir / (src.name + "_inventory.json")
    out_path.write_text(json.dumps(items, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    emit("mobile_doc",
         input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="json", source="itunes-backup", entries=len(items))
    emit("progress", percent=100.0, stage="1/1", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_itunes_extract(args: argparse.Namespace) -> int:
    src = Path(args.backup_dir)
    if not src.is_dir(): return fail("missing_input", f"Backup dir not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        items = _itunes_inventory(src)
    except Exception as ex:
        return fail("parse_failed", f"{src.name}: {ex}")
    pattern = (args.pattern or "").lower()
    matches = [r for r in items if pattern in (r["relativePath"] or "").lower()]
    if not matches:
        return fail("no_matches", f"No backup entries match: {args.pattern}")
    extracted = 0
    for r in matches:
        fid = r["fileID"]
        # iOS backups: first 2 chars of SHA-1 hash form the subdir.
        blob = src / fid[:2] / fid
        if not blob.is_file(): continue
        rel = r["relativePath"] or fid
        target = out_dir / r["domain"] / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blob, target)
        extracted += 1
    emit("mobile_doc",
         input=str(src), output=str(out_dir),
         size_bytes=0, format="extracted", source="itunes-backup",
         entries=extracted)
    emit("progress", percent=100.0, stage="1/1", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=extracted)
    return 0


# ── Android adb backup (.ab) ───────────────────────────────────────────

def _ab_to_tar(ab: bytes) -> bytes:
    # Header is text terminated by '\n'; first line: "ANDROID BACKUP".
    if not ab.startswith(b"ANDROID BACKUP\n"):
        raise ValueError("Not an adb backup (.ab) file.")
    # parse 4 header lines, then DEFLATE stream begins.
    header_end = 0
    newline_count = 0
    for i, b in enumerate(ab):
        if b == 0x0A:
            newline_count += 1
            if newline_count == 4:
                header_end = i + 1
                break
    if not header_end:
        raise ValueError("Malformed adb backup header.")
    header = ab[:header_end].decode("ascii", errors="replace").splitlines()
    encryption = header[3].strip() if len(header) > 3 else "none"
    if encryption.lower() != "none":
        raise ValueError(f"Encrypted adb backup ({encryption}) — pass through `abe` first.")
    return zlib.decompress(ab[header_end:])


def op_ab_to_tar(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".ab file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tar_bytes = _ab_to_tar(src.read_bytes())
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".tar")
        out_path.write_bytes(tar_bytes)
        emit("mobile_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="tar", source="adb-backup")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mobile-sidecar",
                                description="iTunes / adb mobile-device backup decoder.")
    sub = p.add_subparsers(dest="op", required=True)

    li = sub.add_parser("itunes-list", help="Inventory an iTunes backup -> JSON.")
    li.add_argument("--backup-dir", required=True, dest="backup_dir")
    li.add_argument("--output-dir", required=True, dest="output_dir")

    ex = sub.add_parser("itunes-extract", help="Extract files from iTunes backup.")
    ex.add_argument("--backup-dir", required=True, dest="backup_dir")
    ex.add_argument("--output-dir", required=True, dest="output_dir")
    ex.add_argument("--pattern", default="",
                    help="Substring to match in relativePath (case-insensitive).")

    ab = sub.add_parser("ab-to-tar", help="Android .ab -> plain tar.")
    ab.add_argument("--input", nargs="+", required=True)
    ab.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "itunes-list":    return op_itunes_list(args)
        if args.op == "itunes-extract": return op_itunes_extract(args)
        if args.op == "ab-to-tar":      return op_ab_to_tar(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

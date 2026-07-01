"""Mobile-photos export sidecar (extends `mobile`).

Handle photo-library exports from mobile devices:

  * Google Takeout 'Google Photos' export -> CSV / NDJSON metadata
    + EXIF re-injection from sidecar `*.json` files.
  * Apple Photos library .photoslibrary -> CSV / JSON manifest.
  * iOS .ips ImagePack archive (system diagnostic) -> JSON.
  * Android MediaStore SQLite dump -> CSV / JSON.

Operations:
  takeout-list       Inspect a Google Photos Takeout dir -> CSV manifest.
  takeout-meta-fix   Re-apply timestamps from Takeout sidecar JSON onto images.
  photoslibrary      Apple .photoslibrary bundle -> JSON manifest.
  mediastore-to-csv  Android MediaStore SQLite -> CSV (DCIM / Pictures rows).
  ips-to-json        iOS .ips diagnostic archive -> JSON.
"""
from __future__ import annotations

import argparse
import csv
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import sqlite3
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Google Takeout ────────────────────────────────────────────────────

def _walk_takeout(root: Path) -> list[dict]:
    """Walk a Takeout dir and pair each image with its `<image>.json` sidecar."""
    rows: list[dict] = []
    image_exts = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".mp4",
                  ".mov", ".webp", ".tif", ".tiff"}
    for cur, _dirs, files in os.walk(root):
        for fn in files:
            full = Path(cur) / fn
            ext = full.suffix.lower()
            if ext not in image_exts: continue
            sidecar = full.with_suffix(full.suffix + ".json")
            if not sidecar.exists():
                # Some Takeouts use `<stem>.json` (no double-suffix).
                sidecar = full.with_suffix(".json")
            meta: dict = {}
            if sidecar.is_file():
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            rows.append({
                "path": str(full),
                "size_bytes": full.stat().st_size,
                "title": meta.get("title", full.name),
                "description": meta.get("description", ""),
                "creation_time": (meta.get("creationTime", {}) or {}).get("formatted", ""),
                "photo_taken_time": (meta.get("photoTakenTime", {}) or {}).get("formatted", ""),
                "geo_lat": (meta.get("geoData", {}) or {}).get("latitude"),
                "geo_lon": (meta.get("geoData", {}) or {}).get("longitude"),
                "trashed": meta.get("trashed", False),
                "archived": meta.get("archived", False),
            })
    return rows


def op_takeout_list(args: argparse.Namespace) -> int:
    root = Path(args.takeout_dir)
    if not root.is_dir():
        return fail("missing_input", f"Takeout dir not found: {root}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _walk_takeout(root)
    out_path = out_dir / (root.name + "_manifest.csv")
    keys = ["path", "size_bytes", "title", "description",
            "creation_time", "photo_taken_time", "geo_lat", "geo_lon",
            "trashed", "archived"]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows: w.writerow(r)
    emit("photolib_doc",
         input=str(root), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="csv", source="takeout-photos", count=len(rows))
    emit("progress", percent=100.0, stage="1/1", eta_seconds=None)
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(rows))
    return 0


def op_takeout_meta_fix(args: argparse.Namespace) -> int:
    """Re-apply photoTakenTime onto each image's mtime (and atime)."""
    root = Path(args.takeout_dir)
    if not root.is_dir():
        return fail("missing_input", f"Takeout dir not found: {root}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _walk_takeout(root)
    fixed = 0
    skipped = 0
    for r in rows:
        ts_field = ((r.get("photo_taken_time") or "")
                    or (r.get("creation_time") or ""))
        # Parse formats Takeout uses: "Jan 1, 2020, 12:00:00 AM UTC"
        epoch = None
        try:
            from datetime import datetime
            epoch = datetime.strptime(ts_field,
                                       "%b %d, %Y, %I:%M:%S %p %Z").timestamp()
        except (ValueError, TypeError):
            pass
        if epoch is None:
            try:
                epoch = float((r.get("photo_taken_time_unix")
                                or r.get("photoTakenTime", {}).get("timestamp")
                                or 0))
            except (ValueError, TypeError):
                epoch = None
        if not epoch:
            skipped += 1; continue
        try:
            os.utime(r["path"], (epoch, epoch)); fixed += 1
        except Exception:
            skipped += 1
    summary = {"input_dir": str(root), "fixed": fixed, "skipped": skipped,
               "total": len(rows)}
    out_path = out_dir / (root.name + "_meta-fix.json")
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    emit("photolib_doc",
         input=str(root), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="json", source="takeout-photos",
         fixed=fixed, skipped=skipped)
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=fixed)
    return 0


# ── Apple .photoslibrary ──────────────────────────────────────────────

def op_photoslibrary(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle_dir)
    if not bundle.is_dir():
        return fail("missing_input",
                    f".photoslibrary bundle not found: {bundle}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = bundle / "database" / "Photos.sqlite"
    if not db_path.is_file():
        # newer macOS uses different layout
        db_path = bundle / "database" / "photos.db"
    if not db_path.is_file():
        return fail("parse_failed",
                    "Photos.sqlite not found in bundle.")
    try:
        conn = sqlite3.connect(str(db_path))
        conn.text_factory = str
        cur = conn.cursor()
        # Best-effort query — Apple's schema changes between macOS versions.
        candidate_queries = [
            "SELECT ZFILENAME, ZDATECREATED, ZWIDTH, ZHEIGHT, ZUUID "
            "FROM ZASSET LIMIT ?",
            "SELECT ZFILENAME, ZDATECREATED, ZWIDTH, ZHEIGHT, ZUUID "
            "FROM ZGENERICASSET LIMIT ?",
        ]
        rows: list[tuple] = []
        last_err = None
        for q in candidate_queries:
            try:
                rows = cur.execute(q, (args.limit,)).fetchall()
                break
            except sqlite3.OperationalError as e:
                last_err = e
        conn.close()
        if not rows and last_err:
            return fail("parse_failed",
                        f"Photos schema unsupported: {last_err}")
    except Exception as ex:
        return fail("parse_failed", f"{ex}")

    items = [{"filename": r[0], "date_created": r[1],
              "width": r[2], "height": r[3], "uuid": r[4]}
             for r in rows]
    out_path = out_dir / (bundle.stem + "_manifest.json")
    out_path.write_text(json.dumps(items, indent=2, default=str),
                        encoding="utf-8")
    emit("photolib_doc",
         input=str(bundle), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="json", source="photoslibrary", count=len(items))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(items))
    return 0


# ── Android MediaStore SQLite ─────────────────────────────────────────

def op_mediastore_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input",
                          f"MediaStore .db file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            conn = sqlite3.connect(str(src))
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            target_tbl = next((t for t in tables
                                if "image" in t.lower() or "media" in t.lower()),
                               None)
            if not target_tbl:
                return fail("parse_failed",
                            f"{src.name}: no images/media table found.")
            cols = [r[1] for r in cur.execute(
                f"PRAGMA table_info({target_tbl})").fetchall()]
            rows = cur.execute(f"SELECT * FROM {target_tbl}").fetchall()
            conn.close()
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "_" + target_tbl + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows: w.writerow(r)
        emit("photolib_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="mediastore",
             table=target_tbl, count=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── iOS .ips diagnostic archive ───────────────────────────────────────

def op_ips_to_json(args: argparse.Namespace) -> int:
    """iOS .ips files are JSON-formatted crash/diagnostic logs (newer iOS)
    or property-list stacks (older). Try JSON first, fall back to text."""
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".ips file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        text = src.read_text(encoding="utf-8", errors="replace")
        # Newer iOS .ips: header JSON line + body JSON.
        try:
            lines = text.split("\n", 1)
            header = json.loads(lines[0])
            body = json.loads(lines[1]) if len(lines) > 1 else {}
            doc = {"header": header, "body": body}
        except Exception:
            doc = {"raw": text}
        out_path = out_dir / (src.stem + ".ips.json")
        out_path.write_text(json.dumps(doc, indent=2, default=str),
                            encoding="utf-8")
        emit("photolib_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="ios-ips")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mobilephotos-sidecar",
                                description="Mobile photo library export decoders.")
    sub = p.add_subparsers(dest="op", required=True)

    tl = sub.add_parser("takeout-list", help="Google Takeout dir -> CSV manifest")
    tl.add_argument("--takeout-dir", required=True, dest="takeout_dir")
    tl.add_argument("--output-dir", required=True, dest="output_dir")

    tm = sub.add_parser("takeout-meta-fix",
                        help="Apply Takeout sidecar timestamps to images")
    tm.add_argument("--takeout-dir", required=True, dest="takeout_dir")
    tm.add_argument("--output-dir", required=True, dest="output_dir")

    pl = sub.add_parser("photoslibrary",
                        help="Apple .photoslibrary -> JSON manifest")
    pl.add_argument("--bundle-dir", required=True, dest="bundle_dir")
    pl.add_argument("--output-dir", required=True, dest="output_dir")
    pl.add_argument("--limit", type=int, default=100000)

    ms = sub.add_parser("mediastore-to-csv",
                        help="Android MediaStore SQLite -> CSV")
    ms.add_argument("--input", nargs="+", required=True)
    ms.add_argument("--output-dir", required=True, dest="output_dir")

    ips = sub.add_parser("ips-to-json",
                          help="iOS .ips diagnostic archive -> JSON")
    ips.add_argument("--input", nargs="+", required=True)
    ips.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "takeout-list":      return op_takeout_list(args)
        if args.op == "takeout-meta-fix":  return op_takeout_meta_fix(args)
        if args.op == "photoslibrary":     return op_photoslibrary(args)
        if args.op == "mediastore-to-csv": return op_mediastore_to_csv(args)
        if args.op == "ips-to-json":       return op_ips_to_json(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""GIS map-tile / cloud-native raster sidecar.

The `gisconvert` sidecar handles vector formats (KML/GPX/GeoJSON/Shapefile/
GeoPackage); this one is for raster + tile-pyramid formats:

  * MBTiles                Mapbox tile pyramid (SQLite container)
  * PMTiles                Protomaps single-file (range-request friendly)
  * COG                    Cloud Optimized GeoTIFF
  * KMZ                    Zipped KML
  * GeoTIFF (.tif/.tiff geo)

Operations:
  cog              Convert any GeoTIFF -> COG.
  kmz-to-kml       Unpack KMZ -> KML + assets.
  kml-to-kmz       Pack KML -> KMZ.
  mbtiles-info     Probe MBTiles metadata (zoom levels, bounds, format).
  pmtiles-info     Probe PMTiles header.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── COG (Cloud Optimized GeoTIFF) ────────────────────────────────────────

def op_cog(args: argparse.Namespace) -> int:
    """GeoTIFF -> COG via gdal_translate."""
    gdal = shutil.which("gdal_translate") or shutil.which("gdal_translate.exe")
    if not gdal:
        return fail("missing_gdal",
                    "GDAL (gdal_translate) not found. Install GDAL "
                    "(`conda install -c conda-forge gdal` or system package).")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"GeoTIFF(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "_cog.tif")
        cmd = [
            gdal, "-of", "COG",
            "-co", f"COMPRESS={args.compress}",
            "-co", "BLOCKSIZE=512",
            "-co", "OVERVIEWS=AUTO",
            str(src), str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("cog_failed", f"{src.name}: rc={proc.returncode}")
        emit("gistile",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="cog", compress=args.compress)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── KMZ / KML ─────────────────────────────────────────────────────────────

def op_kmz_to_kml(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"KMZ(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        sub = out_dir / src.stem
        sub.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(str(src)) as zf:
                zf.extractall(str(sub))
        except Exception as ex:
            return fail("extract_failed", f"{src.name}: {ex}")
        kml_files = list(sub.glob("*.kml")) + list(sub.glob("**/*.kml"))
        emit("gistile",
             input=str(src), output=str(sub),
             size_bytes=sum(p.stat().st_size for p in sub.rglob("*") if p.is_file()),
             format="kmz-extracted", kml_count=len(kml_files))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_kml_to_kmz(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"KML(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".kmz")
        try:
            with zipfile.ZipFile(str(out_path), "w",
                                  compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(str(src), arcname=src.name)
        except Exception as ex:
            return fail("pack_failed", f"{src.name}: {ex}")
        emit("gistile",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size, format="kmz")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── MBTiles / PMTiles probes ─────────────────────────────────────────────

def op_mbtiles_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"MBTiles not found: {src}")
    try:
        con = sqlite3.connect(str(src))
        cur = con.cursor()
        cur.execute("SELECT name, value FROM metadata")
        meta = {row[0]: row[1] for row in cur.fetchall()}
        cur.execute("SELECT MIN(zoom_level), MAX(zoom_level), COUNT(*) FROM tiles")
        zmin, zmax, count = cur.fetchone() or (None, None, 0)
        con.close()
    except Exception as ex:
        return fail("read_failed", f"{src.name}: {ex}")

    emit("gistile_info",
         path=str(src), format="mbtiles",
         size_bytes=src.stat().st_size,
         metadata=meta, min_zoom=zmin, max_zoom=zmax, tile_count=count)
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def op_pmtiles_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"PMTiles not found: {src}")
    raw = src.read_bytes()
    if raw[:7] != b"PMTiles":
        return fail("bad_magic", f"{src.name}: not a PMTiles file (bad magic).")
    # PMTiles v3 header is 127 bytes after the 7-byte magic.
    version = raw[7]
    emit("gistile_info",
         path=str(src), format="pmtiles",
         size_bytes=src.stat().st_size,
         version=int(version))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gistiles-sidecar",
                                description="GIS raster + tile-pyramid conversion (COG / KMZ / MBTiles / PMTiles).")
    sub = p.add_subparsers(dest="op", required=True)

    c = sub.add_parser("cog", help="GeoTIFF -> Cloud Optimized GeoTIFF.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--compress", default="DEFLATE",
                   choices=["DEFLATE", "LZW", "JPEG", "ZSTD", "WEBP", "NONE"])

    a = sub.add_parser("kmz-to-kml", help="Unpack KMZ -> KML + assets.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    b = sub.add_parser("kml-to-kmz", help="Zip KML -> KMZ.")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")

    m = sub.add_parser("mbtiles-info", help="Probe MBTiles metadata.")
    m.add_argument("--input", required=True)

    pm = sub.add_parser("pmtiles-info", help="Probe PMTiles header.")
    pm.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "cog":          return op_cog(args)
        if args.op == "kmz-to-kml":   return op_kmz_to_kml(args)
        if args.op == "kml-to-kmz":   return op_kml_to_kmz(args)
        if args.op == "mbtiles-info": return op_mbtiles_info(args)
        if args.op == "pmtiles-info": return op_pmtiles_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

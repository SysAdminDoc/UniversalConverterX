"""GIS data converter sidecar -- wraps GDAL's `ogr2ogr` for vector data and
`gdal_translate` for raster data so UCX can convert between every common
geographic format.

Vector formats (ogr2ogr):  GeoJSON, KML, KMZ, GPX, ESRI Shapefile, GeoPackage,
                           CSV (with WKT), FlatGeobuf, GML, MapInfo TAB, GPKG,
                           SQLite (Spatialite), TopoJSON.

Raster formats (gdal_translate): GeoTIFF, JPEG2000, PNG, JPEG, COG (Cloud
                                 Optimised GeoTIFF), HDF5, NetCDF, BMP, ASC,
                                 ENVI, MBTiles.

Frozen-guard: pure-Python wrapper; user installs GDAL separately (the GDAL
binaries are typically 200+ MB, way too big to bundle, and OSGeo4W /
QGIS install ships them in a standard location).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_gdal_tool(name: str) -> str | None:
    """Locate ogr2ogr.exe or gdal_translate.exe from PATH / OSGeo4W / QGIS."""
    env = os.environ.get("GDAL_BIN_DIR")
    if env:
        candidate = Path(env, f"{name}.exe")
        if candidate.is_file(): return str(candidate)

    hit = shutil.which(name) or shutil.which(f"{name}.exe")
    if hit: return hit

    # OSGeo4W default install + QGIS bundles GDAL.
    for root in (
        r"C:\OSGeo4W\bin",
        r"C:\OSGeo4W64\bin",
        r"C:\Program Files\QGIS 3.34\bin",
        r"C:\Program Files\QGIS 3.36\bin",
        r"C:\Program Files\QGIS 3.40\bin",
    ):
        candidate = Path(root, f"{name}.exe")
        if candidate.is_file(): return str(candidate)

    if os.name != "nt":
        for c in (f"/usr/bin/{name}", f"/usr/local/bin/{name}",
                  f"/opt/homebrew/bin/{name}"):
            if Path(c).is_file(): return c

    return None


# Map UCX format names to OGR / GDAL driver names.
VECTOR_DRIVERS = {
    "geojson":   "GeoJSON",
    "kml":       "KML",
    "kmz":       "LIBKML",
    "gpx":       "GPX",
    "shp":       "ESRI Shapefile",
    "shapefile": "ESRI Shapefile",
    "gpkg":      "GPKG",
    "geopackage":"GPKG",
    "csv":       "CSV",
    "fgb":       "FlatGeobuf",
    "gml":       "GML",
    "tab":       "MapInfo File",
    "sqlite":    "SQLite",
    "topojson":  "TopoJSON",
}

RASTER_DRIVERS = {
    "tif":       "GTiff",
    "tiff":      "GTiff",
    "geotiff":   "GTiff",
    "cog":       "COG",       # GDAL >=3.1
    "jp2":       "JP2OpenJPEG",
    "png":       "PNG",
    "jpg":       "JPEG",
    "jpeg":      "JPEG",
    "bmp":       "BMP",
    "asc":       "AAIGrid",
    "envi":      "ENVI",
    "hdf5":      "HDF5",
    "nc":        "netCDF",
    "netcdf":    "netCDF",
    "mbtiles":   "MBTiles",
}


def op_vector(args: argparse.Namespace) -> int:
    exe = find_gdal_tool("ogr2ogr")
    if not exe:
        return fail("missing_gdal",
                    "ogr2ogr not found. Install GDAL (e.g. OSGeo4W, QGIS) or "
                    "set $env:GDAL_BIN_DIR to the directory containing ogr2ogr.exe.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        return fail("missing_input", f"Source(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    driver = VECTOR_DRIVERS.get(target)
    if driver is None:
        return fail("bad_format",
                    f"Unknown vector format '{target}'. Use one of: "
                    + ", ".join(sorted(set(VECTOR_DRIVERS.keys()))))

    out_ext = ".geojson" if target == "geojson" else "." + target
    if target in ("shapefile",): out_ext = ".shp"
    if target in ("geopackage",): out_ext = ".gpkg"

    total = len(inputs)
    emit("log", level="info",
         message=f"Vector convert {total} -> .{target} (driver={driver})")
    emit("progress", percent=0, stage="vector", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + out_ext)
        cmd = [exe, "-f", driver, str(out_path), str(src)]
        if args.target_srs:
            cmd += ["-t_srs", args.target_srs]
        if args.source_srs:
            cmd += ["-s_srs", args.source_srs]
        if args.simplify is not None and args.simplify > 0:
            cmd += ["-simplify", str(args.simplify)]
        if args.overwrite:
            cmd.append("-overwrite")

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            for ln in tail:
                emit("log", level="error", message=ln)
            return fail("ogr2ogr_failed",
                        f"ogr2ogr exited {proc.returncode} on {src.name}")
        if not out_path.exists():
            return fail("output_missing",
                        f"ogr2ogr did not produce output for {src.name}")

        emit("gis_layer",
             input=str(src),
             output=str(out_path),
             driver=driver,
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0)

        pct = (i + 1) / total * 100.0
        elapsed = time.monotonic() - started
        local = pct / 100.0
        eta = (elapsed / local - elapsed) if local > 0.01 else None
        emit("progress",
             percent=round(pct, 1),
             stage=f"converted {i + 1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_raster(args: argparse.Namespace) -> int:
    exe = find_gdal_tool("gdal_translate")
    if not exe:
        return fail("missing_gdal", "gdal_translate not found. Install GDAL.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Raster(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    driver = RASTER_DRIVERS.get(target)
    if driver is None:
        return fail("bad_format",
                    f"Unknown raster format '{target}'. Use one of: "
                    + ", ".join(sorted(set(RASTER_DRIVERS.keys()))))

    out_ext = "." + target
    total = len(inputs)
    emit("log", level="info",
         message=f"Raster convert {total} -> .{target} (driver={driver})")
    emit("progress", percent=0, stage="raster", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + out_ext)
        cmd = [exe, "-of", driver, str(src), str(out_path)]
        if args.outsize:
            cmd += ["-outsize", *args.outsize.split("x")]
        if args.compress:
            cmd += ["-co", f"COMPRESS={args.compress}"]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            for ln in tail:
                emit("log", level="error", message=ln)
            return fail("gdal_translate_failed",
                        f"gdal_translate exited {proc.returncode} on {src.name}")

        emit("gis_raster",
             input=str(src),
             output=str(out_path),
             driver=driver,
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0)

        pct = (i + 1) / total * 100.0
        emit("progress",
             percent=round(pct, 1),
             stage=f"converted {i + 1}/{total}",
             eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gisconvert-sidecar",
                                description="GIS vector + raster conversion via GDAL.")
    sub = p.add_subparsers(dest="op", required=True)

    v = sub.add_parser("vector", help="Convert vector layers via ogr2ogr.")
    v.add_argument("--input", nargs="+", required=True)
    v.add_argument("--output-dir", required=True, dest="output_dir")
    v.add_argument("--format", required=True,
                   help=" | ".join(sorted(set(VECTOR_DRIVERS.keys()))))
    v.add_argument("--target-srs", dest="target_srs",
                   help="EPSG code or PROJ string (e.g. 'EPSG:4326').")
    v.add_argument("--source-srs", dest="source_srs",
                   help="Override source SRS if the file's projection is wrong.")
    v.add_argument("--simplify", type=float,
                   help="Tolerance for line/polygon simplification (in source units).")
    v.add_argument("--overwrite", action="store_true",
                   help="Replace destination if it exists.")

    r = sub.add_parser("raster", help="Convert raster files via gdal_translate.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--format", required=True,
                   help=" | ".join(sorted(set(RASTER_DRIVERS.keys()))))
    r.add_argument("--outsize",
                   help="Resize to W x H pixels (e.g. '1024x768'). Pass '0' for either to scale proportionally.")
    r.add_argument("--compress",
                   help="Compression flag for the chosen driver (e.g. 'LZW', 'DEFLATE', 'JPEG').")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "vector": return op_vector(args)
        if args.op == "raster": return op_raster(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

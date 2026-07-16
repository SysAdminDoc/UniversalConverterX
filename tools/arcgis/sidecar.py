"""ArcGIS file-geodatabase sidecar (extends `gisconvert`).

ArcGIS .gdb is a directory-based file geodatabase that holds vector +
raster + tabular layers. We surface the OGR + GDAL CLI integration so
users can pull every layer out into open formats:

  * .gdb / .gpkg layer enumeration
  * Per-layer extraction -> GeoJSON / Shapefile / GeoPackage / FlatGeobuf
  * ArcGIS Pro `.aprx` project XML probe

Operations:
  list-layers      Enumerate layers in a .gdb / .gpkg via ogrinfo.
  extract-layer    Pull one named layer to GeoJSON / SHP / GPKG / FGB.
  extract-all      Pull every layer to a chosen format.
  aprx-info        ArcGIS Pro .aprx project XML probe.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".exe")


def _list_layers(gdb_path: Path) -> list[dict]:
    cli = _which("ogrinfo")
    if not cli: raise RuntimeError("ogrinfo (GDAL) not on PATH.")
    proc = subprocess.run([cli, "-q", str(gdb_path)],
                           capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ogrinfo exit {proc.returncode}: {proc.stderr}")
    layers: list[dict] = []
    for line in proc.stdout.splitlines():
        m = re.match(r"^\s*\d+:\s+(\S+)(?:\s+\(([^)]*)\))?", line)
        if m:
            layers.append({"name": m.group(1),
                            "geometry_type": m.group(2) or ""})
    return layers


def op_list_layers(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not (p.is_dir() or p.is_file())]
    if miss: return fail("missing_input", f"GDB / GPKG not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            layers = _list_layers(src)
        except Exception as ex:
            return fail("probe_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".layers.json")
        out_path.write_text(json.dumps(layers, indent=2),
                            encoding="utf-8")
        emit("arcgis_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source=src.suffix.lstrip(".").lower() or "gdb",
             layer_count=len(layers))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


_FORMAT_DRIVER = {
    "geojson": ("GeoJSON", "geojson"),
    "shp":     ("ESRI Shapefile", "shp"),
    "gpkg":    ("GPKG", "gpkg"),
    "fgb":     ("FlatGeobuf", "fgb"),
    "gml":     ("GML", "gml"),
    "kml":     ("KML", "kml"),
}


def _extract_one(gdb: Path, layer: str, fmt: str, out_dir: Path) -> Path:
    cli = _which("ogr2ogr")
    if not cli: raise RuntimeError("ogr2ogr (GDAL) not on PATH.")
    if fmt not in _FORMAT_DRIVER:
        raise ValueError(f"Unsupported target: {fmt}. "
                         f"Choose: {', '.join(_FORMAT_DRIVER)}")
    driver, ext = _FORMAT_DRIVER[fmt]
    safe_layer = re.sub(r"[^A-Za-z0-9_.-]", "_", layer)
    out_path = out_dir / f"{gdb.stem}__{safe_layer}.{ext}"
    cmd = [cli, "-f", driver, "-lco", "OVERWRITE=YES",
           str(out_path), str(gdb), layer]
    if fmt == "shp":
        # Shapefiles need a directory not file in some versions; ogr2ogr
        # creates the .shp + sidecars next to the path.
        pass
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"ogr2ogr exit {proc.returncode}: {proc.stderr}")
    return out_path


def op_extract_layer(args: argparse.Namespace) -> int:
    src = Path(args.gdb)
    if not (src.is_dir() or src.is_file()):
        return fail("missing_input", f"GDB not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        out_path = _extract_one(src, args.layer, args.format.lower(), out_dir)
    except Exception as ex:
        return fail("convert_failed", f"{src.name}: {ex}")
    emit("arcgis_doc",
         input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format=args.format.lower(), source="gdb",
         layer=args.layer)
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_extract_all(args: argparse.Namespace) -> int:
    src = Path(args.gdb)
    if not (src.is_dir() or src.is_file()):
        return fail("missing_input", f"GDB not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        layers = _list_layers(src)
    except Exception as ex:
        return fail("probe_failed", f"{src.name}: {ex}")
    if not layers:
        return fail("empty", f"{src.name}: no layers reported.")
    fmt = args.format.lower()
    extracted = 0
    total = len(layers)
    for i, lyr in enumerate(layers):
        try:
            out_path = _extract_one(src, lyr["name"], fmt, out_dir)
        except Exception as ex:
            return fail("convert_failed",
                        f"{src.name} layer {lyr['name']}: {ex}")
        extracted += 1
        emit("arcgis_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=fmt, source="gdb", layer=lyr["name"])
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=extracted)
    return 0


def op_aprx_info(args: argparse.Namespace) -> int:
    """ArcGIS Pro .aprx project files are ZIP-packaged with a JSON +
    XML manifest inside. We surface the JSON manifest if present."""
    import zipfile
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".aprx file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            with zipfile.ZipFile(src) as z:
                names = z.namelist()
                manifest = None
                for n in names:
                    if n.lower().endswith("manifest.json"):
                        try:
                            manifest = json.loads(z.read(n).decode(
                                "utf-8", errors="replace"))
                        except Exception:
                            manifest = None
                        break
                probes.append({
                    "file": str(src), "size_bytes": src.stat().st_size,
                    "entries": len(names),
                    "first_entries": names[:10],
                    "manifest_present": bool(manifest),
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("arcgis_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="aprx")
    out_path = out_dir / "aprx-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arcgis-sidecar",
                                description="ArcGIS .gdb file-geodatabase + .aprx project conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    ll = sub.add_parser("list-layers", help="Enumerate layers in .gdb / .gpkg")
    ll.add_argument("--input", nargs="+", required=True)
    ll.add_argument("--output-dir", required=True, dest="output_dir")

    el = sub.add_parser("extract-layer", help="Extract one layer -> GeoJSON / SHP / GPKG / FGB")
    el.add_argument("--gdb", required=True)
    el.add_argument("--layer", required=True)
    el.add_argument("--format", default="geojson",
                    help="Target: geojson / shp / gpkg / fgb / gml / kml")
    el.add_argument("--output-dir", required=True, dest="output_dir")

    ea = sub.add_parser("extract-all", help="Extract every layer in a .gdb")
    ea.add_argument("--gdb", required=True)
    ea.add_argument("--format", default="geojson",
                    help="Target: geojson / shp / gpkg / fgb / gml / kml")
    ea.add_argument("--output-dir", required=True, dest="output_dir")

    ap = sub.add_parser("aprx-info", help="ArcGIS Pro .aprx project probe")
    ap.add_argument("--input", nargs="+", required=True)
    ap.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "list-layers":   return op_list_layers(args)
        if args.op == "extract-layer": return op_extract_layer(args)
        if args.op == "extract-all":   return op_extract_all(args)
        if args.op == "aprx-info":     return op_aprx_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

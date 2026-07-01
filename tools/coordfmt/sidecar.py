"""Geographic coordinate format conversion sidecar.

Translate any of the standard latitude/longitude representations into
every other common form:

  Decimal Degrees (DD)             40.7128, -74.0060
  Degrees Minutes Seconds (DMS)    40@deg 42' 46.08\" N, 74@deg 0' 21.6\" W
  Degrees Decimal Minutes (DDM)    40@deg 42.768' N, 74@deg 0.36' W
  UTM                              18T 583960 4507523
  MGRS                             18TWL8396007523
  Geohash                          dr5regw
  Plus Codes (Open Location Code)  87G7PX9C+5R
  What3Words (lookup-only)         (out of scope, requires API)

Operations:
  convert    Single point (or list) -> JSON with every representation.
  csv        Bulk transform a CSV column.
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
import re
import sys
import time
from pathlib import Path


def emit(event: str, **fields_) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields_}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_DEC_PAIR = re.compile(r"^\s*(-?\d+(?:\.\d+)?)[,\s]+(-?\d+(?:\.\d+)?)\s*$")


def _parse_dd(text: str) -> tuple[float, float] | None:
    m = _DEC_PAIR.match(text)
    if not m: return None
    return float(m.group(1)), float(m.group(2))


_DMS_RE = re.compile(
    r"\s*(\d+)\s*(?:[@deg\u00B0d]|deg)?\s*"
    r"(?:(\d+)\s*[\u2032'm]\s*"
    r"(?:(\d+(?:\.\d+)?)\s*[\u2033\"s]?)?)?"
    r"\s*([NSEWnsew])?", re.IGNORECASE,
)


def _parse_dms_one(text: str) -> float | None:
    m = _DMS_RE.match(text)
    if not m: return None
    deg = float(m.group(1) or 0)
    mins = float(m.group(2) or 0)
    secs = float(m.group(3) or 0)
    hemi = (m.group(4) or "").upper()
    val = deg + mins / 60 + secs / 3600
    if hemi in ("S", "W"): val = -val
    return val


def _parse_dms_pair(text: str) -> tuple[float, float] | None:
    parts = re.split(r"[,]\s*", text)
    if len(parts) != 2: return None
    a = _parse_dms_one(parts[0])
    b = _parse_dms_one(parts[1])
    if a is None or b is None: return None
    return a, b


def _to_dms(deg: float, is_lat: bool) -> str:
    hemi = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
    deg = abs(deg)
    d = int(deg)
    rem = (deg - d) * 60
    mn = int(rem)
    sc = (rem - mn) * 60
    return f"{d}\u00B0 {mn}' {sc:.2f}\" {hemi}"


def _to_ddm(deg: float, is_lat: bool) -> str:
    hemi = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
    deg = abs(deg)
    d = int(deg)
    mn = (deg - d) * 60
    return f"{d}\u00B0 {mn:.4f}' {hemi}"


def _all_repr(lat: float, lon: float) -> dict:
    out: dict = {
        "lat": lat, "lon": lon,
        "dms": f"{_to_dms(lat, True)}, {_to_dms(lon, False)}",
        "ddm": f"{_to_ddm(lat, True)}, {_to_ddm(lon, False)}",
    }
    # UTM + MGRS
    try:
        import utm
        e, n, zn, zl = utm.from_latlon(lat, lon)
        out["utm"] = f"{zn}{zl} {int(round(e))} {int(round(n))}"
    except ImportError:
        out["utm"] = None
    try:
        import mgrs
        out["mgrs"] = mgrs.MGRS().toMGRS(lat, lon, MGRSPrecision=5)
    except ImportError:
        out["mgrs"] = None
    # Geohash
    try:
        import geohash2 as gh
        out["geohash"] = gh.encode(lat, lon)
    except ImportError:
        try:
            import pygeohash as gh
            out["geohash"] = gh.encode(lat, lon, precision=8)
        except ImportError:
            out["geohash"] = None
    # Plus Codes
    try:
        from openlocationcode import openlocationcode as olc
        out["plus_code"] = olc.encode(lat, lon)
    except ImportError:
        out["plus_code"] = None
    return out


def op_convert(args: argparse.Namespace) -> int:
    values: list[str] = []
    if args.input:
        values.extend(args.input)
    if args.input_file:
        text = Path(args.input_file).read_text(encoding="utf-8")
        values.extend(line.strip() for line in text.splitlines() if line.strip())
    if not values:
        return fail("no_input", "Pass --input <coord> ... or --input-file <path>.")

    rows: list[dict] = []
    for value in values:
        pair = _parse_dd(value) or _parse_dms_pair(value)
        if pair is None:
            row = {"source": value, "error": "could not parse"}
        else:
            row = {"source": value, **_all_repr(*pair)}
        rows.append(row)
        emit("coord", **row)

    if args.output_dir:
        out_dir = Path(args.output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "coordinates.json"
        out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        emit("complete", output=str(out_path),
             size_bytes=out_path.stat().st_size, count=len(rows))
    else:
        emit("complete", output="(stdout)", size_bytes=0, count=len(rows))
    return 0


def op_csv(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"CSV not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (src.stem + "_coord.csv")

    with src.open("r", encoding="utf-8-sig", newline="") as inh, \
         out_path.open("w", encoding="utf-8", newline="") as outh:
        reader = csv.DictReader(inh)
        if not reader.fieldnames:
            return fail("empty", f"{src.name}: no header row.")
        new_cols = ["dms", "ddm", "utm", "mgrs", "geohash", "plus_code"]
        writer = csv.DictWriter(outh,
            fieldnames=list(reader.fieldnames) + new_cols)
        writer.writeheader()
        n = 0
        for row in reader:
            try:
                lat = float(row[args.lat_col]); lon = float(row[args.lon_col])
                row.update({k: v for k, v in _all_repr(lat, lon).items()
                            if k in new_cols})
            except Exception:
                pass
            writer.writerow(row)
            n += 1

    emit("coord_csv",
         input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size, rows=n)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coordfmt-sidecar",
                                description="Geographic coordinate conversion (DD / DMS / DDM / UTM / MGRS / Geohash / Plus Codes).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert one or more lat/lon points.")
    c.add_argument("--input", nargs="*", default=None,
                   help='Coordinate strings, e.g. "40.7128, -74.0060"')
    c.add_argument("--input-file", default=None, dest="input_file")
    c.add_argument("--output-dir", default=None, dest="output_dir")

    cv = sub.add_parser("csv", help="Append all coord representations as columns to a CSV.")
    cv.add_argument("--input", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--lat-col", default="lat", dest="lat_col")
    cv.add_argument("--lon-col", default="lon", dest="lon_col")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "csv":     return op_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

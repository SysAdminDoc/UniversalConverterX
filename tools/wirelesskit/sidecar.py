"""NMEA GPS / AIS / SBAS messaging sidecar.

Convert raw NMEA 0183 sentences and AIS (Automatic Identification System)
messages from boats / aircraft / GPS receivers into navigable formats:

  * NMEA .nmea / .gps / .log -> JSON / CSV / KML / GPX track
  * AIS NMEA "!AIVDM" / "!AIVDO" sentences -> JSON
  * SBAS RTCM-style binary headers -> JSON (probe only)

Pure stdlib for NMEA decoding (covers GGA / RMC / GLL / VTG / GSA / GSV).
AIS payload decoding requires `pyais` (it's in requirements.txt) since
the 6-bit ASCII payload bit-fiddling is non-trivial.
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
from datetime import datetime, timezone
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── NMEA 0183 parser ───────────────────────────────────────────────────

def _checksum_ok(line: str) -> bool:
    if "*" not in line: return True   # missing checksum allowed
    body, cksum = line.lstrip("$!").rsplit("*", 1)
    expected = int(cksum.strip(), 16)
    actual = 0
    for ch in body:
        actual ^= ord(ch)
    return actual == expected


def _nmea_to_dec(coord: str, hemi: str) -> float | None:
    if not coord: return None
    # NMEA: ddmm.mmmm (lat) or dddmm.mmmm (lon)
    dot = coord.find(".")
    deg_len = dot - 2 if dot >= 0 else len(coord) - 2
    deg = float(coord[:deg_len])
    minutes = float(coord[deg_len:])
    decimal = deg + minutes / 60.0
    if hemi in ("S", "W"): decimal = -decimal
    return decimal


def _parse_nmea(text: str) -> list[dict]:
    rows: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not line.startswith(("$", "!")): continue
        if not _checksum_ok(line): continue
        body = line.split("*", 1)[0]
        parts = body.split(",")
        talker = parts[0]
        sentence = talker[3:] if len(talker) >= 5 else ""
        rec: dict = {"raw": line, "talker": talker, "sentence": sentence}
        try:
            if sentence == "GGA" and len(parts) >= 14:
                rec["fix_time"] = parts[1]
                rec["lat"] = _nmea_to_dec(parts[2], parts[3])
                rec["lon"] = _nmea_to_dec(parts[4], parts[5])
                rec["fix_quality"] = int(parts[6]) if parts[6] else None
                rec["satellites"] = int(parts[7]) if parts[7] else None
                rec["hdop"] = float(parts[8]) if parts[8] else None
                rec["altitude"] = float(parts[9]) if parts[9] else None
            elif sentence == "RMC" and len(parts) >= 12:
                rec["fix_time"] = parts[1]
                rec["status"] = parts[2]
                rec["lat"] = _nmea_to_dec(parts[3], parts[4])
                rec["lon"] = _nmea_to_dec(parts[5], parts[6])
                rec["speed_knots"] = float(parts[7]) if parts[7] else None
                rec["track_deg"] = float(parts[8]) if parts[8] else None
                rec["fix_date"] = parts[9]
            elif sentence == "GLL" and len(parts) >= 7:
                rec["lat"] = _nmea_to_dec(parts[1], parts[2])
                rec["lon"] = _nmea_to_dec(parts[3], parts[4])
                rec["fix_time"] = parts[5]
                rec["status"] = parts[6]
            elif sentence == "VTG" and len(parts) >= 9:
                rec["track_deg"] = float(parts[1]) if parts[1] else None
                rec["speed_knots"] = float(parts[5]) if parts[5] else None
                rec["speed_kmh"] = float(parts[7]) if parts[7] else None
            elif sentence in ("GSV", "GSA"):
                rec["raw_fields"] = parts[1:]
        except (ValueError, IndexError):
            pass
        rows.append(rec)
    return rows


def _to_kml(rows: list[dict], name: str) -> str:
    coords = [(r["lon"], r["lat"]) for r in rows
              if r.get("lat") is not None and r.get("lon") is not None]
    track = " ".join(f"{lon:.6f},{lat:.6f},0" for lon, lat in coords)
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<kml xmlns=\"http://www.opengis.net/kml/2.2\">\n"
            "  <Document>\n"
            f"    <name>{name}</name>\n"
            "    <Placemark>\n"
            f"      <name>{name} track</name>\n"
            "      <LineString>\n"
            f"        <coordinates>{track}</coordinates>\n"
            "      </LineString>\n"
            "    </Placemark>\n"
            "  </Document>\n"
            "</kml>\n")


def _to_gpx(rows: list[dict], name: str) -> str:
    pts: list[str] = []
    for r in rows:
        if r.get("lat") is None or r.get("lon") is None: continue
        ele = r.get("altitude")
        ele_xml = f"<ele>{ele}</ele>" if ele is not None else ""
        pts.append(f"      <trkpt lat=\"{r['lat']:.6f}\" lon=\"{r['lon']:.6f}\">"
                   f"{ele_xml}</trkpt>")
    body = "\n".join(pts)
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<gpx version=\"1.1\" creator=\"UniversalConverterX\" "
            "xmlns=\"http://www.topografix.com/GPX/1/1\">\n"
            f"  <trk><name>{name}</name>\n"
            "    <trkseg>\n"
            f"{body}\n"
            "    </trkseg>\n"
            "  </trk>\n"
            "</gpx>\n")


# ── Operations ─────────────────────────────────────────────────────────

def _convert(args: argparse.Namespace, fmt: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"NMEA file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            rows = _parse_nmea(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        if fmt == "json":
            out_path = out_dir / (src.stem + ".json")
            out_path.write_text(json.dumps(rows, indent=2),
                                encoding="utf-8")
        elif fmt == "csv":
            out_path = out_dir / (src.stem + ".csv")
            keys = ["talker", "sentence", "fix_time", "fix_date", "status",
                    "lat", "lon", "altitude", "speed_knots", "track_deg",
                    "satellites", "hdop", "fix_quality"]
            with out_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                for r in rows: w.writerow(r)
        elif fmt == "kml":
            out_path = out_dir / (src.stem + ".kml")
            out_path.write_text(_to_kml(rows, src.stem), encoding="utf-8")
        elif fmt == "gpx":
            out_path = out_dir / (src.stem + ".gpx")
            out_path.write_text(_to_gpx(rows, src.stem), encoding="utf-8")
        else:
            return fail("bad_format", f"Unknown format: {fmt}")
        emit("nmea_msg",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=fmt, source="nmea", sentences=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_json(args): return _convert(args, "json")
def op_to_csv(args):  return _convert(args, "csv")
def op_to_kml(args):  return _convert(args, "kml")
def op_to_gpx(args):  return _convert(args, "gpx")


def op_ais_to_json(args: argparse.Namespace) -> int:
    try:
        from pyais.stream import FileReaderStream
    except ImportError:
        return fail("missing_dep",
                    "pyais not installed (`pip install pyais`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"AIS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            messages: list[dict] = []
            for msg in FileReaderStream(str(src)):
                try:
                    decoded = msg.decode().asdict()
                    messages.append(decoded)
                except Exception:
                    pass
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(messages, indent=2, default=str),
                            encoding="utf-8")
        emit("nmea_msg",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="ais", sentences=len(messages))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wirelesskit-sidecar",
                                description="NMEA GPS / AIS / wireless message conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    for op, helpstr in [
        ("nmea-to-json", "NMEA -> JSON"),
        ("nmea-to-csv",  "NMEA -> CSV"),
        ("nmea-to-kml",  "NMEA -> KML track"),
        ("nmea-to-gpx",  "NMEA -> GPX track"),
        ("ais-to-json",  "AIS NMEA !AIVDM/!AIVDO -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "nmea-to-json": return op_to_json(args)
        if args.op == "nmea-to-csv":  return op_to_csv(args)
        if args.op == "nmea-to-kml":  return op_to_kml(args)
        if args.op == "nmea-to-gpx":  return op_to_gpx(args)
        if args.op == "ais-to-json":  return op_ais_to_json(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

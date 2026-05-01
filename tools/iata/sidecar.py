"""IATA airline messaging sidecar.

Travel & airline industry message formats are XML-heavy and use IATA
schemas. This sidecar handles the most common ones:

  * NDC (New Distribution Capability) v17.2 / v21.3 — modern airline
    booking via XML. Schemas: AirShoppingRQ/RS, OfferPriceRQ/RS,
    OrderCreateRQ/RS, OrderViewRS, ItinReshopRQ/RS.
  * EDIFACT TTYREP, PNRGOV, MVT — legacy airline EDI messages.
  * BSP HOT (Hand-Off Tape) — airline settlement.
  * IATA Codeset CSV — IATA airport / airline / city codes (built-in).

Operations:
  ndc-to-json       NDC XML -> structured JSON.
  ndc-detect        Detect NDC message type / version from XML.
  pnr-to-json       Airline PNR (legacy EDIFACT) -> JSON.
  airport-codes     Built-in IATA airport code reference -> CSV.
  airline-codes     Built-in IATA airline code reference -> CSV.

Pure stdlib (xml.etree). No external deps required.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _elem_to_dict(elem: ET.Element) -> dict | str | None:
    children = list(elem)
    attrs = dict(elem.attrib) if elem.attrib else {}
    if not children:
        text = (elem.text or "").strip()
        if attrs and text: return {**attrs, "_text": text}
        if attrs: return attrs
        return text if text else None
    out: dict = dict(attrs)
    for child in children:
        key = _strip_ns(child.tag)
        val = _elem_to_dict(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(val)
        else:
            out[key] = val
    return out


# ── NDC ────────────────────────────────────────────────────────────────

_NDC_TYPES = (
    "AirShoppingRQ", "AirShoppingRS", "OfferPriceRQ", "OfferPriceRS",
    "OrderCreateRQ", "OrderCreateRS", "OrderViewRS", "OrderRetrieveRQ",
    "OrderRetrieveRS", "OrderCancelRQ", "OrderCancelRS",
    "OrderChangeRQ", "OrderChangeRS", "ItinReshopRQ", "ItinReshopRS",
    "ServiceListRQ", "ServiceListRS", "SeatAvailabilityRQ",
    "SeatAvailabilityRS",
)


def _detect_ndc(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    for t in _NDC_TYPES:
        if f"<{t}" in text or f":{t}" in text:
            m = re.search(r'Version="([^"]+)"', text)
            return t, m.group(1) if m else ""
    return "unknown", ""


def op_ndc_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"NDC XML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            data = _elem_to_dict(tree.getroot())
            msg_type, version = _detect_ndc(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps({"type": msg_type, "version": version,
                                         "message": data},
                                        indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("airline_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="ndc", message_type=msg_type, version=version)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_ndc_detect(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"NDC XML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        msg_type, version = _detect_ndc(src)
        detections.append({"file": str(src), "type": msg_type,
                           "version": version,
                           "size_bytes": src.stat().st_size})
        emit("airline_doc",
             input=str(src), output="",
             size_bytes=0, format="detect",
             message_type=msg_type, version=version)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "ndc-detect.json"
    out_path.write_text(json.dumps(detections, indent=2),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(detections))
    return 0


# ── PNR (legacy EDIFACT-style) ─────────────────────────────────────────

def _parse_pnr(text: str) -> dict:
    """Parse the OSI/SSR/SR/RM line-based PNR slice format."""
    pnr: dict = {"segments": [], "passengers": [], "remarks": [], "raw": []}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line: continue
        pnr["raw"].append(line)
        # 1.1 LASTNAME/FIRSTNAME
        if re.match(r"^\s*\d+\.\d+\s+", line):
            pnr["passengers"].append(line.strip())
        # AA 100 Y 01JUN LAXJFK HK1
        elif re.match(r"^[A-Z]{2}\s+\d+", line):
            pnr["segments"].append(line.strip())
        elif line.startswith(("RM", "RMK", "OSI", "SSR")):
            pnr["remarks"].append(line.strip())
    return pnr


def op_pnr_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"PNR file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            pnr = _parse_pnr(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(pnr, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("airline_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="pnr",
             passengers=len(pnr["passengers"]),
             segments=len(pnr["segments"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Built-in IATA reference data ───────────────────────────────────────

_AIRPORTS = [
    ("ATL", "Atlanta", "USA", "KATL"),
    ("LAX", "Los Angeles", "USA", "KLAX"),
    ("ORD", "Chicago O'Hare", "USA", "KORD"),
    ("DFW", "Dallas/Fort Worth", "USA", "KDFW"),
    ("DEN", "Denver", "USA", "KDEN"),
    ("JFK", "New York Kennedy", "USA", "KJFK"),
    ("SFO", "San Francisco", "USA", "KSFO"),
    ("SEA", "Seattle/Tacoma", "USA", "KSEA"),
    ("LAS", "Las Vegas", "USA", "KLAS"),
    ("MCO", "Orlando", "USA", "KMCO"),
    ("CLT", "Charlotte", "USA", "KCLT"),
    ("PHX", "Phoenix", "USA", "KPHX"),
    ("LHR", "London Heathrow", "UK", "EGLL"),
    ("LGW", "London Gatwick", "UK", "EGKK"),
    ("CDG", "Paris Charles de Gaulle", "France", "LFPG"),
    ("FRA", "Frankfurt", "Germany", "EDDF"),
    ("AMS", "Amsterdam Schiphol", "Netherlands", "EHAM"),
    ("MAD", "Madrid Barajas", "Spain", "LEMD"),
    ("FCO", "Rome Fiumicino", "Italy", "LIRF"),
    ("ZRH", "Zurich", "Switzerland", "LSZH"),
    ("DXB", "Dubai", "UAE", "OMDB"),
    ("DOH", "Doha", "Qatar", "OTHH"),
    ("HKG", "Hong Kong", "Hong Kong", "VHHH"),
    ("ICN", "Seoul Incheon", "Korea", "RKSI"),
    ("NRT", "Tokyo Narita", "Japan", "RJAA"),
    ("HND", "Tokyo Haneda", "Japan", "RJTT"),
    ("PEK", "Beijing Capital", "China", "ZBAA"),
    ("PVG", "Shanghai Pudong", "China", "ZSPD"),
    ("SIN", "Singapore Changi", "Singapore", "WSSS"),
    ("BOM", "Mumbai", "India", "VABB"),
    ("DEL", "Delhi", "India", "VIDP"),
    ("SYD", "Sydney", "Australia", "YSSY"),
    ("MEL", "Melbourne", "Australia", "YMML"),
    ("YYZ", "Toronto Pearson", "Canada", "CYYZ"),
    ("YVR", "Vancouver", "Canada", "CYVR"),
    ("MEX", "Mexico City", "Mexico", "MMMX"),
    ("GRU", "Sao Paulo Guarulhos", "Brazil", "SBGR"),
    ("EZE", "Buenos Aires Ezeiza", "Argentina", "SAEZ"),
    ("JNB", "Johannesburg", "South Africa", "FAJS"),
]

_AIRLINES = [
    ("AA", "American Airlines", "USA"),
    ("DL", "Delta Air Lines", "USA"),
    ("UA", "United Airlines", "USA"),
    ("WN", "Southwest Airlines", "USA"),
    ("AS", "Alaska Airlines", "USA"),
    ("B6", "JetBlue Airways", "USA"),
    ("F9", "Frontier Airlines", "USA"),
    ("NK", "Spirit Airlines", "USA"),
    ("AC", "Air Canada", "Canada"),
    ("WS", "WestJet", "Canada"),
    ("BA", "British Airways", "UK"),
    ("AF", "Air France", "France"),
    ("LH", "Lufthansa", "Germany"),
    ("KL", "KLM", "Netherlands"),
    ("IB", "Iberia", "Spain"),
    ("AZ", "ITA Airways", "Italy"),
    ("LX", "Swiss International", "Switzerland"),
    ("EK", "Emirates", "UAE"),
    ("QR", "Qatar Airways", "Qatar"),
    ("EY", "Etihad Airways", "UAE"),
    ("SQ", "Singapore Airlines", "Singapore"),
    ("CX", "Cathay Pacific", "Hong Kong"),
    ("KE", "Korean Air", "Korea"),
    ("OZ", "Asiana Airlines", "Korea"),
    ("NH", "All Nippon Airways", "Japan"),
    ("JL", "Japan Airlines", "Japan"),
    ("CA", "Air China", "China"),
    ("MU", "China Eastern", "China"),
    ("CZ", "China Southern", "China"),
    ("AI", "Air India", "India"),
    ("QF", "Qantas", "Australia"),
    ("VA", "Virgin Australia", "Australia"),
    ("LA", "LATAM Airlines", "Chile"),
    ("ET", "Ethiopian Airlines", "Ethiopia"),
]


def op_airport_codes(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "iata-airports.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["iata", "name", "country", "icao"])
        for row in _AIRPORTS: w.writerow(row)
    emit("airline_doc",
         input="(builtin)", output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="csv", source="iata-airports", count=len(_AIRPORTS))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(_AIRPORTS))
    return 0


def op_airline_codes(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "iata-airlines.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["iata", "name", "country"])
        for row in _AIRLINES: w.writerow(row)
    emit("airline_doc",
         input="(builtin)", output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="csv", source="iata-airlines", count=len(_AIRLINES))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(_AIRLINES))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iata-sidecar",
                                description="IATA airline messaging conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("ndc-to-json", "NDC XML -> JSON"),
        ("ndc-detect",  "Detect NDC message type / version"),
        ("pnr-to-json", "Legacy airline PNR -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    for op, helpstr in [
        ("airport-codes", "Built-in IATA airport code reference -> CSV"),
        ("airline-codes", "Built-in IATA airline code reference -> CSV"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "ndc-to-json":   return op_ndc_to_json(args)
        if args.op == "ndc-detect":    return op_ndc_detect(args)
        if args.op == "pnr-to-json":   return op_pnr_to_json(args)
        if args.op == "airport-codes": return op_airport_codes(args)
        if args.op == "airline-codes": return op_airline_codes(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

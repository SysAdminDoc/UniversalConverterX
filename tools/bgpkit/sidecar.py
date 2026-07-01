"""BGP / MRT / RPKI routing sidecar.

Convert routing telemetry to analysis-friendly formats:

  * MRT TABLE_DUMP_V2 (RFC 6396) -> JSON / CSV (RIB entries)
  * MRT BGP4MP_MESSAGE             -> JSON (BGP UPDATE / KEEPALIVE)
  * RPKI ROA (CSV from RIPE / NLnet) -> normalized CSV
  * BIRD/Quagga show route output  -> JSON

Operations:
  mrt-rib-to-csv     MRT TABLE_DUMP_V2 RIB -> CSV.
  mrt-rib-to-json    MRT RIB -> JSON.
  bird-routes-to-csv `birdc show route` text -> CSV.
  rpki-roa-fix       Normalize RPKI ROA dumps from RIPE/NLnet/Cloudflare.

Requires: `mrtparse` for MRT decoding (binary format from RouteViews / RIPE RIS).
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
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── MRT (Multi-Threaded Routing Toolkit) decoding via mrtparse ────────

def _iter_mrt(path: Path):
    try:
        from mrtparse import Reader
    except ImportError:
        raise RuntimeError("mrtparse not installed (`pip install mrtparse`).")
    return Reader(str(path))


def _flatten_rib_entry(rib_entry, prefix: str) -> dict:
    """Convert mrtparse rib entry -> flat dict."""
    attrs = rib_entry.get("path_attributes", []) or []
    out: dict = {"prefix": prefix}
    for a in attrs:
        if isinstance(a, dict):
            t = a.get("type", [None, ""])[1]
            if t == "AS_PATH":
                paths = a.get("value", [])
                if paths:
                    seg = paths[0]
                    out["as_path"] = " ".join(map(str, seg.get("value", [])))
            elif t == "ORIGIN":
                out["origin"] = a.get("value", [None, ""])[1]
            elif t == "MULTI_EXIT_DISC":
                out["med"] = a.get("value", "")
            elif t == "LOCAL_PREF":
                out["local_pref"] = a.get("value", "")
            elif t == "NEXT_HOP":
                out["next_hop"] = a.get("value", "")
            elif t == "COMMUNITY":
                out["community"] = " ".join(map(str, a.get("value", [])))
    return out


def op_mrt_rib_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MRT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            rows: list[dict] = []
            for entry in _iter_mrt(src):
                if not isinstance(entry, dict): continue
                t = entry.get("type", [None, ""])[1]
                if "TABLE_DUMP" not in (t or ""): continue
                prefix = (str(entry.get("prefix", "")) +
                          "/" + str(entry.get("prefix_length", "")))
                for rib in entry.get("rib_entries", []) or []:
                    rows.append(_flatten_rib_entry(rib, prefix))
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            keys = ["prefix", "next_hop", "as_path", "origin", "med",
                    "local_pref", "community"]
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("bgp_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="mrt-rib", entries=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_mrt_rib_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MRT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            entries: list[dict] = []
            for entry in _iter_mrt(src):
                if isinstance(entry, dict):
                    entries.append(entry)
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(entries, indent=2, default=str),
                            encoding="utf-8")
        emit("bgp_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="mrt", count=len(entries))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── BIRD `show route` text -> CSV ─────────────────────────────────────

_BIRD_ROUTE_RE = re.compile(
    r"^(?P<prefix>[\d\.:a-fA-F/]+)\s+"
    r"(?:via\s+(?P<via>[\d\.:a-fA-F]+)\s+)?"
    r"(?:on\s+(?P<iface>\S+))?")


def op_bird_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BIRD output not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for raw in text.splitlines():
            m = _BIRD_ROUTE_RE.match(raw)
            if m and m.group("prefix"):
                rows.append({
                    "prefix": m.group("prefix"),
                    "via": m.group("via") or "",
                    "iface": m.group("iface") or "",
                })
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["prefix", "via", "iface"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("bgp_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="bird-routes", routes=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── RPKI ROA dump normalization ────────────────────────────────────────

def op_rpki_roa_fix(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"ROA dump(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            with src.open(encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        # Detect column layout: RIPE = ASN,IP Prefix,Max Length,Trust Anchor
        # Cloudflare = AS, IP, MaxLen
        normalized: list[dict] = []
        for row in rows[1:]:  # skip header
            if len(row) < 3: continue
            asn = re.sub(r"^AS", "", str(row[0]).strip(), flags=re.IGNORECASE)
            prefix = str(row[1]).strip()
            try: maxlen = int(str(row[2]).strip())
            except (ValueError, TypeError): continue
            normalized.append({
                "asn": asn,
                "prefix": prefix,
                "max_length": maxlen,
                "trust_anchor": (row[3].strip() if len(row) > 3 else ""),
            })
        out_path = out_dir / (src.stem + "_normalized.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["asn", "prefix", "max_length",
                                                 "trust_anchor"])
            w.writeheader()
            for r in normalized: w.writerow(r)
        emit("bgp_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="rpki-roa", entries=len(normalized))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bgpkit-sidecar",
                                description="BGP / MRT / RPKI routing telemetry conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("mrt-rib-to-csv",   "MRT TABLE_DUMP_V2 RIB -> CSV"),
        ("mrt-rib-to-json",  "MRT TABLE_DUMP_V2 RIB -> JSON"),
        ("bird-routes-to-csv", "BIRD `show route` text -> CSV"),
        ("rpki-roa-fix",     "Normalize RPKI ROA dumps -> CSV"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "mrt-rib-to-csv":     return op_mrt_rib_to_csv(args)
        if args.op == "mrt-rib-to-json":    return op_mrt_rib_to_json(args)
        if args.op == "bird-routes-to-csv": return op_bird_to_csv(args)
        if args.op == "rpki-roa-fix":       return op_rpki_roa_fix(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

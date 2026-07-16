"""Electronic Data Interchange (EDI) sidecar.

Decode EDI X12 (US healthcare / supply chain / banking) and EDIFACT
(international supply chain) into navigable JSON / CSV.

Operations:
  x12-to-json       EDI X12 -> hierarchical JSON.
  edifact-to-json   EDIFACT -> hierarchical JSON.
  segments-to-csv   Flatten EDI -> per-segment CSV row.

EDI is delimited at four levels by control characters declared at the start
of every interchange (ISA / UNB envelope). We do segment-level parsing
without external libraries to keep the sidecar self-contained.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── X12 ────────────────────────────────────────────────────────────────

def _parse_x12(text: str) -> dict:
    """Return {envelope, segments[]} where each segment is {tag, elements}."""
    text = text.strip()
    if not text.startswith("ISA"):
        raise ValueError("Not an X12 file (must start with ISA segment).")
    # ISA is fixed-width: 106 chars total. The 4 delimiters are derived from it.
    # Element separator = char at position 3 (index 3 in ISA).
    # Sub-element separator = char at position 104.
    # Segment terminator = char at position 105.
    elem_sep = text[3]
    sub_sep = text[104] if len(text) > 104 else ":"
    seg_term = text[105] if len(text) > 105 else "~"

    raw_segments = [s.strip() for s in text.split(seg_term) if s.strip()]
    segments: list[dict] = []
    for raw in raw_segments:
        parts = raw.split(elem_sep)
        tag = parts[0]
        elements = []
        for p in parts[1:]:
            if sub_sep in p:
                elements.append(p.split(sub_sep))
            else:
                elements.append(p)
        segments.append({"tag": tag, "elements": elements})
    return {"format": "x12", "delimiters": {
                "element": elem_sep, "subelement": sub_sep, "segment": seg_term},
            "segments": segments}


# ── EDIFACT ────────────────────────────────────────────────────────────

def _parse_edifact(text: str) -> dict:
    """EDIFACT delimiters are declared in the optional UNA segment."""
    text = text.strip()
    if text.startswith("UNA"):
        # UNA followed by 6 chars: comp_sep, elem_sep, dec, release, _, term.
        comp_sep = text[3]
        elem_sep = text[4]
        release = text[6]
        seg_term = text[8]
        body = text[9:]
    elif text.startswith("UNB"):
        comp_sep, elem_sep, release, seg_term = ":", "+", "?", "'"
        body = text
    else:
        raise ValueError("Not an EDIFACT file (must start with UNA or UNB).")

    raw_segments = []
    cur = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == release and i + 1 < len(body):
            cur.append(body[i + 1]); i += 2; continue
        if ch == seg_term:
            if cur: raw_segments.append("".join(cur).strip()); cur = []
            i += 1; continue
        cur.append(ch); i += 1
    if cur: raw_segments.append("".join(cur).strip())

    segments: list[dict] = []
    for raw in raw_segments:
        if not raw: continue
        parts = raw.split(elem_sep)
        tag = parts[0]
        elements = []
        for p in parts[1:]:
            if comp_sep in p:
                elements.append(p.split(comp_sep))
            else:
                elements.append(p)
        segments.append({"tag": tag, "elements": elements})
    return {"format": "edifact",
            "delimiters": {"element": elem_sep, "component": comp_sep,
                            "release": release, "segment": seg_term},
            "segments": segments}


def _detect(text: str) -> str:
    s = text.strip()
    if s.startswith("ISA"): return "x12"
    if s.startswith(("UNA", "UNB")): return "edifact"
    raise ValueError("Could not auto-detect EDI format.")


def op_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"EDI file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            kind = args.format.lower() if args.format != "auto" else _detect(text)
            parsed = _parse_x12(text) if kind == "x12" else _parse_edifact(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("edi_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source=parsed["format"],
             segments=len(parsed.get("segments", [])))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"EDI file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        text = src.read_text(encoding="utf-8", errors="replace")
        try:
            kind = args.format.lower() if args.format != "auto" else _detect(text)
            parsed = _parse_x12(text) if kind == "x12" else _parse_edifact(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["#", "tag", "elements"])
            for n, seg in enumerate(parsed["segments"], 1):
                elems = "|".join(
                    ":".join(e) if isinstance(e, list) else e
                    for e in seg["elements"]
                )
                w.writerow([n, seg["tag"], elems])
        emit("edi_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source=parsed["format"],
             segments=len(parsed.get("segments", [])))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edi-sidecar",
                                description="EDI X12 / EDIFACT decoder.")
    sub = p.add_subparsers(dest="op", required=True)

    j = sub.add_parser("to-json", help="EDI -> hierarchical JSON.")
    j.add_argument("--input", nargs="+", required=True)
    j.add_argument("--output-dir", required=True, dest="output_dir")
    j.add_argument("--format", default="auto",
                   choices=["auto", "x12", "edifact"])

    c = sub.add_parser("to-csv", help="EDI -> per-segment CSV.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", default="auto",
                   choices=["auto", "x12", "edifact"])

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-json": return op_to_json(args)
        if args.op == "to-csv":  return op_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Tax / accounting export sidecar.

European and US accounting interchange formats:

  * SIE 4 (Swedish Standard Import/Export Format)
  * DATEV CSV (German accounting export)
  * IFX (Interactive Financial Exchange)
  * ELSTER (German tax filing XML)
  * IRS 990 / FATCA / CRS XML

Operations:
  sie-to-csv         Swedish SIE 4 -> CSV (per #VER vouchers).
  sie-to-json        Swedish SIE 4 -> structured JSON.
  datev-to-csv       DATEV header+rows export -> normalized CSV.
  ifx-to-json        IFX (XML) -> JSON.
  elster-detect      ELSTER tax filing XML -> JSON probe.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── SIE 4 (Swedish accounting standard) ───────────────────────────────

def _parse_sie(text: str) -> dict:
    """SIE 4 is a line-based format, latin-1 historically. Each line starts
    with a `#KEYWORD` followed by space-separated tokens or quoted strings."""
    accounts: list[dict] = []
    vouchers: list[dict] = []
    cur_voucher: dict | None = None
    header: dict = {}

    def _split_quoted(line: str) -> list[str]:
        out: list[str] = []; buf = ""; in_q = False
        for ch in line:
            if ch == '"' and not in_q: in_q = True; continue
            if ch == '"' and in_q: in_q = False; out.append(buf); buf = ""; continue
            if ch == " " and not in_q:
                if buf: out.append(buf); buf = ""
                continue
            buf += ch
        if buf: out.append(buf)
        return out

    for raw in text.splitlines():
        line = raw.strip()
        if not line: continue
        parts = _split_quoted(line)
        if not parts: continue
        kw = parts[0].lstrip("#").upper()
        rest = parts[1:]
        if kw == "FNAMN" and rest:
            header["company"] = rest[0]
        elif kw == "RAR" and len(rest) >= 3:
            header.setdefault("fiscal_years", []).append(
                {"index": rest[0], "from": rest[1], "to": rest[2]})
        elif kw == "KONTO" and len(rest) >= 2:
            accounts.append({"account_no": rest[0], "name": rest[1]})
        elif kw == "VER" and len(rest) >= 4:
            cur_voucher = {
                "series": rest[0], "number": rest[1],
                "date": rest[2], "description": rest[3] if len(rest) > 3 else "",
                "lines": [],
            }
            vouchers.append(cur_voucher)
        elif kw == "TRANS" and cur_voucher and len(rest) >= 3:
            cur_voucher["lines"].append({
                "account_no": rest[0],
                "object_dim": rest[1],
                "amount": float(rest[2].replace(",", ".")) if rest[2] else 0,
                "transaction_date": rest[3] if len(rest) > 3 else "",
                "text": rest[4] if len(rest) > 4 else "",
            })
        elif line == "}":
            cur_voucher = None
    return {"header": header, "accounts": accounts, "vouchers": vouchers}


def op_sie_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SIE file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        # SIE files historically use code page 437 / latin-1; try latin-1 first.
        try:
            text = src.read_text(encoding="latin-1")
            parsed = _parse_sie(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["series", "voucher_no", "voucher_date", "description",
                         "account_no", "amount", "transaction_date", "text"])
            for v in parsed["vouchers"]:
                for ln in v["lines"]:
                    w.writerow([v["series"], v["number"], v["date"],
                                 v["description"], ln["account_no"],
                                 ln["amount"], ln["transaction_date"],
                                 ln["text"]])
        emit("tax_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="sie",
             vouchers=len(parsed["vouchers"]),
             accounts=len(parsed["accounts"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_sie_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SIE file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            parsed = _parse_sie(src.read_text(encoding="latin-1"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("tax_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="sie",
             vouchers=len(parsed["vouchers"]),
             accounts=len(parsed["accounts"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── DATEV (German accounting CSV) ─────────────────────────────────────

_DATEV_HEADER_FIELDS = [
    "Umsatz", "Soll/Haben-Kennzeichen", "Belegdatum",
    "Konto", "Gegenkonto", "BU-Schlüssel", "Beleginfo - Art 1",
    "Beleginfo - Inhalt 1", "Buchungstext",
]


def op_datev_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DATEV file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        # DATEV CSV is cp1252-encoded with semicolon separator.
        try:
            with src.open(encoding="cp1252", newline="") as f:
                lines = list(csv.reader(f, delimiter=";"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        if len(lines) < 3:
            return fail("parse_failed",
                        f"{src.name}: too short (need DATEV header + col-row + data).")
        # Row 0 is meta header; row 1 is column names; rows 2+ are data.
        meta_row = lines[0]
        col_row = lines[1]
        data = lines[2:]
        out_path = out_dir / (src.stem + "_normalized.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(col_row)
            for row in data: w.writerow(row)
        emit("tax_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="datev",
             rows=len(data), meta_columns=len(meta_row))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── IFX / ELSTER (XML) ────────────────────────────────────────────────

_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str: return _NS_RE.sub("", tag)


def _xml_to_dict(elem: ET.Element):
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        return text if text else None
    out: dict = {}
    for child in children:
        key = _strip_ns(child.tag)
        val = _xml_to_dict(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(val)
        else:
            out[key] = val
    return out


def op_ifx_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"IFX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            data = _xml_to_dict(tree.getroot())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("tax_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="ifx")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_elster_detect(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"ELSTER file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            verfahren = ""
            datenart = ""
            tax_year = ""
            for elem in root.iter():
                tag = _strip_ns(elem.tag)
                if tag == "Verfahren": verfahren = (elem.text or "").strip()
                elif tag == "DatenArt": datenart = (elem.text or "").strip()
                elif tag == "Datum_kennung": tax_year = (elem.text or "").strip()
            detections.append({
                "file": str(src), "size_bytes": src.stat().st_size,
                "verfahren": verfahren, "datenart": datenart,
                "tax_period": tax_year,
            })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("tax_doc",
             input=str(src), output="",
             size_bytes=0, format="detect",
             source="elster", verfahren=verfahren, datenart=datenart)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "elster-detect.json"
    out_path.write_text(json.dumps(detections, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(detections))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taxkit-sidecar",
                                description="Tax / accounting export conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("sie-to-csv",     "Swedish SIE 4 -> CSV"),
        ("sie-to-json",    "Swedish SIE 4 -> JSON"),
        ("datev-to-csv",   "DATEV German accounting -> normalized CSV"),
        ("ifx-to-json",    "IFX (Interactive Financial Exchange) -> JSON"),
        ("elster-detect",  "ELSTER tax filing XML probe"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "sie-to-csv":     return op_sie_to_csv(args)
        if args.op == "sie-to-json":    return op_sie_to_json(args)
        if args.op == "datev-to-csv":   return op_datev_to_csv(args)
        if args.op == "ifx-to-json":    return op_ifx_to_json(args)
        if args.op == "elster-detect":  return op_elster_detect(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

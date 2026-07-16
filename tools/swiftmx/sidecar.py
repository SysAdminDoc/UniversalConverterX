"""SWIFT MX (ISO 20022 XML banking) sidecar.

ISO 20022 is the modern XML banking-message standard replacing legacy
SWIFT MT. This sidecar handles the MX message families:

  * pacs.* (Payments Clearing & Settlement)
  * pain.* (Payments Initiation)            — pain.001 = SEPA Credit Transfer
  * camt.* (Cash Management)                — camt.052/053/054 statements
  * setr.* (Settlement / Reconciliation)
  * remt.* (Remittance Advice)

Operations:
  mx-to-json     ISO 20022 XML -> structured JSON (recursive element walk).
  mx-detect      Detect MX message family / version from a file (or directory).
  pain-to-csv    pain.001 SEPA Credit Transfer payment instructions -> CSV.
  camt-to-csv    camt.053 statement entries -> CSV.

Pure stdlib (xml.etree). No external deps required.
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


_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _elem_to_dict(elem: ET.Element) -> dict | str | None:
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        return text if text else None
    out: dict = {}
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


def _detect_family(path: Path) -> tuple[str, str]:
    """Return (family, version) e.g. ('pacs.008', '001.08')."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # match xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"
    m = re.search(
        r'xmlns="urn:iso:std:iso:20022:tech:xsd:([a-z]+\.\d+)\.(\d+\.\d+)"',
        text)
    if m: return m.group(1), m.group(2)
    return "unknown", ""


# ── Operations ─────────────────────────────────────────────────────────

def op_mx_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            data = _elem_to_dict(tree.getroot())
            family, version = _detect_family(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps({"family": family, "version": version,
                                         "document": data},
                                        indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("swift_mx",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="iso-20022",
             family=family, version=version)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_mx_detect(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        family, version = _detect_family(src)
        detections.append({"file": str(src), "family": family,
                           "version": version, "size_bytes": src.stat().st_size})
        emit("swift_mx",
             input=str(src), output="",
             size_bytes=0, format="detect",
             family=family, version=version)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "mx-detect.json"
    out_path.write_text(json.dumps(detections, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(detections))
    return 0


def _find(elem: ET.Element, *path: str) -> ET.Element | None:
    """Find descendant ignoring namespaces."""
    cur = elem
    for tag in path:
        nxt = None
        for child in cur:
            if _strip_ns(child.tag) == tag:
                nxt = child; break
        if nxt is None: return None
        cur = nxt
    return cur


def _findall(elem: ET.Element, tag: str) -> list[ET.Element]:
    return [e for e in elem.iter() if _strip_ns(e.tag) == tag]


def _txt(elem: ET.Element | None, *path: str) -> str:
    if elem is None: return ""
    found = _find(elem, *path)
    return ((found.text or "").strip()) if found is not None else ""


def op_pain_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"pain.001 file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            root = ET.parse(str(src)).getroot()
            txns: list[dict] = []
            for txn in _findall(root, "CdtTrfTxInf"):
                amt_node = _find(txn, "Amt", "InstdAmt")
                amt_text = (amt_node.text or "").strip() if amt_node is not None else ""
                ccy = amt_node.get("Ccy", "") if amt_node is not None else ""
                txns.append({
                    "EndToEndId": _txt(txn, "PmtId", "EndToEndId"),
                    "Amount": amt_text,
                    "Currency": ccy,
                    "CreditorName": _txt(txn, "Cdtr", "Nm"),
                    "CreditorIBAN": _txt(txn, "CdtrAcct", "Id", "IBAN"),
                    "CreditorBIC": _txt(txn, "CdtrAgt", "FinInstnId", "BIC"),
                    "RemittanceInfo": _txt(txn, "RmtInf", "Ustrd"),
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            keys = ["EndToEndId", "Amount", "Currency", "CreditorName",
                    "CreditorIBAN", "CreditorBIC", "RemittanceInfo"]
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for t in txns: w.writerow(t)
        emit("swift_mx",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="pain.001", count=len(txns))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_camt_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"camt.053 file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            root = ET.parse(str(src)).getroot()
            entries: list[dict] = []
            for entry in _findall(root, "Ntry"):
                amt_node = _find(entry, "Amt")
                amt_text = (amt_node.text or "").strip() if amt_node is not None else ""
                ccy = amt_node.get("Ccy", "") if amt_node is not None else ""
                entries.append({
                    "BookingDate": _txt(entry, "BookgDt", "Dt"),
                    "ValueDate":   _txt(entry, "ValDt", "Dt"),
                    "Amount":      amt_text,
                    "Currency":    ccy,
                    "CdtDbtInd":   _txt(entry, "CdtDbtInd"),
                    "Status":      _txt(entry, "Sts"),
                    "BankRef":     _txt(entry, "AcctSvcrRef"),
                    "Description": _txt(entry, "AddtlNtryInf"),
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            keys = ["BookingDate", "ValueDate", "Amount", "Currency",
                    "CdtDbtInd", "Status", "BankRef", "Description"]
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for e in entries: w.writerow(e)
        emit("swift_mx",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="camt.053", count=len(entries))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="swiftmx-sidecar",
                                description="SWIFT MX (ISO 20022 XML) banking message decoder.")
    sub = p.add_subparsers(dest="op", required=True)

    for op, helpstr in [
        ("mx-to-json",  "ISO 20022 XML -> JSON tree."),
        ("mx-detect",   "Detect family/version of ISO 20022 XML."),
        ("pain-to-csv", "pain.001 SEPA Credit Transfer -> CSV."),
        ("camt-to-csv", "camt.053 statement entries -> CSV."),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "mx-to-json":  return op_mx_to_json(args)
        if args.op == "mx-detect":   return op_mx_detect(args)
        if args.op == "pain-to-csv": return op_pain_to_csv(args)
        if args.op == "camt-to-csv": return op_camt_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

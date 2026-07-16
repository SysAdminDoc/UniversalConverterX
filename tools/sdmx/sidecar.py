"""Regulatory data standards sidecar.

Convert regulatory and statistical data interchange formats into CSV
for analysis:

  * XBRL (eXtensible Business Reporting Language) — SEC filings
  * iXBRL (Inline XBRL) — embedded financial filings
  * SDMX (Statistical Data and Metadata eXchange) — Eurostat, IMF, OECD
  * DDI (Data Documentation Initiative) — survey codebooks

Operations:
  xbrl-facts-to-csv   XBRL document -> CSV (one row per fact).
  ixbrl-extract       Inline XBRL embedded in HTML -> CSV.
  sdmx-data-to-csv    SDMX-ML 2.1 generic data -> CSV.
  sdmx-codelist       SDMX codelist -> CSV.
  ddi-codebook        DDI 2.5 codebook -> JSON.
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


def _strip_ns(tag: str) -> str: return _NS_RE.sub("", tag)


# ── XBRL facts ────────────────────────────────────────────────────────

def _xbrl_facts(root: ET.Element) -> list[dict]:
    facts: list[dict] = []
    contexts: dict[str, dict] = {}
    units: dict[str, str] = {}
    # Map contexts + units first
    for elem in root:
        tag = _strip_ns(elem.tag)
        if tag == "context":
            ctx_id = elem.get("id", "")
            entity = ""
            period_start = period_end = period_instant = ""
            for c in elem.iter():
                ct = _strip_ns(c.tag)
                if ct == "identifier":
                    entity = (c.text or "").strip()
                elif ct == "startDate":
                    period_start = (c.text or "").strip()
                elif ct == "endDate":
                    period_end = (c.text or "").strip()
                elif ct == "instant":
                    period_instant = (c.text or "").strip()
            contexts[ctx_id] = {
                "entity": entity, "period_start": period_start,
                "period_end": period_end, "period_instant": period_instant,
            }
        elif tag == "unit":
            unit_id = elem.get("id", "")
            measures = []
            for m in elem.iter():
                if _strip_ns(m.tag) == "measure" and m.text:
                    measures.append(m.text.strip())
            units[unit_id] = " * ".join(measures)
    # Walk facts (anything with a contextRef attribute)
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if not ctx_ref: continue
        ctx = contexts.get(ctx_ref, {})
        unit_ref = elem.get("unitRef", "")
        facts.append({
            "concept": _strip_ns(elem.tag),
            "value": (elem.text or "").strip(),
            "context": ctx_ref,
            "unit": units.get(unit_ref, unit_ref),
            "decimals": elem.get("decimals", ""),
            "entity": ctx.get("entity", ""),
            "period_start": ctx.get("period_start", ""),
            "period_end": ctx.get("period_end", ""),
            "period_instant": ctx.get("period_instant", ""),
        })
    return facts


def op_xbrl_facts_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"XBRL file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            facts = _xbrl_facts(tree.getroot())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".facts.csv")
        keys = ["concept", "value", "context", "unit", "decimals",
                "entity", "period_start", "period_end", "period_instant"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in facts: w.writerow(r)
        emit("regulatory_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="xbrl", facts=len(facts))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── iXBRL extraction ──────────────────────────────────────────────────

_IXBRL_TAG_RE = re.compile(
    r"<ix:(?P<kind>nonNumeric|nonFraction|fraction)[^>]*>(?P<inner>.*?)</ix:",
    re.DOTALL | re.IGNORECASE)
_IXBRL_NAME_RE = re.compile(r'name=\"([^\"]+)\"')
_IXBRL_CTX_RE = re.compile(r'contextRef=\"([^\"]+)\"')
_IXBRL_UNIT_RE = re.compile(r'unitRef=\"([^\"]+)\"')


def op_ixbrl_extract(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"iXBRL file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        # Find ix:* tags with their attributes
        tag_starts = re.finditer(r"<ix:(\w+)([^>]*)>(.*?)</ix:\1>",
                                   text, re.DOTALL | re.IGNORECASE)
        for m in tag_starts:
            kind = m.group(1)
            attrs = m.group(2)
            inner = re.sub(r"<[^>]+>", "", m.group(3)).strip()
            name_m = _IXBRL_NAME_RE.search(attrs)
            ctx_m = _IXBRL_CTX_RE.search(attrs)
            unit_m = _IXBRL_UNIT_RE.search(attrs)
            rows.append({
                "kind": kind,
                "concept": name_m.group(1) if name_m else "",
                "value": inner,
                "context": ctx_m.group(1) if ctx_m else "",
                "unit": unit_m.group(1) if unit_m else "",
            })
        out_path = out_dir / (src.stem + ".ixbrl.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f,
                                fieldnames=["kind", "concept", "value",
                                              "context", "unit"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("regulatory_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="ixbrl", facts=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── SDMX ──────────────────────────────────────────────────────────────

def op_sdmx_data_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SDMX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            obs_rows: list[dict] = []
            for series in root.iter():
                if _strip_ns(series.tag) != "Series": continue
                series_attrs = {}
                for child in series:
                    if _strip_ns(child.tag) == "SeriesKey":
                        for v in child:
                            if _strip_ns(v.tag) == "Value":
                                series_attrs[v.get("id", "")] = v.get("value", "")
                for child in series:
                    if _strip_ns(child.tag) == "Obs":
                        row = dict(series_attrs)
                        for sub in child:
                            t = _strip_ns(sub.tag)
                            if t == "ObsDimension":
                                row["TIME"] = sub.get("value", "")
                            elif t == "ObsValue":
                                row["VALUE"] = sub.get("value", "")
                        obs_rows.append(row)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        if not obs_rows:
            return fail("empty", f"{src.name}: no observations decoded.")
        keys = sorted({k for r in obs_rows for k in r})
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in obs_rows: w.writerow(r)
        emit("regulatory_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="sdmx", observations=len(obs_rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_sdmx_codelist(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SDMX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            codelists: list[dict] = []
            for cl in root.iter():
                if _strip_ns(cl.tag) != "Codelist": continue
                cl_id = cl.get("id", "")
                for code in cl:
                    if _strip_ns(code.tag) != "Code": continue
                    code_id = code.get("id", "")
                    name = ""
                    for n in code:
                        if _strip_ns(n.tag) == "Name":
                            name = (n.text or "").strip(); break
                    codelists.append({
                        "codelist": cl_id,
                        "code_id": code_id,
                        "name": name,
                    })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".codelist.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["codelist", "code_id", "name"])
            w.writeheader()
            for r in codelists: w.writerow(r)
        emit("regulatory_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="sdmx-codelist",
             codes=len(codelists))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── DDI codebook ──────────────────────────────────────────────────────

def op_ddi_codebook(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DDI file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            variables = []
            for var in root.iter():
                if _strip_ns(var.tag) != "var": continue
                lbl = ""
                for c in var:
                    if _strip_ns(c.tag) == "labl":
                        lbl = (c.text or "").strip(); break
                variables.append({
                    "name": var.get("name", ""),
                    "id": var.get("ID", ""),
                    "label": lbl,
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".ddi.json")
        out_path.write_text(json.dumps({"variables": variables}, indent=2),
                            encoding="utf-8")
        emit("regulatory_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="ddi", variables=len(variables))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdmx-sidecar",
                                description="Regulatory / statistical data interchange.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("xbrl-facts-to-csv", "XBRL -> CSV (one row per fact)"),
        ("ixbrl-extract",     "Inline XBRL in HTML -> CSV"),
        ("sdmx-data-to-csv",  "SDMX-ML data -> CSV"),
        ("sdmx-codelist",     "SDMX codelist -> CSV"),
        ("ddi-codebook",      "DDI codebook -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "xbrl-facts-to-csv": return op_xbrl_facts_to_csv(args)
        if args.op == "ixbrl-extract":     return op_ixbrl_extract(args)
        if args.op == "sdmx-data-to-csv":  return op_sdmx_data_to_csv(args)
        if args.op == "sdmx-codelist":     return op_sdmx_codelist(args)
        if args.op == "ddi-codebook":      return op_ddi_codebook(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

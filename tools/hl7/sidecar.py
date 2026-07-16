"""HL7 healthcare messaging sidecar.

The complement to `dicomkit` (medical imaging) and `medkit` (3D volumes):
this one handles the *messaging* + *clinical document* layer.

Inputs / outputs:
  * HL7 v2.x  (.hl7 / .v2)            pipe / hat-delimited messages
  * HL7 FHIR  R4 / R5 / R6            JSON or XML
  * HL7 v3 / CDA documents            XML

Operations:
  v2-to-json     Parse HL7 v2 -> structured JSON.
  json-to-v2     Re-emit JSON -> HL7 v2.
  fhir-to-xml    FHIR JSON -> FHIR XML.
  fhir-to-json   FHIR XML -> FHIR JSON.
  v2-to-fhir     HL7 v2 ADT^A01 / ORU^R01 etc. -> FHIR Bundle (best-effort).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── HL7 v2 parsing (pure stdlib) ─────────────────────────────────────────

def _parse_v2(text: str) -> dict:
    """Parse a single HL7 v2 message into a list of segment dicts."""
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    segments = [s for s in text.split("\r") if s.strip()]
    if not segments: return {"segments": []}

    # MSH segment carries the field/component/repetition/escape/subcomponent
    # delimiters in MSH-1 / MSH-2.
    msh = segments[0]
    if not msh.startswith("MSH"):
        raise ValueError("Not an HL7 v2 message (missing MSH segment).")
    field_sep = msh[3]
    encoding_chars = msh[4:8]   # ^~\&
    component_sep = encoding_chars[0]
    repetition_sep = encoding_chars[1]
    subcomp_sep = encoding_chars[3] if len(encoding_chars) > 3 else "&"

    parsed: list[dict] = []
    for seg in segments:
        seg_id = seg[:3]
        body = seg[3:]
        # MSH is special: the field separator IS the first field, so we shift.
        if seg_id == "MSH":
            fields = [field_sep] + body.split(field_sep)[1:]
        else:
            fields = body.split(field_sep)
        out_fields: list = []
        for fld in fields:
            if repetition_sep in fld:
                reps = [_split_components(r, component_sep, subcomp_sep)
                        for r in fld.split(repetition_sep)]
                out_fields.append(reps)
            else:
                out_fields.append(_split_components(fld, component_sep, subcomp_sep))
        parsed.append({"segment": seg_id, "fields": out_fields})
    return {"segments": parsed,
            "field_sep": field_sep,
            "encoding_chars": encoding_chars}


def _split_components(field: str, comp_sep: str, sub_sep: str):
    if comp_sep not in field:
        return field
    return [
        c if sub_sep not in c else c.split(sub_sep)
        for c in field.split(comp_sep)
    ]


def _emit_v2(parsed: dict) -> str:
    field_sep = parsed.get("field_sep", "|")
    encoding = parsed.get("encoding_chars", "^~\\&")
    comp_sep = encoding[0]
    rep_sep = encoding[1]
    sub_sep = encoding[3] if len(encoding) > 3 else "&"

    lines: list[str] = []
    for seg in parsed.get("segments", []):
        seg_id = seg.get("segment", "OBX")
        fields = seg.get("fields", [])
        out_parts: list[str] = []
        # MSH-1 IS the field separator; skip the placeholder.
        skip_first = seg_id == "MSH"
        for i, f in enumerate(fields):
            if skip_first and i == 0:
                continue
            out_parts.append(_join_field(f, comp_sep, rep_sep, sub_sep))
        body = field_sep.join(out_parts)
        lines.append(f"{seg_id}{field_sep if not skip_first else ''}{body}")
    return "\r".join(lines) + "\r"


def _join_field(value, comp_sep: str, rep_sep: str, sub_sep: str) -> str:
    if isinstance(value, str): return value
    if isinstance(value, list) and value and isinstance(value[0], list):
        # repetitions
        return rep_sep.join(_join_components(r, comp_sep, sub_sep) for r in value)
    if isinstance(value, list):
        return _join_components(value, comp_sep, sub_sep)
    return str(value or "")


def _join_components(comps, comp_sep: str, sub_sep: str) -> str:
    out = []
    for c in comps:
        if isinstance(c, list):
            out.append(sub_sep.join(c))
        else:
            out.append(str(c or ""))
    return comp_sep.join(out)


def op_v2_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"HL7 file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            parsed = _parse_v2(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("hl7_message",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", segment_count=len(parsed.get("segments", [])))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_json_to_v2(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"JSON file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            parsed = json.loads(src.read_text(encoding="utf-8"))
            text = _emit_v2(parsed)
        except Exception as ex:
            return fail("emit_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".hl7")
        out_path.write_text(text, encoding="utf-8")
        emit("hl7_message",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="v2", segment_count=len(parsed.get("segments", [])))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── FHIR JSON <-> XML ─────────────────────────────────────────────────────

FHIR_NS = "http://hl7.org/fhir"


def _fhir_json_to_xml(obj: dict, parent: ET.Element | None = None,
                       tag: str | None = None) -> ET.Element:
    """Convert a FHIR JSON resource into the canonical XML form."""
    root_tag = tag or obj.get("resourceType", "Resource")
    el = ET.Element(root_tag) if parent is None else ET.SubElement(parent, root_tag)
    for k, v in obj.items():
        if k == "resourceType": continue
        if isinstance(v, dict):
            _fhir_json_to_xml(v, el, k)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _fhir_json_to_xml(item, el, k)
                else:
                    sub = ET.SubElement(el, k)
                    sub.set("value", str(item))
        else:
            sub = ET.SubElement(el, k)
            sub.set("value", str(v))
    return el


def _fhir_xml_to_json(el: ET.Element) -> dict:
    out: dict = {"resourceType": el.tag.split("}", 1)[-1]}
    children: dict[str, list] = {}
    for child in el:
        tag = child.tag.split("}", 1)[-1]
        if "value" in child.attrib and len(child) == 0:
            children.setdefault(tag, []).append(child.attrib["value"])
        else:
            children.setdefault(tag, []).append(_fhir_xml_to_json(child))
    for tag, values in children.items():
        out[tag] = values[0] if len(values) == 1 else values
    return out


def op_fhir_to_xml(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"FHIR JSON file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            obj = json.loads(src.read_text(encoding="utf-8"))
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        el = _fhir_json_to_xml(obj)
        # Namespace it correctly.
        el.set("xmlns", FHIR_NS)
        out_path = out_dir / (src.stem + ".xml")
        ET.ElementTree(el).write(out_path, encoding="utf-8", xml_declaration=True)
        emit("fhir_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="xml", resource_type=obj.get("resourceType"))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_fhir_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"FHIR XML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(src); root = tree.getroot()
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        obj = _fhir_xml_to_json(root)
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(obj, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("fhir_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", resource_type=obj.get("resourceType"))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hl7-sidecar",
                                description="HL7 v2 + FHIR (R4/R5) message conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("v2-to-json", help="HL7 v2 -> JSON.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    b = sub.add_parser("json-to-v2", help="JSON -> HL7 v2.")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")

    c = sub.add_parser("fhir-to-xml", help="FHIR JSON -> FHIR XML.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")

    d = sub.add_parser("fhir-to-json", help="FHIR XML -> FHIR JSON.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "v2-to-json":   return op_v2_to_json(args)
        if args.op == "json-to-v2":   return op_json_to_v2(args)
        if args.op == "fhir-to-xml":  return op_fhir_to_xml(args)
        if args.op == "fhir-to-json": return op_fhir_to_json(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

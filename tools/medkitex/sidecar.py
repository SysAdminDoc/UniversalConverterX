"""Healthcare extras sidecar (extends `dicomkit` / `dicomrt` / `hl7`).

Specialty healthcare interchange formats:

  * DICOM SR (Structured Report) — radiology measurements / findings
  * DICOM Waveform — ECG / EEG / hemodynamic monitoring traces
  * CCD (Continuity of Care Document, HL7 CDA R2) -> JSON
  * CCDA (Consolidated CDA) sections -> JSON
  * IHE XDS metadata (XDSDocumentEntry) -> JSON
  * BlueButton+ Direct (CCD wrapped in MIME)
  * NCPDP SCRIPT (e-prescribing) -> JSON

Operations:
  dicom-sr-to-json       DICOM SR -> JSON narrative + measurements.
  dicom-waveform-csv     DICOM Waveform -> per-channel CSV.
  ccd-to-json            HL7 CDA R2 / CCD / CCDA -> JSON.
  xds-metadata-to-csv    IHE XDS metadata -> CSV.
  ncpdp-to-json          NCPDP SCRIPT -> JSON.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import struct
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


def _strip_ns(tag: str) -> str: return _NS_RE.sub("", tag)


# ── DICOM SR ──────────────────────────────────────────────────────────

def op_dicom_sr_to_json(args: argparse.Namespace) -> int:
    try:
        import pydicom
    except ImportError:
        return fail("missing_dep", "pydicom not installed (`pip install pydicom`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DICOM SR file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    def _walk_content_seq(seq):
        nodes = []
        for item in seq:
            node = {
                "rel_type": str(getattr(item, "RelationshipType", "")),
                "value_type": str(getattr(item, "ValueType", "")),
            }
            cn = getattr(item, "ConceptNameCodeSequence", None)
            if cn:
                node["concept"] = {
                    "code_value": str(getattr(cn[0], "CodeValue", "")),
                    "scheme": str(getattr(cn[0], "CodingSchemeDesignator", "")),
                    "meaning": str(getattr(cn[0], "CodeMeaning", "")),
                }
            if hasattr(item, "TextValue"):
                node["text"] = str(item.TextValue)
            if hasattr(item, "MeasuredValueSequence"):
                mv = item.MeasuredValueSequence[0]
                node["measured"] = {
                    "value": float(getattr(mv, "NumericValue", 0)),
                    "unit": (str(getattr(mv.MeasurementUnitsCodeSequence[0],
                                            "CodeMeaning", ""))
                              if hasattr(mv, "MeasurementUnitsCodeSequence")
                              else ""),
                }
            if hasattr(item, "ContentSequence"):
                node["children"] = _walk_content_seq(item.ContentSequence)
            nodes.append(node)
        return nodes

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), stop_before_pixels=True)
            if str(getattr(ds, "Modality", "")) != "SR":
                return fail("wrong_modality",
                            f"{src.name}: not DICOM SR (got {ds.Modality}).")
            doc = {
                "study_instance_uid": str(getattr(ds, "StudyInstanceUID", "")),
                "series_instance_uid": str(getattr(ds, "SeriesInstanceUID", "")),
                "patient_id": str(getattr(ds, "PatientID", "")),
                "patient_name": str(getattr(ds, "PatientName", "")),
                "completion_flag": str(getattr(ds, "CompletionFlag", "")),
                "verification_flag": str(getattr(ds, "VerificationFlag", "")),
                "content": _walk_content_seq(
                    getattr(ds, "ContentSequence", []) or []),
            }
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".sr.json")
        out_path.write_text(json.dumps(doc, indent=2, default=str),
                            encoding="utf-8")
        emit("medkitex_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="dicom-sr")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── DICOM Waveform ────────────────────────────────────────────────────

def op_dicom_waveform_csv(args: argparse.Namespace) -> int:
    try:
        import pydicom
        import numpy as np
    except ImportError as ex:
        return fail("missing_dep",
                    f"pydicom + numpy required: {ex}")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DICOM Waveform file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), stop_before_pixels=False)
            seq = getattr(ds, "WaveformSequence", None)
            if not seq:
                return fail("parse_failed",
                            f"{src.name}: no WaveformSequence.")
            wf = seq[0]
            samples = int(wf.NumberOfWaveformSamples)
            channels = int(wf.NumberOfWaveformChannels)
            bps = int(wf.WaveformBitsAllocated)
            sample_rate = float(wf.SamplingFrequency)
            raw = bytes(wf.WaveformData)
            dtype = "<i2" if bps == 16 else "<i1"
            arr = np.frombuffer(raw, dtype=dtype).reshape(samples, channels)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".wf.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s"] + [f"ch{c+1}" for c in range(channels)])
            for n in range(samples):
                row = [n / sample_rate] + [float(arr[n, c])
                                              for c in range(channels)]
                w.writerow(row)
        emit("medkitex_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="dicom-waveform",
             samples=samples, channels=channels)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── HL7 CDA / CCD / CCDA ──────────────────────────────────────────────

def op_ccd_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CCD file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            doc = {"sections": []}
            # Get patient role
            for prole in root.iter():
                if _strip_ns(prole.tag) == "patient":
                    name_el = next((c for c in prole
                                     if _strip_ns(c.tag) == "name"), None)
                    if name_el is not None:
                        given = next((g.text for g in name_el
                                       if _strip_ns(g.tag) == "given"
                                       and g.text), "")
                        family = next((f.text for f in name_el
                                        if _strip_ns(f.tag) == "family"
                                        and f.text), "")
                        doc["patient_name"] = f"{given} {family}".strip()
                    break
            # Find sections
            for section in root.iter():
                if _strip_ns(section.tag) != "section": continue
                code_el = next((c for c in section
                                 if _strip_ns(c.tag) == "code"), None)
                title_el = next((c for c in section
                                  if _strip_ns(c.tag) == "title"), None)
                doc["sections"].append({
                    "code": code_el.get("code", "") if code_el is not None else "",
                    "displayName": (code_el.get("displayName", "")
                                       if code_el is not None else ""),
                    "title": (title_el.text or "").strip()
                              if title_el is not None else "",
                    "entry_count": sum(1 for e in section
                                         if _strip_ns(e.tag) == "entry"),
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".ccd.json")
        out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("medkitex_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="hl7-cda-ccd",
             sections=len(doc["sections"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── IHE XDS metadata ──────────────────────────────────────────────────

def op_xds_metadata_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"XDS metadata file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            entries: list[dict] = []
            for obj in root.iter():
                if _strip_ns(obj.tag) != "ExtrinsicObject": continue
                row = {
                    "id": obj.get("id", ""),
                    "objectType": obj.get("objectType", ""),
                    "mimeType": obj.get("mimeType", ""),
                }
                for slot in obj:
                    if _strip_ns(slot.tag) == "Slot":
                        row[slot.get("name", "")] = ",".join(
                            (v.text or "") for v in slot.iter()
                            if _strip_ns(v.tag) == "Value")
                entries.append(row)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        keys = sorted({k for r in entries for k in r})
        out_path = out_dir / (src.stem + ".xds.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in entries: w.writerow(r)
        emit("medkitex_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="ihe-xds", entries=len(entries))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── NCPDP SCRIPT (HL7-style) ──────────────────────────────────────────

def op_ncpdp_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"NCPDP file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            data = _xml_dump(tree.getroot())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".ncpdp.json")
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("medkitex_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="ncpdp-script")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def _xml_dump(elem):
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        return text if text else None
    out: dict = {}
    for c in children:
        key = _strip_ns(c.tag)
        val = _xml_dump(c)
        if key in out:
            if not isinstance(out[key], list): out[key] = [out[key]]
            out[key].append(val)
        else:
            out[key] = val
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="medkitex-sidecar",
                                description="Healthcare extras decoders.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("dicom-sr-to-json",      "DICOM SR -> JSON narrative + measurements"),
        ("dicom-waveform-csv",    "DICOM Waveform ECG / EEG -> CSV"),
        ("ccd-to-json",           "HL7 CDA R2 / CCD / CCDA -> JSON"),
        ("xds-metadata-to-csv",   "IHE XDS metadata -> CSV"),
        ("ncpdp-to-json",         "NCPDP SCRIPT e-prescribing -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "dicom-sr-to-json":     return op_dicom_sr_to_json(args)
        if args.op == "dicom-waveform-csv":   return op_dicom_waveform_csv(args)
        if args.op == "ccd-to-json":          return op_ccd_to_json(args)
        if args.op == "xds-metadata-to-csv":  return op_xds_metadata_to_csv(args)
        if args.op == "ncpdp-to-json":        return op_ncpdp_to_json(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

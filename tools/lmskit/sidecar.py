"""Learning Management System (LMS) sidecar.

Probe / extract LMS course-content interchange formats:

  * SCORM 1.2 / 2004 (.zip with imsmanifest.xml)
  * Common Cartridge .imscc (zip + cartridge manifest)
  * QTI 2.x / 3.x quiz items
  * xAPI (Tin Can) statement JSON / NDJSON
  * LTI 1.3 launch JWT decode
  * Moodle .mbz course backup (gzipped tar with moodle_backup.xml)

Operations:
  scorm-info          SCORM .zip imsmanifest.xml -> JSON probe.
  imscc-info          Common Cartridge .imscc -> JSON probe.
  qti-questions       QTI items -> CSV (id, type, prompt).
  xapi-to-csv         xAPI statement JSON / NDJSON -> CSV.
  lti-decode          LTI 1.3 launch JWT decode (no signature check).
  mbz-info            Moodle .mbz backup probe.
"""
from __future__ import annotations

import argparse
import base64
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
import tarfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str: return _NS_RE.sub("", tag)


# ── SCORM ─────────────────────────────────────────────────────────────

def op_scorm_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SCORM .zip file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            with zipfile.ZipFile(src) as z:
                names = z.namelist()
                manifest_name = next(
                    (n for n in names if n.lower().endswith("imsmanifest.xml")),
                    None)
                if not manifest_name:
                    return fail("parse_failed",
                                f"{src.name}: no imsmanifest.xml found.")
                xml = z.read(manifest_name).decode("utf-8", errors="replace")
                root = ET.fromstring(xml)
                organizations = []
                for org in root.iter():
                    if _strip_ns(org.tag) == "organization":
                        title = ""
                        for c in org:
                            if _strip_ns(c.tag) == "title":
                                title = (c.text or "").strip(); break
                        organizations.append(title)
                items = sum(1 for e in root.iter() if _strip_ns(e.tag) == "item")
                resources = sum(1 for e in root.iter()
                                if _strip_ns(e.tag) == "resource")
                schema = ""
                for e in root.iter():
                    if _strip_ns(e.tag) == "schemaversion":
                        schema = (e.text or "").strip(); break
                probes.append({
                    "file": str(src), "size_bytes": src.stat().st_size,
                    "manifest_path": manifest_name,
                    "schemaversion": schema,
                    "organizations": organizations,
                    "item_count": items,
                    "resource_count": resources,
                    "entry_count": len(names),
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("lms_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="scorm")
    out_path = out_dir / "scorm-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── Common Cartridge .imscc ───────────────────────────────────────────

def op_imscc_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".imscc file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            with zipfile.ZipFile(src) as z:
                names = z.namelist()
                manifest_name = next(
                    (n for n in names if n.lower().endswith("imsmanifest.xml")),
                    None)
                resources_count = 0
                schema = ""
                if manifest_name:
                    xml = z.read(manifest_name).decode("utf-8",
                                                          errors="replace")
                    try:
                        root = ET.fromstring(xml)
                        resources_count = sum(
                            1 for e in root.iter()
                            if _strip_ns(e.tag) == "resource")
                        for e in root.iter():
                            if _strip_ns(e.tag) == "schema":
                                schema = (e.text or "").strip(); break
                    except Exception:
                        pass
                probes.append({
                    "file": str(src), "size_bytes": src.stat().st_size,
                    "entry_count": len(names),
                    "schema": schema,
                    "resources": resources_count,
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("lms_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="imscc")
    out_path = out_dir / "imscc-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── QTI questions ─────────────────────────────────────────────────────

def _qti_questions(root: ET.Element) -> list[dict]:
    rows: list[dict] = []
    for item in root.iter():
        if _strip_ns(item.tag) not in ("assessmentItem", "item"): continue
        ident = item.get("identifier", "") or item.get("ident", "")
        title = item.get("title", "")
        prompt = ""
        type_ = ""
        for child in item.iter():
            t = _strip_ns(child.tag)
            if t == "prompt":
                prompt = (child.text or "").strip()[:1000]
            if t == "responseDeclaration":
                type_ = child.get("cardinality", "") + "/" + child.get(
                    "baseType", "")
        rows.append({"id": ident, "title": title, "type": type_,
                     "prompt": prompt})
    return rows


def op_qti_questions(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"QTI file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            rows = _qti_questions(tree.getroot())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".qti.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "title", "type", "prompt"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("lms_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="qti", questions=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── xAPI / Tin Can ────────────────────────────────────────────────────

def op_xapi_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"xAPI file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8")
            stmts: list[dict]
            stripped = text.lstrip()
            if stripped.startswith("["):
                stmts = json.loads(text)
            elif stripped.startswith("{"):
                # NDJSON / single statement
                stmts = []
                for line in text.splitlines():
                    line = line.strip()
                    if not line: continue
                    stmts.append(json.loads(line))
            else:
                return fail("parse_failed",
                            f"{src.name}: not a JSON / NDJSON xAPI file.")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for s in stmts:
            actor = (s.get("actor", {}) or {})
            verb = (s.get("verb", {}) or {})
            obj = (s.get("object", {}) or {})
            result = (s.get("result", {}) or {})
            rows.append({
                "id": s.get("id", ""),
                "timestamp": s.get("timestamp", ""),
                "actor_name": actor.get("name", ""),
                "actor_mbox": actor.get("mbox", ""),
                "verb_id": verb.get("id", ""),
                "verb_display": (verb.get("display", {}) or {}).get("en-US",
                    next(iter((verb.get("display", {}) or {}).values()), "")),
                "object_id": obj.get("id", ""),
                "object_definition": (obj.get("definition", {}) or {}).get(
                    "type", ""),
                "result_completion": result.get("completion", ""),
                "result_success": result.get("success", ""),
                "result_score": ((result.get("score", {}) or {}).get("scaled",
                                                                       "")),
            })
        out_path = out_dir / (src.stem + ".xapi.csv")
        keys = ["id", "timestamp", "actor_name", "actor_mbox",
                "verb_id", "verb_display", "object_id",
                "object_definition", "result_completion",
                "result_success", "result_score"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("lms_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="xapi", statements=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── LTI 1.3 JWT decode ────────────────────────────────────────────────

def _b64url(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def op_lti_decode(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"JWT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            text = src.read_text(encoding="utf-8", errors="replace").strip()
            parts = text.split(".")
            if len(parts) != 3:
                return fail("parse_failed",
                            f"{src.name}: not a JWT (expected 3 parts).")
            header = json.loads(_b64url(parts[0]))
            payload = json.loads(_b64url(parts[1]))
            probes.append({
                "file": str(src), "header": header, "payload": payload,
                "signature_present": bool(parts[2]),
            })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("lms_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="lti-1.3-jwt")
    out_path = out_dir / "lti-decode.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── Moodle .mbz ───────────────────────────────────────────────────────

def op_mbz_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".mbz file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            with tarfile.open(src, "r:gz") as tar:
                names = tar.getnames()
                backup_xml = None
                for n in names:
                    if n.lower().endswith("moodle_backup.xml"):
                        f = tar.extractfile(n)
                        if f:
                            backup_xml = f.read().decode("utf-8",
                                                            errors="replace")
                        break
            info: dict = {"file": str(src), "size_bytes": src.stat().st_size,
                          "entry_count": len(names)}
            if backup_xml:
                root = ET.fromstring(backup_xml)
                info["course_fullname"] = ""
                for c in root.iter():
                    t = _strip_ns(c.tag)
                    if t == "fullname":
                        info["course_fullname"] = (c.text or "").strip()
                        break
                info["activity_count"] = sum(
                    1 for c in root.iter()
                    if _strip_ns(c.tag) == "activity")
            probes.append(info)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("lms_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="moodle-mbz")
    out_path = out_dir / "mbz-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lmskit-sidecar",
                                description="LMS course-content format probes.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("scorm-info",     "SCORM .zip imsmanifest.xml probe"),
        ("imscc-info",     "Common Cartridge .imscc probe"),
        ("qti-questions",  "QTI items -> CSV"),
        ("xapi-to-csv",    "xAPI statements -> CSV"),
        ("lti-decode",     "LTI 1.3 JWT decode (no sig check)"),
        ("mbz-info",       "Moodle .mbz backup probe"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "scorm-info":    return op_scorm_info(args)
        if args.op == "imscc-info":    return op_imscc_info(args)
        if args.op == "qti-questions": return op_qti_questions(args)
        if args.op == "xapi-to-csv":   return op_xapi_to_csv(args)
        if args.op == "lti-decode":    return op_lti_decode(args)
        if args.op == "mbz-info":      return op_mbz_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

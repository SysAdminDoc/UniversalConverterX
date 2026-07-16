"""Business intelligence / reporting tool sidecar.

Probe BI / reporting project files for structural metadata. None of
these formats are fully convertible to each other (they encode tool-
specific render trees), but the manifests give SQL extractions and
schema inventories useful for migrations:

  * Tableau .twb (XML) / .twbx (zipped) workbook
  * Power BI .pbix (zip) / .pbit template
  * Looker LookML .lkml model files
  * dbt project (.yml + .sql) probe
  * Crystal Reports .rpt (binary) magic check
  * SSRS .rdl (XML) report definition

Operations:
  twb-info          Tableau .twb / .twbx -> JSON probe (datasources, worksheets).
  pbix-info         Power BI .pbix -> JSON probe (DataModelSchema).
  rdl-info          SSRS .rdl -> JSON probe (datasets + parameters).
  lookml-info       Looker LookML directory probe.
  dbt-project       dbt project dir probe (models + sources + tests).
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str: return _NS_RE.sub("", tag)


# ── Tableau .twb / .twbx ──────────────────────────────────────────────

def _read_twb_xml(path: Path) -> str:
    if path.suffix.lower() == ".twbx":
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".twb"):
                    return z.read(name).decode("utf-8", errors="replace")
        raise ValueError("No .twb inside .twbx archive.")
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_twb(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    info: dict = {"version": root.get("version", "")}
    datasources = []
    for ds in root.iter("datasource"):
        connection = ds.find("connection")
        conn_attr = dict(connection.attrib) if connection is not None else {}
        datasources.append({
            "name": ds.get("caption") or ds.get("name", ""),
            "connection_class": conn_attr.get("class", ""),
            "connection_server": conn_attr.get("server", ""),
            "connection_dbname": conn_attr.get("dbname", ""),
        })
    worksheets = [w.get("name", "") for w in root.iter("worksheet")]
    dashboards = [d.get("name", "") for d in root.iter("dashboard")]
    info["datasources"] = datasources
    info["worksheet_count"] = len(worksheets)
    info["worksheets"] = worksheets[:50]
    info["dashboard_count"] = len(dashboards)
    info["dashboards"] = dashboards
    return info


def op_twb_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Tableau file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            xml_text = _read_twb_xml(src)
            info = _parse_twb(xml_text)
            info["file"] = str(src)
            info["size_bytes"] = src.stat().st_size
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("bi_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="tableau",
             worksheets=info["worksheet_count"])
    out_path = out_dir / "tableau-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── Power BI .pbix ─────────────────────────────────────────────────────

def _parse_pbix(path: Path) -> dict:
    info: dict = {}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        info["entries"] = len(names)
        # DataModelSchema is UTF-16-LE JSON
        if "DataModelSchema" in names:
            try:
                raw = z.read("DataModelSchema")
                # PBIX files use UTF-16 LE with no BOM in some versions.
                text = raw.decode("utf-16-le", errors="replace").lstrip("\ufeff")
                schema = json.loads(text)
                model = schema.get("model", {})
                info["tables"] = [t.get("name", "")
                                   for t in model.get("tables", [])]
                info["table_count"] = len(model.get("tables", []))
                info["measures"] = sum(
                    len(t.get("measures", []) or [])
                    for t in model.get("tables", []))
                info["data_sources"] = [(d.get("type", "") + ":"
                                          + d.get("name", ""))
                                         for d in model.get("dataSources", [])]
                info["culture"] = schema.get("model", {}).get("culture", "")
            except Exception as ex:
                info["schema_error"] = str(ex)
        if "Connections" in names:
            try:
                conn_text = z.read("Connections").decode("utf-8",
                                                            errors="replace")
                info["connections_present"] = True
                info["connections_size"] = len(conn_text)
            except Exception:
                pass
    return info


def op_pbix_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".pbix file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info = _parse_pbix(src)
            info["file"] = str(src)
            info["size_bytes"] = src.stat().st_size
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("bi_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="powerbi",
             tables=info.get("table_count", 0))
    out_path = out_dir / "pbix-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── SSRS .rdl ─────────────────────────────────────────────────────────

def _parse_rdl(path: Path) -> dict:
    tree = ET.parse(str(path))
    root = tree.getroot()
    datasets = []
    for ds in root.iter():
        if _strip_ns(ds.tag) == "DataSet":
            datasets.append({
                "name": ds.get("Name", ""),
                "fields": [_strip_ns(f.tag) + ": " + (f.get("Name") or "")
                            for f in ds if _strip_ns(f.tag) == "Fields"],
            })
    parameters = []
    for pr in root.iter():
        if _strip_ns(pr.tag) == "ReportParameter":
            parameters.append(pr.get("Name", ""))
    return {"dataset_count": len(datasets), "datasets": datasets,
            "parameter_count": len(parameters), "parameters": parameters}


def op_rdl_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".rdl file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info = _parse_rdl(src)
            info["file"] = str(src)
            info["size_bytes"] = src.stat().st_size
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("bi_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="ssrs-rdl",
             datasets=info["dataset_count"])
    out_path = out_dir / "rdl-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── Looker LookML / dbt ───────────────────────────────────────────────

_LKML_VIEW_RE = re.compile(r"^\s*view:\s+(\w+)", re.MULTILINE)
_LKML_MODEL_RE = re.compile(r"^\s*model:\s+(\w+)", re.MULTILINE)
_LKML_EXPLORE_RE = re.compile(r"^\s*explore:\s+(\w+)", re.MULTILINE)
_LKML_DIM_RE = re.compile(r"^\s*dimension:\s+(\w+)", re.MULTILINE)
_LKML_MEASURE_RE = re.compile(r"^\s*measure:\s+(\w+)", re.MULTILINE)


def op_lookml_info(args: argparse.Namespace) -> int:
    root = Path(args.lookml_dir)
    if not root.is_dir():
        return fail("missing_input", f"LookML dir not found: {root}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    aggregate = {"models": [], "views": [], "explores": [],
                 "dimension_count": 0, "measure_count": 0,
                 "lkml_file_count": 0}
    for cur, _dirs, files in __import__("os").walk(root):
        for fn in files:
            if not fn.lower().endswith((".lkml", ".lookml")): continue
            full = Path(cur) / fn
            text = full.read_text(encoding="utf-8", errors="replace")
            aggregate["lkml_file_count"] += 1
            aggregate["models"].extend(_LKML_MODEL_RE.findall(text))
            aggregate["views"].extend(_LKML_VIEW_RE.findall(text))
            aggregate["explores"].extend(_LKML_EXPLORE_RE.findall(text))
            aggregate["dimension_count"] += len(
                _LKML_DIM_RE.findall(text))
            aggregate["measure_count"] += len(
                _LKML_MEASURE_RE.findall(text))
    out_path = out_dir / "lookml-info.json"
    out_path.write_text(json.dumps(aggregate, indent=2),
                        encoding="utf-8")
    emit("bi_doc",
         input=str(root), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="json", source="looker-lookml",
         views=len(aggregate["views"]))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_dbt_project(args: argparse.Namespace) -> int:
    root = Path(args.project_dir)
    if not root.is_dir():
        return fail("missing_input", f"dbt project dir not found: {root}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    info: dict = {
        "project_yml_present": (root / "dbt_project.yml").is_file(),
        "models": [], "sources": [], "tests": [], "seeds": [],
    }
    for cur, _dirs, files in __import__("os").walk(root):
        cur_path = Path(cur)
        for fn in files:
            full = cur_path / fn
            if fn.lower().endswith(".sql"):
                rel = full.relative_to(root).as_posix()
                if "/models/" in rel or rel.startswith("models/"):
                    info["models"].append(rel)
                elif "/tests/" in rel or rel.startswith("tests/"):
                    info["tests"].append(rel)
            elif fn.lower().endswith(".csv"):
                rel = full.relative_to(root).as_posix()
                if "/seeds/" in rel or rel.startswith("seeds/"):
                    info["seeds"].append(rel)
            elif fn.lower() in ("schema.yml", "sources.yml"):
                rel = full.relative_to(root).as_posix()
                info["sources"].append(rel)
    info["model_count"] = len(info["models"])
    info["test_count"] = len(info["tests"])
    info["seed_count"] = len(info["seeds"])
    out_path = out_dir / "dbt-project-info.json"
    out_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    emit("bi_doc",
         input=str(root), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="json", source="dbt-project",
         models=info["model_count"])
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bireport-sidecar",
                                description="Business intelligence project probes.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("twb-info",   "Tableau .twb/.twbx probe -> JSON"),
        ("pbix-info",  "Power BI .pbix probe -> JSON"),
        ("rdl-info",   "SSRS .rdl probe -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")

    lkml = sub.add_parser("lookml-info", help="Looker LookML directory probe")
    lkml.add_argument("--lookml-dir", required=True, dest="lookml_dir")
    lkml.add_argument("--output-dir", required=True, dest="output_dir")

    dbt = sub.add_parser("dbt-project", help="dbt project directory probe")
    dbt.add_argument("--project-dir", required=True, dest="project_dir")
    dbt.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "twb-info":     return op_twb_info(args)
        if args.op == "pbix-info":    return op_pbix_info(args)
        if args.op == "rdl-info":     return op_rdl_info(args)
        if args.op == "lookml-info":  return op_lookml_info(args)
        if args.op == "dbt-project":  return op_dbt_project(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

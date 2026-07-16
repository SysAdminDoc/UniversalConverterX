"""Test-result format sidecar.

Convert test-runner result formats into a normalized CSV / JSON / HTML
manifest (one row per test case):

  * JUnit XML (used by Jest, Vitest, Mocha, pytest, Maven, Gradle, MSTest)
  * TAP (Test Anything Protocol) v12/v13/v14
  * NUnit 3 XML
  * TestNG XML
  * Allure JSON test-cases
  * Cucumber JSON
  * xUnit.net XML

Operations:
  junit-to-csv     JUnit XML -> normalized CSV.
  junit-to-html    JUnit XML -> standalone HTML report.
  tap-to-csv       TAP -> CSV.
  allure-to-csv    Allure JSON cases -> CSV.
  cucumber-to-csv  Cucumber JSON -> CSV (one row per scenario step).
  detect           Auto-detect test-result format from file content.

Pure stdlib (xml.etree). All formats normalized to columns:
  suite, name, classname, status (passed/failed/skipped/error),
  duration_s, message, file, line.
"""
from __future__ import annotations

import argparse
import csv
import html
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


# ── JUnit ──────────────────────────────────────────────────────────────

def _parse_junit(path: Path) -> list[dict]:
    tree = ET.parse(str(path))
    root = tree.getroot()
    cases: list[dict] = []
    suites = (list(root.iter()) if _strip_ns(root.tag) == "testsuites"
              else [root])
    for elem in root.iter():
        if _strip_ns(elem.tag) != "testcase": continue
        suite = ""
        # walk up to find suite
        for anc in root.iter():
            if _strip_ns(anc.tag) == "testsuite" and elem in list(anc):
                suite = anc.get("name", ""); break
        case: dict = {
            "suite": suite,
            "name": elem.get("name", ""),
            "classname": elem.get("classname", ""),
            "duration_s": float(elem.get("time", "0") or 0),
            "status": "passed",
            "message": "",
            "file": elem.get("file", ""),
            "line": elem.get("line", ""),
        }
        for child in elem:
            tag = _strip_ns(child.tag)
            if tag == "failure": case["status"] = "failed"
            elif tag == "error": case["status"] = "error"
            elif tag == "skipped": case["status"] = "skipped"
            if tag in ("failure", "error", "skipped"):
                case["message"] = (child.get("message", "")
                                    or (child.text or "")).strip()[:1000]
        cases.append(case)
    return cases


def op_junit_to_csv(args: argparse.Namespace) -> int:
    return _testreport_csv(args, _parse_junit, "junit")


def op_junit_to_html(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"JUnit XML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            cases = _parse_junit(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        passed = sum(1 for c in cases if c["status"] == "passed")
        failed = sum(1 for c in cases if c["status"] == "failed")
        errored = sum(1 for c in cases if c["status"] == "error")
        skipped = sum(1 for c in cases if c["status"] == "skipped")
        rows = []
        for c in cases:
            status_class = c["status"]
            rows.append(
                f'<tr class="{status_class}"><td>{html.escape(c["suite"])}</td>'
                f'<td>{html.escape(c["classname"])}</td>'
                f'<td>{html.escape(c["name"])}</td>'
                f'<td class="status">{status_class}</td>'
                f'<td>{c["duration_s"]:.3f}</td>'
                f'<td>{html.escape(c["message"])}</td></tr>')
        body = "\n".join(rows)
        html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Test Report — {html.escape(src.name)}</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1em; background: #1e1e2e;
       color: #cdd6f4; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #45475a; padding: 4px 8px; text-align: left; }}
th {{ background: #313244; }}
tr.passed .status {{ color: #a6e3a1; }}
tr.failed .status, tr.error .status {{ color: #f38ba8; font-weight: bold; }}
tr.skipped .status {{ color: #f9e2af; }}
.summary {{ margin-bottom: 1em; }}
</style></head><body>
<h1>Test Report — {html.escape(src.name)}</h1>
<div class="summary">
  <strong>Passed:</strong> {passed} ·
  <strong>Failed:</strong> {failed} ·
  <strong>Errored:</strong> {errored} ·
  <strong>Skipped:</strong> {skipped} ·
  <strong>Total:</strong> {len(cases)}
</div>
<table><thead><tr><th>Suite</th><th>Class</th><th>Test</th><th>Status</th>
<th>Duration (s)</th><th>Message</th></tr></thead><tbody>
{body}
</tbody></table></body></html>
"""
        out_path = out_dir / (src.stem + ".html")
        out_path.write_text(html_doc, encoding="utf-8")
        emit("test_report",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="html", source="junit", cases=len(cases),
             passed=passed, failed=failed, skipped=skipped)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── TAP ────────────────────────────────────────────────────────────────

_TAP_LINE_RE = re.compile(
    r"^(?P<status>ok|not ok)\s+(?P<num>\d+)?\s*-?\s*(?P<desc>[^#]*)"
    r"(?:#\s*(?P<directive>SKIP|TODO)(?:\s+(?P<reason>.*))?)?",
    re.IGNORECASE)


def _parse_tap(path: Path) -> list[dict]:
    cases: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    suite = path.stem
    for line in text.splitlines():
        m = _TAP_LINE_RE.match(line.strip())
        if not m: continue
        status = "passed" if m.group("status").lower() == "ok" else "failed"
        directive = (m.group("directive") or "").upper()
        if directive == "SKIP": status = "skipped"
        if directive == "TODO" and status == "failed": status = "skipped"
        cases.append({
            "suite": suite,
            "name": (m.group("desc") or "").strip(),
            "classname": "",
            "duration_s": 0.0,
            "status": status,
            "message": (m.group("reason") or "").strip(),
            "file": "", "line": "",
        })
    return cases


def op_tap_to_csv(args):
    return _testreport_csv(args, _parse_tap, "tap")


# ── Allure ─────────────────────────────────────────────────────────────

def _parse_allure(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("results", [])
    out: list[dict] = []
    status_map = {"passed": "passed", "failed": "failed", "broken": "error",
                  "skipped": "skipped"}
    for c in items:
        out.append({
            "suite": (c.get("labels", []) or [{}])[0].get("value", ""),
            "name": c.get("name", ""),
            "classname": c.get("fullName", ""),
            "duration_s": (c.get("stop", 0) - c.get("start", 0)) / 1000.0
                          if c.get("stop") else 0.0,
            "status": status_map.get(c.get("status", "unknown"), "unknown"),
            "message": (c.get("statusDetails", {}) or {}).get("message", ""),
            "file": c.get("source", ""),
            "line": "",
        })
    return out


def op_allure_to_csv(args):
    return _testreport_csv(args, _parse_allure, "allure")


# ── Cucumber ───────────────────────────────────────────────────────────

def _parse_cucumber(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for feature in data:
        f_name = feature.get("name", "")
        for elem in feature.get("elements", []):
            scenario = elem.get("name", "")
            for step in elem.get("steps", []):
                result = step.get("result", {}) or {}
                rows.append({
                    "suite": f_name,
                    "name": f"{scenario} :: {step.get('name', '')}",
                    "classname": elem.get("type", ""),
                    "duration_s": result.get("duration", 0) / 1e9,
                    "status": result.get("status", "unknown"),
                    "message": result.get("error_message", "")[:1000],
                    "file": feature.get("uri", ""),
                    "line": str(step.get("line", "")),
                })
    return rows


def op_cucumber_to_csv(args):
    return _testreport_csv(args, _parse_cucumber, "cucumber")


# ── Detection ──────────────────────────────────────────────────────────

def op_detect(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    for src in inputs:
        kind = "unknown"
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            if text.lstrip().startswith("TAP version"):
                kind = "tap"
            elif text.lstrip().startswith("<?xml"):
                # peek at root tag
                lower = text[:512].lower()
                if "testsuites" in lower or "testsuite" in lower: kind = "junit"
                elif "test-run" in lower or "testresults" in lower: kind = "nunit"
                elif "testng" in lower: kind = "testng"
                elif "assemblies" in lower: kind = "xunit"
            elif text.lstrip().startswith("["):
                arr = json.loads(text)
                if arr and isinstance(arr, list):
                    if "elements" in arr[0] and "uri" in arr[0]: kind = "cucumber"
                    elif "uuid" in arr[0] and "labels" in arr[0]: kind = "allure"
        except Exception:
            pass
        detections.append({"file": str(src), "format": kind,
                           "size_bytes": src.stat().st_size})
        emit("test_report",
             input=str(src), output="",
             size_bytes=0, format="detect", source=kind)
    out_path = out_dir / "test-format-detect.json"
    out_path.write_text(json.dumps(detections, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(detections))
    return 0


# ── Shared CSV writer ──────────────────────────────────────────────────

def _testreport_csv(args, parser, source) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"test report(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            cases = parser(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        keys = ["suite", "classname", "name", "status", "duration_s",
                "message", "file", "line"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for c in cases: w.writerow(c)
        passed = sum(1 for c in cases if c["status"] == "passed")
        failed = sum(1 for c in cases if c["status"] in ("failed", "error"))
        emit("test_report",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source=source,
             cases=len(cases), passed=passed, failed=failed)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="testreports-sidecar",
                                description="Test-runner result format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("junit-to-csv",     "JUnit XML -> normalized CSV"),
        ("junit-to-html",    "JUnit XML -> standalone HTML report"),
        ("tap-to-csv",       "TAP -> CSV"),
        ("allure-to-csv",    "Allure JSON cases -> CSV"),
        ("cucumber-to-csv",  "Cucumber JSON -> CSV (one row per step)"),
        ("detect",           "Probe-only: identify test-result format"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "junit-to-csv":    return op_junit_to_csv(args)
        if args.op == "junit-to-html":   return op_junit_to_html(args)
        if args.op == "tap-to-csv":      return op_tap_to_csv(args)
        if args.op == "allure-to-csv":   return op_allure_to_csv(args)
        if args.op == "cucumber-to-csv": return op_cucumber_to_csv(args)
        if args.op == "detect":          return op_detect(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

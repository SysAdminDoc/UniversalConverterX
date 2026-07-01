"""CAD sidecar -- DXF read / write / version-up / cleanup via ezdxf.

DWG conversion (Autodesk's binary CAD format) requires the ODA File Converter
(free but separate; sidecar shells out to ODAFileConverter.exe when present).

Operations:
  dxf-to-svg   Render DXF -> SVG (matplotlib backend).
  dxf-to-pdf   Render DXF -> PDF (matplotlib backend).
  dxf-version  Save DXF in a different version (R12/R2000/R2007/R2010/R2013/R2018).
  dwg-to-dxf   Convert DWG -> DXF via ODA File Converter.
  audit        Run the ezdxf auditor on a DXF and emit findings.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_oda() -> str | None:
    env = os.environ.get("ODA_PATH")
    if env and Path(env).is_file(): return env
    for n in ("ODAFileConverter.exe",):
        hit = shutil.which(n)
        if hit: return hit
    for c in (
        r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
        r"C:\Program Files\ODAFileConverter\ODAFileConverter.exe",
    ):
        if Path(c).is_file(): return c
    return None


def op_dxf_to_svg(args: argparse.Namespace) -> int:
    try:
        import ezdxf
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib.pyplot as plt
    except ImportError as ex:
        return fail("missing_ezdxf", f"ezdxf or matplotlib missing: {ex}")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"DXF(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_ext = "." + args.op.split("-to-")[1]   # "svg" or "pdf"

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            doc = ezdxf.readfile(str(src))
            msp = doc.modelspace()
            fig, ax = plt.subplots()
            ctx = RenderContext(doc)
            backend = MatplotlibBackend(ax)
            Frontend(ctx, backend).draw_layout(msp, finalize=True)
            out_path = out_dir / (src.stem + out_ext)
            fig.savefig(str(out_path), dpi=int(args.dpi), bbox_inches="tight")
            plt.close(fig)
        except Exception as ex:
            return fail("render_failed", f"{src.name}: {ex}")
        emit("cad_render",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size, format=out_ext.lstrip("."))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_dxf_version(args: argparse.Namespace) -> int:
    try: import ezdxf
    except ImportError as ex: return fail("missing_ezdxf", str(ex))
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"DXF(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.target_version.upper()
    valid = {"R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"}
    if target not in valid:
        return fail("bad_version", f"Unknown DXF version '{target}'. Use one of: {sorted(valid)}")

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            doc = ezdxf.readfile(str(src))
            doc.dxfversion = "AC1009" if target == "R12" else f"AC10{int(target[1:]) - 18:02d}" if target.startswith("R20") else target
            # Cleanest way is ezdxf.upgrade or save_as with explicit version arg.
            out_path = out_dir / (src.stem + f"_{target}.dxf")
            doc.saveas(str(out_path))
        except Exception as ex:
            return fail("save_failed", f"{src.name}: {ex}")
        emit("cad_render",
             input=str(src), output=str(out_path), version=target,
             size_bytes=out_path.stat().st_size)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_dwg_to_dxf(args: argparse.Namespace) -> int:
    oda = _find_oda()
    if not oda:
        return fail("missing_oda",
                    "ODA File Converter not found. Download free from "
                    "https://www.opendesign.com/guestfiles/oda_file_converter "
                    "or set $env:ODA_PATH.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"DWG(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # ODA File Converter wants source / dest folders, output version, type, recurse, audit.
    # Args: <Input folder> <Output folder> <version> <type> <recurse> <audit>
    # Output version: ACAD2018 / ACAD2013 / ... ; type 1=DWG 0=DXF.
    # We work per-file by staging in temp dirs.
    import tempfile
    total = len(inputs)
    for i, src in enumerate(inputs):
        with tempfile.TemporaryDirectory() as tmp_in:
            shutil.copy2(str(src), Path(tmp_in) / src.name)
            cmd = [oda, tmp_in, str(out_dir),
                   "ACAD2018", "0", "0", "1"]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout).splitlines()[-5:]
                for ln in tail: emit("log", level="error", message=ln)
                return fail("oda_failed", f"{src.name}: rc={proc.returncode}")
        out_path = out_dir / (src.stem + ".dxf")
        emit("cad_render",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_audit(args: argparse.Namespace) -> int:
    try: import ezdxf
    except ImportError as ex: return fail("missing_ezdxf", str(ex))
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"DXF not found: {args.input}")
    try:
        doc, auditor = ezdxf.recover.readfile(str(src))
    except Exception as ex:
        return fail("audit_failed", f"{src.name}: {ex}")
    findings = []
    for err in (auditor.errors or []):
        findings.append({"severity": "error", "message": str(err)})
    for warn in (auditor.fixes or []):
        findings.append({"severity": "fix", "message": str(warn)})
    emit("cad_audit",
         path=str(src),
         dxfversion=str(getattr(doc, "dxfversion", "")),
         entity_count=int(len(doc.modelspace())),
         findings=findings)
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=len(findings))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cadkit-sidecar",
                                description="CAD (DXF/DWG) conversion and inspection.")
    sub = p.add_subparsers(dest="op", required=True)
    a = sub.add_parser("dxf-to-svg"); a.add_argument("--input", nargs="+", required=True); a.add_argument("--output-dir", required=True, dest="output_dir"); a.add_argument("--dpi", default=150)
    b = sub.add_parser("dxf-to-pdf"); b.add_argument("--input", nargs="+", required=True); b.add_argument("--output-dir", required=True, dest="output_dir"); b.add_argument("--dpi", default=150)
    c = sub.add_parser("dxf-version", help="Save DXF in another version")
    c.add_argument("--input", nargs="+", required=True); c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--target-version", required=True, dest="target_version", help="R12 | R2000 | R2007 | R2010 | R2013 | R2018")
    d = sub.add_parser("dwg-to-dxf"); d.add_argument("--input", nargs="+", required=True); d.add_argument("--output-dir", required=True, dest="output_dir")
    e = sub.add_parser("audit"); e.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "dxf-to-svg":  return op_dxf_to_svg(args)
        if args.op == "dxf-to-pdf":  return op_dxf_to_svg(args)
        if args.op == "dxf-version": return op_dxf_version(args)
        if args.op == "dwg-to-dxf":  return op_dwg_to_dxf(args)
        if args.op == "audit":       return op_audit(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

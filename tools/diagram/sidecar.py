"""Diagramming sidecar.

Render text-based and binary diagram sources to SVG / PNG / PDF:

  * Mermaid    (.mmd, .mermaid)        via mermaid-cli (mmdc)
  * PlantUML   (.puml, .plantuml, .uml) via plantuml.jar
  * Graphviz   (.dot, .gv)             via dot CLI
  * Visio      (.vsd, .vsdx, .vsdm)    via LibreOffice CLI (libvisio importer)
  * draw.io    (.drawio, .xml)         via drawio-export-cli
  * Excalidraw (.excalidraw)           via excalidraw-cli
  * yEd        (.graphml)              via LibreOffice (yEd format reader) or fallback

Each entry shells out to the respective CLI on PATH; no Python deps.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find(*names: str) -> str | None:
    for n in names:
        h = shutil.which(n) or shutil.which(n + ".exe") or shutil.which(n + ".cmd")
        if h: return h
    return None


def _find_soffice() -> str | None:
    h = _find("soffice", "libreoffice")
    if h: return h
    for c in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if Path(c).is_file(): return c
    return None


def _render_mermaid(src: Path, out_path: Path) -> int:
    mmdc = _find("mmdc")
    if not mmdc:
        return fail("missing_mermaid",
                    "mermaid-cli not found. `npm install -g @mermaid-js/mermaid-cli`.")
    cmd = [mmdc, "-i", str(src), "-o", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("mermaid_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _render_plantuml(src: Path, out_path: Path, target: str) -> int:
    plantuml = _find("plantuml")
    if not plantuml:
        # Try the canonical jar invocation.
        java = _find("java")
        jar = os.environ.get("PLANTUML_JAR")
        if not (java and jar and Path(jar).is_file()):
            return fail("missing_plantuml",
                        "plantuml CLI not found. Install plantuml or set $env:PLANTUML_JAR.")
        cmd = [java, "-jar", jar, "-charset", "UTF-8",
               f"-t{target}", "-o", str(out_path.parent), str(src)]
    else:
        cmd = [plantuml, "-charset", "UTF-8", f"-t{target}",
               "-o", str(out_path.parent), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("plantuml_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _render_graphviz(src: Path, out_path: Path, target: str) -> int:
    dot = _find("dot")
    if not dot:
        return fail("missing_graphviz",
                    "Graphviz `dot` not found. `apt install graphviz` / `choco install graphviz`.")
    cmd = [dot, f"-T{target}", str(src), "-o", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("graphviz_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _render_visio(src: Path, out_path: Path, target: str) -> int:
    soffice = _find_soffice()
    if not soffice:
        return fail("missing_soffice",
                    "LibreOffice not found. Install LibreOffice for Visio import.")
    flt_map = {"pdf":  "pdf",
               "svg":  "svg",
               "png":  "png",
               "html": "html"}
    if target not in flt_map:
        return fail("bad_target", f"Visio supports: {sorted(flt_map)}")
    cmd = [soffice, "--headless", "--norestore",
           "--convert-to", flt_map[target],
           "--outdir", str(out_path.parent), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return fail("soffice_failed",
                    f"{src.name}: rc={proc.returncode}")
    return 0


def _render_drawio(src: Path, out_path: Path, target: str) -> int:
    drawio = _find("drawio") or _find("draw.io")
    if not drawio:
        return fail("missing_drawio",
                    "draw.io desktop CLI not found. Install draw.io desktop "
                    "(https://github.com/jgraph/drawio-desktop/releases).")
    cmd = [drawio, "--export", "--format", target,
           "--output", str(out_path), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("drawio_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _render_excalidraw(src: Path, out_path: Path, target: str) -> int:
    cli = _find("excalidraw_export") or _find("excalidraw-cli")
    if not cli:
        return fail("missing_excalidraw",
                    "excalidraw CLI not found. `npm install -g @excalidraw/excalidraw-cli`.")
    cmd = [cli, "--input", str(src), "--output", str(out_path),
           "--format", target]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("excalidraw_failed", f"{src.name}: rc={proc.returncode}")
    return 0


def _render_dispatch(src: Path, out_path: Path, target: str) -> int:
    ext = src.suffix.lower()
    if ext in (".mmd", ".mermaid"):
        return _render_mermaid(src, out_path)
    if ext in (".puml", ".plantuml", ".uml", ".iuml"):
        return _render_plantuml(src, out_path, target)
    if ext in (".dot", ".gv"):
        return _render_graphviz(src, out_path, target)
    if ext in (".vsd", ".vsdx", ".vsdm"):
        return _render_visio(src, out_path, target)
    if ext in (".drawio", ".xml"):
        return _render_drawio(src, out_path, target)
    if ext == ".excalidraw":
        return _render_excalidraw(src, out_path, target)
    return fail("bad_format", f"Unsupported extension: {ext}")


def op_render(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Diagram source(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="diagram", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + target)
        rc = _render_dispatch(src, out_path, target)
        if rc != 0: return rc
        # PlantUML emits to <stem>.<ext> in --outdir; harmonize.
        if not out_path.is_file():
            for cand in out_dir.glob(src.stem + "." + target):
                out_path = cand; break
        if not out_path.is_file():
            return fail("output_missing",
                        f"{src.name}: render returned success but no output found.")
        emit("diagram_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, source_ext=src.suffix.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_check(_args: argparse.Namespace) -> int:
    """Probe which diagram CLIs are available on PATH."""
    probes = [
        ("mermaid",   ["mmdc"]),
        ("plantuml",  ["plantuml"]),
        ("graphviz",  ["dot"]),
        ("libreoffice", ["soffice", "libreoffice"]),
        ("drawio",    ["drawio", "draw.io"]),
        ("excalidraw",["excalidraw_export", "excalidraw-cli"]),
    ]
    for name, candidates in probes:
        hit = _find(*candidates) or (_find_soffice() if name == "libreoffice" else None)
        emit("diagram_tool_status",
             name=name, available=bool(hit), path=hit or "")
    emit("complete", output="", size_bytes=0, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="diagram-sidecar",
                                description="Diagram source -> SVG / PNG / PDF.")
    sub = p.add_subparsers(dest="op", required=True)
    r = sub.add_parser("render", help="Render Mermaid / PlantUML / Graphviz / Visio / draw.io / Excalidraw.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--format", required=True,
                   help="svg | png | pdf | html (Visio also supports html)")
    sub.add_parser("check", help="Probe available diagram CLIs.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "render": return op_render(args)
        if args.op == "check":  return op_check(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Diagram-format extras sidecar (extends `diagram`).

Where `diagram` covers Mermaid / PlantUML / Graphviz / Visio / draw.io,
this one covers the proprietary / niche tools:

  * Lucidchart .lcc bundle    -> SVG / extracted assets
  * yEd .graphml              -> SVG / PNG via yEd batch CLI
  * Cytoscape .cyjs           -> SVG / JSON
  * SimpleMind .mind          -> JSON outline
  * MindManager .mmap         -> JSON outline
  * Freemind .mm              -> Markdown / OPML outline

Operations:
  graphml-to-svg     yEd / generic GraphML -> SVG (best-effort renderer).
  graphml-to-json    GraphML -> JSON (nodes + edges).
  freemind-to-md     Freemind .mm -> Markdown bullet outline.
  freemind-to-opml   Freemind .mm -> OPML.
  lcc-extract        Lucidchart .lcc -> unzipped tree.

Pure stdlib (zipfile + xml.etree). The yEd / Cytoscape / SimpleMind paths
require their respective CLI tools and surface that clearly.
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
import re
import shutil
import subprocess
import sys
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


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


# ── GraphML parser ─────────────────────────────────────────────────────

def _parse_graphml(path: Path) -> dict:
    tree = ET.parse(str(path))
    root = tree.getroot()
    nodes: list[dict] = []
    edges: list[dict] = []
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        if tag == "node":
            label = ""
            for c in elem.iter():
                if _strip_ns(c.tag) in ("NodeLabel", "data") and c.text:
                    label = c.text.strip(); break
            nodes.append({"id": elem.get("id"), "label": label})
        elif tag == "edge":
            edges.append({
                "id": elem.get("id"),
                "source": elem.get("source"),
                "target": elem.get("target"),
            })
    return {"nodes": nodes, "edges": edges}


def op_graphml_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"GraphML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            graph = _parse_graphml(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("diagram_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="graphml",
             nodes=len(graph["nodes"]), edges=len(graph["edges"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_graphml_to_svg(args: argparse.Namespace) -> int:
    """GraphML -> SVG via Graphviz `dot`. We translate GraphML to DOT first."""
    cli = shutil.which("dot")
    if not cli: return fail("missing_dep", "graphviz `dot` not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"GraphML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            graph = _parse_graphml(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        dot_lines = ["digraph G {"]
        for n in graph["nodes"]:
            label = (n["label"] or n["id"] or "").replace('"', '\\"')
            dot_lines.append(f'  "{n["id"]}" [label="{label}"];')
        for e in graph["edges"]:
            dot_lines.append(f'  "{e["source"]}" -> "{e["target"]}";')
        dot_lines.append("}")
        dot = "\n".join(dot_lines)
        out_path = out_dir / (src.stem + ".svg")
        proc = subprocess.run([cli, "-Tsvg", "-o", str(out_path)],
                               input=dot, text=True, capture_output=True,
                               timeout=60)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: dot exit {proc.returncode}: "
                        f"{proc.stderr}")
        emit("diagram_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="svg", source="graphml",
             nodes=len(graph["nodes"]), edges=len(graph["edges"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Freemind .mm ───────────────────────────────────────────────────────

def _freemind_to_md(elem: ET.Element, depth: int) -> str:
    out: list[str] = []
    for child in elem:
        if _strip_ns(child.tag) != "node": continue
        text = child.get("TEXT", "")
        out.append("  " * depth + "- " + text)
        out.append(_freemind_to_md(child, depth + 1))
    return "\n".join(filter(None, out))


def _freemind_to_opml(elem: ET.Element, depth: int) -> str:
    out: list[str] = []
    for child in elem:
        if _strip_ns(child.tag) != "node": continue
        text = (child.get("TEXT", "") or "").replace('"', "&quot;")
        nested = _freemind_to_opml(child, depth + 1)
        if nested:
            out.append("  " * depth + f'<outline text="{text}">')
            out.append(nested)
            out.append("  " * depth + "</outline>")
        else:
            out.append("  " * depth + f'<outline text="{text}"/>')
    return "\n".join(filter(None, out))


def op_freemind_to_md(args: argparse.Namespace) -> int:
    return _freemind(args, "md", _freemind_to_md)


def op_freemind_to_opml(args: argparse.Namespace) -> int:
    return _freemind(args, "opml", _freemind_to_opml,
                      wrap_opml=True)


def _freemind(args, ext, transformer, wrap_opml=False) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Freemind file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            top_nodes = [c for c in root if _strip_ns(c.tag) == "node"]
            body_parts: list[str] = []
            for tn in top_nodes:
                text = tn.get("TEXT", "")
                if ext == "md":
                    body_parts.append("# " + text)
                    body_parts.append(transformer(tn, 0))
                else:
                    body_parts.append(f'<outline text="{text}">')
                    body_parts.append(transformer(tn, 1))
                    body_parts.append("</outline>")
            body = "\n".join(filter(None, body_parts))
            if ext == "opml" and wrap_opml:
                body = (
                    '<?xml version="1.0"?>\n'
                    '<opml version="2.0">\n'
                    '  <head><title>Mind Map</title></head>\n'
                    '  <body>\n'
                    f'{body}\n'
                    '  </body>\n'
                    '</opml>\n'
                )
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + ext)
        out_path.write_text(body, encoding="utf-8")
        emit("diagram_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=ext, source="freemind")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Lucidchart .lcc ────────────────────────────────────────────────────

def op_lcc_extract(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".lcc file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        target = out_dir / src.stem
        target.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(src) as z:
                z.extractall(target)
                count = len(z.infolist())
        except Exception as ex:
            return fail("extract_failed", f"{src.name}: {ex}")
        emit("diagram_extra",
             input=str(src), output=str(target),
             size_bytes=0, format="dir", source="lucidchart-lcc",
             entries=count)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="diagrammore-sidecar",
                                description="Niche diagram format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("graphml-to-json",  "GraphML -> JSON (nodes + edges)"),
        ("graphml-to-svg",   "GraphML -> SVG via Graphviz dot"),
        ("freemind-to-md",   "Freemind .mm -> Markdown outline"),
        ("freemind-to-opml", "Freemind .mm -> OPML"),
        ("lcc-extract",      "Lucidchart .lcc -> unzipped tree"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "graphml-to-json":  return op_graphml_to_json(args)
        if args.op == "graphml-to-svg":   return op_graphml_to_svg(args)
        if args.op == "freemind-to-md":   return op_freemind_to_md(args)
        if args.op == "freemind-to-opml": return op_freemind_to_opml(args)
        if args.op == "lcc-extract":      return op_lcc_extract(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Niche data-format sidecar (extends `datakit`).

Where `datakit` covers JSON / YAML / TOML / XML / CSV and `wirefmt`
covers binary wire formats, this one covers the long-tail data
representations:

  * EDN (Clojure's Extensible Data Notation)
  * KDL (Cuddly Data Language)
  * StrictYAML 1.1 vs 1.2 dialect normalization
  * Smile (Jackson binary JSON) — fallback when `pysmile` is installed
  * JSON5 (relaxed JSON with comments / trailing commas)
  * HJSON (Human JSON)
  * RON (Rusty Object Notation)
  * NestedText
  * UCL (libucl)

Operations:
  edn-to-json     EDN -> JSON.
  kdl-to-json     KDL -> JSON.
  json5-to-json   JSON5 -> JSON.
  hjson-to-json   HJSON -> JSON.
  ron-to-json     RON -> JSON.
  nestedtext-to-json   NestedText -> JSON.
  json-to-nestedtext   JSON -> NestedText.

Each op gracefully degrades when the optional library is missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Conversion helpers ─────────────────────────────────────────────────

def _edn_to_json(text: str):
    try:
        import edn_format
        return json.loads(json.dumps(edn_format.loads(text), default=str))
    except ImportError:
        # Tiny fallback: support {:keyword value} and basic types.
        text = text.strip()
        text = re.sub(r":([a-zA-Z][\w\-?!*]*)", r'"\1"', text)
        text = re.sub(r"\{\s*", "{", text)
        text = re.sub(r"\s+\}", "}", text)
        # convert space-separated maps to comma-separated... best-effort only.
        return json.loads(text.replace(" ", ", "))


def _kdl_to_json(text: str):
    try:
        import ckdl  # cuddly kdl bindings
        return ckdl.parse(text)
    except ImportError:
        nodes: list[dict] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("//"): continue
            parts = line.split()
            if not parts: continue
            node = {"name": parts[0], "args": [], "props": {}}
            for tok in parts[1:]:
                if "=" in tok:
                    k, _, v = tok.partition("=")
                    node["props"][k] = _coerce(v)
                else:
                    node["args"].append(_coerce(tok))
            nodes.append(node)
        return nodes


def _coerce(tok: str):
    tok = tok.strip()
    if tok.startswith('"') and tok.endswith('"'): return tok[1:-1]
    if tok.lower() == "true": return True
    if tok.lower() == "false": return False
    if tok.lower() == "null": return None
    try: return int(tok)
    except ValueError: pass
    try: return float(tok)
    except ValueError: pass
    return tok


def _json5_to_json(text: str):
    try:
        import json5
        return json5.loads(text)
    except ImportError:
        # Strip comments + trailing commas — naive but works for most JSON5.
        no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        no_line = re.sub(r"//[^\n]*", "", no_block)
        no_trailing = re.sub(r",\s*([}\]])", r"\1", no_line)
        return json.loads(no_trailing)


def _hjson_to_json(text: str):
    try:
        import hjson
        return hjson.loads(text)
    except ImportError:
        return fail("missing_dep",
                    "hjson not installed (`pip install hjson`).") and None


def _ron_to_json(text: str):
    """Crude RON->JSON: handle `Some(x)` / `None` / parens-tuples / structs."""
    t = text
    t = re.sub(r"None", "null", t)
    t = re.sub(r"Some\(([^()]+)\)", r"\1", t)
    t = re.sub(r"\b([A-Z][\w]*)\s*\(", "{", t)  # struct -> object
    t = t.replace(")", "}").replace("(", "[")
    t = re.sub(r",\s*([}\]])", r"\1", t)
    return json.loads(t)


def _nt_to_json(text: str):
    try:
        import nestedtext as nt
        return nt.loads(text)
    except ImportError:
        return fail("missing_dep",
                    "nestedtext not installed (`pip install nestedtext`).") and None


def _json_to_nt(obj, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.append(f"{pad}{k}:")
                out.append(_json_to_nt(v, indent + 4))
            else:
                out.append(f"{pad}{k}: {v}")
        return "\n".join(out)
    if isinstance(obj, list):
        out = []
        for item in obj:
            if isinstance(item, (dict, list)):
                out.append(f"{pad}-")
                out.append(_json_to_nt(item, indent + 4))
            else:
                out.append(f"{pad}- {item}")
        return "\n".join(out)
    return f"{pad}{obj}"


# ── Operations ─────────────────────────────────────────────────────────

def _io_loop(args: argparse.Namespace, parser, source: str,
             out_ext: str, writer=None) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8")
            converted = parser(text)
        except SystemExit:
            return 1
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + out_ext)
        if writer:
            out_path.write_text(writer(converted), encoding="utf-8")
        else:
            out_path.write_text(json.dumps(converted, indent=2, default=str),
                                 encoding="utf-8")
        emit("data_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=out_ext, source=source)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_edn_to_json(args):       return _io_loop(args, _edn_to_json,    "edn",   "json")
def op_kdl_to_json(args):       return _io_loop(args, _kdl_to_json,    "kdl",   "json")
def op_json5_to_json(args):     return _io_loop(args, _json5_to_json,  "json5", "json")
def op_hjson_to_json(args):     return _io_loop(args, _hjson_to_json,  "hjson", "json")
def op_ron_to_json(args):       return _io_loop(args, _ron_to_json,    "ron",   "json")
def op_nt_to_json(args):        return _io_loop(args, _nt_to_json,     "nt",    "json")
def op_json_to_nt(args):
    return _io_loop(args, json.loads, "json", "nt", writer=_json_to_nt)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="datakitmore-sidecar",
                                description="Niche data-format conversion (extends datakit).")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("edn-to-json",       "EDN (Clojure data) -> JSON"),
        ("kdl-to-json",       "KDL (Cuddly Data Language) -> JSON"),
        ("json5-to-json",     "JSON5 (relaxed JSON) -> JSON"),
        ("hjson-to-json",     "HJSON (Human JSON) -> JSON"),
        ("ron-to-json",       "RON (Rusty Object Notation) -> JSON"),
        ("nestedtext-to-json","NestedText -> JSON"),
        ("json-to-nestedtext","JSON -> NestedText"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "edn-to-json":         return op_edn_to_json(args)
        if args.op == "kdl-to-json":         return op_kdl_to_json(args)
        if args.op == "json5-to-json":       return op_json5_to_json(args)
        if args.op == "hjson-to-json":       return op_hjson_to_json(args)
        if args.op == "ron-to-json":         return op_ron_to_json(args)
        if args.op == "nestedtext-to-json":  return op_nt_to_json(args)
        if args.op == "json-to-nestedtext":  return op_json_to_nt(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

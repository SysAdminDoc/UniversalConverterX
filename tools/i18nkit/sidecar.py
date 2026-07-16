"""Localization-format sidecar.

Mutual conversion across every translation file format that lives in modern
codebases:

  .po  / .pot  (gettext)             babel.messages
  .mo                                msgfmt-style compiler / decompiler
  .xliff / .xlf  (XLIFF 1.2 / 2.0)   xml.etree
  .tmx                               translation memory exchange
  .resx (.NET)                       xml.etree
  .strings (.lproj iOS/macOS)        plain key=value with Apple escapes
  .json (i18next / chrome-i18n)      json
  .yaml (Rails / generic)            PyYAML
  .csv (key,source,target)           stdlib csv

Internally we normalize every format into a list of MessageEntry rows
({key, source, target, comment}) and re-serialize on the way out.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import struct
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


@dataclass
class Entry:
    key: str
    source: str = ""
    target: str = ""
    comment: str = ""


# ---- readers ----------------------------------------------------------------

def read_po(path: Path) -> list[Entry]:
    try:
        from babel.messages.pofile import read_po as _read_po
    except ImportError as ex:
        raise RuntimeError(f"Babel missing: {ex}") from ex
    out: list[Entry] = []
    with path.open("rb") as f:
        cat = _read_po(f)
    for msg in cat:
        if not msg.id: continue
        out.append(Entry(key=msg.id if isinstance(msg.id, str) else msg.id[0],
                         source=msg.id if isinstance(msg.id, str) else msg.id[0],
                         target=msg.string if isinstance(msg.string, str) else (msg.string[0] if msg.string else ""),
                         comment="; ".join(msg.user_comments or [])))
    return out


def read_mo(path: Path) -> list[Entry]:
    try:
        from babel.messages.mofile import read_mo as _read_mo
    except ImportError as ex:
        raise RuntimeError(f"Babel missing: {ex}") from ex
    with path.open("rb") as f:
        cat = _read_mo(f)
    out: list[Entry] = []
    for msg in cat:
        if not msg.id: continue
        out.append(Entry(key=str(msg.id),
                         source=str(msg.id),
                         target=str(msg.string) if msg.string else ""))
    return out


def read_xliff(path: Path) -> list[Entry]:
    tree = ET.parse(path); root = tree.getroot()
    out: list[Entry] = []
    # XLIFF 1.2 has <trans-unit>; 2.0 has <unit><segment>.
    for tu in root.iter():
        tag = tu.tag.split("}", 1)[-1]
        if tag == "trans-unit":
            key = tu.get("id") or ""
            src = (tu.findtext("./{*}source") or
                   "".join(c.text or "" for c in tu if c.tag.endswith("source")))
            tgt = (tu.findtext("./{*}target") or
                   "".join(c.text or "" for c in tu if c.tag.endswith("target")))
            out.append(Entry(key=key, source=src or "", target=tgt or ""))
        elif tag == "unit":
            key = tu.get("id") or ""
            for seg in tu.iter():
                if seg.tag.endswith("segment"):
                    src = "".join(c.text or "" for c in seg if c.tag.endswith("source"))
                    tgt = "".join(c.text or "" for c in seg if c.tag.endswith("target"))
                    out.append(Entry(key=key, source=src, target=tgt))
    return out


def read_tmx(path: Path) -> list[Entry]:
    tree = ET.parse(path); root = tree.getroot()
    out: list[Entry] = []
    for tu in root.iter("tu"):
        tuvs = tu.findall("tuv")
        if len(tuvs) < 2: continue
        src_seg = tuvs[0].findtext("seg") or ""
        tgt_seg = tuvs[1].findtext("seg") or ""
        out.append(Entry(key=src_seg[:80], source=src_seg, target=tgt_seg))
    return out


def read_resx(path: Path) -> list[Entry]:
    tree = ET.parse(path); root = tree.getroot()
    out: list[Entry] = []
    for d in root.findall("data"):
        key = d.get("name") or ""
        val = d.findtext("value") or ""
        cmt = d.findtext("comment") or ""
        out.append(Entry(key=key, source=val, target=val, comment=cmt))
    return out


_STRINGS_LINE = re.compile(r'^"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)"\s*;', re.M)


def _unescape_strings(s: str) -> str:
    return (s.replace('\\"', '"').replace("\\\\", "\\")
             .replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r"))


def _escape_strings(s: str) -> str:
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))


def read_strings(path: Path) -> list[Entry]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [Entry(key=_unescape_strings(k), source=_unescape_strings(v),
                  target=_unescape_strings(v))
            for k, v in _STRINGS_LINE.findall(text)]


def read_json(path: Path) -> list[Entry]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    out: list[Entry] = []

    def walk(prefix: str, node):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(node, str):
            out.append(Entry(key=prefix, source=node, target=node))
    walk("", obj)
    return out


def read_yaml(path: Path) -> list[Entry]:
    import yaml
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[Entry] = []

    def walk(prefix: str, node):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(node, str):
            out.append(Entry(key=prefix, source=node, target=node))
    walk("", obj)
    return out


def read_csv(path: Path) -> list[Entry]:
    out: list[Entry] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(Entry(
                key=row.get("key", "") or row.get("Key", ""),
                source=row.get("source", "") or row.get("Source", ""),
                target=row.get("target", "") or row.get("Target", ""),
                comment=row.get("comment", "") or row.get("Comment", ""),
            ))
    return out


# ---- writers ----------------------------------------------------------------

def write_po(entries: list[Entry], path: Path) -> None:
    from babel.messages import Catalog
    from babel.messages.pofile import write_po as _write_po
    cat = Catalog()
    for e in entries:
        cat.add(e.source or e.key, string=e.target or "",
                user_comments=[e.comment] if e.comment else None)
    with path.open("wb") as f:
        _write_po(f, cat)


def write_mo(entries: list[Entry], path: Path) -> None:
    from babel.messages import Catalog
    from babel.messages.mofile import write_mo as _write_mo
    cat = Catalog()
    for e in entries:
        cat.add(e.source or e.key, string=e.target or "")
    with path.open("wb") as f:
        _write_mo(f, cat)


def write_xliff(entries: list[Entry], path: Path) -> None:
    root = ET.Element("xliff", version="1.2", xmlns="urn:oasis:names:tc:xliff:document:1.2")
    fileel = ET.SubElement(root, "file", original="ucx", **{
        "source-language": "en", "target-language": "en", "datatype": "plaintext"})
    body = ET.SubElement(fileel, "body")
    for i, e in enumerate(entries):
        tu = ET.SubElement(body, "trans-unit", id=e.key or f"u{i}")
        ET.SubElement(tu, "source").text = e.source
        ET.SubElement(tu, "target").text = e.target
        if e.comment:
            ET.SubElement(tu, "note").text = e.comment
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_tmx(entries: list[Entry], path: Path) -> None:
    root = ET.Element("tmx", version="1.4")
    header = ET.SubElement(root, "header",
                           **{"creationtool": "ucx", "creationtoolversion": "1.0",
                              "datatype": "plaintext", "segtype": "sentence",
                              "adminlang": "en-US", "srclang": "en", "o-tmf": "ucx"})
    body = ET.SubElement(root, "body")
    for e in entries:
        tu = ET.SubElement(body, "tu")
        for lang, txt in (("en", e.source), ("xx", e.target)):
            tuv = ET.SubElement(tu, "tuv", **{"xml:lang": lang})
            ET.SubElement(tuv, "seg").text = txt
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_resx(entries: list[Entry], path: Path) -> None:
    root = ET.Element("root")
    for e in entries:
        d = ET.SubElement(root, "data", name=e.key, **{"xml:space": "preserve"})
        ET.SubElement(d, "value").text = e.target or e.source
        if e.comment: ET.SubElement(d, "comment").text = e.comment
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_strings(entries: list[Entry], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(f'"{_escape_strings(e.key)}" = '
                    f'"{_escape_strings(e.target or e.source)}";\n')


def write_json(entries: list[Entry], path: Path) -> None:
    obj: dict = {}
    for e in entries:
        node = obj
        parts = e.key.split(".") if e.key else ["__"]
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = e.target or e.source
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_yaml(entries: list[Entry], path: Path) -> None:
    import yaml
    obj: dict = {}
    for e in entries:
        node = obj
        parts = e.key.split(".") if e.key else ["__"]
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = e.target or e.source
    path.write_text(yaml.safe_dump(obj, allow_unicode=True), encoding="utf-8")


def write_csv(entries: list[Entry], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "source", "target", "comment"])
        for e in entries:
            w.writerow([e.key, e.source, e.target, e.comment])


READERS = {
    ".po": read_po, ".pot": read_po, ".mo": read_mo,
    ".xliff": read_xliff, ".xlf": read_xliff,
    ".tmx": read_tmx, ".resx": read_resx,
    ".strings": read_strings, ".json": read_json,
    ".yaml": read_yaml, ".yml": read_yaml, ".csv": read_csv,
}
WRITERS = {
    "po": write_po, "pot": write_po, "mo": write_mo,
    "xliff": write_xliff, "xlf": write_xliff,
    "tmx": write_tmx, "resx": write_resx,
    "strings": write_strings, "json": write_json,
    "yaml": write_yaml, "yml": write_yaml, "csv": write_csv,
}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Localization file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in WRITERS:
        return fail("bad_format", f"Unsupported target '{target}'. Choose: {sorted(WRITERS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        reader = READERS.get(ext)
        if not reader:
            return fail("bad_format", f"Unsupported source ext '{ext}'.")
        try:
            entries = reader(src)
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + target)
        try:
            WRITERS[target](entries, out_path)
        except Exception as ex:
            return fail("write_failed", f"{src.name}: {ex}")

        emit("locale_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, entry_count=len(entries))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="i18nkit-sidecar",
                                description="Localization format converter.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert PO/MO/XLIFF/TMX/RESX/.strings/JSON/YAML/CSV.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help=f"Target: {sorted(WRITERS)}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

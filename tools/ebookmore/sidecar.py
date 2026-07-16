"""Niche / legacy ebook format sidecar (extends `ebookconvert`).

For mainstream EPUB / MOBI / PDF / AZW3 we already use Calibre. This
sidecar covers the long-tail formats Calibre doesn't fully handle:

  * LRF / LRX  — Sony Reader (legacy)
  * TPZ        — Topaz Kindle (DRM-free)
  * PalmDoc    — .pdb / .prc Palm OS / older Kindle
  * iSilo      — .pdb / .isl
  * DAISY      — .daisy / .opf accessibility format
  * .fb2       — FictionBook 2 (Russian / Slavic ecosystem)
  * .pdb header probe — distinguishes PalmDoc / iSilo / Mobi6 from raw .pdb

Operations:
  fb2-to-html       FictionBook 2 -> single HTML.
  fb2-to-text       FictionBook 2 -> plain text.
  pdb-info          PalmDoc / iSilo / Mobi PDB header probe -> JSON.
  palmdoc-to-text   PalmDoc DOC pdb -> plain text.
  legacy-via-calibre Calibre conversion path with ebook-meta+ebook-convert
                     for LRF, TPZ, etc. (calibre installed = handles all).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── FictionBook 2 (.fb2) ───────────────────────────────────────────────

_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _fb2_text(elem: ET.Element) -> str:
    out: list[str] = []
    if elem.text: out.append(elem.text)
    for child in elem:
        tag = _strip_ns(child.tag)
        if tag in ("p", "subtitle", "v"):
            out.append("\n" + (_fb2_text(child) or "") + "\n")
        elif tag in ("title", "epigraph"):
            out.append("\n\n" + (_fb2_text(child) or "") + "\n\n")
        elif tag in ("emphasis", "strong"):
            out.append((_fb2_text(child) or ""))
        elif tag == "empty-line":
            out.append("\n")
        else:
            out.append(_fb2_text(child) or "")
        if child.tail: out.append(child.tail)
    return "".join(out)


def _fb2_html(elem: ET.Element) -> str:
    parts: list[str] = []
    if elem.text:
        parts.append(_html_escape(elem.text))
    for child in elem:
        tag = _strip_ns(child.tag)
        if tag == "p":
            parts.append("<p>" + _fb2_html(child) + "</p>")
        elif tag == "section":
            parts.append("<section>" + _fb2_html(child) + "</section>")
        elif tag == "title":
            parts.append("<h2>" + _fb2_html(child) + "</h2>")
        elif tag == "subtitle":
            parts.append("<h3>" + _fb2_html(child) + "</h3>")
        elif tag == "emphasis":
            parts.append("<em>" + _fb2_html(child) + "</em>")
        elif tag == "strong":
            parts.append("<strong>" + _fb2_html(child) + "</strong>")
        elif tag == "empty-line":
            parts.append("<br/>")
        else:
            parts.append(_fb2_html(child))
        if child.tail: parts.append(_html_escape(child.tail))
    return "".join(parts)


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def op_fb2_to_html(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"FB2 file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            body_elem = None
            for c in root:
                if _strip_ns(c.tag) == "body":
                    body_elem = c; break
            if body_elem is None:
                return fail("parse_failed",
                            f"{src.name}: <body> not found in FB2.")
            html_body = _fb2_html(body_elem)
            title = ""
            for elem in root.iter():
                if _strip_ns(elem.tag) == "book-title":
                    title = elem.text or ""; break
            html = (f"<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                    f"<title>{_html_escape(title)}</title></head><body>"
                    f"<h1>{_html_escape(title)}</h1>{html_body}</body></html>")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".html")
        out_path.write_text(html, encoding="utf-8")
        emit("ebook_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="html", source="fb2")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_fb2_to_text(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"FB2 file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            body_elem = None
            for c in tree.getroot():
                if _strip_ns(c.tag) == "body":
                    body_elem = c; break
            text = _fb2_text(body_elem) if body_elem is not None else ""
            text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".txt")
        out_path.write_text(text, encoding="utf-8")
        emit("ebook_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="text", source="fb2")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── PDB / PalmDoc ──────────────────────────────────────────────────────

def _pdb_header(data: bytes) -> dict:
    if len(data) < 78:
        raise ValueError("Truncated PDB header.")
    name = data[0:32].rstrip(b"\x00").decode("latin-1", errors="replace")
    file_attr, version = struct.unpack(">HH", data[32:36])
    create, modify, backup = struct.unpack(">III", data[36:48])
    mod_num, app_info, sort_info = struct.unpack(">III", data[48:60])
    db_type = data[60:64].decode("latin-1", errors="replace")
    creator = data[64:68].decode("latin-1", errors="replace")
    next_record_id = struct.unpack(">I", data[68:72])[0]
    record_count = struct.unpack(">H", data[76:78])[0]
    return {
        "name": name, "version": version, "type": db_type,
        "creator": creator, "record_count": record_count,
        "size_bytes": len(data),
    }


def op_pdb_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"PDB file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            info = _pdb_header(src.read_bytes())
            info["file"] = str(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("ebook_extra",
             input=str(src), output="",
             size_bytes=0, format="json", source="pdb",
             type=info["type"], creator=info["creator"])
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "pdb-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def _pdb_records(data: bytes) -> list[bytes]:
    rcount = struct.unpack(">H", data[76:78])[0]
    offsets: list[int] = []
    for i in range(rcount):
        ofs = struct.unpack(">I", data[78 + i * 8:82 + i * 8])[0]
        offsets.append(ofs)
    offsets.append(len(data))
    return [data[offsets[i]:offsets[i + 1]] for i in range(rcount)]


def _palmdoc_decompress(buf: bytes) -> bytes:
    """LZ77-style PalmDoc compression."""
    out = bytearray()
    i = 0
    while i < len(buf):
        b = buf[i]; i += 1
        if 0x09 <= b <= 0x7F:
            out.append(b)
        elif b <= 0x08:
            out += buf[i:i + b]; i += b
        elif b >= 0xC0:
            out.append(0x20); out.append(b ^ 0x80)
        else:
            if i >= len(buf): break
            cmd = (b << 8) | buf[i]; i += 1
            distance = (cmd >> 3) & 0x7FF
            length = (cmd & 7) + 3
            start = len(out) - distance
            for k in range(length):
                if 0 <= start + k < len(out):
                    out.append(out[start + k])
    return bytes(out)


def op_palmdoc_to_text(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"PDB file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = src.read_bytes()
            db_type = data[60:64]
            if db_type not in (b"TEXt", b"REAd"):
                return fail("wrong_type",
                            f"{src.name}: not PalmDoc TEXt/REAd "
                            f"(got {db_type.decode('latin-1', 'replace')}).")
            records = _pdb_records(data)
            if not records: raise ValueError("No records.")
            header0 = records[0]
            compression = struct.unpack(">H", header0[0:2])[0]
            text_chunks: list[bytes] = []
            for rec in records[1:]:
                if compression == 2:
                    text_chunks.append(_palmdoc_decompress(rec))
                elif compression == 17480:  # 'DH' high-compression — skip
                    text_chunks.append(rec)
                else:
                    text_chunks.append(rec)
            full = b"".join(text_chunks).decode("latin-1", errors="replace")
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".txt")
        out_path.write_text(full, encoding="utf-8")
        emit("ebook_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="text", source="palmdoc")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Calibre fallback for legacy LRF/TPZ/etc. ───────────────────────────

def op_legacy_via_calibre(args: argparse.Namespace) -> int:
    cli = shutil.which("ebook-convert") or shutil.which("ebook-convert.exe")
    if not cli: return fail("missing_dep", "ebook-convert (Calibre) not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"eBook file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.target_format.lower()

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + fmt)
        proc = subprocess.run([cli, str(src), str(out_path)],
                               capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: ebook-convert exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        emit("ebook_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=fmt, source="calibre")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ebookmore-sidecar",
                                description="Legacy / niche ebook format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("fb2-to-html",     "FictionBook 2 (.fb2) -> HTML"),
        ("fb2-to-text",     "FictionBook 2 -> plain text"),
        ("pdb-info",        "PalmDoc / iSilo / Mobi .pdb header probe"),
        ("palmdoc-to-text", "PalmDoc TEXt .pdb -> plain text"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    cv = sub.add_parser("legacy-via-calibre",
                        help="Calibre fallback for LRF / TPZ / PRC / etc.")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--to", required=True, dest="target_format",
                    help="Target ebook format: epub / mobi / pdf / txt / azw3 / lrf")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "fb2-to-html":         return op_fb2_to_html(args)
        if args.op == "fb2-to-text":         return op_fb2_to_text(args)
        if args.op == "pdb-info":            return op_pdb_info(args)
        if args.op == "palmdoc-to-text":     return op_palmdoc_to_text(args)
        if args.op == "legacy-via-calibre":  return op_legacy_via_calibre(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

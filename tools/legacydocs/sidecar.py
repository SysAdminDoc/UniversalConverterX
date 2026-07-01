"""Legacy word-processor sidecar (extends `legacyoffice`).

Specifically targets DOS / early-Windows word processors that LibreOffice
doesn't reliably handle:

  * WordStar (.ws / .wsd)        — DOS word processor
  * Microsoft Write (.wri)       — Windows 3.x bundled word processor
  * Lotus Word Pro (.lwp / .lap) — IBM Lotus suite
  * ChiWriter (.chi / .cht)      — scientific DOS word processor
  * AbleWord / TextMaker classic (.tmd)

Operations:
  ws-to-text     WordStar -> plain text (strip 8th-bit attributes).
  wri-to-text    MS Write -> plain text (extract OLE document body).
  lwp-to-text    Lotus Word Pro -> plain text (best-effort string extract).
  detect         Probe-only: identify which legacy word processor.

These formats use proprietary control-byte encodings; we extract the
readable text payload deterministically without external deps.
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
import struct
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── WordStar ───────────────────────────────────────────────────────────

def _decode_wordstar(data: bytes) -> str:
    """WordStar uses 8-bit characters with the high bit indicating end-of-word
    or special markers. Drop control bytes (< 0x20 except CR/LF/TAB/FF), strip
    the 8th bit, and convert to readable text."""
    out: list[str] = []
    for b in data:
        masked = b & 0x7F
        if masked == 0x0D: out.append("\n")
        elif masked == 0x0A: out.append("\n")
        elif masked == 0x09: out.append("\t")
        elif masked == 0x0C: out.append("\n\f\n")  # form feed -> page break
        elif masked < 0x20: continue              # other control bytes drop
        elif masked == 0x7F: continue             # delete
        else:
            out.append(chr(masked))
    text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def op_ws_to_text(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"WordStar file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = _decode_wordstar(src.read_bytes())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".txt")
        out_path.write_text(text, encoding="utf-8")
        emit("legacy_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="text", source="wordstar")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── MS Write (.wri) ────────────────────────────────────────────────────

def _decode_wri(data: bytes) -> str:
    """MS Write .wri: OLE Compound Document or simpler structured layout
    with magic 0xBE 0x31 / 0xBE 0x32 at offset 0. Find the longest run of
    printable ASCII / latin-1 in the document body."""
    if len(data) < 96 or data[0:2] not in (b"\x31\xBE", b"\x32\xBE"):
        # Some Write files use 0xBE 0x31 byte order
        if data[0:2] not in (b"\xBE\x31", b"\xBE\x32"):
            raise ValueError("Not MS Write (magic mismatch).")
    # Body offset usually starts after the 256-byte header.
    body = data[256:] if len(data) > 256 else data
    chars: list[str] = []
    for b in body:
        if b in (0x09, 0x0A, 0x0D):
            chars.append(chr(b))
        elif 0x20 <= b <= 0x7E:
            chars.append(chr(b))
        elif 0xA0 <= b <= 0xFF:
            chars.append(chr(b))
        else:
            if chars and chars[-1] != "\n": chars.append(" ")
    text = "".join(chars)
    text = re.sub(r" {3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def op_wri_to_text(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MS Write file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = _decode_wri(src.read_bytes())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".txt")
        out_path.write_text(text, encoding="utf-8")
        emit("legacy_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="text", source="ms-write")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Lotus Word Pro (.lwp) ──────────────────────────────────────────────

_PRINTABLE_RE = re.compile(rb"[\x20-\x7E\xA0-\xFF\t\n\r]{6,}")


def _decode_lwp(data: bytes) -> str:
    """Last-resort string extraction: scan for printable runs of length >= 6."""
    runs = _PRINTABLE_RE.findall(data)
    text = "\n".join(r.decode("latin-1", errors="replace") for r in runs)
    return text + "\n"


def op_lwp_to_text(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Lotus Word Pro file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = _decode_lwp(src.read_bytes())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".txt")
        out_path.write_text(text, encoding="utf-8")
        emit("legacy_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="text", source="lotus-wordpro")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Detect ─────────────────────────────────────────────────────────────

def _detect(data: bytes) -> str:
    if data[0:2] in (b"\xBE\x31", b"\xBE\x32", b"\x31\xBE", b"\x32\xBE"):
        return "ms-write"
    if data[0:8] == b"WordPro ":
        return "lotus-wordpro"
    # WordStar heuristic: count high-bit set bytes among letter codes
    if len(data) > 100:
        sample = data[:1024]
        high_bit_letters = sum(1 for b in sample
                                if 0xC0 <= b <= 0xFF or
                                (0x80 <= b <= 0xFF and (b & 0x7F) >= 0x40))
        if high_bit_letters > len(sample) * 0.05:
            return "wordstar"
    if data[0:8] == b"\x7B\x5C\x72\x74\x66\x31":  # {\rtf1
        return "rtf"
    return "unknown"


def op_detect(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    for src in inputs:
        try:
            data = src.read_bytes()
            detections.append({"file": str(src), "format": _detect(data),
                               "size_bytes": len(data)})
        except Exception as ex:
            detections.append({"file": str(src), "error": str(ex)})
    out_path = out_dir / "legacy-detect.json"
    out_path.write_text(json.dumps(detections, indent=2), encoding="utf-8")
    for d in detections:
        emit("legacy_doc",
             input=d["file"], output="",
             size_bytes=0, format="detect",
             source=d.get("format", "unknown"))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(detections))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="legacydocs-sidecar",
                                description="Legacy word-processor format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("ws-to-text",   "WordStar -> plain text"),
        ("wri-to-text",  "Microsoft Write -> plain text"),
        ("lwp-to-text",  "Lotus Word Pro -> plain text (string scrape)"),
        ("detect",       "Probe-only: identify legacy WP format"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "ws-to-text":  return op_ws_to_text(args)
        if args.op == "wri-to-text": return op_wri_to_text(args)
        if args.op == "lwp-to-text": return op_lwp_to_text(args)
        if args.op == "detect":      return op_detect(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

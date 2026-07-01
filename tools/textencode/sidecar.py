"""Text-encoding / line-ending conversion sidecar.

Operations:
  recode    Re-encode text files between charsets (utf-8, utf-16, latin-1,
            cp1252, shift_jis, gb18030, big5, koi8-r, iso-8859-x, ...).
  newline   Normalize line endings: lf | crlf | cr (Mac classic).
  bom       Add or remove a UTF-8 / UTF-16 BOM.
  detect    Use chardet to guess the source encoding.

Pure stdlib + chardet; no native deps.
"""
from __future__ import annotations

import argparse
import codecs
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _detect(raw: bytes) -> str:
    try:
        import chardet
        guess = chardet.detect(raw)
        return guess.get("encoding") or "utf-8"
    except ImportError:
        # Fall back to a couple of obvious sniffs.
        if raw.startswith(codecs.BOM_UTF8): return "utf-8-sig"
        if raw.startswith(codecs.BOM_UTF16_LE): return "utf-16-le"
        if raw.startswith(codecs.BOM_UTF16_BE): return "utf-16-be"
        return "utf-8"


def op_recode(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Text file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="recode", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            raw = src.read_bytes()
            src_enc = args.from_encoding or _detect(raw)
            text = raw.decode(src_enc, errors=args.errors)
            out_bytes = text.encode(args.to_encoding, errors=args.errors)
            if args.bom == "add" and args.to_encoding.lower().startswith("utf-8"):
                if not out_bytes.startswith(codecs.BOM_UTF8):
                    out_bytes = codecs.BOM_UTF8 + out_bytes
            elif args.bom == "strip" and out_bytes.startswith(codecs.BOM_UTF8):
                out_bytes = out_bytes[len(codecs.BOM_UTF8):]
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("recode_failed", f"{src.name}: {ex}")

        out_path = out_dir / src.name
        out_path.write_bytes(out_bytes)
        emit("text_encode",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             from_encoding=src_enc, to_encoding=args.to_encoding,
             bom=args.bom)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_newline(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Text file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sep = {"lf": "\n", "crlf": "\r\n", "cr": "\r"}.get(args.style)
    if sep is None:
        return fail("bad_style", "Use --style lf | crlf | cr.")

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        out_bytes = normalized.replace("\n", sep).encode("utf-8")
        out_path = out_dir / src.name
        out_path.write_bytes(out_bytes)
        emit("text_encode",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             newline=args.style)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_detect(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")
    try:
        import chardet
    except ImportError as ex:
        return fail("missing_chardet", f"chardet not installed: {ex}")
    with src.open("rb") as f:
        raw = f.read(min(src.stat().st_size, 1_048_576))
    g = chardet.detect(raw)
    emit("text_encode_info",
         path=str(src), encoding=g.get("encoding"),
         confidence=float(g.get("confidence") or 0.0),
         language=g.get("language"))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="textencode-sidecar",
                                description="Text encoding / line ending / BOM conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    r = sub.add_parser("recode", help="Convert between charsets.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--to-encoding", required=True, dest="to_encoding",
                   help="Target charset (utf-8, utf-16, latin-1, cp1252, "
                        "shift_jis, gb18030, big5, koi8-r, iso-8859-1...).")
    r.add_argument("--from-encoding", default=None, dest="from_encoding",
                   help="Source charset (auto-detect if omitted).")
    r.add_argument("--errors", default="strict",
                   choices=["strict", "replace", "ignore",
                            "xmlcharrefreplace", "backslashreplace"])
    r.add_argument("--bom", default="keep",
                   choices=["keep", "add", "strip"],
                   help="UTF-8 BOM handling.")

    n = sub.add_parser("newline", help="Normalize line endings.")
    n.add_argument("--input", nargs="+", required=True)
    n.add_argument("--output-dir", required=True, dest="output_dir")
    n.add_argument("--style", required=True, choices=["lf", "crlf", "cr"])

    d = sub.add_parser("detect", help="Guess source encoding.")
    d.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "recode":  return op_recode(args)
        if args.op == "newline": return op_newline(args)
        if args.op == "detect":  return op_detect(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

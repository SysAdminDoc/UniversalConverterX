"""Microcontroller binary-image sidecar.

Convert between flash-image record formats used in embedded development:

  * Intel HEX        (.hex, .ihex)
  * Motorola SREC    (.srec, .s19, .s28, .s37)
  * TI-TXT           (.txt for MSP430 / TI families)
  * Raw binary       (.bin, .raw)

Backed by `bincopy` (BSD-3) which speaks all four formats natively.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_FORMAT_MAP = {
    "hex": "ihex", "ihex": "ihex", "ihx": "ihex",
    "srec": "srec", "s19": "srec", "s28": "srec", "s37": "srec", "mot": "srec",
    "tixt": "ti-txt", "ti-txt": "ti-txt", "txt": "ti-txt",
    "bin": "binary", "raw": "binary", "img": "binary",
}


def _read(path: Path):
    import bincopy
    bf = bincopy.BinFile()
    ext = path.suffix.lower().lstrip(".")
    fmt = _FORMAT_MAP.get(ext, "ihex")
    if fmt == "ihex":     bf.add_ihex_file(str(path))
    elif fmt == "srec":   bf.add_srec_file(str(path))
    elif fmt == "ti-txt": bf.add_ti_txt_file(str(path))
    elif fmt == "binary":
        bf.add_binary(path.read_bytes(), address=0)
    return bf


def _write(bf, path: Path) -> None:
    ext = path.suffix.lower().lstrip(".")
    fmt = _FORMAT_MAP.get(ext, ext)
    if fmt == "ihex":
        path.write_text(bf.as_ihex(), encoding="ascii")
    elif fmt == "srec":
        path.write_text(bf.as_srec(), encoding="ascii")
    elif fmt == "ti-txt":
        path.write_text(bf.as_ti_txt(), encoding="ascii")
    elif fmt == "binary":
        path.write_bytes(bf.as_binary())
    else:
        raise ValueError(f"Unsupported output ext: {ext}")


def op_convert(args: argparse.Namespace) -> int:
    try:
        import bincopy  # noqa: F401
    except ImportError as ex:
        return fail("missing_bincopy",
                    f"bincopy not installed: {ex}. `pip install bincopy`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="hex", eta_seconds=None)
    for i, src in enumerate(inputs):
        try:
            bf = _read(src)
            out_path = out_dir / (src.stem + target_ext)
            _write(bf, out_path)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("hex_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."),
             total_bytes=int(getattr(bf, "total_bytes", 0) or 0))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    try:
        import bincopy  # noqa: F401
    except ImportError as ex:
        return fail("missing_bincopy", str(ex))
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")
    bf = _read(src)
    segments = [{"address": int(seg[0]), "length": int(len(seg[1]))}
                for seg in bf.segments] if hasattr(bf, "segments") else []
    emit("hex_image_info",
         path=str(src),
         total_bytes=int(getattr(bf, "total_bytes", 0) or 0),
         minimum_address=int(getattr(bf, "minimum_address", 0) or 0),
         maximum_address=int(getattr(bf, "maximum_address", 0) or 0),
         segments=segments[:64])
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hexkit-sidecar",
                                description="Microcontroller binary image conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert HEX / SREC / TI-TXT / binary.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="hex | srec | s19 | s28 | s37 | tixt | bin")
    i = sub.add_parser("info", help="Probe segment layout / address range.")
    i.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "info":    return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

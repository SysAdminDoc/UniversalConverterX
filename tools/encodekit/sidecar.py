"""Binary encoding sidecar.

Encode any file as Base64 / Base32 / Base85 / Hex (and decode back).

Operations:
  encode    Read raw bytes -> emit text encoding to .b64 / .b32 / .b85 / .hex.
  decode    Read text encoding -> emit raw bytes.
  inline    Like encode but wraps as a data URL (data:<mime>;base64,...).
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import mimetypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


ENCODERS = {
    "base64": (base64.b64encode, base64.b64decode, ".b64"),
    "base32": (base64.b32encode, base64.b32decode, ".b32"),
    "base85": (base64.b85encode, base64.b85decode, ".b85"),
    "hex":    (lambda b: binascii.hexlify(b),
               lambda b: binascii.unhexlify(b.strip().replace(b" ", b"")),
               ".hex"),
}


def op_encode(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    enc = args.encoding.lower()
    if enc not in ENCODERS:
        return fail("bad_encoding", f"Choose: {sorted(ENCODERS)}")
    encode_fn, _, ext = ENCODERS[enc]

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="encode", eta_seconds=None)
    for i, src in enumerate(inputs):
        try:
            data = src.read_bytes()
            encoded = encode_fn(data)
            if args.wrap and enc != "hex":
                # Wrap at fixed line width (76 = MIME default).
                wrapped = b"\n".join(encoded[i:i + args.wrap]
                                     for i in range(0, len(encoded), args.wrap))
                encoded = wrapped + b"\n"
        except Exception as ex:
            return fail("encode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.name + ext)
        out_path.write_bytes(encoded)
        emit("encoded_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             encoding=enc)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_decode(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    enc = args.encoding.lower()
    if enc not in ENCODERS:
        return fail("bad_encoding", f"Choose: {sorted(ENCODERS)}")
    _, decode_fn, _ = ENCODERS[enc]

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = src.read_bytes()
            # Strip whitespace introduced by line wrapping.
            if enc != "hex":
                data = b"".join(data.split())
            decoded = decode_fn(data)
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        # Strip the encoding suffix to get the original name.
        stem = src.stem if src.suffix.lower() in {v[2] for v in ENCODERS.values()} else src.name
        out_path = out_dir / stem
        out_path.write_bytes(decoded)
        emit("encoded_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             encoding=enc, direction="decode")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_inline(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        mime, _ = mimetypes.guess_type(str(src))
        if not mime: mime = "application/octet-stream"
        b64 = base64.b64encode(src.read_bytes()).decode("ascii")
        url = f"data:{mime};base64,{b64}"
        out_path = out_dir / (src.name + ".dataurl.txt")
        out_path.write_text(url, encoding="ascii")
        emit("encoded_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             encoding="data-url", mime=mime)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="encodekit-sidecar",
                                description="Base64 / Base32 / Base85 / Hex / data-URL.")
    sub = p.add_subparsers(dest="op", required=True)

    e = sub.add_parser("encode", help="Encode binary file(s) to text.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    e.add_argument("--encoding", default="base64",
                   choices=["base64", "base32", "base85", "hex"])
    e.add_argument("--wrap", type=int, default=76,
                   help="Line wrap width (0 = no wrap; ignored for hex).")

    d = sub.add_parser("decode", help="Decode text-encoded file(s).")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")
    d.add_argument("--encoding", default="base64",
                   choices=["base64", "base32", "base85", "hex"])

    i = sub.add_parser("inline", help="Encode as data:<mime>;base64,... URL.")
    i.add_argument("--input", nargs="+", required=True)
    i.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "encode": return op_encode(args)
        if args.op == "decode": return op_decode(args)
        if args.op == "inline": return op_inline(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

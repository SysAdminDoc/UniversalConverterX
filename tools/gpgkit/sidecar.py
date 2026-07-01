"""OpenPGP / GnuPG key + message armoring sidecar.

Convert OpenPGP material between ASCII-armored and binary forms, and
probe key metadata.

Operations:
  armor      Binary .gpg / .pgp file -> ASCII-armored (.asc).
  dearmor    ASCII-armored .asc -> binary.
  key-info   Probe a public-key file: user IDs, fingerprints, expiry.

Backed by `python-gnupg` when GPG is on PATH, with a pure-stdlib
ASCII-armor codec fallback for armor / dearmor that doesn't require GPG
to be installed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import re
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


# CRC-24 used in OpenPGP ASCII armor framing.
def _crc24(data: bytes) -> int:
    crc = 0xB704CE
    for b in data:
        crc ^= b << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def _detect_armor_kind(raw: bytes) -> str:
    if b"PRIVATE KEY" in raw[:200]: return "PGP PRIVATE KEY BLOCK"
    if b"PUBLIC KEY" in raw[:200]:  return "PGP PUBLIC KEY BLOCK"
    if b"SIGNATURE" in raw[:200]:   return "PGP SIGNATURE"
    return "PGP MESSAGE"


def _armor(raw: bytes, header: str) -> bytes:
    crc = _crc24(raw)
    crc_bytes = crc.to_bytes(3, "big")
    crc_b64 = base64.b64encode(crc_bytes).decode("ascii")
    body = base64.b64encode(raw).decode("ascii")
    wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return (
        f"-----BEGIN {header}-----\n\n"
        f"{wrapped}\n={crc_b64}\n"
        f"-----END {header}-----\n"
    ).encode("ascii")


_ARMOR_RE = re.compile(
    rb"-----BEGIN ([A-Z0-9 ]+?)-----\s*\n(?:.*?\n)?\n([A-Za-z0-9+/=\n]+?)=([A-Za-z0-9+/=]+)\n-----END",
    re.DOTALL,
)


def _dearmor(text: bytes) -> tuple[bytes, str]:
    m = _ARMOR_RE.search(text)
    if not m: raise ValueError("Not an OpenPGP ASCII-armored block.")
    header = m.group(1).decode("ascii")
    body = m.group(2).decode("ascii").replace("\n", "")
    return base64.b64decode(body), header


def op_armor(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        raw = src.read_bytes()
        header = args.kind or _detect_armor_kind(raw)
        out_path = out_dir / (src.stem + ".asc")
        out_path.write_bytes(_armor(raw, header))
        emit("pgp_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="armor", header=header)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_dearmor(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            raw, header = _dearmor(src.read_bytes())
        except Exception as ex:
            return fail("dearmor_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".gpg")
        out_path.write_bytes(raw)
        emit("pgp_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="binary", header=header)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_key_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Key not found: {src}")
    gpg = shutil.which("gpg") or shutil.which("gpg.exe")
    if not gpg:
        return fail("missing_gpg",
                    "gpg CLI not found. Install GnuPG (https://gnupg.org).")

    cmd = [gpg, "--with-colons", "--show-keys", str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("gpg_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")

    fingerprints: list[str] = []
    uids: list[str] = []
    for line in proc.stdout.splitlines():
        f = line.split(":")
        if not f: continue
        if f[0] == "fpr" and len(f) > 9: fingerprints.append(f[9])
        if f[0] == "uid" and len(f) > 9: uids.append(f[9])

    emit("pgp_key",
         path=str(src),
         size_bytes=src.stat().st_size,
         fingerprints=fingerprints,
         user_ids=uids)
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gpgkit-sidecar",
                                description="OpenPGP / GnuPG armoring + key probing.")
    sub = p.add_subparsers(dest="op", required=True)
    a = sub.add_parser("armor", help="Binary -> ASCII armor (.asc).")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")
    a.add_argument("--kind", default=None,
                   help="Override block type (default: auto-detect).")

    d = sub.add_parser("dearmor", help="ASCII armor -> binary.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")

    k = sub.add_parser("key-info", help="Probe key metadata via gpg.")
    k.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "armor":    return op_armor(args)
        if args.op == "dearmor":  return op_dearmor(args)
        if args.op == "key-info": return op_key_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""SSH key conversion sidecar.

Convert SSH key material between every common encoding:

  * OpenSSH legacy (.pub / id_rsa)
  * OpenSSH new format (begins `-----BEGIN OPENSSH PRIVATE KEY-----`)
  * PKCS#8 PEM (compatible with most TLS / Java / .NET stacks)
  * PuTTY .ppk (versions 2 and 3)
  * RFC 4716 (the "SSH Public Key File Format" with comment headers)

Backed by `cryptography` (BSD-3) + `bcrypt` (Apache-2.0) + manual .ppk
parser. We never write encrypted private keys silently; users opt in via
`--password`.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _resolve_pw(arg: str | None) -> bytes:
    if arg is not None: return arg.encode("utf-8")
    if (envv := os.environ.get("UCX_SSH_PASSWORD")):
        return envv.encode("utf-8")
    return b""


def _load_private(path: Path, pw: bytes):
    """Auto-detect OpenSSH / PEM / DER private key."""
    from cryptography.hazmat.primitives.serialization import (
        load_ssh_private_key, load_pem_private_key, load_der_private_key,
    )
    raw = path.read_bytes()
    if b"OPENSSH PRIVATE KEY" in raw:
        return load_ssh_private_key(raw, password=pw or None)
    if b"-----BEGIN" in raw:
        return load_pem_private_key(raw, password=pw or None)
    return load_der_private_key(raw, password=pw or None)


def _load_public_ssh(path: Path):
    from cryptography.hazmat.primitives.serialization import load_ssh_public_key
    raw = path.read_bytes()
    return load_ssh_public_key(raw)


# ----- PuTTY .ppk handling --------------------------------------------------

def _parse_ppk(data: bytes):
    """Bare-minimum PuTTY .ppk v2 / v3 parser. Returns dict with raw fields."""
    text = data.decode("utf-8", errors="replace")
    fields: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line:
            i += 1; continue
        k, v = line.split(":", 1)
        k = k.strip(); v = v.strip()
        if k.startswith("Public-Lines"):
            n = int(v); i += 1
            block = "".join(lines[i:i + n])
            fields["public_b64"] = block
            i += n
        elif k.startswith("Private-Lines"):
            n = int(v); i += 1
            block = "".join(lines[i:i + n])
            fields["private_b64"] = block
            i += n
        else:
            fields[k.lower()] = v
            i += 1
    return fields


def op_to_pem(args: argparse.Namespace) -> int:
    """Convert OpenSSH / .ppk private keys -> PKCS#8 PEM."""
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, NoEncryption, BestAvailableEncryption,
        )
    except ImportError as ex:
        return fail("missing_cryptography", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Key(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    pw = _resolve_pw(args.password)
    out_pw = _resolve_pw(args.out_password)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            if src.suffix.lower() == ".ppk":
                # Use putty-keygen if available; otherwise emit a clear error.
                import shutil as _shutil
                pkg = _shutil.which("puttygen") or _shutil.which("puttygen.exe")
                if not pkg:
                    return fail("missing_puttygen",
                                "PuTTY's `puttygen` not found. Install PuTTY for .ppk -> PEM.")
                out_path = out_dir / (src.stem + ".pem")
                cmd = [pkg, str(src), "-O", "private-openssh-new", "-o", str(out_path)]
                import subprocess
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if proc.returncode != 0:
                    return fail("puttygen_failed",
                                f"{src.name}: rc={proc.returncode}: "
                                f"{(proc.stderr or proc.stdout).strip()[:240]}")
            else:
                key = _load_private(src, pw)
                enc = BestAvailableEncryption(out_pw) if out_pw else NoEncryption()
                pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, enc)
                out_path = out_dir / (src.stem + ".pem")
                out_path.write_bytes(pem)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("ssh_key",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="pem-pkcs8")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_openssh(args: argparse.Namespace) -> int:
    """Convert PEM / .ppk private keys -> OpenSSH-format private key."""
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, NoEncryption, BestAvailableEncryption,
        )
    except ImportError as ex:
        return fail("missing_cryptography", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Key(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pw = _resolve_pw(args.password)
    out_pw = _resolve_pw(args.out_password)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            if src.suffix.lower() == ".ppk":
                import shutil as _shutil, subprocess
                pkg = _shutil.which("puttygen") or _shutil.which("puttygen.exe")
                if not pkg:
                    return fail("missing_puttygen", "puttygen not found.")
                out_path = out_dir / src.stem
                cmd = [pkg, str(src), "-O", "private-openssh-new", "-o", str(out_path)]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if proc.returncode != 0:
                    return fail("puttygen_failed",
                                f"{src.name}: rc={proc.returncode}")
            else:
                key = _load_private(src, pw)
                enc = BestAvailableEncryption(out_pw) if out_pw else NoEncryption()
                openssh = key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, enc)
                out_path = out_dir / src.stem
                out_path.write_bytes(openssh)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("ssh_key",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="openssh")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_ppk(args: argparse.Namespace) -> int:
    """Convert OpenSSH / PEM private keys -> PuTTY .ppk via puttygen."""
    import shutil as _shutil, subprocess
    pkg = _shutil.which("puttygen") or _shutil.which("puttygen.exe")
    if not pkg:
        return fail("missing_puttygen",
                    "PuTTY's `puttygen` not found. Install PuTTY (puttygen) on PATH.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Key(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".ppk")
        cmd = [pkg, str(src), "-O", "private", "-o", str(out_path),
               "--ppk-version", str(args.ppk_version)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            return fail("puttygen_failed",
                        f"{src.name}: rc={proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()[:240]}")
        emit("ssh_key",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="ppk", ppk_version=int(args.ppk_version))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_pub_to_rfc4716(args: argparse.Namespace) -> int:
    """OpenSSH `id_rsa.pub` -> RFC 4716 public-key format."""
    try:
        from cryptography.hazmat.primitives.serialization import (
            load_ssh_public_key, Encoding, PublicFormat,
        )
    except ImportError as ex:
        return fail("missing_cryptography", str(ex))
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Public key(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            key = load_ssh_public_key(src.read_bytes())
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        # Re-emit OpenSSH first, then wrap in RFC 4716 format.
        openssh = key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode("ascii")
        # Strip "ssh-<algo> " prefix and trailing comment.
        parts = openssh.split(" ", 2)
        b64 = parts[1]
        wrapped = "\n".join(b64[j:j + 70] for j in range(0, len(b64), 70))
        out_text = (
            "---- BEGIN SSH2 PUBLIC KEY ----\n"
            'Comment: "Converted by UCX"\n'
            f"{wrapped}\n"
            "---- END SSH2 PUBLIC KEY ----\n"
        )
        out_path = out_dir / (src.stem + ".rfc4716")
        out_path.write_text(out_text, encoding="ascii")
        emit("ssh_key",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="rfc4716", role="public")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sshkit-sidecar",
                                description="SSH key format conversion (OpenSSH / PEM / PuTTY .ppk / RFC 4716).")
    sub = p.add_subparsers(dest="op", required=True)
    a = sub.add_parser("to-pem", help="Any private key -> PKCS#8 PEM.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")
    a.add_argument("--password", default=None,
                   help="Source key password (or $UCX_SSH_PASSWORD).")
    a.add_argument("--out-password", default=None, dest="out_password",
                   help="Encrypt output with this password.")

    b = sub.add_parser("to-openssh", help="Any private key -> OpenSSH-format key.")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")
    b.add_argument("--password", default=None)
    b.add_argument("--out-password", default=None, dest="out_password")

    c = sub.add_parser("to-ppk", help="Any private key -> PuTTY .ppk (requires puttygen).")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--ppk-version", default="3", choices=["2", "3"], dest="ppk_version")

    d = sub.add_parser("pub-to-rfc4716", help="OpenSSH .pub -> RFC 4716 wrapped key.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-pem":         return op_to_pem(args)
        if args.op == "to-openssh":     return op_to_openssh(args)
        if args.op == "to-ppk":         return op_to_ppk(args)
        if args.op == "pub-to-rfc4716": return op_pub_to_rfc4716(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

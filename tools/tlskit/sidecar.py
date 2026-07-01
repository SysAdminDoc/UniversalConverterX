"""TLS / X.509 certificate + key sidecar.

Convert between every encoding that openssl, browsers, and language
runtimes throw around:

  * PEM (Base64 / RFC 7468)
  * DER (raw binary ASN.1)
  * PKCS#7 (.p7b, .p7c)            certificate bundle
  * PKCS#12 (.p12, .pfx)            cert + key bundle, password-protected
  * PKCS#8 / PKCS#1 / PKCS#3 keys

Operations:
  cert-info      Probe a certificate (subject / issuer / validity / SAN / fingerprints).
  cert-convert   Convert between PEM / DER / PKCS#7.
  bundle-extract Extract certs + key from .p12 / .pfx into PEM files.
  bundle-create  Create a .p12 / .pfx from PEM cert(s) + key.
  key-convert    Convert keys between PEM and DER.
"""
from __future__ import annotations

import argparse
import getpass
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _resolve_pw(arg_pw: str | None, env_var: str = "UCX_PFX_PASSWORD") -> bytes:
    if arg_pw is not None:
        return arg_pw.encode("utf-8")
    if (envv := os.environ.get(env_var)):
        return envv.encode("utf-8")
    return b""


def _load_cert(path: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    raw = path.read_bytes()
    if raw.startswith(b"-----BEGIN"):
        return x509.load_pem_x509_certificate(raw)
    return x509.load_der_x509_certificate(raw)


def op_cert_info(args: argparse.Namespace) -> int:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
    except ImportError as ex:
        return fail("missing_cryptography",
                    f"cryptography not installed: {ex}.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Cert not found: {src}")
    try:
        cert = _load_cert(src)
    except Exception as ex:
        return fail("read_failed", f"{src.name}: {ex}")

    fp_sha256 = cert.fingerprint(hashes.SHA256()).hex(":")
    fp_sha1 = cert.fingerprint(hashes.SHA1()).hex(":")
    sans: list[str] = []
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        sans = [str(g.value) for g in san_ext.value]
    except x509.ExtensionNotFound:
        pass

    emit("tls_cert",
         path=str(src),
         subject=cert.subject.rfc4514_string(),
         issuer=cert.issuer.rfc4514_string(),
         not_before=cert.not_valid_before_utc.isoformat(),
         not_after=cert.not_valid_after_utc.isoformat(),
         serial=str(cert.serial_number),
         signature_algorithm=cert.signature_algorithm_oid._name,
         fingerprint_sha256=fp_sha256,
         fingerprint_sha1=fp_sha1,
         subject_alt_names=sans,
         version=cert.version.name)
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def op_cert_convert(args: argparse.Namespace) -> int:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import pkcs7
    except ImportError as ex:
        return fail("missing_cryptography", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Cert(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower()

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            cert = _load_cert(src)
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")

        if target == "pem":
            data = cert.public_bytes(serialization.Encoding.PEM)
            out_path = out_dir / (src.stem + ".pem")
        elif target == "der":
            data = cert.public_bytes(serialization.Encoding.DER)
            out_path = out_dir / (src.stem + ".der")
        elif target in ("p7b", "pkcs7"):
            data = pkcs7.serialize_certificates([cert],
                                                 serialization.Encoding.PEM)
            out_path = out_dir / (src.stem + ".p7b")
        else:
            return fail("bad_format", "Choose pem | der | p7b.")
        out_path.write_bytes(data)

        emit("tls_cert",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size, format=target)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bundle_extract(args: argparse.Namespace) -> int:
    try:
        from cryptography.hazmat.primitives.serialization import (
            pkcs12, Encoding, PrivateFormat, NoEncryption,
        )
        from cryptography.hazmat.primitives import serialization
    except ImportError as ex:
        return fail("missing_cryptography", str(ex))

    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"PFX not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    pw = _resolve_pw(args.password)
    try:
        key, cert, extras = pkcs12.load_key_and_certificates(src.read_bytes(),
                                                              pw or None)
    except Exception as ex:
        return fail("bundle_failed", f"{src.name}: {ex}")

    if cert is not None:
        cp = out_dir / (src.stem + ".cert.pem")
        cp.write_bytes(cert.public_bytes(Encoding.PEM))
        emit("tls_cert", input=str(src), output=str(cp),
             size_bytes=cp.stat().st_size, format="pem", role="cert")
    if key is not None:
        kp = out_dir / (src.stem + ".key.pem")
        kp.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8,
                                          NoEncryption()))
        emit("tls_cert", input=str(src), output=str(kp),
             size_bytes=kp.stat().st_size, format="pem", role="key")
    for n, extra in enumerate(extras or []):
        ep = out_dir / (src.stem + f".chain{n}.pem")
        ep.write_bytes(extra.public_bytes(Encoding.PEM))
        emit("tls_cert", input=str(src), output=str(ep),
             size_bytes=ep.stat().st_size, format="pem",
             role="chain", index=n)
    emit("complete", output=str(out_dir), size_bytes=0,
         count=int(cert is not None) + int(key is not None) + len(extras or []))
    return 0


def op_bundle_create(args: argparse.Namespace) -> int:
    try:
        from cryptography.hazmat.primitives.serialization import (
            pkcs12, BestAvailableEncryption, NoEncryption,
        )
        from cryptography.hazmat.primitives import serialization
    except ImportError as ex:
        return fail("missing_cryptography", str(ex))

    cert_path = Path(args.cert)
    key_path = Path(args.key)
    if not cert_path.is_file(): return fail("missing_input", f"Cert not found: {cert_path}")
    if not key_path.is_file():  return fail("missing_input", f"Key not found: {key_path}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (cert_path.stem + ".p12")

    cert = _load_cert(cert_path)
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    chain = []
    for cp in args.chain or []:
        chain.append(_load_cert(Path(cp)))

    pw = _resolve_pw(args.password)
    enc = BestAvailableEncryption(pw) if pw else NoEncryption()
    p12 = pkcs12.serialize_key_and_certificates(
        name=(args.friendly_name or cert_path.stem).encode("utf-8"),
        key=key, cert=cert, cas=chain or None, encryption_algorithm=enc)
    out_path.write_bytes(p12)

    emit("tls_cert",
         input=str(cert_path), output=str(out_path),
         size_bytes=out_path.stat().st_size, format="p12",
         encrypted=bool(pw))
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_key_convert(args: argparse.Namespace) -> int:
    try:
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key, load_der_private_key,
            Encoding, PrivateFormat, NoEncryption, BestAvailableEncryption,
        )
    except ImportError as ex:
        return fail("missing_cryptography", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Key(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower()

    total = len(inputs)
    for i, src in enumerate(inputs):
        raw = src.read_bytes()
        try:
            key = (load_pem_private_key(raw, password=None)
                   if raw.startswith(b"-----BEGIN")
                   else load_der_private_key(raw, password=None))
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")

        out_pw = _resolve_pw(args.password)
        enc = BestAvailableEncryption(out_pw) if out_pw else NoEncryption()
        if target == "pem":
            data = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, enc)
            out_path = out_dir / (src.stem + ".pem")
        elif target == "der":
            data = key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, enc)
            out_path = out_dir / (src.stem + ".der")
        else:
            return fail("bad_format", "Choose pem | der.")
        out_path.write_bytes(data)
        emit("tls_cert",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, role="key", encrypted=bool(out_pw))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tlskit-sidecar",
                                description="X.509 / PKCS#7 / PKCS#12 / PEM / DER conversion + probing.")
    sub = p.add_subparsers(dest="op", required=True)

    info = sub.add_parser("cert-info", help="Probe certificate metadata.")
    info.add_argument("--input", required=True)

    cc = sub.add_parser("cert-convert", help="PEM <-> DER <-> PKCS7 (.p7b).")
    cc.add_argument("--input", nargs="+", required=True)
    cc.add_argument("--output-dir", required=True, dest="output_dir")
    cc.add_argument("--format", required=True, choices=["pem", "der", "p7b"])

    be = sub.add_parser("bundle-extract", help="Extract certs + key from .p12 / .pfx.")
    be.add_argument("--input", required=True)
    be.add_argument("--output-dir", required=True, dest="output_dir")
    be.add_argument("--password", default=None,
                    help="PFX password (or set $UCX_PFX_PASSWORD).")

    bc = sub.add_parser("bundle-create", help="Build .p12 / .pfx from PEM cert + key.")
    bc.add_argument("--cert", required=True)
    bc.add_argument("--key", required=True)
    bc.add_argument("--chain", nargs="*", default=None,
                    help="Optional intermediate cert PEM file(s).")
    bc.add_argument("--output-dir", required=True, dest="output_dir")
    bc.add_argument("--password", default=None,
                    help="PFX output password (or $UCX_PFX_PASSWORD).")
    bc.add_argument("--friendly-name", default=None, dest="friendly_name")

    kc = sub.add_parser("key-convert", help="Private key PEM <-> DER.")
    kc.add_argument("--input", nargs="+", required=True)
    kc.add_argument("--output-dir", required=True, dest="output_dir")
    kc.add_argument("--format", required=True, choices=["pem", "der"])
    kc.add_argument("--password", default=None,
                    help="Encrypt output with this password.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "cert-info":      return op_cert_info(args)
        if args.op == "cert-convert":   return op_cert_convert(args)
        if args.op == "bundle-extract": return op_bundle_extract(args)
        if args.op == "bundle-create":  return op_bundle_create(args)
        if args.op == "key-convert":    return op_key_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

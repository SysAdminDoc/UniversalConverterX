"""ASN.1 BER/DER/PEM <-> JSON sidecar.

ASN.1 is the binary encoding scheme that underlies X.509 certificates,
PKCS#7/CMS, LDAP, SNMP, Kerberos, 3GPP, S/MIME, and many other crypto
and telecom standards. We provide a structural decoder (TLV walk) so
users can inspect any DER/BER blob without needing the schema, plus
PEM <-> DER conversion which is purely a base64 + framing change.

Operations:
  ber-to-json   ASN.1 BER/DER -> structural JSON tree.
  pem-to-der    PEM -> DER (strip header/footer, base64-decode).
  der-to-pem    DER -> PEM (base64-wrap + add BEGIN/END framing).

Pure stdlib — no external deps required for structural decoding.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Tag class / type tables for human-readable output ──────────────────

_UNIVERSAL_TAGS = {
    1: "BOOLEAN", 2: "INTEGER", 3: "BIT STRING", 4: "OCTET STRING",
    5: "NULL", 6: "OID", 7: "ObjectDescriptor", 8: "EXTERNAL",
    9: "REAL", 10: "ENUMERATED", 12: "UTF8String", 16: "SEQUENCE",
    17: "SET", 18: "NumericString", 19: "PrintableString",
    20: "T61String", 22: "IA5String", 23: "UTCTime", 24: "GeneralizedTime",
    26: "VisibleString", 27: "GeneralString", 28: "UniversalString",
    30: "BMPString",
}
_CLASSES = {0: "universal", 1: "application", 2: "context", 3: "private"}


def _read_tlv(data: bytes, offset: int) -> tuple[dict, int]:
    """Read one TLV at offset; return (node_dict, new_offset)."""
    if offset >= len(data):
        raise ValueError("Truncated ASN.1 input.")
    first = data[offset]
    cls = (first >> 6) & 0x3
    constructed = bool(first & 0x20)
    tag_num = first & 0x1F
    p = offset + 1
    if tag_num == 0x1F:  # high tag number
        tag_num = 0
        while True:
            if p >= len(data):
                raise ValueError("Truncated tag.")
            b = data[p]; p += 1
            tag_num = (tag_num << 7) | (b & 0x7F)
            if not (b & 0x80): break
    # length
    if p >= len(data):
        raise ValueError("Truncated length.")
    lb = data[p]; p += 1
    if lb < 0x80:
        length = lb
    elif lb == 0x80:
        raise ValueError("Indefinite length not supported.")
    else:
        n = lb & 0x7F
        if p + n > len(data):
            raise ValueError("Truncated long-form length.")
        length = int.from_bytes(data[p:p + n], "big"); p += n
    if p + length > len(data):
        raise ValueError("Content exceeds buffer.")
    value = data[p:p + length]
    end = p + length

    node: dict = {
        "class": _CLASSES[cls],
        "constructed": constructed,
        "tag": tag_num,
        "length": length,
    }
    if cls == 0 and tag_num in _UNIVERSAL_TAGS:
        node["type"] = _UNIVERSAL_TAGS[tag_num]

    if constructed:
        children: list[dict] = []
        sub = 0
        while sub < len(value):
            child, sub = _read_tlv(value, sub)
            children.append(child)
        node["children"] = children
    else:
        # primitive — render value sensibly per type
        if cls == 0 and tag_num == 1:  # BOOLEAN
            node["value"] = bool(value[0]) if value else False
        elif cls == 0 and tag_num == 2:  # INTEGER
            node["value"] = int.from_bytes(value, "big", signed=True)
        elif cls == 0 and tag_num == 6:  # OID
            node["value"] = _decode_oid(value)
        elif cls == 0 and tag_num in (12, 19, 22, 26, 27, 30):
            try:
                node["value"] = value.decode("utf-8", errors="replace")
            except Exception:
                node["value_hex"] = value.hex()
        elif cls == 0 and tag_num in (23, 24):  # UTCTime/GeneralizedTime
            node["value"] = value.decode("ascii", errors="replace")
        else:
            node["value_hex"] = value.hex()
    return node, end


def _decode_oid(data: bytes) -> str:
    if not data: return ""
    parts = [data[0] // 40, data[0] % 40]
    val = 0
    for b in data[1:]:
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            parts.append(val); val = 0
    return ".".join(str(p) for p in parts)


# ── Operations ─────────────────────────────────────────────────────────

def op_ber_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BER/DER file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = src.read_bytes()
            # if PEM, convert first
            if data.startswith(b"-----BEGIN"):
                data = _pem_to_der(data.decode("ascii", errors="replace"))
            tree, end = _read_tlv(data, 0)
            if end != len(data):
                tree.setdefault("notes", []).append(f"trailing {len(data)-end} bytes")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("asn1_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="ber-der")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


_PEM_RE = re.compile(r"-----BEGIN ([^-]+)-----\s*(.*?)\s*-----END \1-----",
                     re.DOTALL)


def _pem_to_der(text: str) -> bytes:
    m = _PEM_RE.search(text)
    if not m: raise ValueError("No PEM block found.")
    return base64.b64decode("".join(m.group(2).split()))


def op_pem_to_der(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"PEM file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = _pem_to_der(src.read_text(encoding="utf-8", errors="replace"))
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".der")
        out_path.write_bytes(data)
        emit("asn1_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="der", source="pem")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_der_to_pem(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DER file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    label = (args.label or "CERTIFICATE").upper()

    total = len(inputs)
    for i, src in enumerate(inputs):
        data = src.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        body = "\n".join(b64[k:k + 64] for k in range(0, len(b64), 64))
        pem = f"-----BEGIN {label}-----\n{body}\n-----END {label}-----\n"
        out_path = out_dir / (src.stem + ".pem")
        out_path.write_text(pem, encoding="ascii")
        emit("asn1_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="pem", source="der", label=label)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="asn1-sidecar",
                                description="ASN.1 BER/DER/PEM converter.")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("ber-to-json", help="ASN.1 BER/DER -> JSON tree.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    b = sub.add_parser("pem-to-der", help="PEM -> DER.")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")

    d = sub.add_parser("der-to-pem", help="DER -> PEM.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")
    d.add_argument("--label", default="CERTIFICATE",
                   help="PEM label (CERTIFICATE / RSA PRIVATE KEY / etc.).")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "ber-to-json": return op_ber_to_json(args)
        if args.op == "pem-to-der":  return op_pem_to_der(args)
        if args.op == "der-to-pem":  return op_der_to_pem(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

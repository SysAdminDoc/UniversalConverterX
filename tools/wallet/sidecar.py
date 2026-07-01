"""Cryptocurrency wallet metadata sidecar.

READ-ONLY. Convert + inspect wallet-related encodings without touching
private-key derivation. We deliberately keep the surface small to avoid
becoming a wallet:

  * BIP39 mnemonic check          Validate a word list + checksum
  * BIP32 ext-key encoding        xprv/xpub <-> JSON metadata (no derivation)
  * Ethereum keystore JSON v3     Decode header (cipher / KDF / addr) only
  * Bitcoin descriptor wallet     Parse human-readable descriptors -> JSON
  * PSBT (Partially Signed BTC Tx) Decode + summarize inputs / outputs

NEVER prints private keys to stdout. NEVER signs anything. NEVER unlocks
keystores. If a user wants those operations, they should use a dedicated
wallet (Electrum, Bitcoin Core, MetaMask, etc.).
"""
from __future__ import annotations

import argparse
import hashlib
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── BIP39 ────────────────────────────────────────────────────────────────

# Standard BIP39 supports 12/15/18/21/24 word phrases.
def op_bip39_check(args: argparse.Namespace) -> int:
    try:
        from mnemonic import Mnemonic
    except ImportError as ex:
        return fail("missing_mnemonic",
                    f"`mnemonic` not installed: {ex}. `pip install mnemonic`.")

    if args.input_file:
        text = Path(args.input_file).read_text(encoding="utf-8")
    else:
        text = " ".join(args.words or [])
    if not text.strip():
        return fail("no_input", "Provide --input-file or --words.")

    m = Mnemonic(args.language)
    is_valid = m.check(text.strip())
    word_count = len(text.split())
    emit("wallet_bip39",
         language=args.language,
         word_count=word_count,
         valid=bool(is_valid),
         checksum_ok=bool(is_valid),
         length_class={
             12: "128-bit", 15: "160-bit", 18: "192-bit",
             21: "224-bit", 24: "256-bit",
         }.get(word_count, f"non-standard ({word_count} words)"))
    emit("complete", output="(stdout)", size_bytes=0, count=1)
    return 0 if is_valid else 1


# ── Ethereum keystore JSON v3 ───────────────────────────────────────────

def op_keystore_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Keystore not found: {src}")
    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
    except Exception as ex:
        return fail("read_failed", f"{src.name}: {ex}")
    crypto = obj.get("crypto") or obj.get("Crypto") or {}
    emit("wallet_keystore",
         path=str(src),
         size_bytes=src.stat().st_size,
         version=int(obj.get("version", 0)),
         id=obj.get("id"),
         address=obj.get("address"),
         cipher=crypto.get("cipher"),
         kdf=crypto.get("kdf"),
         kdf_params=crypto.get("kdfparams"),
         note="Header metadata only -- private key NOT decoded by design.")
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


# ── Bitcoin output descriptor ───────────────────────────────────────────

def op_descriptor(args: argparse.Namespace) -> int:
    """Parse a Bitcoin descriptor like `wpkh([fingerprint/path]xpub.../0/*)`."""
    descriptor = args.descriptor
    parts = {"raw": descriptor}
    if descriptor.startswith(("wpkh(", "pkh(", "tr(", "sh(", "wsh(", "multi(", "sortedmulti(")):
        kind = descriptor.split("(", 1)[0]
        inner = descriptor[len(kind) + 1:].rsplit(")", 1)[0]
        parts["script_type"] = kind
        parts["inner"] = inner
    # Extract origin path [fingerprint/path] if present.
    if "[" in descriptor:
        bracket = descriptor.split("[", 1)[1].split("]", 1)[0]
        parts["fingerprint"] = bracket.split("/", 1)[0]
        parts["derivation"] = "/" + "/".join(bracket.split("/")[1:])
    emit("wallet_descriptor", **parts)
    emit("complete", output="(stdout)", size_bytes=0, count=1)
    return 0


# ── PSBT decode ──────────────────────────────────────────────────────────

def op_psbt_decode(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"PSBT not found: {src}")
    raw = src.read_bytes()
    if raw.startswith(b"-----BEGIN") or raw[:6] == b"cHNidP":  # base64
        try:
            import base64
            raw = base64.b64decode(raw.strip())
        except Exception:
            pass
    if raw[:5] != b"psbt\xff":
        return fail("bad_psbt", f"{src.name}: not a PSBT (magic mismatch).")

    # Walk top-level key/value pairs (very rough probe; full parsing belongs
    # in a wallet tool). We just count input + output sections.
    n = 5  # past magic + separator
    sections = 0
    inputs_count = outputs_count = 0
    while n < len(raw):
        # End of section is a 0x00 byte.
        if raw[n] == 0:
            sections += 1
            n += 1
            continue
        # Variable-length key/value reads -- approximate.
        n += 1 + raw[n]
        if n >= len(raw): break
        n += 1 + raw[n] if raw[n] < 0xFD else 1
        if n >= len(raw): break
    inputs_count = max(0, sections - 1) // 2
    outputs_count = max(0, sections - 1) - inputs_count

    emit("wallet_psbt",
         path=str(src),
         size_bytes=src.stat().st_size,
         sections=sections,
         estimated_inputs=inputs_count,
         estimated_outputs=outputs_count,
         note="Heuristic decode -- use Bitcoin Core or psbt-tools for full parsing.")
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wallet-sidecar",
                                description="Read-only cryptocurrency wallet metadata.")
    sub = p.add_subparsers(dest="op", required=True)

    b = sub.add_parser("bip39-check", help="Validate a BIP39 mnemonic phrase.")
    b.add_argument("--words", nargs="*", default=None)
    b.add_argument("--input-file", default=None, dest="input_file")
    b.add_argument("--language", default="english",
                   help="english | japanese | spanish | french | italian | korean | chinese_simplified | chinese_traditional")

    k = sub.add_parser("keystore-info", help="Probe Ethereum keystore JSON header.")
    k.add_argument("--input", required=True)

    d = sub.add_parser("descriptor", help="Parse a Bitcoin output descriptor.")
    d.add_argument("--descriptor", required=True)

    ps = sub.add_parser("psbt-decode", help="Heuristic decode of a Partially Signed Bitcoin Transaction.")
    ps.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "bip39-check":   return op_bip39_check(args)
        if args.op == "keystore-info": return op_keystore_info(args)
        if args.op == "descriptor":    return op_descriptor(args)
        if args.op == "psbt-decode":   return op_psbt_decode(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

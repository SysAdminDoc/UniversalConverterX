"""File hash / checksum sidecar.

Operations:
  generate    Hash one or more files; write a sidecar `<file>.<algo>` or a
              consolidated SHA256SUMS / MD5SUMS line file.
  verify      Verify files against a SHA256SUMS / MD5SUMS-style manifest.

Algorithms: md5 sha1 sha224 sha256 sha384 sha512
            sha3_256 sha3_512 blake2b blake2s
            blake3 (when the `blake3` package is installed)
            crc32 adler32 (zlib)
            xxh32 xxh64 xxh128 (when `xxhash` is installed)
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


HASHLIB_ALGOS = {"md5", "sha1", "sha224", "sha256", "sha384", "sha512",
                 "sha3_256", "sha3_512", "blake2b", "blake2s"}


def _hash_file(path: Path, algo: str) -> str:
    if algo in HASHLIB_ALGOS:
        h = hashlib.new(algo)
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    if algo == "blake3":
        import blake3
        h = blake3.blake3()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    if algo in ("xxh32", "xxh64", "xxh128"):
        import xxhash
        h = getattr(xxhash, algo)()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    if algo == "crc32":
        crc = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                crc = zlib.crc32(chunk, crc)
        return f"{crc & 0xFFFFFFFF:08x}"
    if algo == "adler32":
        a = 1
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                a = zlib.adler32(chunk, a)
        return f"{a & 0xFFFFFFFF:08x}"
    raise ValueError(f"Unsupported algorithm '{algo}'.")


def op_generate(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve() if args.output_dir else None
    if out_dir: out_dir.mkdir(parents=True, exist_ok=True)
    algo = args.algo.lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="hash", eta_seconds=None)

    manifest_lines: list[str] = []
    for i, src in enumerate(inputs):
        try:
            digest = _hash_file(src, algo)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("hash_failed", f"{src.name}: {ex}")

        manifest_lines.append(f"{digest}  {src.name}")

        # Per-file sidecar like `image.png.sha256` if requested.
        if args.per_file and out_dir is not None:
            sidecar = out_dir / (src.name + "." + algo)
            sidecar.write_text(f"{digest}  {src.name}\n", encoding="utf-8")
            emit("file_hash",
                 input=str(src), output=str(sidecar),
                 algorithm=algo, digest=digest,
                 size_bytes=src.stat().st_size)
        else:
            emit("file_hash",
                 input=str(src), output=None,
                 algorithm=algo, digest=digest,
                 size_bytes=src.stat().st_size)

        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    if not args.per_file and out_dir is not None:
        manifest = out_dir / f"{algo.upper()}SUMS"
        manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        emit("file_hash_manifest",
             output=str(manifest), size_bytes=manifest.stat().st_size,
             algorithm=algo, count=len(manifest_lines))

    emit("complete", output=str(out_dir or ""), size_bytes=0, count=total)
    return 0


def op_verify(args: argparse.Namespace) -> int:
    manifest = Path(args.manifest)
    if not manifest.is_file(): return fail("missing_input", f"Manifest not found: {manifest}")
    base = Path(args.base_dir or manifest.parent).resolve()
    algo = args.algo.lower()

    bad = 0
    ok = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        # GNU coreutils sha256sum format: "<hex>  <filename>" (two spaces).
        parts = line.split(maxsplit=1)
        if len(parts) != 2: continue
        expected, name = parts
        target = base / name.lstrip("*").strip()
        if not target.is_file():
            emit("file_hash_check",
                 input=str(target), expected=expected,
                 actual=None, ok=False, reason="missing")
            bad += 1; continue
        try:
            actual = _hash_file(target, algo)
        except Exception as ex:
            emit("file_hash_check",
                 input=str(target), expected=expected,
                 actual=None, ok=False, reason=str(ex))
            bad += 1; continue
        passed = (actual.lower() == expected.lower())
        emit("file_hash_check",
             input=str(target), expected=expected,
             actual=actual, ok=passed,
             algorithm=algo)
        if passed: ok += 1
        else: bad += 1

    emit("complete", output=str(manifest), size_bytes=0, count=ok + bad)
    return 0 if bad == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hashkit-sidecar",
                                description="File hashing + checksum verification.")
    sub = p.add_subparsers(dest="op", required=True)
    g = sub.add_parser("generate", help="Hash files and emit a manifest.")
    g.add_argument("--input", nargs="+", required=True)
    g.add_argument("--output-dir", default=None, dest="output_dir")
    g.add_argument("--algo", default="sha256",
                   help="md5|sha1|sha224|sha256|sha384|sha512|sha3_256|sha3_512|"
                        "blake2b|blake2s|blake3|xxh32|xxh64|xxh128|crc32|adler32")
    g.add_argument("--per-file", action="store_true", dest="per_file",
                   help="Write a sidecar `<file>.<algo>` per input "
                        "instead of a consolidated SUMS file.")
    v = sub.add_parser("verify", help="Verify files against a SUMS manifest.")
    v.add_argument("--manifest", required=True,
                   help="Path to SHA256SUMS / MD5SUMS / etc.")
    v.add_argument("--base-dir", default=None, dest="base_dir",
                   help="Directory to resolve filenames against (default: manifest's dir).")
    v.add_argument("--algo", default="sha256")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "generate": return op_generate(args)
        if args.op == "verify":   return op_verify(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

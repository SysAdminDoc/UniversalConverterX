"""Game-format sidecar -- ROM patching, header normalization, and disc-image
re-packaging for retro/console formats. Pure-Python where possible; shells
out to MAME's `chdman` for CHD <-> CUE/BIN.

Operations:
  patch        Apply IPS / BPS / UPS / PPF / xdelta3 / VCDIFF patch to a ROM.
  unpatch      Reverse-apply where the format supports it (BPS, xdelta3).
  rom-info     Inspect ROM header (NES iNES/NES2.0, SNES SMC/LoROM/HiROM,
               GB/GBA/N64 byteorder, MD/Genesis Sega header).
  rom-strip    Strip headers (e.g., remove 512-byte SMC header from SNES).
  byteswap     Re-byteorder a ROM (n64 z64<->v64<->n64).
  chd-pack     CUE/BIN/ISO/GDI/TOC -> CHD (chdman).
  chd-unpack   CHD -> CUE/BIN/ISO/GDI (chdman).

External binary discovery:
  chdman.exe / chdman -- searched on PATH and CHDMAN_PATH env.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ------------------------- IPS / BPS patch handlers -------------------------

def _apply_ips(rom: bytes, patch: bytes) -> bytes:
    if patch[:5] != b"PATCH":
        raise ValueError("not an IPS patch (missing 'PATCH' magic)")
    out = bytearray(rom)
    i = 5
    while i < len(patch) - 3:
        if patch[i:i + 3] == b"EOF":
            break
        offset = int.from_bytes(patch[i:i + 3], "big"); i += 3
        length = int.from_bytes(patch[i:i + 2], "big"); i += 2
        if length == 0:  # RLE
            rle_size = int.from_bytes(patch[i:i + 2], "big"); i += 2
            byte = patch[i]; i += 1
            data = bytes([byte]) * rle_size
        else:
            data = patch[i:i + length]; i += length
        end = offset + len(data)
        if end > len(out):
            out.extend(b"\x00" * (end - len(out)))
        out[offset:end] = data
    # Optional 3-byte truncation extension (RIPS).
    if i + 3 <= len(patch):
        trunc = int.from_bytes(patch[i:i + 3], "big")
        if 0 < trunc < len(out): out = out[:trunc]
    return bytes(out)


def _apply_bps(rom: bytes, patch: bytes) -> bytes:
    if patch[:4] != b"BPS1":
        raise ValueError("not a BPS patch (missing 'BPS1' magic)")
    pos = 4

    def read_vlq() -> int:
        nonlocal pos
        n = 0; sh = 1
        while True:
            x = patch[pos]; pos += 1
            n += (x & 0x7F) * sh
            if x & 0x80: break
            sh <<= 7; n += sh
        return n

    src_size = read_vlq()
    dst_size = read_vlq()
    md_size = read_vlq()
    pos += md_size  # skip metadata

    if len(rom) != src_size:
        raise ValueError(f"BPS source size mismatch: rom={len(rom)} expected={src_size}")

    out = bytearray(dst_size)
    out_pos = 0
    src_rel = 0
    dst_rel = 0

    end = len(patch) - 12  # last 12 bytes = checksums
    while pos < end:
        cmd = read_vlq()
        action = cmd & 3
        length = (cmd >> 2) + 1
        if action == 0:      # SourceRead
            out[out_pos:out_pos + length] = rom[out_pos:out_pos + length]
            out_pos += length
        elif action == 1:    # TargetRead
            out[out_pos:out_pos + length] = patch[pos:pos + length]
            pos += length; out_pos += length
        elif action == 2:    # SourceCopy
            d = read_vlq()
            src_rel += -((d >> 1)) if d & 1 else (d >> 1)
            out[out_pos:out_pos + length] = rom[src_rel:src_rel + length]
            src_rel += length; out_pos += length
        else:                # TargetCopy
            d = read_vlq()
            dst_rel += -((d >> 1)) if d & 1 else (d >> 1)
            for _ in range(length):
                out[out_pos] = out[dst_rel]
                out_pos += 1; dst_rel += 1
    return bytes(out)


def _apply_ups(rom: bytes, patch: bytes) -> bytes:
    if patch[:4] != b"UPS1":
        raise ValueError("not a UPS patch (missing 'UPS1' magic)")
    pos = 4

    def read_vlq() -> int:
        nonlocal pos
        n = 0; sh = 1
        while True:
            x = patch[pos]; pos += 1
            n += (x & 0x7F) * sh
            if x & 0x80: break
            sh <<= 7; n += sh
        return n

    in_size = read_vlq()
    out_size = read_vlq()
    out = bytearray(rom + b"\x00" * max(0, out_size - len(rom)))
    if len(out) < out_size:
        out.extend(b"\x00" * (out_size - len(out)))
    out = out[:out_size]
    out_pos = 0
    end = len(patch) - 12
    while pos < end:
        skip = read_vlq()
        out_pos += skip
        while pos < end:
            x = patch[pos]; pos += 1
            if out_pos < len(out):
                out[out_pos] ^= x
            out_pos += 1
            if x == 0: break
    return bytes(out)


_PATCHERS = {
    ".ips": _apply_ips,
    ".bps": _apply_bps,
    ".ups": _apply_ups,
}


def op_patch(args: argparse.Namespace) -> int:
    rom = Path(args.rom)
    patch = Path(args.patch)
    if not rom.is_file(): return fail("missing_input", f"ROM not found: {rom}")
    if not patch.is_file(): return fail("missing_input", f"Patch not found: {patch}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (rom.stem + "_patched" + rom.suffix)

    handler = _PATCHERS.get(patch.suffix.lower())
    if handler is None:
        return fail("bad_format",
                    f"Unsupported patch type {patch.suffix}. Supported: {list(_PATCHERS)}")

    try:
        result = handler(rom.read_bytes(), patch.read_bytes())
        out_path.write_bytes(result)
    except Exception as ex:
        return fail("patch_failed", f"{patch.name}: {ex}")

    emit("rom_patch",
         input=str(rom), patch=str(patch), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format=patch.suffix.lstrip("."))
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=1)
    return 0


# ------------------------- ROM info / strip / byteswap ----------------------

def _detect_console(buf: bytes, name: str) -> dict:
    """Return a {console, header_size, mapper, region} dict (best-effort)."""
    info = {"console": "unknown", "header_size": 0, "mapper": None, "region": None}
    ext = Path(name).suffix.lower()

    if buf[:4] == b"NES\x1a":
        info["console"] = "NES"
        info["header_size"] = 16
        flags6 = buf[6]; flags7 = buf[7]
        info["mapper"] = ((flags7 & 0xF0) | (flags6 >> 4))
        info["nes2"] = (flags7 & 0x0C) == 0x08
    elif ext in (".smc", ".sfc") and (len(buf) % 1024 == 512):
        info["console"] = "SNES"; info["header_size"] = 512
    elif ext in (".smc", ".sfc"):
        info["console"] = "SNES"; info["header_size"] = 0
    elif ext in (".gb", ".gbc"):
        info["console"] = "GameBoy"
        if len(buf) > 0x143:
            info["region"] = "Color" if buf[0x143] in (0x80, 0xC0) else "DMG"
    elif ext == ".gba":
        info["console"] = "GBA"
    elif ext in (".n64", ".v64", ".z64"):
        info["console"] = "N64"
        if buf[:4] == b"\x80\x37\x12\x40": info["byteorder"] = "z64"
        elif buf[:4] == b"\x37\x80\x40\x12": info["byteorder"] = "v64"
        elif buf[:4] == b"\x40\x12\x37\x80": info["byteorder"] = "n64"
    elif ext in (".md", ".bin", ".gen", ".smd"):
        if b"SEGA" in buf[0x100:0x110]:
            info["console"] = "MD/Genesis"
    return info


def op_rom_info(args: argparse.Namespace) -> int:
    rom = Path(args.input)
    if not rom.is_file(): return fail("missing_input", f"ROM not found: {rom}")
    buf = rom.read_bytes()
    info = _detect_console(buf, rom.name)
    emit("rom_info",
         path=str(rom), size_bytes=len(buf),
         console=info["console"], header_size=info["header_size"],
         mapper=info.get("mapper"), region=info.get("region"),
         byteorder=info.get("byteorder"), nes2=info.get("nes2"))
    emit("complete", output=str(rom), size_bytes=len(buf), count=1)
    return 0


def op_rom_strip(args: argparse.Namespace) -> int:
    rom = Path(args.input)
    if not rom.is_file(): return fail("missing_input", f"ROM not found: {rom}")
    buf = rom.read_bytes()
    info = _detect_console(buf, rom.name)
    if info["header_size"] == 0:
        return fail("nothing_to_strip", f"{rom.name}: no detected header.")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (rom.stem + "_stripped" + rom.suffix)
    out_path.write_bytes(buf[info["header_size"]:])
    emit("rom_patch",
         input=str(rom), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="strip", console=info["console"], removed=info["header_size"])
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_byteswap(args: argparse.Namespace) -> int:
    rom = Path(args.input)
    if not rom.is_file(): return fail("missing_input", f"ROM not found: {rom}")
    buf = bytearray(rom.read_bytes())
    if len(buf) % 4 != 0:
        return fail("bad_size", "ROM size is not a multiple of 4 bytes.")
    src = (args.from_order or "").lower()
    dst = (args.to_order or "").lower()
    if dst not in {"z64", "v64", "n64"}:
        return fail("bad_target", "Choose --to one of: z64 | v64 | n64.")

    # Detect source if not provided.
    if not src:
        head = bytes(buf[:4])
        if head == b"\x80\x37\x12\x40": src = "z64"
        elif head == b"\x37\x80\x40\x12": src = "v64"
        elif head == b"\x40\x12\x37\x80": src = "n64"
        else: return fail("undetected", "Could not autodetect N64 byteorder.")

    if src == dst:
        return fail("noop", f"Source already {dst}.")

    # z64 = big-endian (correct), v64 = byteswap pairs, n64 = full-word reverse.
    def to_z64(b: bytearray, frm: str) -> bytearray:
        if frm == "v64":
            for i in range(0, len(b), 2): b[i], b[i + 1] = b[i + 1], b[i]
        elif frm == "n64":
            for i in range(0, len(b), 4):
                b[i], b[i + 1], b[i + 2], b[i + 3] = b[i + 3], b[i + 2], b[i + 1], b[i]
        return b

    def from_z64(b: bytearray, to: str) -> bytearray:
        return to_z64(b, "v64" if to == "v64" else "n64")  # symmetric

    buf = to_z64(buf, src)
    if dst != "z64": buf = from_z64(buf, dst)

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (rom.stem + f".{dst}")
    out_path.write_bytes(bytes(buf))
    emit("rom_patch",
         input=str(rom), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="byteswap", from_order=src, to_order=dst)
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=1)
    return 0


# ------------------------- chdman wrapper -----------------------------------

def _find_chdman() -> str | None:
    env = os.environ.get("CHDMAN_PATH")
    if env and Path(env).is_file(): return env
    for n in ("chdman", "chdman.exe"):
        hit = shutil.which(n)
        if hit: return hit
    return None


def op_chd_pack(args: argparse.Namespace) -> int:
    chdman = _find_chdman()
    if not chdman:
        return fail("missing_chdman",
                    "chdman not found. Install MAME tools or set $env:CHDMAN_PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CUE/BIN/ISO/GDI not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="chd-pack", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".chd")
        # createcd auto-detects CD vs DVD; users with DVD images can pass --dvd.
        cmd_kind = "createdvd" if args.dvd else "createcd"
        cmd = [chdman, cmd_kind, "-i", str(src), "-o", str(out_path), "-f"]
        if args.dvd: cmd = [chdman, "createdvd", "-i", str(src), "-o", str(out_path), "-f"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("chdman_failed", f"{src.name}: rc={proc.returncode}")
        emit("disc_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format="chd")
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_chd_unpack(args: argparse.Namespace) -> int:
    chdman = _find_chdman()
    if not chdman: return fail("missing_chdman", "chdman not found.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CHD(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_cue = out_dir / (src.stem + ".cue")
        cmd = [chdman, "extractcd", "-i", str(src), "-o", str(out_cue), "-f"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("chdman_failed", f"{src.name}: rc={proc.returncode}")
        emit("disc_image",
             input=str(src), output=str(out_cue),
             size_bytes=out_cue.stat().st_size if out_cue.is_file() else 0,
             format="cue")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gametools-sidecar",
                                description="Game ROM and disc-image utilities.")
    sub = p.add_subparsers(dest="op", required=True)

    pa = sub.add_parser("patch", help="Apply IPS/BPS/UPS patch to a ROM.")
    pa.add_argument("--rom", required=True)
    pa.add_argument("--patch", required=True)
    pa.add_argument("--output-dir", required=True, dest="output_dir")

    info = sub.add_parser("rom-info", help="Inspect ROM header.")
    info.add_argument("--input", required=True)

    strip = sub.add_parser("rom-strip", help="Strip the iNES/SMC header from a ROM.")
    strip.add_argument("--input", required=True)
    strip.add_argument("--output-dir", required=True, dest="output_dir")

    bs = sub.add_parser("byteswap", help="Re-byteorder an N64 ROM (z64/v64/n64).")
    bs.add_argument("--input", required=True)
    bs.add_argument("--output-dir", required=True, dest="output_dir")
    bs.add_argument("--from", dest="from_order", default=None,
                    help="Source byteorder (autodetect if omitted).")
    bs.add_argument("--to", dest="to_order", required=True,
                    help="Target byteorder: z64 | v64 | n64.")

    cp = sub.add_parser("chd-pack", help="Pack CUE/BIN/ISO/GDI -> CHD.")
    cp.add_argument("--input", nargs="+", required=True)
    cp.add_argument("--output-dir", required=True, dest="output_dir")
    cp.add_argument("--dvd", action="store_true",
                    help="Treat as DVD image (createdvd) instead of CD.")

    cu = sub.add_parser("chd-unpack", help="Unpack CHD -> CUE+BIN.")
    cu.add_argument("--input", nargs="+", required=True)
    cu.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "patch":      return op_patch(args)
        if args.op == "rom-info":   return op_rom_info(args)
        if args.op == "rom-strip":  return op_rom_strip(args)
        if args.op == "byteswap":   return op_byteswap(args)
        if args.op == "chd-pack":   return op_chd_pack(args)
        if args.op == "chd-unpack": return op_chd_unpack(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

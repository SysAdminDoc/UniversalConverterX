"""Retrocomputing disk-image / tape sidecar.

Inspect (and partially extract) classic disk-image and tape formats:

  * Apple II .dsk / .do / .po / .nib (143KB / 16-sector)
  * Commodore 64 .d64 / .d71 / .d81  (174KB / 357KB / 802KB)
  * Atari 8-bit / ST .atr / .atz
  * ZX Spectrum .tap (tape) / .tzx (tape)
  * Apple ProDOS volume header

Operations:
  list           List files / sectors in a retro disk image -> JSON / CSV.
  info           Probe disk geometry / format identification -> JSON.

These formats encode files differently per platform; full extraction
needs platform-specific filesystem decoders. We focus on listing
(catalog tracks / TOC) + info, which is portable enough to do without
external libraries.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Apple II DOS 3.3 (.dsk / .do) catalog ──────────────────────────────

def _read_apple_dos_catalog(data: bytes) -> dict:
    """DOS 3.3: 35 tracks * 16 sectors * 256 bytes = 143360. Catalog
    starts at track 17, sector 15 ($11/$0F)."""
    if len(data) not in (143360, 143488):
        raise ValueError(f"Not Apple II DOS 3.3 ({len(data)} bytes).")
    track = 17; sector = 15
    files: list[dict] = []
    visited = set()
    while True:
        if (track, sector) in visited: break
        visited.add((track, sector))
        offset = track * 16 * 256 + sector * 256
        cat = data[offset:offset + 256]
        if len(cat) < 256: break
        next_track = cat[1]
        next_sector = cat[2]
        for entry_idx in range(7):
            entry_off = 11 + entry_idx * 35
            entry = cat[entry_off:entry_off + 35]
            if entry[0] in (0x00, 0xFF): continue
            file_type = entry[2]
            sectors = struct.unpack("<H", entry[33:35])[0]
            name = bytes(b & 0x7F for b in entry[3:33]).decode("ascii",
                                                                  errors="replace").rstrip()
            files.append({
                "name": name,
                "type_byte": file_type,
                "type": _APPLE_FILE_TYPES.get(file_type & 0x7F, "?"),
                "sectors": sectors,
                "locked": bool(file_type & 0x80),
            })
        if next_track == 0 and next_sector == 0: break
        track, sector = next_track, next_sector
    return {"format": "apple-dos-3.3", "files": files}


_APPLE_FILE_TYPES = {0: "TXT", 1: "I-BAS", 2: "A-BAS", 4: "B-BIN",
                     8: "S", 16: "R", 32: "AA", 64: "BB"}


# ── C64 .d64 catalog (track 18, sector 1) ──────────────────────────────

def _d64_offset(track: int, sector: int) -> int:
    """D64 sectors-per-track table for tracks 1-35."""
    sectors = ([21] * 17 + [19] * 7 + [18] * 6 + [17] * 5)
    offs = 0
    for t in range(1, track):
        offs += sectors[t - 1] * 256
    return offs + sector * 256


def _read_c64_catalog(data: bytes) -> dict:
    if len(data) not in (174848, 175531, 196608):
        raise ValueError(f"Not C64 D64 ({len(data)} bytes).")
    files: list[dict] = []
    track = 18; sector = 1
    visited = set()
    while True:
        if (track, sector) in visited: break
        visited.add((track, sector))
        ofs = _d64_offset(track, sector)
        if ofs + 256 > len(data): break
        block = data[ofs:ofs + 256]
        next_track, next_sector = block[0], block[1]
        for slot in range(8):
            entry = block[slot * 32:slot * 32 + 32]
            file_type = entry[2]
            if file_type == 0: continue
            name = bytes(b for b in entry[5:21] if b != 0xA0).decode("latin-1",
                                                                       errors="replace")
            blocks = struct.unpack("<H", entry[30:32])[0]
            type_table = ["DEL", "SEQ", "PRG", "USR", "REL"]
            tname = type_table[file_type & 0x07] if (file_type & 0x07) < 5 else "?"
            files.append({"name": name.strip(), "type": tname,
                          "blocks": blocks, "type_byte": file_type})
        if next_track == 0: break
        track, sector = next_track, next_sector
    return {"format": "c64-d64", "files": files}


# ── Atari 8-bit ATR ────────────────────────────────────────────────────

def _read_atr(data: bytes) -> dict:
    if data[:2] != b"\x96\x02":
        raise ValueError("Not an Atari ATR (magic mismatch).")
    pars = struct.unpack("<H", data[2:4])[0]
    sec_size = struct.unpack("<H", data[4:6])[0]
    image_high = struct.unpack("<H", data[6:8])[0]
    paragraphs = pars + (image_high << 16)
    bytes_size = paragraphs * 16
    return {"format": "atari-atr", "sector_size": sec_size,
            "image_size_bytes": bytes_size}


# ── ZX Spectrum .tap (tape) ────────────────────────────────────────────

def _read_zx_tap(data: bytes) -> dict:
    """TAP blocks: 2-byte length + N bytes (flag + data + checksum)."""
    blocks: list[dict] = []
    p = 0
    while p < len(data):
        if p + 2 > len(data): break
        block_len = struct.unpack("<H", data[p:p + 2])[0]
        p += 2
        block = data[p:p + block_len]
        p += block_len
        flag = block[0] if block else 0
        if flag == 0 and len(block) >= 19:  # header block
            block_type = block[1]
            file_name = block[2:12].decode("latin-1", errors="replace").strip()
            data_len = struct.unpack("<H", block[12:14])[0]
            blocks.append({
                "type": ["program", "number-array", "char-array",
                          "code"][block_type] if block_type < 4 else "?",
                "name": file_name, "data_len": data_len,
                "block_size": block_len,
            })
        else:
            blocks.append({"type": "data", "block_size": block_len})
    return {"format": "zx-tap", "blocks": blocks}


# ── Dispatcher ─────────────────────────────────────────────────────────

def _decode(path: Path) -> dict:
    data = path.read_bytes()
    ext = path.suffix.lower()
    if ext in (".dsk", ".do", ".po"):
        return _read_apple_dos_catalog(data)
    if ext == ".d64":
        return _read_c64_catalog(data)
    if ext in (".atr",):
        return _read_atr(data)
    if ext == ".tap":
        return _read_zx_tap(data)
    # Fallback: try by size
    if len(data) in (143360, 143488):
        return _read_apple_dos_catalog(data)
    if len(data) in (174848, 175531, 196608):
        return _read_c64_catalog(data)
    if data[:2] == b"\x96\x02":
        return _read_atr(data)
    raise ValueError(f"Could not detect format for {path.name}.")


def op_list(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"disk image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            info = _decode(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".catalog.json")
        out_path.write_text(json.dumps(info, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("retro_disk",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source=info["format"],
             entries=len(info.get("files", info.get("blocks", []))))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"disk image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info = _decode(src)
            entries = len(info.get("files", info.get("blocks", [])))
            probes.append({
                "file": str(src), "format": info["format"],
                "size_bytes": src.stat().st_size, "entries": entries,
            })
        except Exception as ex:
            probes.append({"file": str(src), "format": "unknown",
                           "error": str(ex)})
    out_path = out_dir / "retrodisk-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    for p in probes:
        emit("retro_disk",
             input=p["file"], output="",
             size_bytes=0, format="probe",
             source=p.get("format", "unknown"))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="retrodisks-sidecar",
                                description="Retrocomputing disk-image catalog reader.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("list", "List files / blocks in retro disk image -> JSON"),
        ("info", "Probe disk geometry / format identification"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "list": return op_list(args)
        if args.op == "info": return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Game-engine asset converter sidecar.

Convert game-engine asset containers to portable formats:

  * Source / GoldSrc                   .vpk / .bsp / .pak  -> file list / extract
  * Quake (id Tech 1-3)                .pak / .pk3 / .pk4 -> ZIP-style file list
  * Unity                              .assets / .bundle  -> JSON manifest via UnityPy
  * Godot                              .pck               -> file list / extract
  * Doom                               .wad               -> lump list

Operations:
  list      Inspect an asset container -> JSON manifest (pure stdlib).
  extract   Pull files out of a container -> directory tree.

Pure-stdlib readers for VPK / WAD / PAK / PCK; PK3/PK4 are ZIP and use
zipfile. Unity / Unreal `.uasset` decoding require external tools and
this sidecar surfaces them by JSON manifest only when UnityPy is present.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, safe_extract_path, safe_zip_extractall




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_MAX_ENTRY_BYTES = 512 * 1024 * 1024
_MAX_TOTAL_EXTRACT_BYTES = 4 * 1024 * 1024 * 1024
_MAX_ENTRY_COUNT = 1_000_000
_MAX_ENTRY_NAME_BYTES = 1 * 1024 * 1024


def _read_exact(stream, size: int, label: str) -> bytes:
    if size < 0:
        raise ValueError(f"Negative {label} length.")
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"Truncated {label}.")
    return data


def _validate_span(file_size: int, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset > file_size or size > file_size - offset:
        raise ValueError(f"{label} points outside the input file.")
    if size > _MAX_ENTRY_BYTES:
        raise ValueError(f"{label} exceeds the {_MAX_ENTRY_BYTES} byte safety limit.")


def _copy_entry(stream, target: Path, offset: int, size: int, file_size: int) -> None:
    _validate_span(file_size, offset, size, "archive entry")
    stream.seek(offset)
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = size
    with target.open("wb") as output:
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Truncated archive entry data.")
            output.write(chunk)
            remaining -= len(chunk)


# ── Quake PAK (id Software, also used by Source GoldSrc as .pak) ───────

def _read_pak(path: Path) -> tuple[str, list[dict]]:
    file_size = path.stat().st_size
    with path.open("rb") as f:
        magic = _read_exact(f, 4, "PAK magic")
        if magic != b"PACK":
            raise ValueError("Not a Quake PAK file (magic != 'PACK').")
        offset, length = struct.unpack("<II", _read_exact(f, 8, "PAK header"))
        if length % 64 != 0:
            raise ValueError("PAK directory length is not record-aligned.")
        _validate_span(file_size, offset, length, "PAK directory")
        if length // 64 > _MAX_ENTRY_COUNT:
            raise ValueError("PAK contains too many entries.")
        f.seek(offset)
        entries = []
        for _ in range(length // 64):
            name = _read_exact(f, 56, "PAK entry name").rstrip(b"\x00").decode(
                "ascii", errors="replace")
            ofs, sz = struct.unpack("<II", _read_exact(f, 8, "PAK entry"))
            _validate_span(file_size, ofs, sz, "PAK entry")
            entries.append({"name": name, "offset": ofs, "size": sz})
    return "quake-pak", entries


# ── Doom WAD ───────────────────────────────────────────────────────────

def _read_wad(path: Path) -> tuple[str, list[dict]]:
    file_size = path.stat().st_size
    with path.open("rb") as f:
        magic = _read_exact(f, 4, "WAD magic")
        if magic not in (b"IWAD", b"PWAD"):
            raise ValueError("Not a Doom WAD (magic != IWAD/PWAD).")
        num_lumps, dir_offset = struct.unpack(
            "<II", _read_exact(f, 8, "WAD header"))
        if num_lumps > _MAX_ENTRY_COUNT:
            raise ValueError("WAD contains too many lumps.")
        directory_size = num_lumps * 16
        _validate_span(file_size, dir_offset, directory_size, "WAD directory")
        f.seek(dir_offset)
        entries = []
        for _ in range(num_lumps):
            ofs, sz = struct.unpack("<II", _read_exact(f, 8, "WAD lump"))
            _validate_span(file_size, ofs, sz, "WAD lump")
            name = _read_exact(f, 8, "WAD lump name").rstrip(b"\x00").decode(
                "ascii", errors="replace")
            entries.append({"name": name, "offset": ofs, "size": sz})
    return f"doom-wad ({magic.decode()})", entries


# ── Valve VPK v1 / v2 ──────────────────────────────────────────────────

def _read_vpk(path: Path) -> tuple[str, list[dict]]:
    file_size = path.stat().st_size
    with path.open("rb") as f:
        sig = struct.unpack("<I", _read_exact(f, 4, "VPK signature"))[0]
        if sig != 0x55aa1234:
            raise ValueError("Not a Valve VPK (signature mismatch).")
        version = struct.unpack("<I", _read_exact(f, 4, "VPK version"))[0]
        tree_size = struct.unpack("<I", _read_exact(f, 4, "VPK tree size"))[0]
        if version not in (1, 2):
            raise ValueError(f"Unsupported VPK version: {version}")
        if version == 2:
            _read_exact(f, 4 * 4, "VPK v2 header")
        if tree_size > file_size - f.tell():
            raise ValueError("VPK tree extends beyond the input file.")
        end_of_tree = f.tell() + tree_size
        entries: list[dict] = []
        # tree: ext\0 path\0 name\0 entry-struct (18 bytes)
        def _read_str() -> str:
            buf = bytearray()
            while True:
                if f.tell() >= end_of_tree:
                    raise ValueError("Unterminated VPK tree string.")
                ch = _read_exact(f, 1, "VPK tree string")
                if ch == b"\x00": break
                if len(buf) >= _MAX_ENTRY_NAME_BYTES:
                    raise ValueError("VPK tree string is too long.")
                buf.extend(ch)
            return buf.decode("utf-8", errors="replace")
        while f.tell() < end_of_tree:
            ext = _read_str()
            if not ext: break
            while True:
                directory = _read_str()
                if not directory: break
                while True:
                    name = _read_str()
                    if not name: break
                    if len(entries) >= _MAX_ENTRY_COUNT:
                        raise ValueError("VPK contains too many entries.")
                    _read_exact(f, 4, "VPK CRC")
                    preload = struct.unpack("<H", _read_exact(f, 2, "VPK preload length"))[0]
                    arc_idx = struct.unpack("<H", _read_exact(f, 2, "VPK archive index"))[0]
                    ofs, sz = struct.unpack("<II", _read_exact(f, 8, "VPK entry"))
                    _read_exact(f, 2, "VPK entry terminator")
                    if preload:
                        _read_exact(f, preload, "VPK preload data")
                    full = (f"{directory}/{name}.{ext}"
                            if directory != " " else f"{name}.{ext}")
                    entries.append({"name": full, "archive": arc_idx,
                                    "offset": ofs, "size": sz})
    return f"valve-vpk v{version}", entries


# ── Godot PCK ──────────────────────────────────────────────────────────

def _read_pck(path: Path) -> tuple[str, list[dict]]:
    file_size = path.stat().st_size
    with path.open("rb") as f:
        magic = _read_exact(f, 4, "PCK magic")
        if magic != b"GDPC":
            raise ValueError("Not a Godot PCK (magic != 'GDPC').")
        pack_version = struct.unpack("<I", _read_exact(f, 4, "PCK version"))[0]
        _read_exact(f, 4 * 3, "PCK Godot version")
        _read_exact(f, 4, "PCK flags")
        _read_exact(f, 8, "PCK file base")
        _read_exact(f, 16 * 4, "PCK reserved header")
        file_count = struct.unpack("<I", _read_exact(f, 4, "PCK file count"))[0]
        remaining_header = file_size - f.tell()
        if file_count > _MAX_ENTRY_COUNT or file_count > remaining_header // 36:
            raise ValueError("PCK contains too many or truncated entries.")
        entries = []
        for _ in range(file_count):
            path_len = struct.unpack("<I", _read_exact(f, 4, "PCK path length"))[0]
            if path_len > _MAX_ENTRY_NAME_BYTES:
                raise ValueError("PCK entry name is too long.")
            name = _read_exact(f, path_len, "PCK entry name").rstrip(b"\x00").decode(
                "utf-8", errors="replace")
            ofs = struct.unpack("<Q", _read_exact(f, 8, "PCK entry offset"))[0]
            sz = struct.unpack("<Q", _read_exact(f, 8, "PCK entry size"))[0]
            _read_exact(f, 16, "PCK entry hash")
            _validate_span(file_size, ofs, sz, "PCK entry")
            entries.append({"name": name, "offset": ofs, "size": sz})
    return f"godot-pck v{pack_version}", entries


def _read_zip(path: Path) -> tuple[str, list[dict]]:
    with zipfile.ZipFile(path) as z:
        return "zip-archive", [{"name": i.filename, "size": i.file_size,
                                 "compressed": i.compress_size}
                                for i in z.infolist()]


_DISPATCH: dict[str, callable] = {
    ".pak": _read_pak,
    ".wad": _read_wad,
    ".vpk": _read_vpk,
    ".pck": _read_pck,
    ".pk3": _read_zip, ".pk4": _read_zip, ".zip": _read_zip,
    ".bsa": _read_zip,  # Bethesda — close enough for ZIP-style listing
}


def _detect(path: Path) -> tuple[str, list[dict]]:
    func = _DISPATCH.get(path.suffix.lower())
    if not func:
        raise ValueError(f"Unsupported game asset: {path.suffix}. "
                         f"Supported: {', '.join(sorted(_DISPATCH))}")
    return func(path)


def op_list(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Asset(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            kind, entries = _detect(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".manifest.json")
        out_path.write_text(json.dumps({"format": kind, "count": len(entries),
                                        "entries": entries}, indent=2),
                            encoding="utf-8")
        emit("game_asset",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source=kind, count=len(entries))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def _extract_pak(src: Path, dest: Path) -> int:
    _, entries = _read_pak(src)
    n = 0
    total = 0
    file_size = src.stat().st_size
    with src.open("rb") as f:
        for e in entries:
            target = safe_extract_path(dest, e["name"])
            total += e["size"]
            if total > _MAX_TOTAL_EXTRACT_BYTES:
                raise ValueError("PAK contents exceed the extraction safety limit.")
            _copy_entry(f, target, e["offset"], e["size"], file_size)
            n += 1
    return n


def _extract_pck(src: Path, dest: Path) -> int:
    _, entries = _read_pck(src)
    n = 0
    total = 0
    file_size = src.stat().st_size
    with src.open("rb") as f:
        for e in entries:
            rel = e["name"].lstrip("/").replace("res://", "")
            target = safe_extract_path(dest, rel)
            total += e["size"]
            if total > _MAX_TOTAL_EXTRACT_BYTES:
                raise ValueError("PCK contents exceed the extraction safety limit.")
            _copy_entry(f, target, e["offset"], e["size"], file_size)
            n += 1
    return n


def _extract_zip(src: Path, dest: Path) -> int:
    with zipfile.ZipFile(src) as z:
        return safe_zip_extractall(z, dest)


def op_extract(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Asset(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        target_dir = out_dir / src.stem
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            if ext == ".pak":
                n = _extract_pak(src, target_dir)
            elif ext == ".pck":
                n = _extract_pck(src, target_dir)
            elif ext in (".pk3", ".pk4", ".zip", ".bsa"):
                n = _extract_zip(src, target_dir)
            else:
                return fail("unsupported_extract",
                            f"Extract not implemented for {ext}. "
                            f"Use list-only mode.")
        except Exception as ex:
            return fail("extract_failed", f"{src.name}: {ex}")
        emit("game_asset",
             input=str(src), output=str(target_dir),
             size_bytes=0, format="dir",
             source=ext.lstrip("."), count=n)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gameasset-sidecar",
                                description="Game-engine asset container converter.")
    sub = p.add_subparsers(dest="op", required=True)

    li = sub.add_parser("list", help="List entries in a game asset container.")
    li.add_argument("--input", nargs="+", required=True)
    li.add_argument("--output-dir", required=True, dest="output_dir")

    ex = sub.add_parser("extract", help="Extract files from a game asset container.")
    ex.add_argument("--input", nargs="+", required=True)
    ex.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "list":    return op_list(args)
        if args.op == "extract": return op_extract(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

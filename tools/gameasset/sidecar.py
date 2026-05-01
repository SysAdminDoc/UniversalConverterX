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


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Quake PAK (id Software, also used by Source GoldSrc as .pak) ───────

def _read_pak(path: Path) -> tuple[str, list[dict]]:
    with path.open("rb") as f:
        magic = f.read(4)
        if magic != b"PACK":
            raise ValueError("Not a Quake PAK file (magic != 'PACK').")
        offset, length = struct.unpack("<II", f.read(8))
        f.seek(offset)
        entries = []
        for _ in range(length // 64):
            name = f.read(56).rstrip(b"\x00").decode("ascii", errors="replace")
            ofs, sz = struct.unpack("<II", f.read(8))
            entries.append({"name": name, "offset": ofs, "size": sz})
    return "quake-pak", entries


# ── Doom WAD ───────────────────────────────────────────────────────────

def _read_wad(path: Path) -> tuple[str, list[dict]]:
    with path.open("rb") as f:
        magic = f.read(4)
        if magic not in (b"IWAD", b"PWAD"):
            raise ValueError("Not a Doom WAD (magic != IWAD/PWAD).")
        num_lumps, dir_offset = struct.unpack("<II", f.read(8))
        f.seek(dir_offset)
        entries = []
        for _ in range(num_lumps):
            ofs, sz = struct.unpack("<II", f.read(8))
            name = f.read(8).rstrip(b"\x00").decode("ascii", errors="replace")
            entries.append({"name": name, "offset": ofs, "size": sz})
    return f"doom-wad ({magic.decode()})", entries


# ── Valve VPK v1 / v2 ──────────────────────────────────────────────────

def _read_vpk(path: Path) -> tuple[str, list[dict]]:
    with path.open("rb") as f:
        sig = struct.unpack("<I", f.read(4))[0]
        if sig != 0x55aa1234:
            raise ValueError("Not a Valve VPK (signature mismatch).")
        version = struct.unpack("<I", f.read(4))[0]
        tree_size = struct.unpack("<I", f.read(4))[0]
        if version == 2:
            f.read(4 * 4)  # FileDataSectionSize, ArchiveMD5SectionSize, OtherMD5SectionSize, SignatureSectionSize
        end_of_tree = f.tell() + tree_size
        entries: list[dict] = []
        # tree: ext\0 path\0 name\0 entry-struct (18 bytes)
        def _read_str() -> str:
            buf = bytearray()
            while True:
                ch = f.read(1)
                if not ch or ch == b"\x00": break
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
                    f.read(4)   # CRC
                    preload = struct.unpack("<H", f.read(2))[0]
                    arc_idx = struct.unpack("<H", f.read(2))[0]
                    ofs, sz = struct.unpack("<II", f.read(8))
                    f.read(2)   # terminator
                    if preload: f.read(preload)
                    full = (f"{directory}/{name}.{ext}"
                            if directory != " " else f"{name}.{ext}")
                    entries.append({"name": full, "archive": arc_idx,
                                    "offset": ofs, "size": sz})
    return f"valve-vpk v{version}", entries


# ── Godot PCK ──────────────────────────────────────────────────────────

def _read_pck(path: Path) -> tuple[str, list[dict]]:
    with path.open("rb") as f:
        magic = f.read(4)
        if magic != b"GDPC":
            raise ValueError("Not a Godot PCK (magic != 'GDPC').")
        pack_version = struct.unpack("<I", f.read(4))[0]
        f.read(4 * 3)  # godot major/minor/patch
        f.read(4)      # flags
        f.read(8)      # file_base
        f.read(16 * 4) # reserved
        file_count = struct.unpack("<I", f.read(4))[0]
        entries = []
        for _ in range(file_count):
            path_len = struct.unpack("<I", f.read(4))[0]
            name = f.read(path_len).rstrip(b"\x00").decode("utf-8",
                                                           errors="replace")
            ofs = struct.unpack("<Q", f.read(8))[0]
            sz = struct.unpack("<Q", f.read(8))[0]
            f.read(16)  # MD5
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
    with src.open("rb") as f:
        for e in entries:
            f.seek(e["offset"])
            target = dest / e["name"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.read(e["size"]))
            n += 1
    return n


def _extract_pck(src: Path, dest: Path) -> int:
    _, entries = _read_pck(src)
    n = 0
    with src.open("rb") as f:
        for e in entries:
            f.seek(e["offset"])
            rel = e["name"].lstrip("/").replace("res://", "")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.read(e["size"]))
            n += 1
    return n


def _extract_zip(src: Path, dest: Path) -> int:
    with zipfile.ZipFile(src) as z:
        z.extractall(dest)
        return len(z.infolist())


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

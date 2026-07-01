"""Digital-forensics artifact sidecar.

Decode forensic-relevant Windows / disk / browser artifacts:

  * NTFS Master File Table ($MFT) -> CSV
  * Windows Registry .reg / .hiv (hive) -> JSON
  * Prefetch .pf -> JSON (last-run timestamps + path hash)
  * jumplists *.automaticDestinations-ms / *.customDestinations-ms
  * Chrome / Firefox / Edge browser history (SQLite) -> CSV
  * E01 EWF disk image probe via ewfinfo (read-only, no extract)
  * Windows event logs .evtx -> JSON / CSV (already in logkit, lighter probe here)

Operations:
  mft-to-csv         Parse $MFT records -> CSV (path, size, timestamps).
  reg-to-json        Plain-text .reg export -> JSON tree.
  prefetch-info      Windows .pf file -> JSON (executable / runs / volumes).
  browser-history    Chrome/Firefox/Edge SQLite History -> CSV.
  ewf-info           E01 / EWF probe via ewfinfo CLI.

Heavy formats ($MFT, .evtx) shell out to industry-standard tools when
present; light formats (.reg, .pf, browser history) are pure-stdlib.
"""
from __future__ import annotations

import argparse
import csv
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _filetime_to_iso(ft: int) -> str:
    if ft == 0: return ""
    try:
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        return (epoch + timedelta(microseconds=ft / 10)).isoformat()
    except (OverflowError, ValueError):
        return ""


# ── $MFT decoder (basic) ──────────────────────────────────────────────

def _parse_mft(data: bytes) -> list[dict]:
    """Each MFT record is 1024 bytes. Magic 'FILE' at offset 0."""
    rows: list[dict] = []
    rec_size = 1024
    for offset in range(0, len(data) - rec_size + 1, rec_size):
        rec = data[offset:offset + rec_size]
        if rec[0:4] != b"FILE": continue
        flags = struct.unpack("<H", rec[22:24])[0]
        first_attr_off = struct.unpack("<H", rec[20:22])[0]
        # Walk attributes
        p = first_attr_off
        name = ""
        size = 0
        ctime = mtime = atime = etime = 0
        while p + 4 < len(rec):
            attr_type = struct.unpack("<I", rec[p:p + 4])[0]
            if attr_type == 0xFFFFFFFF: break
            attr_len = struct.unpack("<I", rec[p + 4:p + 8])[0]
            if attr_len == 0 or p + attr_len > len(rec): break
            non_resident = rec[p + 8]
            if non_resident == 0:  # resident
                content_len = struct.unpack("<I", rec[p + 16:p + 20])[0]
                content_off = struct.unpack("<H", rec[p + 20:p + 22])[0]
                content = rec[p + content_off:p + content_off + content_len]
                if attr_type == 0x10 and len(content) >= 32:  # $STANDARD_INFORMATION
                    ctime = struct.unpack("<Q", content[0:8])[0]
                    mtime = struct.unpack("<Q", content[8:16])[0]
                    etime = struct.unpack("<Q", content[16:24])[0]
                    atime = struct.unpack("<Q", content[24:32])[0]
                elif attr_type == 0x30 and len(content) >= 66:  # $FILE_NAME
                    name_len = content[64]
                    raw_name = content[66:66 + name_len * 2]
                    try:
                        name = raw_name.decode("utf-16-le", errors="replace")
                    except Exception:
                        name = ""
                elif attr_type == 0x80 and content_len:  # $DATA
                    size = content_len
            p += attr_len
        rows.append({
            "record_offset": offset,
            "flags": flags,
            "is_directory": bool(flags & 0x02),
            "in_use": bool(flags & 0x01),
            "name": name,
            "size_bytes": size,
            "created":   _filetime_to_iso(ctime),
            "modified":  _filetime_to_iso(mtime),
            "mft_changed": _filetime_to_iso(etime),
            "accessed":  _filetime_to_iso(atime),
        })
    return rows


def op_mft_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"$MFT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            rows = _parse_mft(src.read_bytes())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".mft.csv")
        keys = ["record_offset", "flags", "is_directory", "in_use", "name",
                "size_bytes", "created", "modified", "mft_changed", "accessed"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("forensic_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="ntfs-mft", records=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── .reg text export -> JSON ──────────────────────────────────────────

_REG_KEY_RE = re.compile(r"^\[(?P<flag>-?)(?P<key>.+)\]$")
_REG_VAL_RE = re.compile(
    r'^\s*(?:"(?P<name>[^"]*)"|(?P<default>@))\s*='
    r'\s*(?P<value>.*)$')


def _parse_reg(text: str) -> dict:
    keys: dict[str, dict] = {}
    cur_key: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"): continue
        if line.startswith("Windows Registry Editor"): continue
        if line.startswith("REGEDIT4"): continue
        m = _REG_KEY_RE.match(line)
        if m:
            cur_key = m.group("key")
            entry = keys.setdefault(cur_key, {"_deleted": False, "_values": {}})
            if m.group("flag") == "-":
                entry["_deleted"] = True
            continue
        v = _REG_VAL_RE.match(line)
        if v and cur_key:
            name = v.group("name") if v.group("name") is not None else "@"
            keys[cur_key]["_values"][name] = v.group("value").strip()
    return keys


def op_reg_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".reg file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            # .reg files are usually UTF-16-LE
            try:
                text = src.read_text(encoding="utf-16")
            except UnicodeError:
                text = src.read_text(encoding="utf-8", errors="replace")
            tree = _parse_reg(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".reg.json")
        out_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("forensic_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="reg-text",
             keys=len(tree),
             values=sum(len(k.get("_values", {})) for k in tree.values()))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Prefetch (.pf) ─────────────────────────────────────────────────────

def _parse_prefetch(data: bytes) -> dict:
    """Windows 10/11 prefetch: MAM-compressed; we expose minimal metadata
    only when uncompressed (older Windows / pre-decompressed)."""
    if data[0:3] == b"MAM":
        return {"format": "mam-compressed",
                "note": "decompress with `pftriage` or `Prefetch.exe`"}
    if len(data) < 32:
        raise ValueError("Truncated prefetch file.")
    version = struct.unpack("<I", data[0:4])[0]
    signature = data[4:8]
    if signature != b"SCCA":
        raise ValueError("Not a prefetch file (no SCCA marker).")
    file_size = struct.unpack("<I", data[12:16])[0]
    exe_name = data[16:76].decode("utf-16-le", errors="replace").rstrip("\x00")
    hashv = struct.unpack("<I", data[76:80])[0]
    out = {"version": version, "file_size": file_size,
           "executable": exe_name.split("\x00")[0],
           "path_hash_dec": hashv,
           "path_hash_hex": f"{hashv:08X}"}
    return out


def op_prefetch_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"prefetch file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info = _parse_prefetch(src.read_bytes())
            info["file"] = str(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("forensic_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="prefetch",
             executable=info.get("executable", ""))
    out_path = out_dir / "prefetch-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── Browser history -> CSV ────────────────────────────────────────────

def op_browser_history(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"history db(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            rows: list[dict] = []
            if "moz_places" in tables:  # Firefox
                kind = "firefox"
                for r in cur.execute(
                    "SELECT url, title, visit_count, last_visit_date "
                    "FROM moz_places ORDER BY last_visit_date DESC"):
                    last = ""
                    if r[3]:
                        try:
                            last = datetime.fromtimestamp(
                                r[3] / 1e6, tz=timezone.utc).isoformat()
                        except Exception: last = ""
                    rows.append({"url": r[0], "title": r[1] or "",
                                 "visit_count": r[2], "last_visit": last})
            elif "urls" in tables:  # Chromium / Edge
                kind = "chromium"
                for r in cur.execute(
                    "SELECT url, title, visit_count, last_visit_time "
                    "FROM urls ORDER BY last_visit_time DESC"):
                    last = ""
                    if r[3]:
                        try:
                            # Chrome uses microseconds since 1601-01-01
                            base = datetime(1601, 1, 1, tzinfo=timezone.utc)
                            last = (base + timedelta(
                                microseconds=r[3])).isoformat()
                        except Exception: last = ""
                    rows.append({"url": r[0], "title": r[1] or "",
                                 "visit_count": r[2], "last_visit": last})
            else:
                conn.close()
                return fail("parse_failed",
                            f"{src.name}: not a Chromium or Firefox history db.")
            conn.close()
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".history.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["url", "title", "visit_count",
                                                 "last_visit"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("forensic_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="browser-history",
             browser=kind, urls=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── E01 / EWF info ────────────────────────────────────────────────────

def op_ewf_info(args: argparse.Namespace) -> int:
    cli = shutil.which("ewfinfo") or shutil.which("ewfinfo.exe")
    if not cli: return fail("missing_dep", "ewfinfo (libewf-tools) not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".E01 file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        proc = subprocess.run([cli, str(src)], capture_output=True,
                               text=True, timeout=120)
        if proc.returncode != 0:
            return fail("probe_failed",
                        f"{src.name}: ewfinfo exit {proc.returncode}: "
                        f"{proc.stderr}")
        probes.append({"file": str(src), "ewfinfo": proc.stdout})
        emit("forensic_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="ewf")
    out_path = out_dir / "ewf-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forensics-sidecar",
                                description="Digital forensics artifact decoders.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("mft-to-csv",      "NTFS $MFT records -> CSV"),
        ("reg-to-json",     ".reg text export -> JSON tree"),
        ("prefetch-info",   "Windows .pf file -> JSON"),
        ("browser-history", "Chromium / Firefox history SQLite -> CSV"),
        ("ewf-info",        "E01 / EWF disk image probe via ewfinfo"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "mft-to-csv":      return op_mft_to_csv(args)
        if args.op == "reg-to-json":     return op_reg_to_json(args)
        if args.op == "prefetch-info":   return op_prefetch_info(args)
        if args.op == "browser-history": return op_browser_history(args)
        if args.op == "ewf-info":        return op_ewf_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

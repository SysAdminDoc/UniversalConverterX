"""Digital Audio Workstation (DAW) project sidecar.

Probe DAW project files for structural metadata (track count, plugins,
sample references) — full conversion across DAWs is rarely possible due
to plugin-specific state, so this sidecar focuses on read-only probes:

  * Ableton Live `.als` (gzipped XML)
  * FL Studio `.flp` (proprietary chunked binary)
  * REAPER `.rpp` (text-based S-expression-ish)
  * Logic Pro `.logicx` (bundle directory)
  * Audacity `.aup` / `.aup3` (XML / SQLite)
  * LMMS `.mmp` (XML)
  * Reason `.reason` / `.rns`
  * Bitwig `.bwproject`
  * Tracktion `.tracktion` / `.tracktionedit`
  * DAWproject `.dawproject` (open standard, bitwig-led)

Operations:
  als-info       Ableton .als (gunzip + XML walk) -> JSON probe.
  rpp-info       REAPER .rpp text -> JSON track / item summary.
  aup-info       Audacity .aup XML -> JSON probe.
  aup3-info      Audacity 3.x .aup3 SQLite -> JSON probe.
  flp-info       FL Studio .flp chunked-binary -> JSON probe (limited).
  mmp-info       LMMS .mmp XML -> JSON probe.
  dawproject-info DAWproject open-standard ZIP -> JSON probe.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Ableton Live .als ──────────────────────────────────────────────────

def _parse_als(path: Path) -> dict:
    with gzip.open(path, "rb") as f:
        data = f.read()
    root = ET.fromstring(data)
    info: dict = {"creator": root.get("Creator", ""),
                   "schema_change_count": root.get("SchemaChangeCount", "")}
    tracks = []
    for ttype in ("MidiTrack", "AudioTrack", "ReturnTrack", "GroupTrack",
                   "PreHearTrack"):
        for t in root.iter(ttype):
            name_el = t.find("Name/EffectiveName")
            tracks.append({
                "type": ttype,
                "name": (name_el.get("Value") if name_el is not None else ""),
            })
    info["tracks"] = tracks
    info["track_count"] = len(tracks)
    plugins: list[str] = []
    for plug in root.iter("PluginDesc"):
        for sub in plug.iter():
            if sub.tag in ("PlugName", "VST3Name", "VstName"):
                v = sub.get("Value", "")
                if v: plugins.append(v)
    info["plugins"] = sorted(set(plugins))
    return info


def op_als_info(args: argparse.Namespace) -> int:
    return _probe_loop(args, _parse_als, "ableton-als")


# ── REAPER .rpp ────────────────────────────────────────────────────────

_RPP_TRACK_RE = re.compile(r"^\s*<TRACK\b", re.MULTILINE)
_RPP_NAME_RE = re.compile(r'^\s*NAME\s+"([^"]*)"', re.MULTILINE)
_RPP_ITEM_RE = re.compile(r"^\s*<ITEM\b", re.MULTILINE)
_RPP_FX_RE = re.compile(r'<VST\s+\S+\s+"([^"]+)"', re.MULTILINE)


def _parse_rpp(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    tracks = len(_RPP_TRACK_RE.findall(text))
    items = len(_RPP_ITEM_RE.findall(text))
    fx_names = sorted(set(_RPP_FX_RE.findall(text)))
    track_names = _RPP_NAME_RE.findall(text)
    return {"tracks": tracks, "items": items,
            "fx_plugins": fx_names,
            "first_track_names": track_names[:50]}


def op_rpp_info(args): return _probe_loop(args, _parse_rpp, "reaper-rpp")


# ── Audacity .aup (XML) and .aup3 (SQLite) ─────────────────────────────

def _parse_aup_xml(path: Path) -> dict:
    tree = ET.parse(str(path))
    root = tree.getroot()
    rate = root.get("rate", "")
    audacity_version = root.get("audacityversion", "")
    tracks = []
    for t in root.iter("wavetrack"):
        tracks.append({
            "name": t.get("name", ""),
            "rate": t.get("rate", rate),
            "channels": t.get("channels", ""),
        })
    return {"audacity_version": audacity_version,
            "rate": rate,
            "tracks": tracks, "track_count": len(tracks)}


def op_aup_info(args): return _probe_loop(args, _parse_aup_xml, "audacity-aup")


def _parse_aup3(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cur = conn.cursor()
    try:
        rows = cur.execute("SELECT name, value FROM tags").fetchall()
        tags = {r[0]: r[1] for r in rows}
    except sqlite3.OperationalError:
        tags = {}
    try:
        track_count = cur.execute(
            "SELECT COUNT(*) FROM tracks").fetchone()[0]
    except sqlite3.OperationalError:
        track_count = 0
    try:
        block_count = cur.execute(
            "SELECT COUNT(*) FROM sampleblocks").fetchone()[0]
    except sqlite3.OperationalError:
        block_count = 0
    conn.close()
    return {"tags": tags, "track_count": track_count,
            "sampleblock_count": block_count}


def op_aup3_info(args): return _probe_loop(args, _parse_aup3, "audacity-aup3")


# ── FL Studio .flp (chunk reader) ──────────────────────────────────────

def _parse_flp(path: Path) -> dict:
    with path.open("rb") as f:
        magic = f.read(4)
        if magic != b"FLhd":
            raise ValueError(f"Not FL Studio (magic {magic!r}).")
        f.read(4)  # header size
        ftype = struct.unpack("<H", f.read(2))[0]
        channel_count = struct.unpack("<H", f.read(2))[0]
        ppq = struct.unpack("<H", f.read(2))[0]
        fldt = f.read(4)
        if fldt != b"FLdt":
            raise ValueError("Missing FLdt chunk.")
        data_size = struct.unpack("<I", f.read(4))[0]
    return {"flp_type": ftype, "channels": channel_count, "ppq": ppq,
            "data_size_bytes": data_size}


def op_flp_info(args): return _probe_loop(args, _parse_flp, "flstudio-flp")


# ── LMMS .mmp ──────────────────────────────────────────────────────────

def _parse_mmp(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".mmpz":
        # mmpz is gzipped
        with gzip.open(path, "rb") as f:
            text = f.read().decode("utf-8", errors="replace")
    root = ET.fromstring(text)
    head = root.find("head")
    head_meta = {
        "bpm": head.get("bpm", "") if head is not None else "",
        "master_pitch": head.get("masterpitch", "") if head is not None else "",
        "master_vol":  head.get("mastervol", "") if head is not None else "",
    }
    tracks = []
    for t in root.iter("track"):
        tracks.append({
            "name": t.get("name", ""), "type": t.get("type", ""),
            "muted": t.get("muted", "0") == "1",
        })
    return {"head": head_meta, "tracks": tracks,
            "track_count": len(tracks)}


def op_mmp_info(args): return _probe_loop(args, _parse_mmp, "lmms-mmp")


# ── DAWproject (open standard, ZIP-packaged) ───────────────────────────

def _parse_dawproject(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        info: dict = {"entries": names[:50], "entry_count": len(names)}
        if "metadata.xml" in names:
            try:
                meta_xml = z.read("metadata.xml").decode("utf-8",
                                                          errors="replace")
                meta_root = ET.fromstring(meta_xml)
                info["metadata"] = {c.tag: (c.text or "")
                                     for c in meta_root}
            except Exception:
                pass
        if "project.xml" in names:
            try:
                proj_xml = z.read("project.xml").decode("utf-8",
                                                          errors="replace")
                proj_root = ET.fromstring(proj_xml)
                tracks = list(proj_root.iter("Track"))
                info["track_count"] = len(tracks)
            except Exception:
                pass
    return info


def op_dawproject_info(args):
    return _probe_loop(args, _parse_dawproject, "dawproject")


# ── Generic probe loop ─────────────────────────────────────────────────

def _probe_loop(args, parser, source: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DAW file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info = parser(src)
            info["file"] = str(src)
            info["size_bytes"] = src.stat().st_size
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("daw_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source=source,
             tracks=info.get("track_count") or len(info.get("tracks", [])))
    out_path = out_dir / f"{source}-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dawproject-sidecar",
                                description="DAW project file probes.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("als-info",         "Ableton Live .als project probe"),
        ("rpp-info",         "REAPER .rpp project probe"),
        ("aup-info",         "Audacity .aup XML project probe"),
        ("aup3-info",        "Audacity 3.x .aup3 SQLite probe"),
        ("flp-info",         "FL Studio .flp project probe"),
        ("mmp-info",         "LMMS .mmp / .mmpz project probe"),
        ("dawproject-info",  "DAWproject open-standard ZIP probe"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "als-info":         return op_als_info(args)
        if args.op == "rpp-info":         return op_rpp_info(args)
        if args.op == "aup-info":         return op_aup_info(args)
        if args.op == "aup3-info":        return op_aup3_info(args)
        if args.op == "flp-info":         return op_flp_info(args)
        if args.op == "mmp-info":         return op_mmp_info(args)
        if args.op == "dawproject-info":  return op_dawproject_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Media playlist sidecar.

Mutually convert every common playlist format. We normalize each format
into a list of:
    {path, title, artist, length, album}
and re-serialize on the way out.

  * M3U / M3U8         (.m3u, .m3u8)         Winamp / VLC / iTunes
  * PLS                (.pls)                 Winamp INI-style
  * XSPF               (.xspf)                XML Shareable Playlist Format
  * WPL                (.wpl)                 Windows Media Player
  * ASX                (.asx)                 Microsoft Active Streaming
  * B4S                (.b4s)                 Winamp 3 / 5
  * iTunes Library     (.xml binary plist)    iTunes / Music.app
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields_) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields_}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


@dataclass
class Track:
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    length: int = -1   # seconds; -1 = unknown


# ── Readers ──────────────────────────────────────────────────────────────

def read_m3u(path: Path) -> list[Track]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[Track] = []
    pending_meta = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            pending_meta = ""; continue
        if line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF:"):
            pending_meta = line[len("#EXTINF:"):]
            continue
        if line.startswith("#"):
            continue
        # Track entry.
        title = artist = ""; length = -1
        if pending_meta:
            try:
                len_str, info = pending_meta.split(",", 1)
                length = int(len_str.strip()) if len_str.strip() else -1
                if " - " in info:
                    artist, title = info.split(" - ", 1)
                else:
                    title = info
            except Exception:
                pass
        out.append(Track(path=line, title=title.strip(),
                          artist=artist.strip(), length=length))
        pending_meta = ""
    return out


def read_pls(path: Path) -> list[Track]:
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(str(path), encoding="utf-8")
    tracks: dict[int, dict] = {}
    for section in cfg.sections():
        if section.lower() != "playlist": continue
        for k, v in cfg.items(section):
            for tag in ("file", "title", "length"):
                if k.startswith(tag):
                    n = int(k[len(tag):]) if k[len(tag):].isdigit() else 0
                    tracks.setdefault(n, {})[tag] = v
    return [Track(path=t.get("file", ""),
                  title=t.get("title", ""),
                  length=int(t.get("length", "-1") or "-1"))
            for n, t in sorted(tracks.items())]


def read_xspf(path: Path) -> list[Track]:
    tree = ET.parse(path); root = tree.getroot()
    ns = {"x": "http://xspf.org/ns/0/"}
    out: list[Track] = []
    for tr in root.iter():
        if not tr.tag.endswith("track"): continue
        loc = tr.findtext("./{*}location", "") or tr.findtext("./x:location", "", namespaces=ns)
        title = tr.findtext("./{*}title", "") or ""
        creator = tr.findtext("./{*}creator", "") or ""
        album = tr.findtext("./{*}album", "") or ""
        dur = tr.findtext("./{*}duration", "0") or "0"
        try: length = int(dur) // 1000  # XSPF uses ms
        except Exception: length = -1
        out.append(Track(path=loc.strip(), title=title.strip(),
                          artist=creator.strip(), album=album.strip(),
                          length=length))
    return out


def read_wpl(path: Path) -> list[Track]:
    """WPL is XML SMIL-flavored, used by Windows Media Player."""
    tree = ET.parse(path); root = tree.getroot()
    out: list[Track] = []
    for media in root.iter("media"):
        out.append(Track(path=media.get("src", "")))
    return out


def read_asx(path: Path) -> list[Track]:
    text = path.read_text(encoding="utf-8", errors="replace")
    # ASX is XML but case-insensitive and often malformed; normalize tag case.
    norm = text.lower()
    # Quick parse: find all <ref href="..."/>.
    out: list[Track] = []
    import re
    for m in re.finditer(r'<ref\s+href\s*=\s*"([^"]+)"', norm):
        out.append(Track(path=m.group(1)))
    return out


def read_b4s(path: Path) -> list[Track]:
    """Winamp 3/5 B4S is XML."""
    tree = ET.parse(path); root = tree.getroot()
    out: list[Track] = []
    for entry in root.iter("entry"):
        out.append(Track(path=entry.get("Playstring", ""),
                          title=entry.findtext("./Name", "") or ""))
    return out


def read_itunes_xml(path: Path) -> list[Track]:
    """iTunes Library .xml is a binary or XML plist."""
    import plistlib
    with path.open("rb") as f:
        obj = plistlib.load(f)
    tracks_obj = obj.get("Tracks", {})
    if not isinstance(tracks_obj, dict): return []
    out: list[Track] = []
    for _id, t in tracks_obj.items():
        if not isinstance(t, dict): continue
        out.append(Track(
            path=t.get("Location", ""),
            title=t.get("Name", ""),
            artist=t.get("Artist", ""),
            album=t.get("Album", ""),
            length=int((t.get("Total Time", 0) or 0) // 1000),
        ))
    return out


READERS = {
    ".m3u": read_m3u, ".m3u8": read_m3u,
    ".pls": read_pls,
    ".xspf": read_xspf,
    ".wpl": read_wpl,
    ".asx": read_asx,
    ".b4s": read_b4s,
    ".xml": read_itunes_xml,
}


# ── Writers ──────────────────────────────────────────────────────────────

def write_m3u(tracks: list[Track], path: Path) -> None:
    lines = ["#EXTM3U"]
    for t in tracks:
        meta = f"{t.length},{(t.artist + ' - ') if t.artist else ''}{t.title}"
        lines.append(f"#EXTINF:{meta}")
        lines.append(t.path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pls(tracks: list[Track], path: Path) -> None:
    lines = ["[playlist]", f"NumberOfEntries={len(tracks)}"]
    for i, t in enumerate(tracks, 1):
        lines.append(f"File{i}={t.path}")
        lines.append(f"Title{i}={t.title}")
        lines.append(f"Length{i}={t.length}")
    lines.append("Version=2")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_xspf(tracks: list[Track], path: Path) -> None:
    root = ET.Element("playlist", version="1", xmlns="http://xspf.org/ns/0/")
    track_list = ET.SubElement(root, "trackList")
    for t in tracks:
        tr = ET.SubElement(track_list, "track")
        ET.SubElement(tr, "location").text = t.path
        if t.title:   ET.SubElement(tr, "title").text = t.title
        if t.artist:  ET.SubElement(tr, "creator").text = t.artist
        if t.album:   ET.SubElement(tr, "album").text = t.album
        if t.length and t.length > 0:
            ET.SubElement(tr, "duration").text = str(t.length * 1000)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_wpl(tracks: list[Track], path: Path) -> None:
    root = ET.Element("smil")
    body = ET.SubElement(root, "body")
    seq = ET.SubElement(body, "seq")
    for t in tracks:
        ET.SubElement(seq, "media", src=t.path)
    path.write_bytes(b'<?wpl version="1.0"?>\n' +
                     ET.tostring(root, encoding="utf-8"))


def write_b4s(tracks: list[Track], path: Path) -> None:
    root = ET.Element("WinampXML")
    pl = ET.SubElement(root, "playlist", num_entries=str(len(tracks)),
                       label="UCX export")
    for i, t in enumerate(tracks):
        e = ET.SubElement(pl, "entry", Playstring=t.path)
        if t.title: ET.SubElement(e, "Name").text = t.title
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_csv(tracks: list[Track], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "title", "artist", "album", "length_seconds"])
        for t in tracks:
            w.writerow([t.path, t.title, t.artist, t.album, t.length])


def write_json(tracks: list[Track], path: Path) -> None:
    path.write_text(json.dumps([asdict(t) for t in tracks],
                                ensure_ascii=False, indent=2),
                     encoding="utf-8")


WRITERS = {
    "m3u":  write_m3u, "m3u8": write_m3u,
    "pls":  write_pls,
    "xspf": write_xspf,
    "wpl":  write_wpl,
    "b4s":  write_b4s,
    "csv":  write_csv,
    "json": write_json,
}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Playlist file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in WRITERS:
        return fail("bad_target", f"Choose: {sorted(WRITERS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="playlist", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        reader = READERS.get(ext)
        if not reader:
            return fail("bad_format", f"Unsupported source ext '{ext}'.")
        try:
            tracks = reader(src)
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + target)
        try:
            WRITERS[target](tracks, out_path)
        except Exception as ex:
            return fail("write_failed", f"{src.name}: {ex}")
        emit("playlist_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, track_count=len(tracks))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="playlist-sidecar",
                                description="Media playlist conversion (M3U / PLS / XSPF / WPL / ASX / B4S / iTunes XML).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert between playlist formats.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="m3u | m3u8 | pls | xspf | wpl | b4s | csv | json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

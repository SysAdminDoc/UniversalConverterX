"""Playlist extras sidecar (extends `playlist`).

Handles the playlist formats that aren't standard line-based:

  * iTunes Library .xml (Apple plist format) -> M3U / JSON / CSV
  * Spotify export JSON (e.g. exportify) -> M3U / CSV
  * Apple Music Library JSON -> M3U / CSV
  * Foobar2000 .fpl (binary) -> M3U (heuristic path extraction)

Operations:
  itunes-to-m3u   iTunes Library.xml -> M3U + per-playlist subset.
  itunes-to-json  iTunes Library.xml -> normalized JSON.
  spotify-to-m3u  exportify-style Spotify CSV/JSON -> M3U.
  spotify-to-csv  Spotify export JSON -> normalized CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import plistlib
import sys
import urllib.parse
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── iTunes Library.xml (plist) ─────────────────────────────────────────

def _load_itunes_plist(path: Path) -> dict:
    with path.open("rb") as f:
        return plistlib.load(f)


def _track_to_path(track: dict) -> str:
    loc = track.get("Location", "")
    if loc.startswith("file://"):
        return urllib.parse.unquote(loc[7:])
    return loc


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in s).strip()


def op_itunes_to_m3u(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"iTunes XML not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    written = 0
    for i, src in enumerate(inputs):
        try:
            data = _load_itunes_plist(src)
            tracks = data.get("Tracks", {})
            playlists = data.get("Playlists", [])
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        # whole library m3u
        all_paths = [_track_to_path(t) for t in tracks.values() if t.get("Location")]
        all_path = out_dir / (src.stem + "_all.m3u")
        all_path.write_text("#EXTM3U\n" + "\n".join(all_paths) + "\n",
                            encoding="utf-8")
        emit("playlist_extra",
             input=str(src), output=str(all_path),
             size_bytes=all_path.stat().st_size,
             format="m3u", source="itunes-xml",
             playlist="(All Tracks)", count=len(all_paths))
        written += 1
        # per-playlist m3u
        for pl in playlists:
            name = pl.get("Name", "Untitled")
            items = pl.get("Playlist Items", [])
            ids = [it.get("Track ID") for it in items if it.get("Track ID")]
            paths: list[str] = []
            for tid in ids:
                t = tracks.get(str(tid))
                if t and t.get("Location"): paths.append(_track_to_path(t))
            if not paths: continue
            pl_path = out_dir / (src.stem + "_" + _safe(name)[:60] + ".m3u")
            pl_path.write_text("#EXTM3U\n" + "\n".join(paths) + "\n",
                                encoding="utf-8")
            emit("playlist_extra",
                 input=str(src), output=str(pl_path),
                 size_bytes=pl_path.stat().st_size,
                 format="m3u", source="itunes-xml",
                 playlist=name, count=len(paths))
            written += 1
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=written)
    return 0


def op_itunes_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"iTunes XML not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = _load_itunes_plist(src)
            tracks = data.get("Tracks", {})
            normalized = {
                "library_persistent_id": data.get("Library Persistent ID"),
                "music_folder": data.get("Music Folder"),
                "tracks": [
                    {
                        "id": tid,
                        "name": t.get("Name"),
                        "artist": t.get("Artist"),
                        "album": t.get("Album"),
                        "genre": t.get("Genre"),
                        "duration_ms": t.get("Total Time"),
                        "track_number": t.get("Track Number"),
                        "year": t.get("Year"),
                        "play_count": t.get("Play Count", 0),
                        "rating": t.get("Rating"),
                        "path": _track_to_path(t),
                    } for tid, t in tracks.items()
                ],
                "playlists": [
                    {
                        "name": pl.get("Name"),
                        "id": pl.get("Playlist Persistent ID"),
                        "item_count": len(pl.get("Playlist Items", [])),
                        "track_ids": [it.get("Track ID")
                                      for it in pl.get("Playlist Items", [])],
                    } for pl in data.get("Playlists", [])
                ],
            }
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(normalized, indent=2, default=str),
                            encoding="utf-8")
        emit("playlist_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="itunes-xml",
             tracks=len(normalized["tracks"]),
             playlists=len(normalized["playlists"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Spotify export ─────────────────────────────────────────────────────

def _spotify_load(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list): return data
        if isinstance(data, dict) and "tracks" in data: return data["tracks"]
        if isinstance(data, dict) and "items" in data: return data["items"]
        return [data]
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8") as f:
            return list(csv.DictReader(f))
    raise ValueError(f"Unsupported Spotify export: {path.suffix}")


def op_spotify_to_m3u(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Spotify export not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tracks = _spotify_load(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".m3u")
        with out_path.open("w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for t in tracks:
                title = (t.get("Track Name") or t.get("name")
                         or t.get("track_name") or "Unknown")
                artist = (t.get("Artist Name(s)") or t.get("artist")
                          or t.get("artist_name") or "Unknown")
                duration = (t.get("Duration (ms)") or t.get("duration_ms")
                            or 0)
                try: secs = int(duration) // 1000
                except (TypeError, ValueError): secs = 0
                f.write(f"#EXTINF:{secs},{artist} - {title}\n")
                # Spotify URL or local path if user mapped it
                uri = (t.get("Spotify Track URI") or t.get("uri")
                       or t.get("track_uri") or t.get("Local Path") or "")
                f.write(uri + "\n")
        emit("playlist_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="m3u", source="spotify-export", count=len(tracks))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_spotify_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Spotify export not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tracks = _spotify_load(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".normalized.csv")
        keys = ["title", "artist", "album", "duration_ms", "uri",
                "added_at", "popularity"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for t in tracks:
                w.writerow({
                    "title":  t.get("Track Name") or t.get("name") or "",
                    "artist": t.get("Artist Name(s)") or t.get("artist") or "",
                    "album":  t.get("Album Name") or t.get("album") or "",
                    "duration_ms": t.get("Duration (ms)") or t.get("duration_ms") or "",
                    "uri":    t.get("Spotify Track URI") or t.get("uri") or "",
                    "added_at": t.get("Added At") or t.get("added_at") or "",
                    "popularity": t.get("Popularity") or t.get("popularity") or "",
                })
        emit("playlist_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="spotify-export", count=len(tracks))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="playlistmore-sidecar",
                                description="iTunes Library + Spotify export -> M3U / JSON / CSV.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("itunes-to-m3u",  "iTunes Library.xml -> M3U (whole + per-playlist)"),
        ("itunes-to-json", "iTunes Library.xml -> normalized JSON"),
        ("spotify-to-m3u", "Spotify export JSON/CSV -> M3U"),
        ("spotify-to-csv", "Spotify export JSON/CSV -> normalized CSV"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "itunes-to-m3u":  return op_itunes_to_m3u(args)
        if args.op == "itunes-to-json": return op_itunes_to_json(args)
        if args.op == "spotify-to-m3u": return op_spotify_to_m3u(args)
        if args.op == "spotify-to-csv": return op_spotify_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

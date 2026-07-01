"""Music notation conversion sidecar.

Cross-converts the major OSS notation interchange formats:

  * MusicXML (.musicxml, .mxl)
  * MIDI     (.mid, .midi)
  * ABC      (.abc)
  * MuseScore (.mscz, .mscx)  (read-only without MuseScore CLI; write via mscore3)
  * GuitarPro (.gp, .gp4, .gp5, .gpx)  -> MIDI / MusicXML

Backed by `music21` (BSD-3) for MusicXML <-> MIDI <-> ABC, plus optional
shellouts to `mscore`/`musescore3` for .mscz import/export, and `pygp` /
`guitarpro` for GuitarPro tab files.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_musescore() -> str | None:
    env = os.environ.get("MUSESCORE_PATH")
    if env and Path(env).is_file(): return env
    for n in ("mscore", "mscore3", "mscore4", "musescore3", "musescore4"):
        h = shutil.which(n) or shutil.which(n + ".exe")
        if h: return h
    for c in (
        r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
        r"C:\Program Files\MuseScore 3\bin\MuseScore3.exe",
        "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
        "/Applications/MuseScore 3.app/Contents/MacOS/mscore",
    ):
        if Path(c).is_file(): return c
    return None


def _read_with_music21(path: Path):
    from music21 import converter
    return converter.parse(str(path))


def _write_with_music21(score, path: Path) -> None:
    ext = path.suffix.lower()
    fmt_map = {".musicxml": "musicxml", ".mxl": "mxl",
               ".mid": "midi", ".midi": "midi",
               ".abc": "abc", ".pdf": "musicxml.pdf",
               ".png": "musicxml.png"}
    if ext not in fmt_map: raise ValueError(f"music21 cannot write {ext}")
    score.write(fmt_map[ext], fp=str(path))


def _read_guitarpro(path: Path):
    """GP3-GP5 / GPX via the `guitarpro` package -> music21 Score."""
    import guitarpro as gp
    from music21 import stream, note, tempo, meter
    song = gp.parse(str(path))
    score = stream.Score()
    if song.tempo:
        score.append(tempo.MetronomeMark(number=int(song.tempo)))
    for track in song.tracks:
        part = stream.Part(id=track.name or f"track_{track.number}")
        for measure in track.measures:
            for voice in measure.voices:
                for beat in voice.beats:
                    if not beat.notes:
                        part.append(note.Rest(quarterLength=4.0 / beat.duration.value))
                        continue
                    if len(beat.notes) > 1:
                        chord = note.Chord([n.value + 12 * (n.octave or 0)
                                             for n in beat.notes])
                        chord.quarterLength = 4.0 / beat.duration.value
                        part.append(chord)
                    else:
                        n = beat.notes[0]
                        nn = note.Note(midi=n.value + 40)
                        nn.quarterLength = 4.0 / beat.duration.value
                        part.append(nn)
        score.append(part)
    return score


def _via_musescore(src: Path, out_path: Path) -> int:
    """For .mscz / .mscx import or export, shell out to MuseScore."""
    mscore = _find_musescore()
    if not mscore:
        return fail("missing_musescore",
                    "MuseScore CLI not found. Install MuseScore 3/4 or set $env:MUSESCORE_PATH.")
    proc = subprocess.run([mscore, "-o", str(out_path), str(src)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("mscore_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Score file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="music", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        out_path = out_dir / (src.stem + target_ext)
        try:
            # Routes that go through music21:
            if ext in (".musicxml", ".mxl", ".mid", ".midi", ".abc"):
                if target_ext in (".musicxml", ".mxl", ".mid", ".midi", ".abc"):
                    score = _read_with_music21(src)
                    _write_with_music21(score, out_path)
                elif target_ext in (".mscz", ".mscx"):
                    # music21 -> MusicXML -> MuseScore CLI -> .mscz
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".musicxml", delete=False) as tmp:
                        tmp_path = Path(tmp.name)
                    try:
                        score = _read_with_music21(src)
                        _write_with_music21(score, tmp_path)
                        rc = _via_musescore(tmp_path, out_path)
                        if rc != 0: return rc
                    finally:
                        tmp_path.unlink(missing_ok=True)
                else:
                    return fail("bad_target", f"music21 cannot write {target_ext}")
            elif ext in (".gp", ".gp3", ".gp4", ".gp5", ".gpx"):
                score = _read_guitarpro(src)
                if target_ext in (".musicxml", ".mxl", ".mid", ".midi", ".abc"):
                    _write_with_music21(score, out_path)
                else:
                    return fail("bad_target",
                                f"GuitarPro -> {target_ext} not supported.")
            elif ext in (".mscz", ".mscx"):
                # Use MuseScore CLI for both directions if it's available.
                rc = _via_musescore(src, out_path)
                if rc != 0: return rc
            else:
                return fail("bad_format", f"Unsupported source ext '{ext}'.")
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("score_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             source=ext.lstrip("."), target=target_ext.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="music-sidecar",
                                description="Music notation conversion (MusicXML / MIDI / ABC / MuseScore / GuitarPro).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert between music notation formats.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="musicxml | mxl | mid | midi | abc | mscz | mscx | pdf | png")
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

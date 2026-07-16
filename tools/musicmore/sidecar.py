"""Music notation extras sidecar (extends `music`).

Wraps LilyPond and MuseScore CLI for round-trips that aren't reachable
through music21 alone:

  * LilyPond .ly  -> PDF / SVG / PNG / MIDI  (via `lilypond` CLI)
  * MusicXML <-> LilyPond .ly                 (via `musicxml2ly` + `ly2musicxml`)
  * MuseScore .mscz / .mscx -> MIDI / PDF / SVG / MusicXML  (via `mscore` CLI)
  * abc <-> MusicXML  (via abcm2ps / abc2xml)

Operations:
  ly-to-pdf       LilyPond -> PDF.
  ly-to-svg       LilyPond -> SVG (one per page).
  ly-to-midi      LilyPond -> MIDI.
  musicxml-to-ly  MusicXML -> LilyPond .ly.
  ly-to-musicxml  LilyPond -> MusicXML (best-effort).
  mscz-to-midi    MuseScore -> MIDI.
  mscz-to-pdf     MuseScore -> PDF.

Each op shells out to the appropriate external tool and surfaces
failures clearly when a CLI is missing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".exe")


def _shell(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _run_lilypond(args: argparse.Namespace, fmt: str) -> int:
    ly = _which("lilypond")
    if not ly: return fail("missing_dep", "lilypond not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".ly file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    fmt_flag = {"pdf": ["--pdf"], "svg": ["--svg"], "png": ["--png"],
                "midi": []}.get(fmt, [])
    total = len(inputs)
    for i, src in enumerate(inputs):
        out_stem = out_dir / src.stem
        cmd = [ly, *fmt_flag, "-o", str(out_stem), str(src)]
        proc = _shell(cmd)
        if proc.returncode != 0:
            return fail("render_failed",
                        f"{src.name}: lilypond exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        # lilypond produces <stem>.pdf / .svg / .png / .midi
        produced = list(out_dir.glob(src.stem + f".{fmt}*"))
        if fmt == "midi":
            produced = list(out_dir.glob(src.stem + ".mid*"))
        if not produced:
            return fail("render_failed",
                        f"{src.name}: lilypond produced no .{fmt} output.")
        out_path = produced[0]
        emit("score_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=fmt, source="lilypond")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_ly_to_pdf(args):  return _run_lilypond(args, "pdf")
def op_ly_to_svg(args):  return _run_lilypond(args, "svg")
def op_ly_to_midi(args): return _run_lilypond(args, "midi")


def op_musicxml_to_ly(args: argparse.Namespace) -> int:
    cli = _which("musicxml2ly")
    if not cli: return fail("missing_dep", "musicxml2ly not on PATH (ships with LilyPond).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MusicXML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".ly")
        cmd = [cli, "-o", str(out_path), str(src)]
        proc = _shell(cmd)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: musicxml2ly exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        emit("score_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="lilypond", source="musicxml")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_ly_to_musicxml(args: argparse.Namespace) -> int:
    """LilyPond -> MIDI (via lilypond) -> MusicXML (via music21).

    There's no direct ly2musicxml tool that's reliable. The most portable
    path is ly -> midi -> music21 -> musicxml.
    """
    try:
        from music21 import converter
    except ImportError:
        return fail("missing_dep",
                    "music21 not installed (`pip install music21`).")
    ly = _which("lilypond")
    if not ly: return fail("missing_dep", "lilypond not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".ly file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_stem = out_dir / src.stem
        proc = _shell([ly, "-o", str(out_stem), str(src)])
        if proc.returncode != 0:
            return fail("render_failed",
                        f"{src.name}: lilypond exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        midi_files = list(out_dir.glob(src.stem + ".mid*"))
        if not midi_files:
            return fail("render_failed",
                        f"{src.name}: lilypond produced no MIDI.")
        try:
            score = converter.parse(str(midi_files[0]))
            xml_path = out_dir / (src.stem + ".musicxml")
            score.write("musicxml", fp=str(xml_path))
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("score_extra",
             input=str(src), output=str(xml_path),
             size_bytes=xml_path.stat().st_size,
             format="musicxml", source="lilypond")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def _run_mscore(args: argparse.Namespace, target_ext: str) -> int:
    cli = _which("mscore") or _which("musescore") or _which("MuseScore4")
    if not cli: return fail("missing_dep",
                              "MuseScore CLI (mscore / musescore / MuseScore4) not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".mscz file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + target_ext)
        cmd = [cli, "-o", str(out_path), str(src)]
        proc = _shell(cmd, timeout=600)
        if proc.returncode != 0 or not out_path.is_file():
            return fail("convert_failed",
                        f"{src.name}: mscore exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        emit("score_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext, source="musescore")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_mscz_to_midi(args): return _run_mscore(args, "mid")
def op_mscz_to_pdf(args):  return _run_mscore(args, "pdf")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="musicmore-sidecar",
                                description="LilyPond + MuseScore notation conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("ly-to-pdf",      "LilyPond -> PDF"),
        ("ly-to-svg",      "LilyPond -> SVG"),
        ("ly-to-midi",     "LilyPond -> MIDI"),
        ("musicxml-to-ly", "MusicXML -> LilyPond"),
        ("ly-to-musicxml", "LilyPond -> MusicXML (via MIDI roundtrip)"),
        ("mscz-to-midi",   "MuseScore -> MIDI"),
        ("mscz-to-pdf",    "MuseScore -> PDF"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "ly-to-pdf":      return op_ly_to_pdf(args)
        if args.op == "ly-to-svg":      return op_ly_to_svg(args)
        if args.op == "ly-to-midi":     return op_ly_to_midi(args)
        if args.op == "musicxml-to-ly": return op_musicxml_to_ly(args)
        if args.op == "ly-to-musicxml": return op_ly_to_musicxml(args)
        if args.op == "mscz-to-midi":   return op_mscz_to_midi(args)
        if args.op == "mscz-to-pdf":    return op_mscz_to_pdf(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

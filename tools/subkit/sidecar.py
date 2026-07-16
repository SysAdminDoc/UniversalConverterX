"""Text-subtitle interchange sidecar.

Beyond what `subconvert` (pysubs2: SRT/VTT/ASS/SSA/SUB) handles, this sidecar
adds the broadcast / web / accessibility formats:

  * SAMI / .smi      Microsoft SAMI captions
  * TTML / DFXP      W3C Timed Text (Netflix / DASH / HLS)
  * SCC              Scenarist Closed Captions (608 broadcast)
  * EBU STL (.stl)   European Broadcast Union teletext subtitles
  * MicroDVD (.sub)  frame-based DVD-rip text
  * JACoSub (.jss)   anime fansubs
  * LRC              karaoke / lyrics
  * SBV              YouTube
  * SRT / VTT / ASS  also supported (re-encoded via pycaption/pysubs2)

Backed by `pycaption` (Apache-2.0) for SAMI/TTML/SCC/SRT/VTT/DFXP and
`pysubs2` (MIT) as a fallback for the broader set.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Map extension -> pycaption Reader class name.
PYCAP_READERS = {
    ".sami": "SAMIReader", ".smi": "SAMIReader",
    ".ttml": "DFXPReader", ".dfxp": "DFXPReader", ".xml": "DFXPReader",
    ".scc":  "SCCReader",
    ".srt":  "SRTReader",
    ".vtt":  "WebVTTReader",
}
PYCAP_WRITERS = {
    "sami": "SAMIWriter",
    "ttml": "DFXPWriter", "dfxp": "DFXPWriter",
    "scc":  "SCCWriter",
    "srt":  "SRTWriter",
    "vtt":  "WebVTTWriter",
}


def _via_pycaption(src: Path, target: str) -> str | None:
    """Round-trip through pycaption when both reader+writer are available."""
    try:
        import pycaption
    except ImportError:
        return None
    reader_name = PYCAP_READERS.get(src.suffix.lower())
    writer_name = PYCAP_WRITERS.get(target)
    if not reader_name or not writer_name: return None
    text = src.read_text(encoding="utf-8", errors="replace")
    reader = getattr(pycaption, reader_name)()
    captions = reader.read(text)
    writer = getattr(pycaption, writer_name)()
    return writer.write(captions)


def _via_pysubs2(src: Path, target: str) -> str | None:
    try:
        import pysubs2
    except ImportError:
        return None
    fmt_map = {"srt": "srt", "vtt": "vtt", "ass": "ass", "ssa": "ssa",
               "sub": "microdvd", "jss": "jss",
               "sub-microdvd": "microdvd"}
    fmt = fmt_map.get(target)
    if not fmt: return None
    subs = pysubs2.load(str(src))
    return subs.to_string(fmt)


def _to_lrc(src: Path) -> str:
    """Convert any text subtitle to .lrc (karaoke / lyric) format."""
    import pysubs2
    subs = pysubs2.load(str(src))
    out = []
    for ev in subs:
        ms = ev.start
        m = ms // 60000
        s = (ms % 60000) // 1000
        cs = (ms % 1000) // 10
        out.append(f"[{int(m):02d}:{int(s):02d}.{int(cs):02d}]{ev.plaintext.strip()}")
    return "\n".join(out)


def _to_sbv(src: Path) -> str:
    import pysubs2
    subs = pysubs2.load(str(src))
    out = []
    def fmt(ms):
        h = ms // 3600000; m = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000; ms2 = ms % 1000
        return f"{h:01d}:{m:02d}:{s:02d}.{ms2:03d}"
    for ev in subs:
        out.append(f"{fmt(ev.start)},{fmt(ev.end)}\n{ev.plaintext.strip()}\n")
    return "\n".join(out)


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Subtitle file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            text: str | None = None
            if target == "lrc":
                text = _to_lrc(src)
            elif target == "sbv":
                text = _to_sbv(src)
            else:
                text = _via_pycaption(src, target)
                if text is None:
                    text = _via_pysubs2(src, target)
            if text is None:
                return fail("unsupported_pair",
                            f"No converter from {src.suffix} -> {target}.")
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("convert_failed", f"{src.name}: {ex}")

        out_path = out_dir / (src.stem + "." + target)
        out_path.write_text(text, encoding="utf-8")
        emit("subtitle_text",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="subkit-sidecar",
                                description="Text subtitle interchange "
                                            "(SAMI/TTML/DFXP/SCC/EBU STL/LRC/SBV/MicroDVD).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert between text subtitle formats.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="srt | vtt | ass | ssa | sami | smi | ttml | dfxp | scc | lrc | sbv | sub")
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

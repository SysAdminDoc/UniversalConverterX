"""Audio metadata sidecar -- read / write / strip tags via mutagen.

Supports MP3 (ID3v2), FLAC (Vorbis), OGG/OPUS (Vorbis), M4A/MP4 (iTunes),
APE, WMA, WAV (RIFF INFO + ID3), AIFF.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _open(path: Path):
    try:
        from mutagen import File as MFile
    except ImportError:
        raise RuntimeError("mutagen not installed in this build.")
    f = MFile(str(path), easy=True)
    if f is None:
        raise RuntimeError(f"Unrecognised audio format: {path.name}")
    return f


def op_read(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Audio file not found: {args.input}")
    try:
        f = _open(src)
    except Exception as ex:
        return fail("read_failed", str(ex))

    tags = {}
    for k, v in (f.tags or {}).items():
        tags[str(k)] = list(v) if hasattr(v, "__iter__") and not isinstance(v, (str, bytes)) else str(v)
    info = f.info
    emit("audio_tag",
         path=str(src),
         length_seconds=float(getattr(info, "length", 0) or 0),
         bitrate=int(getattr(info, "bitrate", 0) or 0),
         sample_rate=int(getattr(info, "sample_rate", 0) or 0),
         channels=int(getattr(info, "channels", 0) or 0),
         tags=tags)
    emit("complete", output=str(src), size_bytes=src.stat().st_size)
    return 0


def op_write(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Audio file(s) not found: {missing}")

    pairs = {}
    for kv in (args.set or []):
        if "=" not in kv:
            return fail("bad_arg", f"--set expects key=value, got '{kv}'")
        k, v = kv.split("=", 1)
        pairs[k.strip()] = v.strip()
    drop = set(args.drop or [])

    total = len(inputs)
    emit("progress", percent=0, stage="tag", eta_seconds=None)
    for i, src in enumerate(inputs):
        try:
            f = _open(src)
            if f.tags is None:
                f.add_tags()
            for k, v in pairs.items():
                try: f[k] = v
                except Exception:
                    # Some formats reject specific keys via easy=; surface the rest.
                    emit("log", level="warn", message=f"{src.name}: cannot set '{k}'")
            for k in drop:
                if k in (f.tags or {}): del f[k]
            f.save()
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("write_failed", str(ex))
        emit("audio_tag",
             path=str(src),
             updated=list(pairs.keys()),
             dropped=list(drop))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"tagged {i+1}/{total}", eta_seconds=None)
    emit("complete", output="", size_bytes=0, count=total)
    return 0


def op_strip(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Audio file(s) not found: {missing}")
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            f = _open(src)
            f.delete()
        except Exception as ex:
            return fail("strip_failed", f"{src.name}: {ex}")
        emit("audio_tag", path=str(src), stripped=True)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"stripped {i+1}/{total}", eta_seconds=None)
    emit("complete", output="", size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="audiotag-sidecar",
                                description="Read / write / strip audio metadata via mutagen.")
    sub = p.add_subparsers(dest="op", required=True)

    r = sub.add_parser("read", help="Emit current tags + audio info.")
    r.add_argument("--input", required=True)

    w = sub.add_parser("write", help="Set tags on one or more audio files.")
    w.add_argument("--input", nargs="+", required=True)
    w.add_argument("--set", action="append",
                   help="Repeatable key=value (e.g. --set artist=Foo --set title=Bar).")
    w.add_argument("--drop", action="append",
                   help="Repeatable tag-key names to remove.")

    s = sub.add_parser("strip", help="Remove every tag block (ID3 / Vorbis / etc.)")
    s.add_argument("--input", nargs="+", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "read":  return op_read(args)
        if args.op == "write": return op_write(args)
        if args.op == "strip": return op_strip(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

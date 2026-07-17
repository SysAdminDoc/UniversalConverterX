"""edge-tts sidecar — NDJSON Microsoft Edge Neural TTS for the UCX Text-to-Speech module.

Wraps the `edge-tts` package (MIT, no API key) which streams speech audio from
the Microsoft Edge online TTS service. ~322 neural voices in 50+ languages.

Subcommands:
  list-voices   emit the voice catalog as NDJSON `voice` events
  speak         synthesize text to an audio file (mp3 native; transcoded to
                wav/ogg/flac via ffmpeg if installed)

Standard NDJSON contract: progress / log / complete / error events on stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit


# ── NDJSON helpers ───────────────────────────────────────────────────────────



def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


def progress(percent: float, stage: str = "", eta: int | None = None) -> None:
    payload: dict = {"percent": round(percent, 1), "stage": stage}
    if eta is not None:
        payload["eta_seconds"] = eta
    emit("progress", **payload)


# ── Bootstrap ────────────────────────────────────────────────────────────────

def _ensure_deps() -> None:
    """Require the build-bundled dependency without runtime installs."""
    try:
        import edge_tts  # noqa: F401
        return
    except ImportError:
        fail("missing_dep", "edge-tts is not bundled into this sidecar; runtime package installation is disabled.")
    sys.exit(1)


# ── list-voices ──────────────────────────────────────────────────────────────

async def _list_voices_async(filter_locale: str | None) -> int:
    import edge_tts  # type: ignore
    voices = await edge_tts.list_voices()
    count = 0
    for v in voices:
        # v keys typically: Name, ShortName, Gender, Locale, FriendlyName,
        # SuggestedCodec, Status, VoiceTag.
        short = v.get("ShortName", "")
        locale = v.get("Locale", "")
        if filter_locale and not locale.lower().startswith(filter_locale.lower()):
            continue
        emit(
            "voice",
            short_name=short,
            friendly_name=v.get("FriendlyName", short),
            gender=v.get("Gender", ""),
            locale=locale,
            categories=v.get("VoiceTag", {}).get("ContentCategories", []),
            personalities=v.get("VoiceTag", {}).get("VoicePersonalities", []),
        )
        count += 1
    emit("complete", voice_count=count)
    return 0


def op_list_voices(args: argparse.Namespace) -> int:
    return asyncio.run(_list_voices_async(args.locale))


# ── speak ────────────────────────────────────────────────────────────────────

def _format_rate(value: int) -> str:
    """edge-tts rate is signed percentage as a string, e.g. '+10%' or '-25%'."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}%"


def _format_pitch(value_hz: int) -> str:
    """edge-tts pitch is signed Hz string, e.g. '+25Hz' or '-50Hz'."""
    sign = "+" if value_hz >= 0 else ""
    return f"{sign}{value_hz}Hz"


def _format_volume(value: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}%"


async def _synthesize_async(args: argparse.Namespace, text: str, mp3_path: Path) -> int:
    import edge_tts  # type: ignore

    rate = _format_rate(args.rate)
    pitch = _format_pitch(args.pitch)
    volume = _format_volume(args.volume)

    log("info", f"Voice: {args.voice}  rate={rate}  pitch={pitch}  volume={volume}")
    progress(2.0, "connecting to Edge TTS")

    communicate = edge_tts.Communicate(
        text=text,
        voice=args.voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )

    # edge-tts streams audio as a sequence of byte chunks (MP3 by default).
    # We don't get a deterministic total size, so progress is "approximate":
    # report monotonically against bytes received.
    bytes_written = 0
    progress(8.0, "synthesizing")
    try:
        with mp3_path.open("wb") as out:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    data = chunk["data"]
                    out.write(data)
                    bytes_written += len(data)
                    # crude tick: emit every ~256 KB to keep watchdog alive
                    if bytes_written % (256 * 1024) < len(data):
                        progress(min(80.0, 8.0 + bytes_written / 1_500_000 * 70),
                                 f"synthesizing ({bytes_written // 1024} KB)")
    except Exception as exc:
        return fail("synthesis_failed", f"edge-tts failed: {exc}")

    if bytes_written == 0 or not mp3_path.exists() or mp3_path.stat().st_size == 0:
        return fail("empty_output", "edge-tts produced no audio data.")

    return 0


def _transcode_with_ffmpeg(src: Path, dst: Path) -> bool:
    """Transcode src (MP3) to dst (extension-driven). Returns True on success.

    Supported targets: wav, flac, ogg, opus, m4a (aac). MP3 is a no-op (the
    caller skips transcoding).
    """
    ffmpeg = shutil.which("ffmpeg") or os.environ.get("FFMPEG_PATH")
    if not ffmpeg:
        log("warn", "ffmpeg not on PATH — keeping MP3 output instead of "
                   f"transcoding to {dst.suffix}.")
        try:
            shutil.copyfile(src, dst.with_suffix(".mp3"))
        except Exception:
            pass
        return False

    ext = dst.suffix.lower()
    codec_args: list[str]
    if ext == ".wav":
        codec_args = ["-c:a", "pcm_s16le"]
    elif ext == ".flac":
        codec_args = ["-c:a", "flac"]
    elif ext == ".ogg":
        codec_args = ["-c:a", "libvorbis", "-q:a", "5"]
    elif ext == ".opus":
        codec_args = ["-c:a", "libopus", "-b:a", "96k"]
    elif ext in {".m4a", ".aac"}:
        codec_args = ["-c:a", "aac", "-b:a", "192k"]
    else:
        log("warn", f"Unknown target extension {ext!r}; using stream copy.")
        codec_args = ["-c:a", "copy"]

    cmd = [ffmpeg, "-y", "-i", str(src), *codec_args, str(dst)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log("error", f"ffmpeg transcode failed: {result.stderr.strip()[-400:]}")
        return False
    return True


def op_speak(args: argparse.Namespace) -> int:
    if not args.text and not args.input_file:
        return fail("no_input",
                    "Provide either --text \"...\" or --input-file <path>.")
    if args.input_file:
        in_path = Path(args.input_file)
        if not in_path.is_file():
            return fail("missing_input", f"Input text file not found: {in_path}")
        text = in_path.read_text(encoding="utf-8")
    else:
        text = args.text or ""

    text = text.strip()
    if not text:
        return fail("empty_text", "Input text was empty after stripping.")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    target_ext = out_path.suffix.lower()
    if target_ext == "":
        target_ext = ".mp3"
        out_path = out_path.with_suffix(target_ext)

    # Synthesise to a temp .mp3 (edge-tts native), then transcode if needed.
    with tempfile.TemporaryDirectory(prefix="ucx_edge_tts_") as tmp:
        mp3_path = Path(tmp) / "voice.mp3"

        rc = asyncio.run(_synthesize_async(args, text, mp3_path))
        if rc != 0:
            return rc

        if target_ext == ".mp3":
            shutil.copyfile(mp3_path, out_path)
        else:
            progress(85.0, f"transcoding to {target_ext.lstrip('.')}")
            ok = _transcode_with_ffmpeg(mp3_path, out_path)
            if not ok and not out_path.exists():
                # transcode failed; salvage by saving the MP3 alongside
                fallback = out_path.with_suffix(".mp3")
                shutil.copyfile(mp3_path, fallback)
                out_path = fallback

    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")

    progress(100.0, "done")
    emit(
        "complete",
        output=str(out_path),
        size_bytes=out_path.stat().st_size,
        voice=args.voice,
    )
    return 0


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="edge-tts-sidecar",
        description="UCX edge-tts sidecar — Microsoft Edge Neural TTS via the edge-tts package.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    lv = sub.add_parser("list-voices", help="Emit the voice catalog as NDJSON")
    lv.add_argument("--locale", default=None,
                    help="Optional locale prefix filter, e.g. 'en' or 'en-US'")

    sp = sub.add_parser("speak", help="Synthesize text to an audio file")
    sp.add_argument("--text", default=None,
                    help="Inline text to synthesize (mutually exclusive with --input-file)")
    sp.add_argument("--input-file", default=None,
                    help="UTF-8 text file to read instead of --text")
    sp.add_argument("--output", required=True,
                    help="Output audio path; extension drives format (.mp3/.wav/.flac/.ogg/.opus/.m4a)")
    sp.add_argument("--voice", default="en-US-AriaNeural",
                    help="ShortName from `list-voices` (default: en-US-AriaNeural)")
    sp.add_argument("--rate", type=int, default=0,
                    help="Speaking rate as percentage delta, -100..+200 (0 = neutral)")
    sp.add_argument("--pitch", type=int, default=0,
                    help="Pitch shift in Hz, -100..+100 (0 = neutral)")
    sp.add_argument("--volume", type=int, default=0,
                    help="Volume delta as percentage, -100..+100 (0 = neutral)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "list-voices":
            _ensure_deps()
            return op_list_voices(args)
        if args.op == "speak":
            _ensure_deps()
            return op_speak(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

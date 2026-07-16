"""Premium open-source TTS sidecar.

Three SOTA OSS engines, all bundled into one sidecar with a unified
`speak` op:

  * Kokoro-82M    (Hexgrad 2025, Apache-2.0, ~82 M params, single .onnx,
                   54 voices, 9 languages, fast on CPU)
  * F5-TTS        (HKUST 2024, MIT, zero-shot voice cloning from a 5-15 s
                   reference clip; transformer-based)
  * XTTS v2       (Coqui MPL-2.0, multilingual + voice cloning; legacy but
                   still strong)
  * Edge-TTS      (already shipped as a separate sidecar; this one is for
                   higher-fidelity / cloned / fully local voices)

Default = Kokoro because it has the best speed-to-quality ratio for non-
cloning use cases and runs entirely on CPU.

Usage:
  speak --backend kokoro --voice af_bella --text "Hello world."
  speak --backend f5     --reference my_voice.wav --reference-text "..." \
                         --text "..."
  speak --backend xtts   --voice <voice-id> --language en --text "..."
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


# Kokoro voice presets (see hexgrad/Kokoro-82M README for full list).
KOKORO_VOICES = [
    "af_bella", "af_sarah", "af_nicole", "af_sky",
    "am_adam", "am_michael",
    "bf_emma", "bf_isabella", "bm_george", "bm_lewis",
    "ja_alpha", "ja_beta",
    "zh_alpha", "zh_beta",
]


def op_speak_kokoro(args: argparse.Namespace) -> int:
    try:
        from kokoro import KPipeline
    except ImportError as ex:
        return fail("missing_kokoro",
                    f"kokoro not installed: {ex}. `pip install kokoro`.")
    try:
        import soundfile as sf
    except ImportError as ex:
        return fail("missing_soundfile", f"soundfile missing: {ex}.")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    text = args.text or (Path(args.text_file).read_text(encoding="utf-8") if args.text_file else "")
    if not text.strip():
        return fail("empty_text", "Provide --text or --text-file with content.")

    pipeline = KPipeline(lang_code=args.lang_code)
    started = time.monotonic()
    emit("progress", percent=0, stage="kokoro", eta_seconds=None)
    chunks = list(pipeline(text, voice=args.voice, speed=float(args.speed)))
    out_path = out_dir / (args.name + ".wav")

    import numpy as np
    audio = np.concatenate([c.audio for c in chunks if c.audio is not None]) if chunks else None
    if audio is None:
        return fail("no_audio", "Kokoro returned no audio.")
    sf.write(str(out_path), audio, 24000)

    emit("tts_audio",
         input=text[:80], output=str(out_path),
         size_bytes=out_path.stat().st_size,
         backend="kokoro", voice=args.voice,
         duration_seconds=float(len(audio) / 24000))
    emit("progress", percent=100, stage="done",
         eta_seconds=int(time.monotonic() - started))
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_speak_f5(args: argparse.Namespace) -> int:
    try:
        from f5_tts.api import F5TTS
    except ImportError as ex:
        return fail("missing_f5tts",
                    f"f5-tts not installed: {ex}. `pip install f5-tts`.")

    if not args.reference or not args.reference_text:
        return fail("bad_args",
                    "F5-TTS requires --reference (5-15s audio) and --reference-text.")
    ref = Path(args.reference)
    if not ref.is_file():
        return fail("missing_input", f"Reference audio not found: {ref}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    text = args.text or (Path(args.text_file).read_text(encoding="utf-8") if args.text_file else "")
    if not text.strip(): return fail("empty_text", "Provide --text.")

    started = time.monotonic()
    emit("progress", percent=0, stage="f5", eta_seconds=None)

    f5 = F5TTS()
    out_path = out_dir / (args.name + ".wav")
    try:
        wav, sr, _ = f5.infer(
            ref_file=str(ref),
            ref_text=args.reference_text,
            gen_text=text,
            file_wave=str(out_path),
            seed=args.seed if args.seed is not None else -1,
        )
    except Exception as ex:
        return fail("f5_failed", f"{ref.name}: {ex}")

    emit("tts_audio",
         input=text[:80], output=str(out_path),
         size_bytes=out_path.stat().st_size,
         backend="f5-tts",
         duration_seconds=float(len(wav) / max(1, sr)))
    emit("progress", percent=100, stage="done",
         eta_seconds=int(time.monotonic() - started))
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_speak_xtts(args: argparse.Namespace) -> int:
    try:
        from TTS.api import TTS  # coqui-ai/TTS
    except ImportError as ex:
        return fail("missing_xtts",
                    f"TTS (coqui) not installed: {ex}. `pip install TTS`.")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    text = args.text or (Path(args.text_file).read_text(encoding="utf-8") if args.text_file else "")
    if not text.strip(): return fail("empty_text", "Provide --text.")

    started = time.monotonic()
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False)
    out_path = out_dir / (args.name + ".wav")
    speaker_wav = args.reference if args.reference and Path(args.reference).is_file() else None
    tts.tts_to_file(text=text, language=args.language,
                    speaker_wav=speaker_wav,
                    speaker=args.voice if not speaker_wav else None,
                    file_path=str(out_path))
    emit("tts_audio",
         input=text[:80], output=str(out_path),
         size_bytes=out_path.stat().st_size,
         backend="xtts-v2", language=args.language,
         voice=args.voice or "(cloned)")
    emit("progress", percent=100, stage="done",
         eta_seconds=int(time.monotonic() - started))
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_voices(_args: argparse.Namespace) -> int:
    for v in KOKORO_VOICES:
        emit("tts_voice", backend="kokoro", id=v,
             language=v.split("_")[0])
    emit("tts_voice", backend="f5-tts", id="(any reference)",
         description="Zero-shot cloning -- any 5-15s reference clip works.")
    emit("tts_voice", backend="xtts-v2", id="(any reference)",
         description="Cloning + multilingual speaker pool.")
    emit("complete", output="", size_bytes=0, count=len(KOKORO_VOICES) + 2)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="premiumtts-sidecar",
                                description="Premium TTS (Kokoro / F5-TTS / XTTS v2).")
    sub = p.add_subparsers(dest="op", required=True)

    sp = sub.add_parser("speak", help="Synthesize text to audio.")
    sp.add_argument("--backend", default="kokoro",
                    choices=["kokoro", "f5", "xtts"])
    sp.add_argument("--text", default=None)
    sp.add_argument("--text-file", default=None, dest="text_file")
    sp.add_argument("--output-dir", required=True, dest="output_dir")
    sp.add_argument("--name", default="speech",
                    help="Output filename stem (default 'speech').")
    sp.add_argument("--voice", default="af_bella",
                    help=f"Kokoro voice id (one of {KOKORO_VOICES})")
    sp.add_argument("--lang-code", default="a", dest="lang_code",
                    help="Kokoro language code: a (en-us) | b (en-gb) | j (ja) | z (zh) | f (fr) | h (hi)")
    sp.add_argument("--speed", type=float, default=1.0)
    sp.add_argument("--reference", default=None,
                    help="(F5/XTTS) reference audio for zero-shot cloning.")
    sp.add_argument("--reference-text", default=None, dest="reference_text",
                    help="(F5) transcript of the reference audio.")
    sp.add_argument("--language", default="en",
                    help="(XTTS) target language code (en, es, fr, ...)")
    sp.add_argument("--seed", type=int, default=None)

    sub.add_parser("voices", help="Enumerate built-in voices.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "speak":
            if args.backend == "kokoro": return op_speak_kokoro(args)
            if args.backend == "f5":     return op_speak_f5(args)
            if args.backend == "xtts":   return op_speak_xtts(args)
            return fail("bad_backend", args.backend)
        if args.op == "voices": return op_voices(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

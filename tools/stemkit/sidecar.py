"""Stem separation sidecar -- music source separation via the
`audio-separator` package, which wraps multiple SOTA model families:

  * UVR-MDX-Net      (vocals / instrumental, fast)
  * MDX23 / Roformer (BS-Roformer, MelBand-Roformer -- best 4-stem 2024+)
  * Demucs v4        (htdemucs, htdemucs_ft, hdemucs_mmi)
  * VR Arch          (lower quality fallback, CPU-friendly)
  * Spleeter (legacy 2/4/5-stem)

The user picks a model name; we route it through the unified
`audio_separator.separator.Separator` API. Models are downloaded on first
use and cached under `~/.audio-separator/`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Convenience aliases so users don't need to memorize model filenames.
ALIASES: dict[str, str] = {
    "vocals":         "UVR-MDX-NET-Inst_HQ_3.onnx",
    "vocals-roformer":"model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    "4stem":          "htdemucs_ft.yaml",
    "4stem-fast":     "htdemucs.yaml",
    "6stem":          "htdemucs_6s.yaml",
    "karaoke":        "UVR_MDXNET_KARA_2.onnx",
    "denoise":        "UVR-DeNoise.pth",
    "dereverb":       "UVR-DeEcho-DeReverb.pth",
}


def _imports():
    try:
        from audio_separator.separator import Separator  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_audio_separator",
             message=f"audio-separator not installed: {ex}. "
                     "Install via `pip install audio-separator[gpu]` or `[cpu]`.")
        return False


def op_separate(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from audio_separator.separator import Separator

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Audio file(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    model_name = ALIASES.get(args.model, args.model)
    emit("log", level="info", message=f"Loading separator (model={model_name})...")
    sep = Separator(output_dir=str(out_dir), output_format=args.format.upper())
    try:
        sep.load_model(model_filename=model_name)
    except Exception as ex:
        return fail("load_failed", f"Model '{model_name}': {ex}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="separate", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            outputs = sep.separate(str(src))
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("separate_failed", f"{src.name}: {ex}")

        for produced in outputs:
            p = Path(produced) if Path(produced).is_absolute() else (out_dir / produced)
            emit("stem_track",
                 input=str(src), output=str(p),
                 size_bytes=p.stat().st_size if p.is_file() else 0,
                 model=model_name)

        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_models(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from audio_separator.separator import Separator
    sep = Separator()
    try:
        models = sep.list_supported_model_files()
    except Exception as ex:
        return fail("list_failed", str(ex))
    flat: list[dict[str, str]] = []
    if isinstance(models, dict):
        for arch, items in models.items():
            if isinstance(items, dict):
                for friendly, fname in items.items():
                    flat.append({"arch": str(arch),
                                 "name": str(friendly),
                                 "filename": str(fname)})
    emit("stem_models", count=len(flat), models=flat,
         aliases=[{"alias": k, "model": v} for k, v in ALIASES.items()])
    emit("complete", output="", size_bytes=0, count=len(flat))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stemkit-sidecar",
                                description="Music source separation (audio-separator).")
    sub = p.add_subparsers(dest="op", required=True)
    s = sub.add_parser("separate", help="Split audio into stems.")
    s.add_argument("--input", nargs="+", required=True)
    s.add_argument("--output-dir", required=True, dest="output_dir")
    s.add_argument("--model", default="4stem",
                   help=f"Model alias or filename. Aliases: {list(ALIASES.keys())}")
    s.add_argument("--format", default="wav",
                   choices=["wav", "flac", "mp3"],
                   help="Output stem format.")
    sub.add_parser("models", help="List downloadable models.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "separate": return op_separate(args)
        if args.op == "models":   return op_models(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

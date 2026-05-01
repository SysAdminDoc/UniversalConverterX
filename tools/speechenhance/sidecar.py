"""Speech enhancement sidecar -- DeepFilterNet (DFN3) state-of-the-art speech
denoising for monaural recordings (interviews / podcasts / voice memos).

DeepFilterNet outperforms RNNoise on noisy / reverberant speech but uses a
real-time neural network so it's slower (~5-15x real-time on CPU, faster on
GPU). For pure broadband noise on clean recordings, prefer the v2.4 RNNoise
sidecar (`rnnoise`). For challenging signals, use this one.
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


def _imports():
    try:
        from df.enhance import enhance, init_df  # noqa: F401
        import soundfile as sf  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_deepfilternet",
             message=f"DeepFilterNet (df) not installed: {ex}")
        return False


def op_enhance(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from df.enhance import enhance, init_df, load_audio, save_audio
    import soundfile as sf

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Audio file(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    emit("log", level="info", message=f"Loading DeepFilterNet model (post-filter atten={args.atten} dB)...")
    model, df_state, _ = init_df(post_filter=True, atten_lim_db=float(args.atten))
    emit("log", level="info",
         message=f"Model ready: sr={df_state.sr()} Hz, hop={df_state.hop_size()}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="enhance", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            audio, _meta = load_audio(str(src), sr=df_state.sr())
            cleaned = enhance(model, df_state, audio)
            out_path = out_dir / (src.stem + "_dfn3.wav")
            save_audio(str(out_path), cleaned, df_state.sr())
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("enhance_failed", f"{src.name}: {ex}")
        emit("speech_enhance",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             model="DeepFilterNet3",
             attenuation_db=float(args.atten))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="speechenhance-sidecar",
                                description="DeepFilterNet speech denoising.")
    sub = p.add_subparsers(dest="op", required=True)
    e = sub.add_parser("enhance", help="Denoise speech audio via DeepFilterNet.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    e.add_argument("--atten", type=float, default=100,
                   help="Attenuation limit in dB. 100 = full denoise; lower preserves more ambience.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "enhance": return op_enhance(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

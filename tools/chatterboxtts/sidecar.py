"""Pinned, offline-first Chatterbox Turbo voice-cloning sidecar."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_assets import (
    IntegrityError,
    LicenseNotAccepted,
    VerifiedAsset,
    download_verified,
    enforce_offline,
    validate_asset,
)
from ucx_sidecar import emit


MODEL_REVISION = "749d1c1a46eb10492095d68fbcf55691ccf137cd"
LICENSE = "MIT (Chatterbox and model weights)"


def _asset(filename: str, size: int, sha256: str) -> VerifiedAsset:
    return VerifiedAsset(
        asset_id=f"chatterbox-turbo/{filename}",
        filename=filename,
        url=f"https://huggingface.co/ResembleAI/chatterbox-turbo/resolve/{MODEL_REVISION}/{filename}?download=true",
        size_bytes=size,
        sha256=sha256,
        license=LICENSE,
    )


MODEL_ASSETS = (
    _asset("t3_turbo_v1.safetensors", 1_915_480_052, "fcf1f8c1d651bb7e3acd69ee5be269b4ac10c02980b7708213d598bc9f7cdf87"),
    _asset("s3gen_meanflow.safetensors", 1_064_875_036, "d65cb687a2ed581ee6cc297e919ffefa63386944f42364ae13b78a594945514f"),
    _asset("ve.safetensors", 5_695_784, "f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c"),
    _asset("added_tokens.json", 418, "72e4ab6acb0d9309ac3df4b526ae5fd80a2da5bc5ab7bb02d85096a374f69193"),
    _asset("merges.txt", 456_318, "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5"),
    _asset("special_tokens_map.json", 470, "92ba8063bf40aa163eadebbfe0de07c2aebe44cf0d4a9e8726580b0781fd2640"),
    _asset("tokenizer_config.json", 3_878, "bca16a2ac1ddbd78b8d6228f0031884cc74b6ea54b967d6f6d2ebae9ccde23e6"),
    _asset("vocab.json", 999_186, "f6bd25a65e4e63ca31360e9fb11c7e4f9a391a78385d640acd814092dd6eee4f"),
)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def model_dir(value: str | None) -> Path:
    base = Path(os.environ.get("UCX_MODEL_DIR") or Path.home() / ".cache" / "ucx" / "models")
    return Path(os.path.abspath(value)) if value else Path(os.path.abspath(base / "chatterboxtts"))


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _safe_directory(path: Path, *, create: bool = False) -> None:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or _is_reparse(path):
        raise IntegrityError(f"Directory is unavailable or is a link/reparse point: {path}")


def validate_model(root: Path) -> None:
    _safe_directory(root)
    for asset in MODEL_ASSETS:
        path = root / asset.filename
        if _is_reparse(path):
            raise IntegrityError(f"Model asset is a link/reparse point: {asset.asset_id}")
        validate_asset(path, asset)


def _output_path(root: Path, stem: str, reserved: set[str]) -> Path:
    for index in range(1, 10_001):
        suffix = "" if index == 1 else f"-{index}"
        candidate = root / f"{stem}_chatterbox{suffix}.wav"
        key = str(candidate).casefold()
        if key not in reserved and not candidate.exists():
            reserved.add(key)
            return candidate
    raise ValueError(f"Could not allocate a unique output name for {stem}.")


def _staging_path(output: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{output.stem}-", suffix=".part.wav", dir=output.parent)
    os.close(descriptor)
    return Path(name)


def op_install(args: argparse.Namespace) -> int:
    root = model_dir(args.model_dir)
    _safe_directory(root, create=True)
    total = sum(asset.size_bytes for asset in MODEL_ASSETS)
    complete = 0
    for asset in MODEL_ASSETS:
        base = complete
        download_verified(
            root,
            asset,
            accept_license=args.accept_license,
            progress=lambda current, _size, base=base: emit(
                "progress", percent=round((base + current) * 100 / total, 1),
                stage="model-download", eta_seconds=None),
        )
        complete += asset.size_bytes
    validate_model(root)
    emit("complete", output=str(root), size_bytes=total, count=len(MODEL_ASSETS))
    return 0


def op_probe(args: argparse.Namespace) -> int:
    root = model_dir(args.model_dir)
    try:
        validate_model(root)
    except IntegrityError as exc:
        return fail("model_unavailable", str(exc))
    emit("capability", name="chatterbox-turbo", available=True,
         model_revision=MODEL_REVISION, offline=True, voice_cloning=True,
         watermarked=True, language="en")
    emit("complete", output=str(root), size_bytes=sum(a.size_bytes for a in MODEL_ASSETS), count=1)
    return 0


def _read_text(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Input text file is unavailable or unsafe: {path}")
    if path.stat().st_size > 64 * 1024:
        raise ValueError(f"Input text exceeds the 64 KiB limit: {path.name}")
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ValueError(f"Input text is empty: {path.name}")
    if len(text) > 4_000:
        raise ValueError(f"Input text exceeds the 4,000-character generation limit: {path.name}")
    return text


def _device(requested: str) -> str:
    import torch
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is not available.")
    return requested


def op_speak(args: argparse.Namespace) -> int:
    enforce_offline()
    input_limit = 100 if args.reference else 101
    if len(args.input) > input_limit:
        return fail("too_many_inputs", "Select one reference-audio file and at most 100 text files.")
    root = model_dir(args.model_dir)
    validate_model(root)
    if not args.accept_voice_cloning:
        return fail("voice_consent_required", "Pass --accept-voice-cloning only with a voice you may use.")
    text_inputs = list(args.input)
    reference_value = args.reference
    if not reference_value:
        audio_extensions = {".wav", ".flac", ".mp3", ".m4a", ".ogg"}
        audio_inputs = [value for value in text_inputs if Path(value).suffix.lower() in audio_extensions]
        text_inputs = [value for value in text_inputs if Path(value).suffix.lower() not in audio_extensions]
        if len(audio_inputs) != 1 or not text_inputs:
            return fail("invalid_inputs", "Select exactly one reference-audio file plus one or more text files.")
        reference_value = audio_inputs[0]
    reference = Path(os.path.abspath(reference_value))
    if not reference.is_file() or reference.is_symlink():
        return fail("invalid_reference", "Voice-reference audio must be a regular local file.")
    if reference.stat().st_size > 100 * 1024 * 1024:
        return fail("invalid_reference", "Voice-reference audio exceeds the 100 MiB limit.")

    try:
        import torchaudio
        from chatterbox.tts_turbo import ChatterboxTurboTTS
    except ImportError as exc:
        return fail("missing_runtime", f"Install the pinned Chatterbox runtime: {exc}")

    device = _device(args.device)
    output_dir = Path(os.path.abspath(args.output_dir))
    _safe_directory(output_dir, create=True)
    engine = ChatterboxTurboTTS.from_local(root, device=device)
    started = time.monotonic()
    outputs: list[Path] = []
    reserved: set[str] = set()
    for index, value in enumerate(text_inputs, 1):
        source = Path(os.path.abspath(value))
        text = _read_text(source)
        output = _output_path(output_dir, source.stem, reserved)
        staging = _staging_path(output)
        emit("progress", percent=round((index - 1) * 100 / len(text_inputs), 1),
             stage="chatterbox-turbo", current=index, total=len(text_inputs), eta_seconds=None)
        try:
            audio = engine.generate(
                text,
                audio_prompt_path=str(reference),
                temperature=args.temperature,
                top_p=args.top_p,
                repetition_penalty=args.repetition_penalty,
            )
            torchaudio.save(str(staging), audio, engine.sr)
            if not staging.is_file() or staging.stat().st_size == 0:
                return fail("no_audio", f"Chatterbox did not produce audio for {source.name}.")
            os.replace(staging, output)
        finally:
            staging.unlink(missing_ok=True)
        outputs.append(output)
        emit("tts_audio", input=str(source), output=str(output), size_bytes=output.stat().st_size,
             backend="chatterbox-turbo", language="en", watermarked=True)
    emit("progress", percent=100, stage="done", eta_seconds=int(time.monotonic() - started))
    emit("complete", output=str(output_dir), size_bytes=sum(path.stat().st_size for path in outputs), count=len(outputs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Chatterbox Turbo voice cloning with PerTh watermarking.")
    sub = parser.add_subparsers(dest="op", required=True)
    install = sub.add_parser("install-model", help="Install the exact reviewed Chatterbox Turbo assets.")
    install.add_argument("--accept-license", action="store_true")
    install.add_argument("--model-dir")
    probe = sub.add_parser("probe", help="Verify every pinned local model asset.")
    probe.add_argument("--model-dir")
    speak = sub.add_parser("speak", help="Clone a consented reference voice for UTF-8 text files.")
    speak.add_argument("--input", nargs="+", required=True)
    speak.add_argument("--output-dir", required=True)
    speak.add_argument("--model-dir")
    speak.add_argument("--reference", help="Reference audio, or select exactly one audio file with the text inputs.")
    speak.add_argument("--accept-voice-cloning", action="store_true")
    speak.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    speak.add_argument("--temperature", type=float, choices=[0.6, 0.7, 0.8, 0.9, 1.0], default=0.8)
    speak.add_argument("--top-p", type=float, choices=[0.8, 0.9, 0.95, 1.0], default=0.95)
    speak.add_argument("--repetition-penalty", type=float, choices=[1.0, 1.1, 1.2, 1.3], default=1.2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "install-model":
            return op_install(args)
        if args.op == "probe":
            return op_probe(args)
        if args.op == "speak":
            return op_speak(args)
        return fail("unknown_op", args.op)
    except IntegrityError as exc:
        return fail("model_integrity", str(exc))
    except LicenseNotAccepted as exc:
        return fail("license_not_accepted", str(exc))
    except Exception as exc:
        if os.environ.get("UCX_DEBUG") == "1":
            traceback.print_exc(file=sys.stderr)
        return fail("internal", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())

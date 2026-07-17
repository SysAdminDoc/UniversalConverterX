"""Pinned, offline-first Dia2 1B dialogue text-to-speech sidecar."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor"))
sys.path.insert(0, str(HERE.parent / "_lib"))
from ucx_assets import (
    IntegrityError,
    LicenseNotAccepted,
    VerifiedAsset,
    download_verified,
    enforce_offline,
    validate_asset,
)
from ucx_sidecar import emit


MODEL_REVISION = "00042629c61c3268a6473552c911966ec7a5a450"
MIMI_REVISION = "89091b3e466eb6a9d11e537bf26b144f194978f7"
DIA_LICENSE = "Apache-2.0"
MIMI_LICENSE = "CC-BY-4.0"


def _asset(filename: str, size: int, sha256: str) -> VerifiedAsset:
    return VerifiedAsset(
        asset_id=f"dia2-1b/{filename}",
        filename=filename,
        url=f"https://huggingface.co/nari-labs/Dia2-1B/resolve/{MODEL_REVISION}/{filename}?download=true",
        size_bytes=size,
        sha256=sha256,
        license=DIA_LICENSE,
    )


DIA_ASSETS = (
    _asset("model.safetensors", 4_305_028_488, "c398c607b159f024dfb76c6102244afe53b01daf18676af8408a3a0bb97d1c76"),
    _asset("config.json", 1_760, "ecc555f1fb4d6d47bf6b9bf01ea9aec61b4a638ae3d5af4d0f01eab67a743c29"),
    _asset("added_tokens.json", 1_156, "e6407562f41f7ca0948082446ef6439c0bb2b2c46a314df17f067ecdc0c8c160"),
    _asset("merges.txt", 466_391, "0b54e8aa4e53d5383e2e4bc635a56b43f9647f7b13832d5d9ecd8f82dac4f510"),
    _asset("special_tokens_map.json", 7_923, "c1fd3b95eeae0a8d7e6f5d4f893d6a657a32eef6a6a6b5d941c742e844df70af"),
    _asset("tokenizer.json", 3_532_285, "7931199d153b72035a0b3acf7bfd276266248a0b6c5e9a5a25d233ca1424846c"),
    _asset("tokenizer_config.json", 13_337, "02b56f0084d1192d2402abb2885f509db5cfe93a855fc05816ea5e2d4ff27171"),
    _asset("vocab.json", 800_662, "82b84012e3add4d01d12ba14442026e49b8cbbaead1f79ecf3d919784f82dc79"),
)


def _mimi_asset(filename: str, size: int, sha256: str) -> VerifiedAsset:
    return VerifiedAsset(
        asset_id=f"mimi/{filename}",
        filename=filename,
        url=f"https://huggingface.co/kyutai/mimi/resolve/{MIMI_REVISION}/{filename}?download=true",
        size_bytes=size,
        sha256=sha256,
        license=MIMI_LICENSE,
    )


MIMI_ASSETS = (
    _mimi_asset("model.safetensors", 384_649_828, "bac7e85083dcded655d24eaadde7e6eea34c0da1b35fa2d284e641bd2b942a5e"),
    _mimi_asset("config.json", 1_117, "aca6f44b04f7bc2e7466b71597d2d51e463ed1cf3cd7025d8848595580546c36"),
    _mimi_asset("preprocessor_config.json", 234, "fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb"),
)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def model_dir(value: str | None) -> Path:
    base = Path(os.environ.get("UCX_MODEL_DIR") or Path.home() / ".cache" / "ucx" / "models")
    return Path(os.path.abspath(value)) if value else Path(os.path.abspath(base / "dia2tts"))


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
    _safe_directory(root / "mimi")
    for asset in DIA_ASSETS:
        path = root / asset.filename
        if _is_reparse(path):
            raise IntegrityError(f"Model asset is a link/reparse point: {asset.asset_id}")
        validate_asset(path, asset)
    for asset in MIMI_ASSETS:
        path = root / "mimi" / asset.filename
        if _is_reparse(path):
            raise IntegrityError(f"Model asset is a link/reparse point: {asset.asset_id}")
        validate_asset(path, asset)


def _output_path(root: Path, stem: str, reserved: set[str]) -> Path:
    for index in range(1, 10_001):
        suffix = "" if index == 1 else f"-{index}"
        candidate = root / f"{stem}_dia2{suffix}.wav"
        key = str(candidate).casefold()
        if key not in reserved and not candidate.exists():
            reserved.add(key)
            return candidate
    raise ValueError(f"Could not allocate a unique output name for {stem}.")


def _staging_path(output: Path) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{output.stem}-", suffix=".part.wav", dir=output.parent)
    os.close(descriptor)
    Path(name).unlink(missing_ok=True)
    return Path(name)


def op_install(args: argparse.Namespace) -> int:
    root = model_dir(args.model_dir)
    _safe_directory(root, create=True)
    _safe_directory(root / "mimi", create=True)
    total = sum(asset.size_bytes for asset in (*DIA_ASSETS, *MIMI_ASSETS))
    complete = 0
    for destination, assets in ((root, DIA_ASSETS), (root / "mimi", MIMI_ASSETS)):
        for asset in assets:
            base = complete
            download_verified(
                destination,
                asset,
                accept_license=args.accept_license,
                progress=lambda current, _size, base=base: emit(
                    "progress", percent=round((base + current) * 100 / total, 1),
                    stage="model-download", eta_seconds=None),
            )
            complete += asset.size_bytes
    validate_model(root)
    emit("complete", output=str(root), size_bytes=total, count=len(DIA_ASSETS) + len(MIMI_ASSETS))
    return 0


def op_probe(args: argparse.Namespace) -> int:
    root = model_dir(args.model_dir)
    try:
        validate_model(root)
    except IntegrityError as exc:
        return fail("model_unavailable", str(exc))
    emit("capability", name="dia2-1b", available=True, model_revision=MODEL_REVISION,
         offline=True, dialogue=True, voice_conditioning=False, language="en")
    emit("complete", output=str(root), size_bytes=sum(a.size_bytes for a in (*DIA_ASSETS, *MIMI_ASSETS)), count=1)
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
    return text if "[S1]" in text or "[S2]" in text else f"[S1] {text}"


def _device(requested: str) -> str:
    import torch
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is not available.")
    return requested


def op_speak(args: argparse.Namespace) -> int:
    enforce_offline()
    if len(args.input) > 100:
        return fail("too_many_inputs", "A single batch may contain at most 100 text files.")
    root = model_dir(args.model_dir)
    validate_model(root)

    try:
        from dia2 import Dia2, GenerationConfig, SamplingConfig
    except ImportError as exc:
        return fail("missing_runtime", f"Install the pinned Dia2 dependencies: {exc}")

    device = _device(args.device)
    output_dir = Path(os.path.abspath(args.output_dir))
    _safe_directory(output_dir, create=True)
    engine = Dia2.from_local(
        root / "config.json", root / "model.safetensors", tokenizer_id=root,
        mimi_id=str(root / "mimi"), device=device, dtype="bfloat16" if device == "cuda" else "float32")
    config = GenerationConfig(
        cfg_scale=args.cfg_scale,
        audio=SamplingConfig(temperature=args.temperature, top_k=args.top_k),
        use_cuda_graph=device == "cuda",
    )
    started = time.monotonic()
    outputs: list[Path] = []
    reserved: set[str] = set()
    for index, value in enumerate(args.input, 1):
        source = Path(os.path.abspath(value))
        text = _read_text(source)
        output = _output_path(output_dir, source.stem, reserved)
        staging = _staging_path(output)
        emit("progress", percent=round((index - 1) * 100 / len(args.input), 1),
             stage="dia2", current=index, total=len(args.input), eta_seconds=None)
        try:
            engine.generate(text, config=config, output_wav=staging)
            if not staging.is_file() or staging.stat().st_size == 0:
                return fail("no_audio", f"Dia2 did not produce audio for {source.name}.")
            os.replace(staging, output)
        finally:
            staging.unlink(missing_ok=True)
        outputs.append(output)
        emit("tts_audio", input=str(source), output=str(output), size_bytes=output.stat().st_size,
             backend="dia2-1b", language="en")
    emit("progress", percent=100, stage="done", eta_seconds=int(time.monotonic() - started))
    emit("complete", output=str(output_dir), size_bytes=sum(path.stat().st_size for path in outputs), count=len(outputs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Dia2 1B dialogue text-to-speech.")
    sub = parser.add_subparsers(dest="op", required=True)
    install = sub.add_parser("install-model", help="Install the exact reviewed Dia2 1B and Mimi assets.")
    install.add_argument("--accept-license", action="store_true")
    install.add_argument("--model-dir")
    probe = sub.add_parser("probe", help="Verify every pinned local model asset.")
    probe.add_argument("--model-dir")
    speak = sub.add_parser("speak", help="Generate local dialogue audio from UTF-8 text files.")
    speak.add_argument("--input", nargs="+", required=True)
    speak.add_argument("--output-dir", required=True)
    speak.add_argument("--model-dir")
    speak.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    speak.add_argument("--temperature", type=float, choices=[0.6, 0.7, 0.8, 0.9], default=0.8)
    speak.add_argument("--top-k", type=int, choices=[25, 50, 100], default=50)
    speak.add_argument("--cfg-scale", type=float, choices=[1.0, 2.0, 3.0, 4.0], default=2.0)
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
        return fail("internal", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())

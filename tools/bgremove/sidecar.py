"""Modern image background-removal sidecar.

Routes to local segmentation models under their individual licenses:

  * BiRefNet           (CVPR 2024 -- most accurate dichotomous segmentation)
  * RMBG-2.0           (BRIA AI -- gated BRIA model license)
  * RMBG-1.4           (BRIA AI -- non-commercial model license)
  * IS-Net             (DIS-1.0 / 5K -- best on hair / fur details)
  * U2Net (rembg)      (legacy, fastest, smallest model)
  * SAM 2              (Meta 2024 -- promptable, but auto-mode used here)

Default backend = "birefnet" because it has the cleanest hair edges and
generalizes well to product / portrait / e-commerce shots.

Output: per input image, an `<stem>_nobg.png` with alpha channel.

Transformers backends never load a mutable Hugging Face cache. They require an
explicitly consented local pack whose full repository revision, executable
Python, configuration, and safetensors weights match model-packs.json. Inference
re-verifies the pack and imports its reviewed code through a fresh private module
cache with network access disabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from ucx_assets import enforce_offline


_HERE = Path(__file__).resolve().parent
_MODEL_MANIFEST = _HERE / "model-packs.json"
_VERIFIED_BACKENDS = frozenset({
    "birefnet", "birefnet-portrait", "birefnet-matting", "rmbg2", "rmbg14",
})
_PACK_MARKER = ".ucx-model.json"


class ModelPackError(RuntimeError):
    """The selected executable model pack is absent or failed integrity checks."""




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _model_manifest(path: Path = _MODEL_MANIFEST) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    packs = payload.get("packs")
    if payload.get("schemaVersion") != 1 or not isinstance(packs, list):
        raise ModelPackError("Unsupported background-removal model-pack manifest.")
    by_backend = {pack.get("backend"): pack for pack in packs if isinstance(pack, dict)}
    if set(by_backend) != _VERIFIED_BACKENDS:
        raise ModelPackError("The model-pack manifest does not cover every executable backend.")
    return payload


def _pack_for_backend(backend: str) -> dict:
    for pack in _model_manifest()["packs"]:
        if pack["backend"] == backend:
            return pack
    raise ModelPackError(f"No verified model pack is defined for backend '{backend}'.")


def _model_root(configured: str | Path | None = None) -> Path:
    value = configured or os.environ.get("UCX_MODEL_DIR")
    base = Path(value).expanduser() if value else Path.home() / ".cache" / "ucx" / "models"
    return (base if base.name == "bgremove" else base / "bgremove").resolve()


def _model_dir(backend: str, configured: str | Path | None = None) -> Path:
    return _model_root(configured) / backend


def _safe_pack_path(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or not relative or ".." in rel.parts:
        raise ModelPackError(f"Unsafe model-pack path: {relative!r}")
    target = (root / rel).resolve()
    if root.resolve() not in target.parents:
        raise ModelPackError(f"Model-pack path escapes its root: {relative!r}")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_pack_directory(pack: dict, directory: Path) -> Path:
    if not directory.is_dir() or directory.is_symlink():
        raise ModelPackError(
            f"{pack['backend']} model pack is not installed at {directory}. "
            "Use download-model --accept-license first.")

    expected = {item["path"] for item in pack["files"]}
    allowed = expected | {_PACK_MARKER}
    actual: set[str] = set()
    for item in directory.rglob("*"):
        if item.is_symlink():
            raise ModelPackError(f"Model packs cannot contain links: {item}")
        if item.is_file():
            actual.add(item.relative_to(directory).as_posix())
    extras = sorted(actual - allowed)
    if extras:
        raise ModelPackError(
            "Model pack contains non-allowlisted files: " + ", ".join(extras))

    marker_path = directory / _PACK_MARKER
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelPackError("Model pack provenance marker is missing or invalid.") from exc
    if (marker.get("modelId") != pack["modelId"]
            or marker.get("revision") != pack["revision"]
            or marker.get("backend") != pack["backend"]):
        raise ModelPackError("Model pack provenance does not match the pinned manifest.")

    for spec in pack["files"]:
        path = _safe_pack_path(directory, spec["path"])
        if not path.is_file() or path.is_symlink():
            raise ModelPackError(f"Model pack is missing {spec['path']}.")
        size = path.stat().st_size
        if size != spec["bytes"]:
            raise ModelPackError(
                f"{spec['path']} size mismatch: expected {spec['bytes']}, got {size}.")
        if "sha256" in spec:
            actual_hash = _sha256(path)
            expected_hash = spec["sha256"].lower()
            if actual_hash != expected_hash:
                raise ModelPackError(
                    f"{spec['path']} SHA-256 mismatch: expected {expected_hash}, "
                    f"got {actual_hash}.")
        elif "gitBlobSha1" in spec:
            actual_hash = _git_blob_sha1(path)
            expected_hash = spec["gitBlobSha1"].lower()
            if actual_hash != expected_hash:
                raise ModelPackError(
                    f"{spec['path']} Git blob digest mismatch: expected {expected_hash}, "
                    f"got {actual_hash}.")
        else:
            raise ModelPackError(f"{spec['path']} has no approved content digest.")
    return directory


def _verify_model_pack(
    backend: str,
    configured: str | Path | None = None,
) -> Path:
    pack = _pack_for_backend(backend)
    return _validate_pack_directory(pack, _model_dir(backend, configured))


def _install_model_pack(stage: Path, target: Path, pack: dict) -> None:
    cache = stage / ".cache"
    if cache.exists():
        shutil.rmtree(cache)
    marker = {
        "schemaVersion": 1,
        "backend": pack["backend"],
        "modelId": pack["modelId"],
        "revision": pack["revision"],
        "license": pack["license"],
    }
    (stage / _PACK_MARKER).write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    _validate_pack_directory(pack, stage)

    backup = target.with_name(target.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(stage, target)
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def op_download_model(args: argparse.Namespace) -> int:
    pack = _pack_for_backend(args.backend)
    if not args.accept_license:
        return fail(
            "model_license_required",
            f"Review {pack['license']} at {pack['licenseUrl']} and re-run with "
            "--accept-license.")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        return fail("missing_dep", f"huggingface-hub is required: {exc}")

    target = _model_dir(args.backend, args.model_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{args.backend}-", dir=target.parent))
    emit("progress", percent=1.0, stage="downloading pinned model pack", eta_seconds=None)
    try:
        snapshot_download(
            repo_id=pack["modelId"],
            revision=pack["revision"],
            local_dir=str(stage),
            allow_patterns=[item["path"] for item in pack["files"]],
        )
        emit("progress", percent=95.0, stage="verifying model pack", eta_seconds=None)
        _install_model_pack(stage, target, pack)
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        suffix = (
            " Accept the gated repository terms and configure HF_TOKEN first."
            if pack.get("gated") else "")
        return fail("model_download_failed", f"{exc}{suffix}")
    emit("progress", percent=100.0, stage="model ready", eta_seconds=0)
    emit(
        "complete",
        output=str(target),
        backend=args.backend,
        model=pack["modelId"],
        revision=pack["revision"],
        size_bytes=sum(item["bytes"] for item in pack["files"]),
    )
    return 0


def _segment_birefnet(images, model_dir: Path, device: str):
    """Yield (path, RGBA Pillow Image) for each input."""
    with tempfile.TemporaryDirectory(prefix="ucx-bgremove-module-cache-") as module_cache:
        previous_cache = os.environ.get("HF_MODULES_CACHE")
        os.environ["HF_MODULES_CACHE"] = module_cache
        try:
            import torch
            from PIL import Image
            from torchvision import transforms
            from transformers import AutoModelForImageSegmentation

            dtype = torch.bfloat16 if device == "cuda" else torch.float32
            model = AutoModelForImageSegmentation.from_pretrained(
                str(model_dir),
                trust_remote_code=True,
                torch_dtype=dtype,
                local_files_only=True,
                use_safetensors=True,
                cache_dir=module_cache,
            )
            model.to(device).eval()

            tfm = transforms.Compose([
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize(
                    [0.485, 0.456, 0.406],
                    [0.229, 0.224, 0.225],
                ),
            ])

            for path in images:
                img = Image.open(str(path)).convert("RGB")
                x = tfm(img).unsqueeze(0).to(device, dtype=dtype)
                with torch.inference_mode():
                    preds = model(x)[-1].sigmoid().cpu()
                mask = preds[0].squeeze().float().numpy()
                mask_img = Image.fromarray((mask * 255).astype("uint8")).resize(img.size)
                rgba = img.convert("RGBA")
                rgba.putalpha(mask_img)
                yield path, rgba
        finally:
            if previous_cache is None:
                os.environ.pop("HF_MODULES_CACHE", None)
            else:
                os.environ["HF_MODULES_CACHE"] = previous_cache


def _segment_rembg(images, model_name: str):
    """Legacy U2Net path via the `rembg` package."""
    filenames = {
        "u2net": ("u2net.onnx",),
        "u2netp": ("u2netp.onnx",),
        "u2net_human_seg": ("u2net_human_seg.onnx",),
        "isnet-general-use": ("isnet-general-use.onnx",),
        "isnet-anime": ("isnet-anime.onnx",),
        "silueta": ("silueta.onnx",),
        "sam": ("sam_vit_b_01ec64.encoder.onnx", "sam_vit_b_01ec64.decoder.onnx"),
    }
    cache = Path(os.environ.get("U2NET_HOME") or Path.home() / ".u2net")
    missing = [name for name in filenames[model_name] if not (cache / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Local rembg model files are required in {cache}; automatic downloads are disabled: {missing}")
    os.environ["U2NET_HOME"] = str(cache)
    from rembg import new_session, remove
    from PIL import Image
    sess = new_session(model_name)
    for path in images:
        with open(path, "rb") as f:
            data = remove(f.read(), session=sess, alpha_matting=True,
                          alpha_matting_foreground_threshold=240,
                          alpha_matting_background_threshold=10,
                          alpha_matting_erode_size=10)
        # rembg returns PNG bytes -- load into PIL for unified handling.
        from io import BytesIO
        yield path, Image.open(BytesIO(data)).convert("RGBA")


def op_remove(args: argparse.Namespace) -> int:
    enforce_offline()
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    backend = args.backend.lower()
    started = time.monotonic()

    try:
        if backend in _VERIFIED_BACKENDS:
            model_dir = _verify_model_pack(backend, args.model_root)
            stream = _segment_birefnet(inputs, model_dir, args.device)
        elif backend in ("u2net", "u2netp", "u2net_human_seg",
                         "isnet-general-use", "isnet-anime",
                         "silueta", "sam"):
            stream = _segment_rembg(inputs, backend)
        else:
            return fail("bad_backend",
                        f"Unsupported backend '{backend}'. Choose: "
                        "birefnet | birefnet-portrait | birefnet-matting | "
                        "rmbg2 | rmbg14 | u2net | u2net_human_seg | "
                        "isnet-general-use | isnet-anime | silueta | sam")
    except ModelPackError as ex:
        return fail("model_pack_invalid", str(ex))
    except ImportError as ex:
        return fail("missing_dep", str(ex))

    total = len(inputs)
    emit("progress", percent=0, stage="bgremove", eta_seconds=None)
    for i, (src, rgba) in enumerate(stream):
        out_path = out_dir / (src.stem + "_nobg.png")
        rgba.save(str(out_path), "PNG", optimize=True)
        emit("matte_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             backend=backend)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_models(args: argparse.Namespace) -> int:
    packs = {pack["backend"]: pack for pack in _model_manifest()["packs"]}
    catalog = [
        ("birefnet", "BiRefNet (general SOTA, MIT, ~424 MiB)"),
        ("birefnet-portrait", "BiRefNet HR Portrait (highest quality faces / hair)"),
        ("birefnet-matting", "BiRefNet Matting (true alpha matting)"),
        ("rmbg2", "RMBG-2.0 (gated BRIA model license, generalist)"),
        ("rmbg14", "RMBG-1.4 (BRIA non-commercial model license, lighter)"),
        ("u2net", "U2Net via rembg (fastest, ~177 MB)"),
        ("u2net_human_seg", "U2Net human segmentation"),
        ("isnet-general-use", "IS-Net general (DIS-5K trained)"),
        ("isnet-anime", "IS-Net anime / illustrations"),
        ("silueta", "Silueta (smaller alternative)"),
        ("sam", "Segment Anything (Meta) -- promptable"),
    ]
    for name, desc in catalog:
        pack = packs.get(name)
        installed = pack is not None and _model_dir(name, args.model_root).is_dir()
        emit(
            "matte_model",
            name=name,
            description=desc,
            installed=installed,
            model=pack["modelId"] if pack else None,
            revision=pack["revision"] if pack else None,
            license=pack["license"] if pack else None,
        )
    emit("complete", output="", size_bytes=0, count=len(catalog))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bgremove-sidecar",
                                description="Modern image background removal "
                                            "(BiRefNet / RMBG-2.0 / IS-Net / U2Net / SAM).")
    sub = p.add_subparsers(dest="op", required=True)
    r = sub.add_parser("remove", help="Remove background; produce RGBA PNG.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--backend", default="birefnet",
                   help="Model backend (run `models` op to list).")
    r.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    r.add_argument("--model-root",
                   help="Model-cache root (overrides UCX_MODEL_DIR).")
    models = sub.add_parser("models", help="List supported backends.")
    models.add_argument("--model-root",
                        help="Model-cache root (overrides UCX_MODEL_DIR).")
    download = sub.add_parser(
        "download-model",
        help="Explicitly download a revision- and digest-pinned model pack.")
    download.add_argument("--backend", required=True, choices=sorted(_VERIFIED_BACKENDS))
    download.add_argument("--accept-license", action="store_true")
    download.add_argument("--model-root",
                          help="Model-cache root (overrides UCX_MODEL_DIR).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "remove": return op_remove(args)
        if args.op == "models": return op_models(args)
        if args.op == "download-model": return op_download_model(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

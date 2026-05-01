"""Stable Diffusion / generative image sidecar.

Wraps Hugging Face `diffusers` for text-to-image, image-to-image, inpainting,
and 4x upscaling. Models are NOT bundled (they're 2-7 GB each); the user
points the sidecar at a Hugging Face model id or a local path.

Default model is "runwayml/stable-diffusion-v1-5". Override with --model.
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


def _load_pipe(model: str, kind: str, dtype: str, device: str):
    import torch
    from diffusers import (
        StableDiffusionPipeline, StableDiffusionImg2ImgPipeline,
        StableDiffusionInpaintPipeline, StableDiffusionUpscalePipeline,
    )
    cls = {
        "txt2img":  StableDiffusionPipeline,
        "img2img":  StableDiffusionImg2ImgPipeline,
        "inpaint":  StableDiffusionInpaintPipeline,
        "upscale":  StableDiffusionUpscalePipeline,
    }[kind]
    torch_dtype = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}.get(dtype, torch.float16)
    pipe = cls.from_pretrained(model, torch_dtype=torch_dtype, safety_checker=None)
    pipe = pipe.to(device)
    pipe.set_progress_bar_config(disable=True)
    return pipe


def _save(image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


def op_txt2img(args: argparse.Namespace) -> int:
    try:
        import torch  # noqa: F401
        from diffusers import StableDiffusionPipeline  # noqa: F401
    except ImportError as ex:
        return fail("missing_diffusers", f"diffusers/torch not installed: {ex}")
    import torch

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pipe = _load_pipe(args.model, "txt2img", args.dtype, args.device)

    seed = args.seed if args.seed is not None else int(time.time())
    generator = torch.Generator(device=args.device).manual_seed(int(seed))

    n = int(args.count)
    emit("log", level="info",
         message=f"SD txt2img model={args.model} steps={args.steps} cfg={args.cfg} {args.width}x{args.height} count={n}")
    emit("progress", percent=0, stage="generate", eta_seconds=None)
    for i in range(n):
        out = pipe(
            prompt=args.prompt,
            negative_prompt=args.negative,
            num_inference_steps=int(args.steps),
            guidance_scale=float(args.cfg),
            width=int(args.width), height=int(args.height),
            generator=generator,
        )
        for j, img in enumerate(out.images):
            out_path = out_dir / f"sd_{i:03d}_{j:02d}.png"
            _save(img, out_path)
            emit("sd_image",
                 prompt=args.prompt, seed=int(seed) + i, index=i,
                 output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 model=args.model)
        emit("progress", percent=round((i + 1) / n * 100, 1),
             stage=f"{i+1}/{n}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=n)
    return 0


def op_img2img(args: argparse.Namespace) -> int:
    try:
        import torch
        from PIL import Image
    except ImportError as ex:
        return fail("missing_diffusers", f"diffusers/torch/Pillow not installed: {ex}")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Image(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pipe = _load_pipe(args.model, "img2img", args.dtype, args.device)

    seed = args.seed if args.seed is not None else int(time.time())
    generator = torch.Generator(device=args.device).manual_seed(int(seed))
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            init = Image.open(str(src)).convert("RGB")
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        out = pipe(
            prompt=args.prompt, negative_prompt=args.negative,
            image=init, strength=float(args.strength),
            num_inference_steps=int(args.steps),
            guidance_scale=float(args.cfg),
            generator=generator,
        )
        out_path = out_dir / (src.stem + "_sd.png")
        _save(out.images[0], out_path)
        emit("sd_image",
             input=str(src), output=str(out_path),
             prompt=args.prompt,
             size_bytes=out_path.stat().st_size, model=args.model)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_models(args: argparse.Namespace) -> int:
    """Suggest a few well-known SD checkpoints; users override via --model."""
    suggestions = [
        ("runwayml/stable-diffusion-v1-5",       "SD 1.5 (small, fast)"),
        ("stabilityai/stable-diffusion-2-1",     "SD 2.1 (better quality)"),
        ("stabilityai/sdxl-turbo",               "SDXL Turbo (1-step)"),
        ("stabilityai/stable-diffusion-xl-base-1.0", "SDXL 1.0 base"),
        ("stabilityai/stable-diffusion-x4-upscaler", "SD x4 upscaler"),
    ]
    for repo, desc in suggestions:
        emit("sd_model", repo_id=repo, description=desc)
    emit("complete", output="", size_bytes=0, count=len(suggestions))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdkit-sidecar",
                                description="Stable Diffusion via Hugging Face diffusers.")
    sub = p.add_subparsers(dest="op", required=True)

    common = lambda c: (
        c.add_argument("--model", default="runwayml/stable-diffusion-v1-5"),
        c.add_argument("--dtype", default="fp16"),
        c.add_argument("--device", default="cuda"),
        c.add_argument("--steps", type=int, default=25),
        c.add_argument("--cfg", type=float, default=7.5),
        c.add_argument("--seed", type=int, default=None),
        c.add_argument("--negative", default=""),
        c.add_argument("--output-dir", required=True, dest="output_dir"),
    )

    t = sub.add_parser("txt2img", help="Text-to-image generation.")
    t.add_argument("--prompt", required=True)
    t.add_argument("--width", type=int, default=512)
    t.add_argument("--height", type=int, default=512)
    t.add_argument("--count", type=int, default=1)
    common(t)

    i = sub.add_parser("img2img", help="Image-to-image transformation.")
    i.add_argument("--input", nargs="+", required=True)
    i.add_argument("--prompt", required=True)
    i.add_argument("--strength", type=float, default=0.6,
                   help="0 = no change, 1 = ignore source.")
    common(i)

    sub.add_parser("models", help="Show suggested SD checkpoint repo ids.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "txt2img": return op_txt2img(args)
        if args.op == "img2img": return op_img2img(args)
        if args.op == "models":  return op_models(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

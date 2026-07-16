"""Generative image sidecar -- routes to the latest OSS image-gen model
families via Hugging Face `diffusers`:

  * FLUX.1 [schnell]  (Black Forest Labs, Apache-2.0)  -- 4-step SOTA fast
  * FLUX.1 [dev]      (Black Forest Labs, non-commercial) -- best OSS quality
  * Stable Diffusion 3.5 Large / Medium    (SAI 2024, MIT/RAIL)
  * SDXL 1.0 base + refiner / SDXL Turbo   (still strong, very compatible)
  * Stable Diffusion 1.5 / 2.1             (legacy / lightweight)
  * SD x4 upscaler                          (latent diffusion super-res)

Default model = "black-forest-labs/FLUX.1-schnell" for the speed/quality
sweet spot. Override with --model.

Models are NOT bundled (FLUX is ~24 GB). The sidecar pulls + caches them
into the user's HF cache on first run.
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


# Recommended catalog -- model id -> (family, kind support, recommended steps,
# guidance scale, license note).
CATALOG: dict[str, dict] = {
    "black-forest-labs/FLUX.1-schnell": {
        "family": "flux", "steps": 4, "cfg": 0.0,
        "desc": "FLUX.1 schnell -- 4-step SOTA, Apache-2.0, ~23 GB"},
    "black-forest-labs/FLUX.1-dev": {
        "family": "flux", "steps": 28, "cfg": 3.5,
        "desc": "FLUX.1 dev -- best OSS quality, non-commercial, ~23 GB"},
    "stabilityai/stable-diffusion-3.5-large": {
        "family": "sd3", "steps": 28, "cfg": 4.5,
        "desc": "SD 3.5 Large -- 8B params, MIT, ~16 GB"},
    "stabilityai/stable-diffusion-3.5-medium": {
        "family": "sd3", "steps": 28, "cfg": 4.5,
        "desc": "SD 3.5 Medium -- 2.5B, MIT, ~10 GB"},
    "stabilityai/stable-diffusion-3-medium-diffusers": {
        "family": "sd3", "steps": 28, "cfg": 4.0,
        "desc": "SD 3 Medium -- 2B, original release"},
    "stabilityai/sdxl-turbo": {
        "family": "sdxl", "steps": 1, "cfg": 0.0,
        "desc": "SDXL Turbo -- 1-step distilled, fastest baseline"},
    "stabilityai/stable-diffusion-xl-base-1.0": {
        "family": "sdxl", "steps": 30, "cfg": 7.0,
        "desc": "SDXL 1.0 base -- still excellent, broad LoRA support"},
    "stabilityai/stable-diffusion-2-1": {
        "family": "sd1x", "steps": 30, "cfg": 7.5,
        "desc": "SD 2.1 -- legacy"},
    "runwayml/stable-diffusion-v1-5": {
        "family": "sd1x", "steps": 25, "cfg": 7.5,
        "desc": "SD 1.5 -- smallest / oldest"},
    "stabilityai/stable-diffusion-x4-upscaler": {
        "family": "sd1x", "steps": 50, "cfg": 9.0,
        "desc": "SD x4 latent upscaler -- super-resolution only"},
}


# Family aliases so users can pass "flux" / "sd3" / "sdxl" instead of full repo id.
ALIASES = {
    "flux":         "black-forest-labs/FLUX.1-schnell",
    "flux-dev":     "black-forest-labs/FLUX.1-dev",
    "flux-schnell": "black-forest-labs/FLUX.1-schnell",
    "sd35":         "stabilityai/stable-diffusion-3.5-large",
    "sd35-medium":  "stabilityai/stable-diffusion-3.5-medium",
    "sd3":          "stabilityai/stable-diffusion-3-medium-diffusers",
    "sdxl":         "stabilityai/stable-diffusion-xl-base-1.0",
    "sdxl-turbo":   "stabilityai/sdxl-turbo",
    "sd21":         "stabilityai/stable-diffusion-2-1",
    "sd15":         "runwayml/stable-diffusion-v1-5",
    "x4":           "stabilityai/stable-diffusion-x4-upscaler",
}


def _resolve_model(name: str) -> str:
    return ALIASES.get(name, name)


def _family_of(model: str) -> str:
    info = CATALOG.get(model)
    if info: return info["family"]
    n = model.lower()
    if "flux" in n: return "flux"
    if "stable-diffusion-3" in n: return "sd3"
    if "sdxl" in n or "stable-diffusion-xl" in n: return "sdxl"
    if "x4-upscaler" in n: return "sd1x"
    return "sd1x"


def _torch_dtype(dtype: str):
    import torch
    return {"fp16": torch.float16, "bf16": torch.bfloat16,
            "fp32": torch.float32}.get(dtype, torch.bfloat16)


def _load_pipe(model: str, kind: str, dtype: str, device: str):
    """kind in {'txt2img','img2img','inpaint','upscale'}."""
    family = _family_of(model)
    td = _torch_dtype(dtype)

    if family == "flux":
        from diffusers import (FluxPipeline, FluxImg2ImgPipeline,
                                FluxInpaintPipeline)
        cls = {"txt2img": FluxPipeline, "img2img": FluxImg2ImgPipeline,
               "inpaint": FluxInpaintPipeline}.get(kind)
        if cls is None: raise ValueError(f"FLUX has no '{kind}' pipeline.")
        pipe = cls.from_pretrained(model, torch_dtype=td)
    elif family == "sd3":
        from diffusers import (StableDiffusion3Pipeline,
                                StableDiffusion3Img2ImgPipeline,
                                StableDiffusion3InpaintPipeline)
        cls = {"txt2img": StableDiffusion3Pipeline,
               "img2img": StableDiffusion3Img2ImgPipeline,
               "inpaint": StableDiffusion3InpaintPipeline}.get(kind)
        if cls is None: raise ValueError(f"SD3 has no '{kind}' pipeline.")
        pipe = cls.from_pretrained(model, torch_dtype=td)
    elif family == "sdxl":
        from diffusers import (StableDiffusionXLPipeline,
                                StableDiffusionXLImg2ImgPipeline,
                                StableDiffusionXLInpaintPipeline)
        cls = {"txt2img": StableDiffusionXLPipeline,
               "img2img": StableDiffusionXLImg2ImgPipeline,
               "inpaint": StableDiffusionXLInpaintPipeline}.get(kind)
        if cls is None: raise ValueError(f"SDXL has no '{kind}' pipeline.")
        pipe = cls.from_pretrained(model, torch_dtype=td, variant="fp16",
                                    use_safetensors=True)
    else:  # sd1x
        from diffusers import (StableDiffusionPipeline,
                                StableDiffusionImg2ImgPipeline,
                                StableDiffusionInpaintPipeline,
                                StableDiffusionUpscalePipeline)
        cls = {"txt2img": StableDiffusionPipeline,
               "img2img": StableDiffusionImg2ImgPipeline,
               "inpaint": StableDiffusionInpaintPipeline,
               "upscale": StableDiffusionUpscalePipeline}[kind]
        pipe = cls.from_pretrained(model, torch_dtype=td, safety_checker=None)

    pipe = pipe.to(device)
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)
    # Memory savings -- not all pipelines support both, so guard.
    try: pipe.enable_attention_slicing("auto")
    except Exception: pass
    try: pipe.enable_model_cpu_offload()
    except Exception: pass
    return pipe


def _save(image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


def _maybe_default_steps_cfg(args: argparse.Namespace, model: str) -> None:
    """If the user didn't override, use the model's recommended values."""
    info = CATALOG.get(model)
    if info is None: return
    if getattr(args, "_steps_explicit", False) is False:
        args.steps = info["steps"]
    if getattr(args, "_cfg_explicit", False) is False:
        args.cfg = info["cfg"]


def op_txt2img(args: argparse.Namespace) -> int:
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
    except ImportError as ex:
        return fail("missing_diffusers", f"diffusers/torch not installed: {ex}")
    import torch

    model = _resolve_model(args.model)
    _maybe_default_steps_cfg(args, model)
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pipe = _load_pipe(model, "txt2img", args.dtype, args.device)

    seed = args.seed if args.seed is not None else int(time.time())
    generator = torch.Generator(device=args.device).manual_seed(int(seed))

    n = int(args.count)
    family = _family_of(model)
    emit("log", level="info",
         message=f"img-gen family={family} model={model} steps={args.steps} "
                 f"cfg={args.cfg} {args.width}x{args.height} count={n}")
    emit("progress", percent=0, stage="generate", eta_seconds=None)
    for i in range(n):
        kwargs = dict(
            prompt=args.prompt,
            num_inference_steps=int(args.steps),
            guidance_scale=float(args.cfg),
            width=int(args.width), height=int(args.height),
            generator=generator,
        )
        if family != "flux":
            kwargs["negative_prompt"] = args.negative
        out = pipe(**kwargs)
        for j, img in enumerate(out.images):
            out_path = out_dir / f"sd_{i:03d}_{j:02d}.png"
            _save(img, out_path)
            emit("sd_image",
                 prompt=args.prompt, seed=int(seed) + i, index=i,
                 output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 model=model, family=family)
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
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    model = _resolve_model(args.model)
    _maybe_default_steps_cfg(args, model)
    pipe = _load_pipe(model, "img2img", args.dtype, args.device)

    seed = args.seed if args.seed is not None else int(time.time())
    generator = torch.Generator(device=args.device).manual_seed(int(seed))
    family = _family_of(model)
    total = len(inputs)
    for i, src in enumerate(inputs):
        try: init = Image.open(str(src)).convert("RGB")
        except Exception as ex: return fail("read_failed", f"{src.name}: {ex}")
        kwargs = dict(
            prompt=args.prompt, image=init,
            strength=float(args.strength),
            num_inference_steps=int(args.steps),
            guidance_scale=float(args.cfg),
            generator=generator,
        )
        if family != "flux":
            kwargs["negative_prompt"] = args.negative
        out = pipe(**kwargs)
        out_path = out_dir / (src.stem + "_gen.png")
        _save(out.images[0], out_path)
        emit("sd_image",
             input=str(src), output=str(out_path),
             prompt=args.prompt,
             size_bytes=out_path.stat().st_size,
             model=model, family=family)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_models(args: argparse.Namespace) -> int:
    """Print the recommended catalog so the UI can populate a model dropdown."""
    for repo, info in CATALOG.items():
        emit("sd_model", repo_id=repo, family=info["family"],
             steps=info["steps"], cfg=info["cfg"],
             description=info["desc"])
    for alias, repo in ALIASES.items():
        emit("sd_model", repo_id=repo, alias=alias,
             family=CATALOG.get(repo, {}).get("family", "unknown"),
             description="(alias)")
    emit("complete", output="", size_bytes=0, count=len(CATALOG))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdkit-sidecar",
                                description="Generative image (FLUX.1 / SD3 / SDXL / SD1.5) via diffusers.")
    sub = p.add_subparsers(dest="op", required=True)

    def add_common(c):
        c.add_argument("--model", default="black-forest-labs/FLUX.1-schnell",
                       help="Repo id or alias (flux | flux-dev | sd35 | sdxl | sdxl-turbo | sd15)")
        c.add_argument("--dtype", default="bf16", choices=["fp16", "bf16", "fp32"])
        c.add_argument("--device", default="cuda")
        c.add_argument("--steps", type=int, default=None)
        c.add_argument("--cfg", type=float, default=None)
        c.add_argument("--seed", type=int, default=None)
        c.add_argument("--negative", default="")
        c.add_argument("--output-dir", required=True, dest="output_dir")

    t = sub.add_parser("txt2img", help="Text-to-image generation.")
    t.add_argument("--prompt", required=True)
    t.add_argument("--width", type=int, default=1024)
    t.add_argument("--height", type=int, default=1024)
    t.add_argument("--count", type=int, default=1)
    add_common(t)

    i = sub.add_parser("img2img", help="Image-to-image transformation.")
    i.add_argument("--input", nargs="+", required=True)
    i.add_argument("--prompt", required=True)
    i.add_argument("--strength", type=float, default=0.6,
                   help="0 = no change, 1 = ignore source.")
    add_common(i)

    sub.add_parser("models", help="Print the catalog of supported model ids + aliases.")
    return p


def _post_parse_defaults(args):
    """Mark whether the user explicitly passed steps/cfg so we don't override them."""
    args._steps_explicit = args.steps is not None
    args._cfg_explicit = args.cfg is not None
    if args.steps is None: args.steps = 28
    if args.cfg is None: args.cfg = 3.5


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _post_parse_defaults(args) if args.op in ("txt2img", "img2img") else None
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

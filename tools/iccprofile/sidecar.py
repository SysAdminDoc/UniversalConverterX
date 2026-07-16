"""ICC color profile sidecar -- apply / strip / convert via Pillow ImageCms.

Operations:
  apply    : Convert image colorspace from --src-profile to --dst-profile.
  embed    : Tag an image with an ICC profile (no pixel transform).
  strip    : Remove embedded ICC profile.
  info     : Report the embedded profile + image colorspace.
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


def _imports():
    try:
        from PIL import Image, ImageCms  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_pillow", message=str(ex))
        return False


# Built-in profiles via ImageCms.createProfile -- saves users from finding ICC files.
BUILTIN = {
    "srgb": "sRGB",
    "displayp3": "P3",     # ImageCms doesn't have native P3; user can pass an ICC file.
    "adobergb": "AdobeRGB",
    "lab": "LAB",
    "xyz": "XYZ",
}


def _resolve_profile(spec: str):
    """Build an ImageCmsProfile either from a file path or a built-in name."""
    from PIL import ImageCms
    p = Path(spec)
    if p.is_file():
        return ImageCms.getOpenProfile(str(p))
    name = BUILTIN.get(spec.lower())
    if name is None:
        raise RuntimeError(f"Unknown profile '{spec}' (file path or one of: "
                           + ", ".join(BUILTIN) + ")")
    return ImageCms.createProfile(name)


def op_apply(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from PIL import Image, ImageCms

    src_p = _resolve_profile(args.src_profile)
    dst_p = _resolve_profile(args.dst_profile)
    intent = {
        "perceptual": ImageCms.Intent.PERCEPTUAL,
        "relative":   ImageCms.Intent.RELATIVE_COLORIMETRIC,
        "saturation": ImageCms.Intent.SATURATION,
        "absolute":   ImageCms.Intent.ABSOLUTE_COLORIMETRIC,
    }.get(args.intent.lower(), ImageCms.Intent.PERCEPTUAL)
    transform = ImageCms.buildTransform(src_p, dst_p, "RGB", "RGB", renderingIntent=intent)

    inputs = [Path(p) for p in args.input]
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(inputs)
    started = time.monotonic()

    for i, src in enumerate(inputs):
        if not src.is_file():
            return fail("missing_input", str(src))
        try:
            img = Image.open(str(src)).convert("RGB")
            transformed = ImageCms.applyTransform(img, transform)
            out_path = out_dir / src.name
            kw = {}
            if args.embed:
                kw["icc_profile"] = ImageCms.ImageCmsProfile(dst_p).tobytes()
            transformed.save(str(out_path), **kw)
        except Exception as ex:
            return fail("apply_failed", f"{src.name}: {ex}")
        emit("color", input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             intent=args.intent)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_embed(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from PIL import Image, ImageCms
    profile = _resolve_profile(args.profile)
    icc = ImageCms.ImageCmsProfile(profile).tobytes()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = [Path(p) for p in args.input]
    for i, src in enumerate(inputs):
        try:
            img = Image.open(str(src))
            out_path = out_dir / src.name
            img.save(str(out_path), icc_profile=icc)
        except Exception as ex:
            return fail("embed_failed", f"{src.name}: {ex}")
        emit("color", input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size, embedded=True)
        emit("progress", percent=round((i + 1) / len(inputs) * 100, 1),
             stage=f"{i+1}/{len(inputs)}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=len(inputs))
    return 0


def op_strip(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from PIL import Image
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = [Path(p) for p in args.input]
    for i, src in enumerate(inputs):
        try:
            img = Image.open(str(src))
            # Re-save without icc_profile to drop it.
            out_path = out_dir / src.name
            data = img.copy(); data.info.pop("icc_profile", None)
            data.save(str(out_path))
        except Exception as ex:
            return fail("strip_failed", f"{src.name}: {ex}")
        emit("color", input=str(src), output=str(out_path), stripped=True)
        emit("progress", percent=round((i + 1) / len(inputs) * 100, 1),
             stage=f"{i+1}/{len(inputs)}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=len(inputs))
    return 0


def op_info(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from PIL import Image, ImageCms
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", str(src))
    img = Image.open(str(src))
    icc = img.info.get("icc_profile")
    profile_name = ""
    if icc:
        try:
            from io import BytesIO
            profile_name = ImageCms.getProfileName(ImageCms.getOpenProfile(BytesIO(icc))).strip()
        except Exception:
            profile_name = "(unparseable)"
    emit("color_info",
         path=str(src),
         mode=str(img.mode),
         size=[img.width, img.height],
         has_icc=bool(icc),
         profile_name=profile_name,
         icc_size=len(icc or b""))
    emit("complete", output=str(src), size_bytes=src.stat().st_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iccprofile-sidecar",
                                description="ICC color profile transforms via Pillow ImageCms.")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("apply", help="Transform pixels from one colorspace to another.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")
    a.add_argument("--src-profile", required=True, dest="src_profile",
                   help="ICC file path, or one of: " + ", ".join(BUILTIN))
    a.add_argument("--dst-profile", required=True, dest="dst_profile")
    a.add_argument("--intent", default="perceptual",
                   help="perceptual | relative | saturation | absolute")
    a.add_argument("--embed", action="store_true",
                   help="Tag the output with the destination profile.")

    e = sub.add_parser("embed", help="Tag without re-mapping pixels.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    e.add_argument("--profile", required=True)

    s = sub.add_parser("strip", help="Drop embedded ICC tag.")
    s.add_argument("--input", nargs="+", required=True)
    s.add_argument("--output-dir", required=True, dest="output_dir")

    i = sub.add_parser("info", help="Report embedded ICC + image colorspace.")
    i.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "apply": return op_apply(args)
        if args.op == "embed": return op_embed(args)
        if args.op == "strip": return op_strip(args)
        if args.op == "info":  return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

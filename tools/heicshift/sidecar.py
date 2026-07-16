"""HEICShift sidecar — NDJSON image format converter for the UCX Image Converter module.

Headless wrapper around pillow_heif + Pillow. Accepts one input image, decodes
it (HEIC/HEIF/AVIF/JPEG/PNG/WebP/TIFF/BMP), then re-encodes to the target
format with sane quality + ICC + EXIF defaults.

Subcommands:
  convert        single-file conversion
  list-formats   emit a known input/output format table as NDJSON

Standard NDJSON contract: progress / log / complete / error events on stdout.
The C# page invokes this sidecar once per file and parallelises across the
queue itself — keeps the contract simple.
"""
from __future__ import annotations

import argparse
import io
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ── NDJSON helpers ───────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


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


# ── Dependency discovery ─────────────────────────────────────────────────────

def _ensure_deps() -> None:
    """Require bundled/managed dependencies without installing at runtime."""
    try:
        import PIL  # noqa: F401
        import pillow_heif  # noqa: F401
        return
    except ImportError:
        pass

    if getattr(sys, "frozen", False):
        message = (
            "Pillow or pillow-heif is not bundled into this sidecar. Reinstall "
            "Universal Converter X or rebuild the sidecar with its declared "
            "dependencies."
        )
    else:
        message = (
            "Pillow or pillow-heif is not installed in the sidecar environment. "
            "Provision Pillow>=12.3.0 and pillow-heif>=0.16.0 in the managed "
            "environment, then retry."
        )
    fail("missing_dep", message)
    sys.exit(1)


# ── Format inventory ─────────────────────────────────────────────────────────

# Input extensions the sidecar can decode reliably (Pillow + pillow_heif + optional pillow-jxl).
INPUT_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif",
    ".heic", ".heif", ".avif",
    ".jxl",   # JPEG XL — decoded only when pillow-jxl-plugin is installed
}

# Output formats and their Pillow save() parameter conventions.
OUTPUT_FORMATS: dict[str, dict] = {
    "jpeg": {"ext": ".jpg",  "pil": "JPEG",  "supports_alpha": False},
    "png":  {"ext": ".png",  "pil": "PNG",   "supports_alpha": True},
    "webp": {"ext": ".webp", "pil": "WEBP",  "supports_alpha": True},
    "tiff": {"ext": ".tiff", "pil": "TIFF",  "supports_alpha": True},
    "bmp":  {"ext": ".bmp",  "pil": "BMP",   "supports_alpha": False},
    "heic": {"ext": ".heic", "pil": "HEIF",  "supports_alpha": True},
    "avif": {"ext": ".avif", "pil": "AVIF",  "supports_alpha": True},
    "jxl":  {"ext": ".jxl",  "pil": "JXL",   "supports_alpha": True},
}

QUALITY_TARGET_FORMATS = {"jpeg", "webp", "avif", "heic", "jxl"}
MULTIFRAME_OUTPUT_FORMATS = {"webp", "tiff"}

ADJUST_PRESETS = {
    "vivid": {"saturation": 30, "contrast": 15},
    "muted": {"saturation": -30, "contrast": -10},
    "bw": {"grayscale": True, "contrast": 10},
    "vintage": {"sepia": True, "saturation": -15, "contrast": -5},
    "cold": {"saturation": -10, "tint": "#3a6ea5@18"},
    "warm": {"saturation": 8, "tint": "#e0a04a@16"},
}


# ROADMAP Item 88 — libjxl security floor. pillow-jxl-plugin >= 1.3.4 is the
# first wrapper release that bundles libjxl 0.11.2, which carries the
# CVE-2025-12474 (tile dimension flaw) + CVE-2026-1837 (gray-to-gray channel
# error) fixes. Older bundled libjxls render untrusted JXL bytes — exactly
# the worst-case threat surface for a converter that accepts arbitrary input.
_JXL_PLUGIN_MIN_VERSION = (1, 3, 4)


def _parse_version(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in (raw or "").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
        else:
            break
    return tuple(parts) if parts else (0,)


def _try_register_jxl() -> bool:
    """Best-effort import of pillow-jxl-plugin so .jxl read/write works.

    Returns True if registered, False otherwise. Callers can degrade to a
    helpful error rather than a blanket "decode_failed" if JXL was the target.

    Emits a `log` event at warning level when the installed pillow-jxl-plugin
    version is below the libjxl security floor (Item 88) so users running
    older wheels get an audible signal even when no malformed JXL is hit.
    """
    try:
        import pillow_jxl  # type: ignore  # noqa: F401
    except ImportError:
        return False

    try:
        try:
            from importlib.metadata import version as _pkg_version  # py>=3.8
        except ImportError:  # pragma: no cover — py<3.8 not supported
            _pkg_version = None  # type: ignore[assignment]
        installed_raw = _pkg_version("pillow-jxl-plugin") if _pkg_version else ""
        installed = _parse_version(installed_raw)
        if installed and installed < _JXL_PLUGIN_MIN_VERSION:
            min_str = ".".join(str(p) for p in _JXL_PLUGIN_MIN_VERSION)
            log("warn",
                f"pillow-jxl-plugin {installed_raw} is below the libjxl "
                f"security floor (>= {min_str}). CVE-2025-12474 / "
                f"CVE-2026-1837 fixes ship in libjxl 0.11.2 — upgrade with "
                f"`pip install --upgrade 'pillow-jxl-plugin>={min_str}'`.")
    except Exception:
        # Probe is best-effort; never break encode/decode because we couldn't
        # introspect package metadata.
        pass
    return True


def op_list_formats(_: argparse.Namespace) -> int:
    for ext in sorted(INPUT_EXTS):
        emit("format", direction="in", ext=ext)
    for fmt, meta in OUTPUT_FORMATS.items():
        emit("format", direction="out", id=fmt, ext=meta["ext"],
             supports_alpha=meta["supports_alpha"])
    emit("complete", input_count=len(INPUT_EXTS), output_count=len(OUTPUT_FORMATS))
    return 0


# ── Quality targeting ───────────────────────────────────────────────────────

def _psnr(reference, distorted) -> float:
    """Compute RGB peak signal-to-noise ratio with Pillow only."""
    from PIL import ImageChops, ImageStat  # type: ignore

    if reference.size != distorted.size:
        return 0.0
    difference = ImageChops.difference(
        reference.convert("RGB"), distorted.convert("RGB"))
    rms = ImageStat.Stat(difference).rms
    mse = sum(channel * channel for channel in rms) / max(1, len(rms))
    if mse <= 0:
        return 100.0
    return 20.0 * math.log10(255.0) - 10.0 * math.log10(mse)


def _find_vship() -> str | None:
    """Find the already-supported local Vship evaluator without downloading."""
    roots = [Path(__file__).resolve().parent]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(sys.executable).resolve().parent)
    for root in roots:
        for candidate in (
            root / "vship.exe",
            root.parent / "vship-metrics" / "vship.exe",
            root.parent / "_bin" / "vship.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    return shutil.which("vship")


def _ssimulacra2_score(vship: str, reference: Path, distorted: Path) -> float:
    completed = subprocess.run(
        [vship, "--ssimulacra2", str(reference), str(distorted)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()[-300:]
        raise RuntimeError(f"vship --ssimulacra2 failed: {detail}")
    for line in completed.stdout.splitlines():
        match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", line)
        if match:
            return float(match.group())
    raise RuntimeError("vship returned no SSIMULACRA2 score")


def _binary_search_quality(
    probe,
    target: float,
    mode: str,
    qmin: int = 1,
    qmax: int = 100,
    max_iters: int = 8,
) -> tuple[int, int, float, bool]:
    """Select the highest size-safe or lowest metric-safe encoder quality.

    ``probe(quality)`` returns ``(size_bytes, metric_or_none)``. The final
    boolean states whether the requested hard constraint was achievable.
    """
    results: dict[int, tuple[int, float]] = {}

    def run(quality: int) -> tuple[int, float]:
        if quality not in results:
            size, metric = probe(quality)
            value = size / 1024.0 if mode == "target-kb" else float(metric)
            results[quality] = (int(size), value)
        return results[quality]

    lo, hi = qmin, qmax
    best_quality: int | None = None
    for _ in range(max_iters):
        if lo > hi:
            break
        quality = (lo + hi) // 2
        _, value = run(quality)
        if mode == "target-kb":
            if value <= target:
                best_quality = quality
                lo = quality + 1
            else:
                hi = quality - 1
        else:
            if value >= target:
                best_quality = quality
                hi = quality - 1
            else:
                lo = quality + 1

    if best_quality is None:
        best_quality = qmin if mode == "target-kb" else qmax
        size, value = run(best_quality)
        return best_quality, size, value, False

    size, value = run(best_quality)
    return best_quality, size, value, True


def _quality_target(args: argparse.Namespace) -> tuple[str, float] | None:
    for attribute, mode in (
        ("target_kb", "target-kb"),
        ("target_psnr", "target-psnr"),
        ("target_ssimulacra2", "target-ssimulacra2"),
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            return mode, float(value)
    return None


def _quality_warning(
    mode: str,
    target: float,
    quality: int,
    size_bytes: int,
    metric: float,
    hard_target_met: bool,
) -> str | None:
    if mode == "target-kb":
        actual = size_bytes / 1024.0
        within_five_percent = abs(actual - target) <= target * 0.05
        if within_five_percent:
            return None
        return (
            f"Target {target:g} KB was not reachable within 5%; best achievable "
            f"result is {actual:.1f} KB at quality {quality}."
        )
    if hard_target_met:
        return None
    label = "PSNR" if mode == "target-psnr" else "SSIMULACRA2"
    return (
        f"Target {label} {target:g} was not achievable; best score is "
        f"{metric:.2f} at quality {quality}."
    )


# ── Batch image editing ─────────────────────────────────────────────────────

def _parse_color(spec: str | None, default=None):
    if not spec or len(spec) > 64:
        return default
    try:
        from PIL import ImageColor  # type: ignore
        return ImageColor.getrgb(spec.strip())[:3]
    except (ValueError, TypeError):
        return default


def _resolve_edits(args: argparse.Namespace) -> dict:
    preset = ADJUST_PRESETS.get(getattr(args, "adjust_preset", None) or "", {})

    def numeric(name: str, low: int, high: int) -> int:
        base = int(preset.get(name, 0) or 0)
        explicit = getattr(args, name, None)
        value = base + (int(explicit) if explicit is not None else 0)
        return max(low, min(high, value))

    return {
        "brightness": numeric("brightness", -100, 100),
        "contrast": numeric("contrast", -100, 100),
        "saturation": numeric("saturation", -100, 100),
        "sharpness": numeric("sharpness", 0, 100),
        "blur": max(0.0, min(20.0, float(getattr(args, "blur", None) or 0))),
        "hue": numeric("hue", 0, 360),
        "grayscale": bool(preset.get("grayscale")) or bool(args.grayscale),
        "sepia": bool(preset.get("sepia")) or bool(args.sepia),
        "invert": bool(preset.get("invert")) or bool(args.invert),
        "vignette": numeric("vignette", 0, 100),
        "grain": numeric("grain", 0, 100),
        "tint": getattr(args, "tint", None) or preset.get("tint"),
        "border": max(0, int(getattr(args, "border", None) or 0)),
        "border_color": getattr(args, "border_color", "#ffffff"),
    }


def _has_edits(edits: dict) -> bool:
    return any(
        edits.get(name)
        for name in (
            "brightness", "contrast", "saturation", "sharpness", "blur",
            "hue", "grayscale", "sepia", "invert", "vignette", "grain",
            "tint", "border",
        )
    )


def _apply_hue(rgb, degrees: int):
    from PIL import Image  # type: ignore

    shift = int(round((degrees % 360) / 360.0 * 255)) & 0xFF
    if shift == 0:
        return rgb
    hue, saturation, value = rgb.convert("HSV").split()
    hue = hue.point(lambda channel: (channel + shift) & 0xFF)
    return Image.merge("HSV", (hue, saturation, value)).convert("RGB")


def _apply_vignette(rgb, strength: int):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter  # type: ignore

    width, height = rgb.size
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).ellipse(
        (-width * 0.15, -height * 0.15, width * 1.15, height * 1.15),
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(width, height) / 8.0))
    dark = ImageEnhance.Brightness(rgb).enhance(1.0 - strength / 100.0 * 0.85)
    return Image.composite(rgb, dark, mask)


def _apply_grain(rgb, strength: int):
    from PIL import Image, ImageChops  # type: ignore

    width, height = rgb.size
    noise = Image.effect_noise((width, height), strength / 100.0 * 48.0)
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    grained = ImageChops.add(rgb, noise_rgb, scale=1.0, offset=-128)
    return Image.blend(rgb, grained, strength / 100.0)


def _apply_tint(rgb, spec: str):
    from PIL import Image, ImageChops  # type: ignore

    color_spec, _, raw_strength = spec.partition("@")
    try:
        strength = int(float(raw_strength)) if raw_strength else 30
    except ValueError:
        strength = 30
    strength = max(0, min(100, strength))
    color = _parse_color(color_spec)
    if color is None:
        raise ValueError(f"Invalid tint colour: {color_spec}")
    overlay = Image.new("RGB", rgb.size, color)
    return Image.blend(rgb, ImageChops.multiply(rgb, overlay), strength / 100.0)


def _apply_edits(image, edits: dict):
    """Apply deterministic adjustments while preserving the alpha channel."""
    if not _has_edits(edits):
        return image.copy()

    from PIL import ImageEnhance, ImageFilter, ImageOps  # type: ignore

    rgba = image.convert("RGBA") if image.mode in {"RGBA", "LA", "P"} else None
    alpha = rgba.getchannel("A") if rgba is not None else None
    rgb = (rgba or image).convert("RGB")

    if edits["brightness"]:
        rgb = ImageEnhance.Brightness(rgb).enhance(max(0.0, 1 + edits["brightness"] / 100))
    if edits["contrast"]:
        rgb = ImageEnhance.Contrast(rgb).enhance(max(0.0, 1 + edits["contrast"] / 100))
    if edits["saturation"]:
        rgb = ImageEnhance.Color(rgb).enhance(max(0.0, 1 + edits["saturation"] / 100))
    if edits["hue"]:
        rgb = _apply_hue(rgb, edits["hue"])
    if edits["sharpness"]:
        rgb = ImageEnhance.Sharpness(rgb).enhance(1 + edits["sharpness"] / 50)
    if edits["blur"]:
        rgb = rgb.filter(ImageFilter.GaussianBlur(radius=edits["blur"]))
    if edits["grayscale"]:
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    if edits["sepia"]:
        gray = ImageOps.grayscale(rgb)
        rgb = ImageOps.colorize(gray, black=(30, 18, 8), white=(255, 240, 200)).convert("RGB")
    if edits["invert"]:
        rgb = ImageOps.invert(rgb)
    if edits["vignette"]:
        rgb = _apply_vignette(rgb, edits["vignette"])
    if edits["grain"]:
        rgb = _apply_grain(rgb, edits["grain"])
    if edits["tint"]:
        rgb = _apply_tint(rgb, edits["tint"])

    if alpha is not None:
        output = rgb.convert("RGBA")
        output.putalpha(alpha)
    else:
        output = rgb

    if edits["border"]:
        color = _parse_color(edits["border_color"])
        if color is None:
            raise ValueError(f"Invalid border colour: {edits['border_color']}")
        fill = color + (255,) if output.mode == "RGBA" else color
        output = ImageOps.expand(output, border=edits["border"], fill=fill)
    return output


def _validate_edit_args(args: argparse.Namespace) -> str | None:
    for flag, name, low, high in (
        ("--brightness", "brightness", -100, 100),
        ("--contrast", "contrast", -100, 100),
        ("--saturation", "saturation", -100, 100),
        ("--sharpness", "sharpness", 0, 100),
        ("--hue", "hue", 0, 360),
        ("--vignette", "vignette", 0, 100),
        ("--grain", "grain", 0, 100),
    ):
        value = getattr(args, name, None)
        if value is not None and not low <= value <= high:
            return f"{flag} must be between {low} and {high}."
    if args.blur is not None and not 0 <= args.blur <= 20:
        return "--blur must be between 0 and 20."
    if args.border is not None and args.border < 0:
        return "--border must be zero or greater."
    if args.tint:
        color, _, raw_strength = args.tint.partition("@")
        if _parse_color(color) is None:
            return "--tint must use a #RRGGBB or named colour."
        try:
            strength = float(raw_strength) if raw_strength else 30
        except ValueError:
            return "--tint strength must be a number from 0 to 100."
        if not 0 <= strength <= 100:
            return "--tint strength must be between 0 and 100."
    if args.border and _parse_color(args.border_color) is None:
        return "--border-color must use a #RRGGBB or named colour."
    return None


# ── Convert one ──────────────────────────────────────────────────────────────

def op_convert(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    fmt = args.format.lower()
    if fmt not in OUTPUT_FORMATS:
        return fail(
            "invalid_format",
            f"Unknown output format {fmt!r}. Choose one of: "
            f"{', '.join(OUTPUT_FORMATS)}",
        )
    meta = OUTPUT_FORMATS[fmt]
    quality_target = _quality_target(args)
    if quality_target is not None:
        mode, target = quality_target
        if target <= 0:
            return fail("invalid_quality_target", "Quality targets must be greater than zero.")
        if mode == "target-ssimulacra2" and target > 100:
            return fail("invalid_quality_target", "SSIMULACRA2 targets must be between 0 and 100.")
        if fmt not in QUALITY_TARGET_FORMATS:
            return fail(
                "unsupported_quality_target",
                f"{fmt} has no lossy quality control; target modes support: "
                f"{', '.join(sorted(QUALITY_TARGET_FORMATS))}.",
            )
        if fmt == "avif" and getattr(args, "avif_lossless", False):
            return fail(
                "conflicting_quality_target",
                "--avif-lossless cannot be combined with a quality target.",
            )

    out_path = Path(args.output)
    if out_path.is_dir() or out_path.suffix == "":
        out_path = (out_path / in_path.stem).with_suffix(meta["ext"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    progress(2.0, "loading")
    from PIL import Image, ImageCms  # type: ignore
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    has_jxl = _try_register_jxl()
    edit_error = _validate_edit_args(args)
    if edit_error:
        return fail("invalid_edit", edit_error)
    edits = _resolve_edits(args)

    # JXL needs an explicit dep — bail with a clear hint rather than a generic
    # decode/encode error when the plugin isn't installed.
    if not has_jxl and (in_path.suffix.lower() == ".jxl" or fmt == "jxl"):
        return fail(
            "missing_jxl_plugin",
            "JPEG XL support requires `pillow-jxl-plugin`. Install with "
            "`pip install pillow-jxl-plugin` (the heicshift build.ps1 already "
            "bundles it for frozen builds).",
        )

    try:
        with Image.open(in_path) as source:
            source_info = dict(source.info)
            source_frame_count = int(getattr(source, "n_frames", 1))
            keep_frames = fmt in MULTIFRAME_OUTPUT_FORMATS
            frame_limit = source_frame_count if keep_frames else 1
            raw_frames = []
            frame_durations = []
            for index in range(frame_limit):
                source.seek(index)
                frame = source.copy()
                frame.load()
                raw_frames.append(frame)
                frame_durations.append(int(source.info.get("duration", 0) or 0))
    except Exception as exc:
        return fail("decode_failed", f"Could not decode {in_path.name}: {exc}")

    progress(40.0, "decoded")
    log(
        "info",
        f"{in_path.name}: mode={raw_frames[0].mode} size={raw_frames[0].size} "
        f"frames={source_frame_count}",
    )
    if source_frame_count > 1 and fmt not in MULTIFRAME_OUTPUT_FORMATS:
        log("warn", f"target {fmt} is single-frame; converting the first frame only")

    def prepare_frame(frame):
        frame = _apply_edits(frame, edits)
        if not meta["supports_alpha"] and frame.mode in {"RGBA", "LA", "P"}:
            rgba = frame.convert("RGBA")
            background = Image.new("RGB", frame.size, (255, 255, 255))
            background.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
            return background
        if frame.mode == "P":
            return frame.convert("RGBA")
        if frame.mode not in {"RGB", "RGBA", "L", "LA"}:
            return frame.convert("RGB")
        return frame

    if not meta["supports_alpha"] and raw_frames[0].mode in {"RGBA", "LA", "P"}:
        log("info", f"target {fmt} has no alpha — flattening on white background")
    frames = [prepare_frame(frame) for frame in raw_frames]
    img = frames[0]
    if _has_edits(edits):
        log("info", f"applied batch edits to {len(frames)} frame(s)")

    # Build save kwargs per format. Quality is honoured for lossy formats.
    save_kwargs: dict = {}
    quality = max(1, min(args.quality, 100))
    if fmt == "jpeg":
        save_kwargs.update(quality=quality, optimize=True, progressive=True)
    elif fmt == "webp":
        save_kwargs.update(quality=quality, method=4)
    elif fmt == "avif":
        # ROADMAP Item 89 — AVIF tuning controls. libavif 1.4.x adds gain-map
        # HDR import for Apple-style JPEG gain maps; full gain-map writing is
        # not exposed by pillow-avif-plugin yet, but speed / subsampling / ICC
        # pass-through cover the practical "AVIF as HDR-capable" use case.
        save_kwargs.update(quality=quality)
        speed = getattr(args, "avif_speed", None)
        if speed is not None:
            save_kwargs["speed"] = max(0, min(int(speed), 10))
        subsampling = (getattr(args, "avif_subsampling", None) or "").strip().lower()
        if subsampling in ("4:0:0", "4:2:0", "4:2:2", "4:4:4"):
            save_kwargs["subsampling"] = subsampling
        if getattr(args, "avif_lossless", False):
            save_kwargs["quality"] = 100
            save_kwargs["lossless"] = True
    elif fmt == "heic":
        save_kwargs.update(quality=quality)
    elif fmt == "png":
        save_kwargs.update(optimize=True, compress_level=6)
    elif fmt == "tiff":
        save_kwargs.update(compression="tiff_lzw")
    elif fmt == "jxl":
        # pillow-jxl-plugin honours `quality` (1-100) and a `lossless` toggle.
        # We expose lossless via quality=100; users who want strict lossless
        # can also pass --strip-icc=False --strip-exif=False --quality=100.
        if quality >= 100 and quality_target is None:
            save_kwargs.update(lossless=True)
        else:
            save_kwargs.update(quality=quality, effort=7)

    if len(frames) > 1:
        save_kwargs["save_all"] = True
        save_kwargs["append_images"] = frames[1:]
        if fmt == "webp":
            save_kwargs["duration"] = frame_durations
            save_kwargs["loop"] = int(source_info.get("loop", 0) or 0)

    # ICC profile pass-through (preserves colour fidelity across colour spaces).
    if not args.strip_icc and "icc_profile" in source_info:
        save_kwargs["icc_profile"] = source_info["icc_profile"]

    # EXIF pass-through (or strip if --strip-exif).
    if not args.strip_exif:
        exif = source_info.get("exif")
        if exif:
            save_kwargs["exif"] = exif

    target_details: dict | None = None
    if quality_target is not None:
        mode, target = quality_target
        progress(55.0, f"searching {mode}")
        vship = _find_vship() if mode == "target-ssimulacra2" else None
        if mode == "target-ssimulacra2" and not vship:
            return fail(
                "missing_vship",
                "--target-ssimulacra2 requires the local vship evaluator. "
                "Install or provision vship, then retry.",
            )

        try:
            with tempfile.TemporaryDirectory(prefix="ucx-quality-") as temp:
                temp_path = Path(temp)
                reference_path = temp_path / "reference.png"
                candidate_path = temp_path / f"candidate{meta['ext']}"
                if mode == "target-ssimulacra2":
                    img.convert("RGB").save(reference_path, format="PNG")

                def probe(candidate_quality: int) -> tuple[int, float | None]:
                    candidate_kwargs = dict(save_kwargs)
                    candidate_kwargs["quality"] = candidate_quality
                    candidate_kwargs.pop("lossless", None)
                    buffer = io.BytesIO()
                    img.save(buffer, format=meta["pil"], **candidate_kwargs)
                    payload = buffer.getvalue()
                    if mode == "target-kb":
                        return len(payload), None
                    if mode == "target-psnr":
                        from PIL import Image  # type: ignore
                        buffer.seek(0)
                        with Image.open(buffer) as decoded:
                            decoded.load()
                            return len(payload), _psnr(img, decoded)
                    candidate_path.write_bytes(payload)
                    return len(payload), _ssimulacra2_score(
                        vship, reference_path, candidate_path)  # type: ignore[arg-type]

                selected_quality, probe_size, metric, target_met = _binary_search_quality(
                    probe, target, mode)
        except Exception as exc:
            return fail("quality_search_failed", f"Could not evaluate {mode}: {exc}")

        save_kwargs["quality"] = selected_quality
        save_kwargs.pop("lossless", None)
        quality = selected_quality
        target_details = {
            "mode": mode,
            "target": target,
            "selected_quality": selected_quality,
            "probe_size_bytes": probe_size,
            "metric": metric,
            "target_met": target_met,
        }
        log(
            "info",
            f"{mode}: selected quality {selected_quality}, "
            f"probe size {probe_size} bytes, metric {metric:.2f}",
        )

    progress(70.0, f"encoding {fmt}")
    try:
        img.save(out_path, format=meta["pil"], **save_kwargs)
    except Exception as exc:
        return fail("encode_failed",
                    f"Could not save {fmt} (kwargs={list(save_kwargs)}): {exc}")

    if not out_path.is_file():
        return fail("output_missing", f"Encoder reported success but file not present: {out_path}")

    size = out_path.stat().st_size
    if target_details is not None:
        warning = _quality_warning(
            target_details["mode"],
            target_details["target"],
            target_details["selected_quality"],
            size,
            target_details["metric"],
            target_details["target_met"],
        )
        target_details["size_bytes"] = size
        target_details["warning"] = warning
        if warning:
            log("warn", warning)
    progress(100.0, "done")
    emit(
        "complete",
        output=str(out_path),
        size_bytes=size,
        format=fmt,
        quality=quality,
        quality_target=target_details,
        frames=len(frames),
        edits_applied=_has_edits(edits),
    )
    return 0


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="heicshift-sidecar",
        description="UCX HEICShift sidecar — Pillow + pillow_heif format converter.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    conv = sub.add_parser("convert", help="Convert one image")
    conv.add_argument("--input",  required=True, help="Input image path")
    conv.add_argument("--output", required=True,
                      help="Output path or directory (extension forced from --format)")
    conv.add_argument("--format", required=True,
                      help=f"Output format: one of {', '.join(OUTPUT_FORMATS)}")
    conv.add_argument("--quality", type=int, default=85,
                      help="Lossy quality 1–100 (jpeg/webp/avif/heic). Default 85.")
    targets = conv.add_mutually_exclusive_group()
    targets.add_argument(
        "--target-kb", type=float, default=None, dest="target_kb",
        help="Choose the highest quality that does not exceed this output size in KB.")
    targets.add_argument(
        "--target-psnr", type=float, default=None, dest="target_psnr",
        help="Choose the lowest quality meeting this minimum PSNR score.")
    targets.add_argument(
        "--target-ssimulacra2", type=float, default=None, dest="target_ssimulacra2",
        help="Choose the lowest quality meeting this local Vship SSIMULACRA2 score.")
    edits = conv.add_argument_group("batch image adjustments")
    edits.add_argument("--adjust-preset", choices=sorted(ADJUST_PRESETS), default=None,
                       help="Named look: vivid, muted, bw, vintage, cold, or warm.")
    edits.add_argument("--brightness", type=int, default=None,
                       help="Brightness adjustment from -100 to 100.")
    edits.add_argument("--contrast", type=int, default=None,
                       help="Contrast adjustment from -100 to 100.")
    edits.add_argument("--saturation", type=int, default=None,
                       help="Saturation adjustment from -100 to 100.")
    edits.add_argument("--sharpness", type=int, default=None,
                       help="Sharpness adjustment from 0 to 100.")
    edits.add_argument("--blur", type=float, default=None,
                       help="Gaussian blur radius from 0 to 20 pixels.")
    edits.add_argument("--hue", type=int, default=None,
                       help="Hue rotation from 0 to 360 degrees.")
    edits.add_argument("--grayscale", action="store_true",
                       help="Convert colours to grayscale while retaining alpha.")
    edits.add_argument("--sepia", action="store_true", help="Apply a sepia tone.")
    edits.add_argument("--invert", action="store_true", help="Invert image colours.")
    edits.add_argument("--vignette", type=int, default=None,
                       help="Radial edge darkening from 0 to 100.")
    edits.add_argument("--grain", type=int, default=None,
                       help="Film grain intensity from 0 to 100.")
    edits.add_argument("--tint", default=None,
                       help="Colour tint such as '#3a6ea5@20' or 'teal@30'.")
    edits.add_argument("--border", type=int, default=None,
                       help="Solid border width in pixels.")
    edits.add_argument("--border-color", default="#ffffff",
                       help="Border colour as #RRGGBB or a named colour.")
    conv.add_argument("--strip-exif", action="store_true",
                      help="Drop EXIF metadata from the output (default: preserve)")
    conv.add_argument("--strip-icc", action="store_true",
                      help="Drop ICC colour profile from the output (default: preserve)")
    conv.add_argument("--avif-speed", type=int, default=None, dest="avif_speed",
                      help="AVIF encoder speed 0..10 (default 6 via pillow-avif-plugin). "
                           "0 = slowest / best quality; 10 = fastest. Ignored for non-AVIF outputs.")
    conv.add_argument("--avif-subsampling", default=None, dest="avif_subsampling",
                      help="AVIF chroma subsampling: 4:0:0 (mono), 4:2:0 (default), "
                           "4:2:2, or 4:4:4 (best for HDR / gradient-heavy sources). "
                           "Ignored for non-AVIF outputs.")
    conv.add_argument("--avif-lossless", action="store_true", dest="avif_lossless",
                      help="Encode AVIF in lossless mode (overrides --quality, ignored for "
                           "non-AVIF outputs).")

    sub.add_parser("list-formats", help="Emit known input/output formats")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":
            _ensure_deps()
            return op_convert(args)
        if args.op == "list-formats":
            return op_list_formats(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

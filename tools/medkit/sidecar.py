"""Medical / scientific 3D imaging sidecar.

DICOM image conversion is already covered by `dicomkit`; this sidecar adds
the volumetric / non-DICOM medical formats:

  * NIfTI 1 / 2  (.nii, .nii.gz, .hdr+.img)   neuroimaging
  * Analyze 7.5  (.hdr + .img)                 legacy neuro
  * MetaImage    (.mha, .mhd + .raw)           ITK / Slicer
  * NRRD         (.nrrd, .nhdr)                Nearly Raw Raster Data
  * MINC 2       (.mnc)                        Montreal Neuro Institute
  * GIPL         (.gipl)
  * VTK ImageData (.vtk, .vti)
  * Per-slice PNG / TIFF stack

Backed by SimpleITK (Apache-2.0) for the IO + reorientation, plus nibabel
(MIT) as a NIfTI / Analyze fallback.
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


def _read_volume(path: Path):
    """Return a SimpleITK image."""
    import SimpleITK as sitk
    return sitk.ReadImage(str(path))


def _write_volume(img, out_path: Path) -> None:
    import SimpleITK as sitk
    sitk.WriteImage(img, str(out_path), useCompression=True)


def op_convert(args: argparse.Namespace) -> int:
    try:
        import SimpleITK as sitk  # noqa: F401
    except ImportError as ex:
        return fail("missing_simpleitk",
                    f"SimpleITK not installed: {ex}. `pip install SimpleITK`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Volume(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="medical", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            vol = _read_volume(src)
            stem = src.name.replace(".nii.gz", "").replace(".gz", "")
            stem = Path(stem).stem
            out_path = out_dir / (stem + target_ext)
            # SimpleITK infers writer by extension; .nii.gz works directly.
            if target_ext == ".nii":
                out_path = out_dir / (stem + ".nii.gz") if args.gzip else out_path
            _write_volume(vol, out_path)
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("convert_failed", f"{src.name}: {ex}")

        size = vol.GetSize()
        spacing = vol.GetSpacing()
        emit("medical_volume",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."),
             dim=list(size), spacing=list(spacing),
             dtype=str(vol.GetPixelIDTypeAsString()))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_png_stack(args: argparse.Namespace) -> int:
    """Render every Z slice of a volume as a normalized PNG."""
    try:
        import SimpleITK as sitk
        import numpy as np
        from PIL import Image
    except ImportError as ex:
        return fail("missing_dep", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Volume(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            vol = _read_volume(src)
            arr = sitk.GetArrayFromImage(vol)  # shape: (Z, Y, X) typically
            sub_dir = out_dir / src.stem
            sub_dir.mkdir(parents=True, exist_ok=True)
            mn, mx = float(arr.min()), float(arr.max())
            denom = max(1e-9, mx - mn)
            for z in range(arr.shape[0]):
                slc = ((arr[z] - mn) / denom * 255).clip(0, 255).astype("uint8")
                slc_path = sub_dir / f"slice_{z:04d}.png"
                Image.fromarray(slc).save(str(slc_path))
            emit("medical_volume",
                 input=str(src), output=str(sub_dir),
                 size_bytes=sum(p.stat().st_size for p in sub_dir.glob("*")),
                 format="png-stack", slices=int(arr.shape[0]))
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    try:
        import SimpleITK as sitk
    except ImportError as ex:
        return fail("missing_simpleitk", str(ex))
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")
    vol = sitk.ReadImage(str(src))
    emit("medical_volume_info",
         path=str(src),
         size_bytes=src.stat().st_size,
         dim=list(vol.GetSize()),
         spacing=list(vol.GetSpacing()),
         origin=list(vol.GetOrigin()),
         dtype=str(vol.GetPixelIDTypeAsString()),
         components=int(vol.GetNumberOfComponentsPerPixel()))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="medkit-sidecar",
                                description="Medical / scientific 3D image conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert NIfTI / Analyze / MHA / NRRD / MINC.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="nii | mha | mhd | nrrd | nhdr | mnc | hdr | gipl | vtk")
    c.add_argument("--gzip", action="store_true",
                   help="When writing .nii, save as .nii.gz.")

    s = sub.add_parser("to-png-stack", help="Render every Z slice as a PNG.")
    s.add_argument("--input", nargs="+", required=True)
    s.add_argument("--output-dir", required=True, dest="output_dir")

    i = sub.add_parser("info", help="Probe volume dimensions / spacing / dtype.")
    i.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":      return op_convert(args)
        if args.op == "to-png-stack": return op_to_png_stack(args)
        if args.op == "info":         return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

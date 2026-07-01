"""DICOM medical imaging sidecar -- read DCM files, export pixel data as PNG /
JPEG / TIFF, and optionally anonymise via pydicom.

Operations:
  to-image    DCM -> PNG / JPEG / TIFF (one image per DICOM file).
  anonymize   Strip patient-identifying tags into a sibling DCM.
  info        Emit a summary of patient / study / series / image attributes.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _imports():
    try:
        import pydicom  # noqa: F401
        import numpy as np  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_deps", message=f"pydicom/numpy/Pillow missing: {ex}")
        return False


# Tags that disclose patient identity. Removed by op_anonymize.
PII_TAGS = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex", "PatientAddress",
    "PatientTelephoneNumbers", "PatientMotherBirthName", "PatientBirthName",
    "OtherPatientNames", "OtherPatientIDs", "PatientWeight", "PatientSize",
    "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName",
    "ReferringPhysicianName", "PerformingPhysicianName", "OperatorsName",
    "AccessionNumber", "StudyID", "PerformedProcedureStepID",
    "DeviceSerialNumber",
]


def op_to_image(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    import pydicom, numpy as np
    from PIL import Image

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"DCM(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target not in ("png", "jpg", "jpeg", "tiff", "tif", "bmp"):
        return fail("bad_format", "Use png | jpg | jpeg | tiff | tif | bmp.")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="to-image", eta_seconds=None)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), force=True)
            arr = ds.pixel_array
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("read_failed", f"{src.name}: {ex}")

        # Normalise into 8-bit for PNG/JPG. Preserve 16-bit for TIFF.
        if target in ("tiff", "tif"):
            if arr.dtype == np.uint8:
                img = Image.fromarray(arr, mode="L")
            else:
                img = Image.fromarray(arr.astype(np.uint16), mode="I;16")
        else:
            mn, mx = float(arr.min()), float(arr.max())
            if mx > mn:
                norm = ((arr - mn) / (mx - mn) * 255.0).clip(0, 255).astype(np.uint8)
            else:
                norm = np.zeros_like(arr, dtype=np.uint8)
            img = Image.fromarray(norm)

        out_path = out_dir / (src.stem + "." + target)
        if target in ("jpg", "jpeg"):
            img.convert("L").save(str(out_path), quality=int(args.quality))
        else:
            img.save(str(out_path))

        emit("dicom_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             modality=str(getattr(ds, "Modality", "")),
             rows=int(getattr(ds, "Rows", 0)),
             cols=int(getattr(ds, "Columns", 0)))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_anonymize(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    import pydicom

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"DCM(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), force=True)
            for tag in PII_TAGS:
                if tag in ds:
                    try: setattr(ds, tag, "ANONYMIZED")
                    except Exception: pass
            out_path = out_dir / src.name
            ds.save_as(str(out_path))
        except Exception as ex:
            return fail("anonymize_failed", f"{src.name}: {ex}")
        emit("dicom_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size, anonymized=True)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    import pydicom
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"DCM not found: {args.input}")
    ds = pydicom.dcmread(str(src), force=True)
    fields = {
        "modality":      str(getattr(ds, "Modality", "")),
        "study_date":    str(getattr(ds, "StudyDate", "")),
        "series_desc":   str(getattr(ds, "SeriesDescription", "")),
        "rows":          int(getattr(ds, "Rows", 0)),
        "cols":          int(getattr(ds, "Columns", 0)),
        "bits":          int(getattr(ds, "BitsAllocated", 0)),
        "manufacturer":  str(getattr(ds, "Manufacturer", "")),
        "transfer_syntax": str(ds.file_meta.TransferSyntaxUID) if hasattr(ds, "file_meta") else "",
    }
    emit("dicom_info", path=str(src), **fields)
    emit("complete", output=str(src), size_bytes=src.stat().st_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dicomkit-sidecar",
                                description="DICOM medical imaging via pydicom.")
    sub = p.add_subparsers(dest="op", required=True)
    img = sub.add_parser("to-image", help="Export pixel data as PNG / JPEG / TIFF.")
    img.add_argument("--input", nargs="+", required=True)
    img.add_argument("--output-dir", required=True, dest="output_dir")
    img.add_argument("--format", default="png")
    img.add_argument("--quality", type=int, default=92)
    an = sub.add_parser("anonymize", help="Strip patient identifiers.")
    an.add_argument("--input", nargs="+", required=True)
    an.add_argument("--output-dir", required=True, dest="output_dir")
    inf = sub.add_parser("info", help="Probe a DICOM and emit core attributes.")
    inf.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-image":  return op_to_image(args)
        if args.op == "anonymize": return op_anonymize(args)
        if args.op == "info":      return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

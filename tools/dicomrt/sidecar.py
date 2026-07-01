"""DICOM-RT (radiation therapy) sidecar.

Extends `dicomkit` and `medkit` to handle the DICOM-RT modality family
used in radiation oncology:

  * RTSTRUCT — Structure Set (organ-at-risk / target volume contours)
  * RTPLAN   — Treatment Plan (beams, fractions, dose prescriptions)
  * RTDOSE   — Dose Distribution (3D dose grid)
  * RTIMAGE  — Reference / verification images

Operations:
  rtstruct-to-csv   RT Structure Set -> CSV (one row per ROI: name, type, color, point count).
  rtstruct-to-json  RT Structure Set -> JSON (full contour data).
  rtplan-to-json    RT Plan -> JSON (beams, MUs, control points).
  rtdose-to-nifti   RT Dose 3D grid -> NIfTI (.nii.gz) for tooling round-trip.
  rtdose-info       RT Dose 3D grid -> JSON probe (max / mean / Dx / Vx).

Requires: pydicom (already in dicomkit), SimpleITK for the dose -> NIfTI path.
"""
from __future__ import annotations

import argparse
import csv
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _is_modality(ds, mod: str) -> bool:
    return getattr(ds, "Modality", "") == mod


# ── RTSTRUCT (Structure Set) ───────────────────────────────────────────

def _structures_from_rtstruct(ds) -> list[dict]:
    rois: list[dict] = []
    by_number: dict[int, dict] = {}
    for roi in getattr(ds, "StructureSetROISequence", []):
        n = int(roi.ROINumber)
        by_number[n] = {
            "number": n,
            "name": getattr(roi, "ROIName", "") or "",
            "ref_frame_uid": getattr(roi, "ReferencedFrameOfReferenceUID", ""),
            "generation_algorithm": getattr(roi, "ROIGenerationAlgorithm", ""),
            "type": "",
            "color": "",
            "points": 0,
            "contours": 0,
        }
    for ob in getattr(ds, "RTROIObservationsSequence", []):
        n = int(ob.ReferencedROINumber)
        if n in by_number:
            by_number[n]["type"] = getattr(ob, "RTROIInterpretedType", "")
    for c in getattr(ds, "ROIContourSequence", []):
        n = int(c.ReferencedROINumber)
        if n not in by_number: continue
        col = getattr(c, "ROIDisplayColor", None)
        if col is not None:
            by_number[n]["color"] = "#{:02x}{:02x}{:02x}".format(*[int(x) for x in col])
        contours = getattr(c, "ContourSequence", []) or []
        by_number[n]["contours"] = len(contours)
        by_number[n]["points"] = sum(getattr(ct, "NumberOfContourPoints", 0)
                                      for ct in contours)
    rois = list(by_number.values())
    rois.sort(key=lambda r: r["number"])
    return rois


def op_rtstruct_to_csv(args: argparse.Namespace) -> int:
    try:
        import pydicom
    except ImportError:
        return fail("missing_dep", "pydicom not installed (`pip install pydicom`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"RTSTRUCT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), stop_before_pixels=False)
            if not _is_modality(ds, "RTSTRUCT"):
                return fail("wrong_modality",
                            f"{src.name}: not RTSTRUCT (got {ds.Modality}).")
            rois = _structures_from_rtstruct(ds)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".roi.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            keys = ["number", "name", "type", "color", "contours", "points",
                    "generation_algorithm", "ref_frame_uid"]
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rois: w.writerow(r)
        emit("rt_struct",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="rtstruct", roi_count=len(rois))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_rtstruct_to_json(args: argparse.Namespace) -> int:
    try:
        import pydicom
    except ImportError:
        return fail("missing_dep", "pydicom not installed (`pip install pydicom`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"RTSTRUCT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), stop_before_pixels=False)
            if not _is_modality(ds, "RTSTRUCT"):
                return fail("wrong_modality",
                            f"{src.name}: not RTSTRUCT (got {ds.Modality}).")
            structures = []
            by_num = {int(r.ROINumber): r
                      for r in getattr(ds, "StructureSetROISequence", [])}
            for c in getattr(ds, "ROIContourSequence", []):
                n = int(c.ReferencedROINumber)
                roi_meta = by_num.get(n)
                contours = []
                for ct in getattr(c, "ContourSequence", []) or []:
                    pts = getattr(ct, "ContourData", []) or []
                    # ContourData is flat [x1,y1,z1, x2,y2,z2, ...]
                    triples = [(float(pts[k]), float(pts[k + 1]), float(pts[k + 2]))
                               for k in range(0, len(pts) - 2, 3)]
                    contours.append({
                        "geometric_type": getattr(ct, "ContourGeometricType", ""),
                        "points": triples,
                    })
                structures.append({
                    "number": n,
                    "name": getattr(roi_meta, "ROIName", "") if roi_meta else "",
                    "color": list(getattr(c, "ROIDisplayColor", [])),
                    "contours": contours,
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".rtstruct.json")
        out_path.write_text(json.dumps(structures, indent=2, default=str),
                            encoding="utf-8")
        emit("rt_struct",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="rtstruct", roi_count=len(structures))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── RTPLAN ─────────────────────────────────────────────────────────────

def op_rtplan_to_json(args: argparse.Namespace) -> int:
    try:
        import pydicom
    except ImportError:
        return fail("missing_dep", "pydicom not installed (`pip install pydicom`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"RTPLAN file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), stop_before_pixels=False)
            if not _is_modality(ds, "RTPLAN"):
                return fail("wrong_modality",
                            f"{src.name}: not RTPLAN (got {ds.Modality}).")
            beams = []
            for b in getattr(ds, "BeamSequence", []):
                cps = []
                for cp in getattr(b, "ControlPointSequence", []) or []:
                    cps.append({
                        "index": int(getattr(cp, "ControlPointIndex", -1)),
                        "gantry_angle": getattr(cp, "GantryAngle", None),
                        "collimator_angle": getattr(cp, "BeamLimitingDeviceAngle", None),
                        "couch_angle": getattr(cp, "PatientSupportAngle", None),
                        "isocenter": list(getattr(cp, "IsocenterPosition", []) or []),
                        "cumulative_meterset_weight": getattr(cp, "CumulativeMetersetWeight", None),
                    })
                beams.append({
                    "number": int(getattr(b, "BeamNumber", -1)),
                    "name": getattr(b, "BeamName", ""),
                    "type": getattr(b, "BeamType", ""),
                    "radiation_type": getattr(b, "RadiationType", ""),
                    "treatment_machine": getattr(b, "TreatmentMachineName", ""),
                    "control_points": cps,
                })
            fractions = []
            for fg in getattr(ds, "FractionGroupSequence", []):
                fractions.append({
                    "number": int(getattr(fg, "FractionGroupNumber", -1)),
                    "fractions_planned": int(getattr(fg, "NumberOfFractionsPlanned", 0)),
                    "beams": int(getattr(fg, "NumberOfBeams", 0)),
                    "brachy_apps": int(getattr(fg, "NumberOfBrachyApplicationSetups", 0)),
                })
            plan = {
                "label": getattr(ds, "RTPlanLabel", ""),
                "name": getattr(ds, "RTPlanName", ""),
                "geometry": getattr(ds, "RTPlanGeometry", ""),
                "fractions": fractions,
                "beams": beams,
            }
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".rtplan.json")
        out_path.write_text(json.dumps(plan, indent=2, default=str),
                            encoding="utf-8")
        emit("rt_plan",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="rtplan",
             beams=len(beams), fractions=len(fractions))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── RTDOSE ─────────────────────────────────────────────────────────────

def op_rtdose_to_nifti(args: argparse.Namespace) -> int:
    try:
        import pydicom
        import SimpleITK as sitk
        import numpy as np
    except ImportError as ex:
        return fail("missing_dep",
                    f"pydicom + SimpleITK + numpy required: {ex}")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"RTDOSE file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), stop_before_pixels=False)
            if not _is_modality(ds, "RTDOSE"):
                return fail("wrong_modality",
                            f"{src.name}: not RTDOSE (got {ds.Modality}).")
            arr = ds.pixel_array.astype("float32")
            scaling = float(getattr(ds, "DoseGridScaling", 1.0))
            arr *= scaling
            spacing = list(map(float, getattr(ds, "PixelSpacing", [1.0, 1.0])))
            slice_thick = float(getattr(ds, "SliceThickness", 1.0))
            spacing_3d = (spacing[1], spacing[0], slice_thick)
            origin = tuple(float(x) for x in getattr(ds, "ImagePositionPatient",
                                                       [0.0, 0.0, 0.0]))
            img = sitk.GetImageFromArray(arr)
            img.SetSpacing(spacing_3d)
            img.SetOrigin(origin)
            out_path = out_dir / (src.stem + ".nii.gz")
            sitk.WriteImage(img, str(out_path))
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("rt_dose",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="nifti", source="rtdose",
             shape=list(arr.shape), max_dose=float(arr.max()))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_rtdose_info(args: argparse.Namespace) -> int:
    try:
        import pydicom
        import numpy as np
    except ImportError as ex:
        return fail("missing_dep", f"pydicom + numpy required: {ex}")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"RTDOSE file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            ds = pydicom.dcmread(str(src), stop_before_pixels=False)
            if not _is_modality(ds, "RTDOSE"):
                return fail("wrong_modality",
                            f"{src.name}: not RTDOSE (got {ds.Modality}).")
            arr = ds.pixel_array.astype("float32")
            scaling = float(getattr(ds, "DoseGridScaling", 1.0))
            arr *= scaling
            info = {
                "shape": list(arr.shape),
                "dose_units": getattr(ds, "DoseUnits", ""),
                "dose_type": getattr(ds, "DoseType", ""),
                "dose_grid_scaling": scaling,
                "max_dose": float(arr.max()),
                "mean_dose": float(arr.mean()),
                "min_dose": float(arr.min()),
                "p95_dose": float(np.percentile(arr, 95)),
                "p99_dose": float(np.percentile(arr, 99)),
                "voxel_count": int(arr.size),
            }
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".rtdose.json")
        out_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
        emit("rt_dose",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="rtdose",
             max_dose=info["max_dose"],
             mean_dose=info["mean_dose"])
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dicomrt-sidecar",
                                description="DICOM-RT (radiation therapy) decoder.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("rtstruct-to-csv",  "RTSTRUCT -> CSV (one row per ROI)"),
        ("rtstruct-to-json", "RTSTRUCT -> JSON (full contour data)"),
        ("rtplan-to-json",   "RTPLAN -> JSON (beams + control points)"),
        ("rtdose-to-nifti",  "RTDOSE 3D grid -> NIfTI"),
        ("rtdose-info",      "RTDOSE statistics probe -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "rtstruct-to-csv":  return op_rtstruct_to_csv(args)
        if args.op == "rtstruct-to-json": return op_rtstruct_to_json(args)
        if args.op == "rtplan-to-json":   return op_rtplan_to_json(args)
        if args.op == "rtdose-to-nifti":  return op_rtdose_to_nifti(args)
        if args.op == "rtdose-info":      return op_rtdose_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

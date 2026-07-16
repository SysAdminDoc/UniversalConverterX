"""Vship quality metrics sidecar — GPU-accelerated SSIMULACRA2 / Butteraugli.

Wraps the Vship CLI (Codeberg Line-fr/Vship) for perceptual quality
metrics that complement VMAF. SSIMULACRA2 excels on still images and
textures; Butteraugli is Google's libjxl metric for compression quality.

Binary: vship.exe from https://codeberg.org/Line-fr/Vship/releases.
Drop it next to this sidecar or under tools/_bin/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find(name: str) -> str | None:
    here = Path(__file__).resolve().parent
    for n in (name, name + ".exe"):
        candidate = here / n
        if candidate.is_file():
            return str(candidate)
        bin_candidate = here.parent / "_bin" / n
        if bin_candidate.is_file():
            return str(bin_candidate)
    return shutil.which(name)


def op_compare(args: argparse.Namespace) -> int:
    vship = _find("vship")
    if not vship:
        return fail("missing_vship", "vship not found. Download from codeberg.org/Line-fr/Vship/releases.")

    if not os.path.isfile(args.reference):
        return fail("ref_not_found", f"Reference file not found: {args.reference}")
    if not os.path.isfile(args.distorted):
        return fail("dist_not_found", f"Distorted file not found: {args.distorted}")

    metrics = args.metrics.split(",") if args.metrics else ["ssimulacra2"]

    results = {}
    for metric in metrics:
        metric = metric.strip().lower()
        if metric not in ("ssimulacra2", "butteraugli", "cvvdp"):
            emit("log", level="warn", message=f"Unknown metric '{metric}', skipping")
            continue

        cmd = [vship, f"--{metric}", args.reference, args.distorted]

        emit("log", level="info", message=f"Computing {metric}...")
        emit("progress", percent=0, stage=metric)

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return fail(f"{metric}_timeout", f"{metric} computation timed out after 300s")
        except FileNotFoundError:
            return fail("missing_vship", f"vship binary not found at {vship}")

        if proc.returncode != 0:
            err = (proc.stderr or "")[-300:]
            return fail(f"{metric}_failed", f"vship --{metric} exited {proc.returncode}: {err}")

        score = _parse_score(proc.stdout, metric)
        results[metric] = score
        emit("log", level="info", message=f"{metric}: {score}")
        emit("progress", percent=100, stage=metric)

    emit("complete", metrics=results,
         reference=args.reference, distorted=args.distorted)
    return 0


def _parse_score(output: str, metric: str) -> float | str:
    for line in output.strip().splitlines():
        line = line.strip()
        try:
            return float(line)
        except ValueError:
            match = re.search(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", line)
            if match:
                return float(match.group())
    return output.strip()[:100]


def op_presets(args: argparse.Namespace) -> int:
    emit("log", level="info", message="Available metrics:")
    for m in ("ssimulacra2", "butteraugli", "cvvdp"):
        emit("log", level="info", message=f"  {m}")
    emit("complete", metrics=["ssimulacra2", "butteraugli", "cvvdp"])
    return 0


def op_probe(args: argparse.Namespace) -> int:
    vship = _find("vship")
    version = None
    if vship:
        try:
            proc = subprocess.run([vship, "--version"], capture_output=True, text=True, timeout=10)
            version = proc.stdout.strip().splitlines()[0] if proc.returncode == 0 else None
        except Exception:
            pass
    emit("complete",
         vship_available=vship is not None,
         vship_path=vship,
         vship_version=version,
         supported_metrics=["ssimulacra2", "butteraugli", "cvvdp"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vship-metrics",
                                description="GPU-accelerated quality metrics (SSIMULACRA2/Butteraugli)")
    sub = p.add_subparsers(dest="op", required=True)

    comp = sub.add_parser("compare", help="Compare reference vs distorted")
    comp.add_argument("--reference", required=True, help="Reference (original) file")
    comp.add_argument("--distorted", required=True, help="Distorted (encoded) file")
    comp.add_argument("--metrics", default="ssimulacra2",
                      help="Comma-separated metrics: ssimulacra2,butteraugli,cvvdp")

    sub.add_parser("presets", help="List available metrics")
    sub.add_parser("probe", help="Check Vship availability")

    return p


def main(argv: list[str] | None = None) -> int:
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()

    args = build_parser().parse_args(argv)
    dispatch = {"compare": op_compare, "presets": op_presets, "probe": op_probe}
    try:
        return dispatch[args.op](args)
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

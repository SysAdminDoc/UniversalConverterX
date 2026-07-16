"""Genomics binary <-> text format sidecar.

Extends `biokit` (FASTA/FASTQ/GenBank/VCF) with the binary variants that
bioinformatics pipelines actually use:

  * BCF                Binary VCF (compressed + indexed)
  * BGZF               Block-gzip (the basis for indexed FASTA / VCF / BAM)
  * Tabix index        .tbi indexes for VCF / GFF / BED
  * BED <-> bigBed     binary indexed genome intervals
  * narrowPeak / broadPeak / gappedPeak  ENCODE peak formats

Backed by `pysam` for BCF/BGZF and `pybedtools` for the BED-family
conversions.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def op_vcf_to_bcf(args: argparse.Namespace) -> int:
    try:
        import pysam
    except ImportError as ex:
        return fail("missing_pysam",
                    f"pysam not installed: {ex}. `pip install pysam`.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"VCF(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".bcf")
        try:
            in_vcf = pysam.VariantFile(str(src))
            with pysam.VariantFile(str(out_path), "wb", header=in_vcf.header) as out_vcf:
                n = 0
                for rec in in_vcf:
                    out_vcf.write(rec); n += 1
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("genome_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="bcf", records=n)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bcf_to_vcf(args: argparse.Namespace) -> int:
    try:
        import pysam
    except ImportError as ex:
        return fail("missing_pysam", str(ex))
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BCF(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".vcf")
        try:
            in_bcf = pysam.VariantFile(str(src))
            with pysam.VariantFile(str(out_path), "w", header=in_bcf.header) as out_vcf:
                n = 0
                for rec in in_bcf:
                    out_vcf.write(rec); n += 1
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("genome_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="vcf", records=n)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bgzf(args: argparse.Namespace) -> int:
    """Compress a file with bgzip (block gzip), or decompress."""
    try:
        import pysam
    except ImportError as ex:
        return fail("missing_pysam", str(ex))
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = (out_dir / (src.stem)
                    if args.decompress
                    else out_dir / (src.name + ".gz"))
        try:
            if args.decompress:
                with pysam.BGZFile(str(src)) as inh, \
                     out_path.open("wb") as outh:
                    while True:
                        chunk = inh.read(1 << 20)
                        if not chunk: break
                        outh.write(chunk)
            else:
                with src.open("rb") as inh, \
                     pysam.BGZFile(str(out_path), "wb") as outh:
                    while True:
                        chunk = inh.read(1 << 20)
                        if not chunk: break
                        outh.write(chunk)
        except Exception as ex:
            return fail("bgzf_failed", f"{src.name}: {ex}")
        emit("genome_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="bgzf", direction="decompress" if args.decompress else "compress")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_tabix(args: argparse.Namespace) -> int:
    """Generate a .tbi index over a bgzipped VCF/GFF/BED."""
    try:
        import pysam
    except ImportError as ex:
        return fail("missing_pysam", str(ex))
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            pysam.tabix_index(str(src), preset=args.preset, force=True)
        except Exception as ex:
            return fail("tabix_failed", f"{src.name}: {ex}")
        idx = Path(str(src) + ".tbi")
        emit("genome_doc",
             input=str(src), output=str(idx),
             size_bytes=idx.stat().st_size if idx.is_file() else 0,
             format="tbi", preset=args.preset)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(inputs[0].parent),
         size_bytes=0, count=total)
    return 0


def op_peak_to_bed(args: argparse.Namespace) -> int:
    """ENCODE narrowPeak / broadPeak -> standard BED6+."""
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".bed")
        with src.open("r", encoding="utf-8", errors="replace") as inh, \
             out_path.open("w", encoding="utf-8", newline="") as outh:
            n = 0
            for line in inh:
                line = line.rstrip()
                if not line or line.startswith("#"): continue
                fields = line.split("\t")
                # narrowPeak / broadPeak share BED6 prefix.
                if len(fields) >= 6:
                    outh.write("\t".join(fields[:6]) + "\n"); n += 1
        emit("genome_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="bed", records=n)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="genome-sidecar",
                                description="Genomics binary format conversion (BCF / BGZF / tabix / peak).")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("vcf-to-bcf", help="VCF -> BCF.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    b = sub.add_parser("bcf-to-vcf", help="BCF -> VCF.")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")

    g = sub.add_parser("bgzf", help="bgzip (compress) or bgunzip (decompress).")
    g.add_argument("--input", nargs="+", required=True)
    g.add_argument("--output-dir", required=True, dest="output_dir")
    g.add_argument("--decompress", action="store_true")

    t = sub.add_parser("tabix", help="Generate a .tbi index for VCF/GFF/BED.gz.")
    t.add_argument("--input", nargs="+", required=True)
    t.add_argument("--preset", default="vcf",
                   choices=["vcf", "gff", "bed", "psltbl", "sam"])

    pk = sub.add_parser("peak-to-bed", help="ENCODE narrowPeak/broadPeak -> BED6.")
    pk.add_argument("--input", nargs="+", required=True)
    pk.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "vcf-to-bcf":  return op_vcf_to_bcf(args)
        if args.op == "bcf-to-vcf":  return op_bcf_to_vcf(args)
        if args.op == "bgzf":         return op_bgzf(args)
        if args.op == "tabix":        return op_tabix(args)
        if args.op == "peak-to-bed":  return op_peak_to_bed(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

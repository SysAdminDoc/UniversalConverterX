"""Bioinformatics file-format sidecar.

Sequence + alignment + variant + annotation file conversion via Biopython
(BSD-3) and pysam (MIT) for SAM/BAM/CRAM, plus stdlib for VCF parsing.

Inputs / outputs:
  * FASTA (.fa, .fasta, .fna, .faa, .ffn)  Sequence
  * FASTQ (.fq, .fastq)                     Sequence + quality
  * GenBank (.gb, .gbk)                     NCBI annotated sequence
  * EMBL (.embl)                            EBI annotated sequence
  * GFF3 / GTF (.gff, .gff3, .gtf)          Annotation
  * BED (.bed)                              Genomic intervals
  * SAM / BAM / CRAM                        Sequence alignment
  * VCF / BCF                               Variant calls
  * Newick (.nwk, .newick)                  Phylogenetic trees
  * Stockholm / Clustal / PHYLIP / NEXUS    Multiple alignment formats

Operations:
  convert    Mutual conversion across the BioPython-supported set.
  fastq-stats     Quick QC stats: length distribution, GC %, mean Q.
  vcf-to-tsv      Flatten VCF info fields to a tab-delimited table.
  bam-to-fastq    Extract reads from BAM/CRAM back to FASTQ.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
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


# ------- Biopython sequence conversion ---------------------------------------

BP_FORMATS = {
    "fasta": "fasta", "fa": "fasta", "fna": "fasta", "faa": "fasta", "ffn": "fasta",
    "fastq": "fastq", "fq": "fastq",
    "genbank": "genbank", "gb": "genbank", "gbk": "genbank",
    "embl": "embl",
    "phylip": "phylip",
    "stockholm": "stockholm", "sto": "stockholm",
    "clustal": "clustal", "aln": "clustal",
    "nexus": "nexus",
    "newick": "newick", "nwk": "newick",
}


def _open_maybe_gz(path: Path, mode: str = "rt"):
    if path.suffix.lower() == ".gz":
        return gzip.open(str(path), mode, encoding="utf-8")
    return open(str(path), mode, encoding="utf-8")


def op_convert(args: argparse.Namespace) -> int:
    try:
        from Bio import SeqIO, AlignIO
    except ImportError as ex:
        return fail("missing_biopython",
                    f"biopython not installed: {ex}. `pip install biopython`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Sequence file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    target_fmt = BP_FORMATS.get(target, target)
    out_ext = "." + target

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="bio", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        # Strip .gz so we can probe the real ext.
        real_ext = ext.lstrip(".")
        if ext == ".gz":
            real_ext = src.with_suffix("").suffix.lstrip(".")
        in_fmt = BP_FORMATS.get(real_ext, real_ext)

        out_path = out_dir / (src.stem.replace(".gz", "") + out_ext)
        try:
            with _open_maybe_gz(src) as inh, out_path.open("w", encoding="utf-8") as outh:
                # Try sequence I/O first; fall back to alignment I/O.
                try:
                    n = SeqIO.convert(inh, in_fmt, outh, target_fmt)
                except Exception:
                    inh.seek(0)
                    aln = AlignIO.read(inh, in_fmt)
                    n = AlignIO.write([aln], outh, target_fmt)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("bio_seq",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, records=int(n))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_fastq_stats(args: argparse.Namespace) -> int:
    try:
        from Bio import SeqIO
    except ImportError as ex:
        return fail("missing_biopython", str(ex))
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")

    counts = {"reads": 0, "bases": 0, "gc": 0, "q_sum": 0, "q_count": 0}
    lens: list[int] = []
    with _open_maybe_gz(src) as inh:
        for rec in SeqIO.parse(inh, "fastq"):
            counts["reads"] += 1
            seq = str(rec.seq).upper()
            counts["bases"] += len(seq)
            counts["gc"] += seq.count("G") + seq.count("C")
            qual = rec.letter_annotations.get("phred_quality", [])
            counts["q_sum"] += sum(qual); counts["q_count"] += len(qual)
            lens.append(len(seq))

    if not lens:
        return fail("empty", "No FASTQ records.")
    lens.sort()
    emit("bio_stats",
         path=str(src),
         reads=counts["reads"],
         bases=counts["bases"],
         gc_percent=round(counts["gc"] / max(1, counts["bases"]) * 100, 2),
         mean_quality=round(counts["q_sum"] / max(1, counts["q_count"]), 2),
         length_min=lens[0], length_max=lens[-1],
         length_median=lens[len(lens) // 2])
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=counts["reads"])
    return 0


def op_vcf_to_tsv(args: argparse.Namespace) -> int:
    """Flatten VCF -> TSV (chrom, pos, ref, alt, info-fields...)."""
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"VCF not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (src.stem + ".tsv")

    columns = ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
    with _open_maybe_gz(src) as inh, out_path.open("w", encoding="utf-8", newline="") as outh:
        w = csv.writer(outh, delimiter="\t")
        w.writerow(columns)
        for line in inh:
            if line.startswith("#") or not line.strip(): continue
            fields = line.rstrip("\n").split("\t")[:8]
            w.writerow(fields)
    emit("bio_seq",
         input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="tsv", source="vcf")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_bam_to_fastq(args: argparse.Namespace) -> int:
    try:
        import pysam
    except ImportError as ex:
        return fail("missing_pysam", f"pysam not installed: {ex}.")

    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"BAM/CRAM/SAM not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (src.stem + ".fastq")

    with pysam.AlignmentFile(str(src), "rb") as bam, out_path.open("w", encoding="utf-8") as outh:
        n = 0
        for r in bam.fetch(until_eof=True):
            if r.is_unmapped or r.query_sequence is None: continue
            qual = "".join(chr(q + 33) for q in (r.query_qualities or []))
            outh.write(f"@{r.query_name}\n{r.query_sequence}\n+\n{qual}\n")
            n += 1
    emit("bio_seq",
         input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="fastq", records=n, source="bam")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="biokit-sidecar",
                                description="Bioinformatics file-format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert FASTA / FASTQ / GenBank / EMBL / Newick / Clustal / PHYLIP / Stockholm / NEXUS.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="fasta | fastq | genbank | embl | phylip | stockholm | clustal | nexus | newick")

    f = sub.add_parser("fastq-stats", help="QC stats on a FASTQ file.")
    f.add_argument("--input", required=True)

    v = sub.add_parser("vcf-to-tsv", help="Flatten VCF -> TSV.")
    v.add_argument("--input", required=True)
    v.add_argument("--output-dir", required=True, dest="output_dir")

    b = sub.add_parser("bam-to-fastq", help="Extract reads from BAM/CRAM -> FASTQ.")
    b.add_argument("--input", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":      return op_convert(args)
        if args.op == "fastq-stats":  return op_fastq_stats(args)
        if args.op == "vcf-to-tsv":   return op_vcf_to_tsv(args)
        if args.op == "bam-to-fastq": return op_bam_to_fastq(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""BED genome-interval format conversion sidecar.

The BED (Browser Extensible Data) format is the lingua franca for
genome interval data. This sidecar handles the BED variants used by
ENCODE / UCSC / Ensembl pipelines:

  * BED3 (chrom, start, end)
  * BED6 (BED3 + name, score, strand)
  * BED12 (BED6 + thick start/end + RGB + block sizes/starts)
  * narrowPeak (BED6 + signal/pValue/qValue/peak)  — ENCODE
  * broadPeak  (BED6 + signal/pValue/qValue)       — ENCODE
  * gappedPeak (BED12 + signal/pValue/qValue)      — ENCODE
  * bigBed (binary; converted via UCSC bedToBigBed / bigBedToBed)
  * GFF3 (Generic Feature Format)
  * GTF (Gene Transfer Format)

Operations:
  to-bed6       Coerce any BED-like to BED6 (drop or fill missing cols).
  bed-to-csv    BED -> CSV with named columns.
  bed-to-json   BED -> JSON array.
  bigbed-to-bed bigBed -> BED via UCSC bigBedToBed CLI.
  bed-to-bigbed BED + chrom.sizes -> bigBed via UCSC bedToBigBed CLI.
  gff-to-bed    GFF3 -> BED6 (strand from col 7, name from attributes).
  gtf-to-bed    GTF  -> BED6 (gene_id / transcript_id pulled from attr).
"""
from __future__ import annotations

import argparse
import csv
import json
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


# ── BED schemas ────────────────────────────────────────────────────────

BED_COLUMNS = [
    "chrom", "start", "end", "name", "score", "strand",
    "thickStart", "thickEnd", "itemRgb", "blockCount",
    "blockSizes", "blockStarts",
]
NARROWPEAK_COLUMNS = [
    "chrom", "start", "end", "name", "score", "strand",
    "signalValue", "pValue", "qValue", "peak",
]
BROADPEAK_COLUMNS = [
    "chrom", "start", "end", "name", "score", "strand",
    "signalValue", "pValue", "qValue",
]


def _read_bed(path: Path) -> tuple[list[dict], int]:
    """Return (rows, max_cols). Lines starting with `track`/`browser`/`#` skipped."""
    rows: list[dict] = []
    max_cols = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "track", "browser")): continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3: continue
        if len(parts) > max_cols: max_cols = len(parts)
        row: dict = {}
        for i, col in enumerate(BED_COLUMNS):
            if i >= len(parts): break
            row[col] = parts[i]
        # convert numeric columns
        for k in ("start", "end", "score", "thickStart", "thickEnd",
                  "blockCount"):
            if row.get(k) and row[k].lstrip("-").isdigit():
                row[k] = int(row[k])
        rows.append(row)
    return rows, max_cols


def _to_bed6(rows: list[dict]) -> list[list]:
    out = []
    for r in rows:
        out.append([
            r.get("chrom", ""),
            r.get("start", 0),
            r.get("end", 0),
            r.get("name") or ".",
            r.get("score", 0),
            r.get("strand") or ".",
        ])
    return out


# ── Operations ─────────────────────────────────────────────────────────

def op_to_bed6(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BED file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            rows, _ = _read_bed(src)
            bed6 = _to_bed6(rows)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".bed6")
        with out_path.open("w", encoding="utf-8", newline="\n") as f:
            for r in bed6:
                f.write("\t".join(str(x) for x in r) + "\n")
        emit("genome_interval",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="bed6", source="bed", count=len(bed6))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bed_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BED file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            rows, max_cols = _read_bed(src)
            cols = BED_COLUMNS[:max_cols] if max_cols <= 12 else BED_COLUMNS
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("genome_interval",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="bed", count=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bed_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BED file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            rows, _ = _read_bed(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        emit("genome_interval",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="bed", count=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bigbed_to_bed(args: argparse.Namespace) -> int:
    cli = shutil.which("bigBedToBed")
    if not cli: return fail("missing_dep", "bigBedToBed (UCSC) not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".bb file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".bed")
        proc = subprocess.run([cli, str(src), str(out_path)],
                               capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: bigBedToBed exit {proc.returncode}: "
                        f"{proc.stderr}")
        emit("genome_interval",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="bed", source="bigbed")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bed_to_bigbed(args: argparse.Namespace) -> int:
    cli = shutil.which("bedToBigBed")
    if not cli: return fail("missing_dep", "bedToBigBed (UCSC) not on PATH.")
    sizes = Path(args.chrom_sizes)
    if not sizes.is_file():
        return fail("missing_input", f"chrom.sizes not found: {sizes}")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BED file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".bb")
        proc = subprocess.run([cli, str(src), str(sizes), str(out_path)],
                               capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: bedToBigBed exit {proc.returncode}: "
                        f"{proc.stderr}")
        emit("genome_interval",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="bigbed", source="bed")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── GFF / GTF -> BED ───────────────────────────────────────────────────

_GTF_KEY_RE = re.compile(r'(\w+)\s+"([^"]*)"')


def _parse_gff_attributes(attr: str) -> dict:
    out: dict = {}
    if "=" in attr:  # GFF3
        for pair in attr.split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1); out[k.strip()] = v.strip()
    else:  # GTF
        for m in _GTF_KEY_RE.finditer(attr):
            out[m.group(1)] = m.group(2)
    return out


def _gff_to_bed_rows(text: str) -> list[list]:
    rows: list[list] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        parts = line.split("\t")
        if len(parts) < 9: continue
        chrom = parts[0]
        start = int(parts[3]) - 1   # GFF/GTF are 1-based; BED is 0-based.
        end = int(parts[4])
        score = parts[5] if parts[5] != "." else "0"
        strand = parts[6] if parts[6] in ("+", "-") else "."
        attr = _parse_gff_attributes(parts[8])
        name = (attr.get("ID") or attr.get("gene_id")
                or attr.get("transcript_id") or attr.get("Name") or ".")
        rows.append([chrom, start, end, name, score, strand])
    return rows


def op_gff_to_bed(args: argparse.Namespace) -> int:
    return _gx_to_bed(args, "gff")


def op_gtf_to_bed(args: argparse.Namespace) -> int:
    return _gx_to_bed(args, "gtf")


def _gx_to_bed(args: argparse.Namespace, kind: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"{kind} file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            rows = _gff_to_bed_rows(src.read_text(encoding="utf-8",
                                                   errors="replace"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".bed")
        with out_path.open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write("\t".join(str(x) for x in r) + "\n")
        emit("genome_interval",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="bed6", source=kind, count=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bed-sidecar",
                                description="BED / bigBed / GFF / GTF genome interval conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    for op, helpstr in [
        ("to-bed6",       "Any BED-like -> BED6"),
        ("bed-to-csv",    "BED -> CSV with named cols"),
        ("bed-to-json",   "BED -> JSON array"),
        ("bigbed-to-bed", "bigBed -> BED via UCSC bigBedToBed"),
        ("gff-to-bed",    "GFF3 -> BED6"),
        ("gtf-to-bed",    "GTF -> BED6"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")

    bb = sub.add_parser("bed-to-bigbed", help="BED + chrom.sizes -> bigBed.")
    bb.add_argument("--input", nargs="+", required=True)
    bb.add_argument("--output-dir", required=True, dest="output_dir")
    bb.add_argument("--chrom-sizes", required=True, dest="chrom_sizes")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-bed6":       return op_to_bed6(args)
        if args.op == "bed-to-csv":    return op_bed_to_csv(args)
        if args.op == "bed-to-json":   return op_bed_to_json(args)
        if args.op == "bigbed-to-bed": return op_bigbed_to_bed(args)
        if args.op == "bed-to-bigbed": return op_bed_to_bigbed(args)
        if args.op == "gff-to-bed":    return op_gff_to_bed(args)
        if args.op == "gtf-to-bed":    return op_gtf_to_bed(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Mass-spectrometry / proteomics format sidecar.

Convert mass-spec data formats to analysis-friendly outputs:

  * mzML (HUPO-PSI XML standard)        -> JSON / CSV peak list
  * mzXML (older ISB format)            -> JSON / CSV peak list
  * mzIdentML (peptide identification)  -> JSON / CSV
  * mascot / sequest .dat              -> manifest only
  * MGF (Mascot Generic Format)         -> JSON / mzML approximation

Operations:
  mzml-to-json      mzML XML -> JSON.
  mzml-to-csv       mzML peak lists -> CSV (one row per spectrum).
  mzxml-to-json     mzXML -> JSON.
  mgf-to-json       MGF -> JSON spectrum list.
  mgf-to-csv        MGF -> CSV (one row per spectrum).

Pure stdlib (xml.etree). For DDA / DIA workflows where pyteomics is
already installed, prefer that — but this gives a no-deps fallback.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


# ── mzML decoding ──────────────────────────────────────────────────────

def _b64_to_floats(b64: str, precision_bits: int, compressed: bool) -> list[float]:
    raw = base64.b64decode(b64)
    if compressed: raw = zlib.decompress(raw)
    fmt = "<f" if precision_bits == 32 else "<d"
    width = 4 if precision_bits == 32 else 8
    return [struct.unpack(fmt, raw[i:i + width])[0]
            for i in range(0, len(raw), width)]


def _parse_mzml(path: Path, decode_peaks: bool = True) -> list[dict]:
    spectra: list[dict] = []
    for _, elem in ET.iterparse(str(path), events=("end",)):
        if _strip_ns(elem.tag) != "spectrum": continue
        sp: dict = {"id": elem.get("id"), "index": elem.get("index"),
                     "ms_level": None, "scan_start_time": None}
        binary_arrays: list[tuple[str, list[float]]] = []
        cur_array_kind: str | None = None
        cur_precision = 64
        cur_compressed = False
        for child in elem.iter():
            tag = _strip_ns(child.tag)
            if tag == "cvParam":
                acc = child.get("accession", "")
                name = child.get("name", "")
                value = child.get("value", "")
                if acc == "MS:1000511": sp["ms_level"] = int(value)
                if acc == "MS:1000016": sp["scan_start_time"] = value
                if acc == "MS:1000523": cur_precision = 64
                if acc == "MS:1000521": cur_precision = 32
                if acc == "MS:1000574": cur_compressed = True
                if acc == "MS:1000514": cur_array_kind = "mz"
                if acc == "MS:1000515": cur_array_kind = "intensity"
            if tag == "binary" and decode_peaks and child.text:
                if cur_array_kind:
                    floats = _b64_to_floats(child.text.strip(),
                                             cur_precision, cur_compressed)
                    binary_arrays.append((cur_array_kind, floats))
                cur_array_kind = None
                cur_compressed = False
                cur_precision = 64
        peaks: list[tuple[float, float]] = []
        mz_vals: list[float] = []
        int_vals: list[float] = []
        for kind, vals in binary_arrays:
            if kind == "mz": mz_vals = vals
            elif kind == "intensity": int_vals = vals
        if mz_vals and int_vals:
            peaks = list(zip(mz_vals, int_vals))
        sp["peaks"] = [{"mz": m, "i": i} for m, i in peaks]
        sp["peak_count"] = len(peaks)
        spectra.append(sp)
        elem.clear()
    return spectra


# ── mzXML decoding ─────────────────────────────────────────────────────

def _parse_mzxml(path: Path) -> list[dict]:
    spectra: list[dict] = []
    for _, elem in ET.iterparse(str(path), events=("end",)):
        if _strip_ns(elem.tag) != "scan": continue
        sp: dict = {
            "num": elem.get("num"),
            "ms_level": int(elem.get("msLevel", "0")) or None,
            "retention_time": elem.get("retentionTime"),
            "polarity": elem.get("polarity"),
            "peaks_count": int(elem.get("peaksCount", "0")),
        }
        for child in elem:
            if _strip_ns(child.tag) == "peaks" and child.text:
                precision = int(child.get("precision", "32"))
                compressed = child.get("compressionType") == "zlib"
                pairs: list[float] = []
                try:
                    pairs = _b64_to_floats(child.text.strip(),
                                            precision, compressed)
                except Exception:
                    pairs = []
                sp["peaks"] = [{"mz": pairs[i], "i": pairs[i + 1]}
                               for i in range(0, len(pairs) - 1, 2)]
        spectra.append(sp)
        elem.clear()
    return spectra


# ── MGF (Mascot Generic Format) ────────────────────────────────────────

def _parse_mgf(text: str) -> list[dict]:
    spectra: list[dict] = []
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        if line == "BEGIN IONS":
            cur = {"peaks": []}; continue
        if line == "END IONS":
            if cur is not None:
                cur["peak_count"] = len(cur["peaks"])
                spectra.append(cur)
            cur = None; continue
        if cur is None: continue
        if "=" in line:
            k, _, v = line.partition("=")
            cur[k.strip().lower()] = v.strip()
        else:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    cur["peaks"].append({"mz": float(parts[0]),
                                          "i": float(parts[1])})
                except ValueError:
                    pass
    return spectra


# ── Operations ─────────────────────────────────────────────────────────

def _write(args, parser, source: str, suffix: str, peaks_in_csv: bool) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            spectra = parser(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        if suffix == "json":
            out_path = out_dir / (src.stem + ".json")
            out_path.write_text(json.dumps(spectra, indent=2,
                                           default=str),
                                encoding="utf-8")
        else:
            out_path = out_dir / (src.stem + ".csv")
            with out_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["index", "id", "ms_level", "rt", "peak_count",
                             "mz_first", "mz_last"])
                for n, sp in enumerate(spectra, 1):
                    peaks = sp.get("peaks") or []
                    mz_first = peaks[0]["mz"] if peaks else ""
                    mz_last = peaks[-1]["mz"] if peaks else ""
                    w.writerow([n, sp.get("id") or sp.get("num", ""),
                                 sp.get("ms_level"),
                                 sp.get("scan_start_time")
                                  or sp.get("retention_time", ""),
                                 sp.get("peak_count") or len(peaks),
                                 mz_first, mz_last])
        emit("massspec_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=suffix, source=source, spectra=len(spectra))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_mzml_to_json(args):  return _write(args, lambda p: _parse_mzml(p, True),  "mzml",  "json", False)
def op_mzml_to_csv(args):   return _write(args, lambda p: _parse_mzml(p, True),  "mzml",  "csv",  True)
def op_mzxml_to_json(args): return _write(args, _parse_mzxml,                    "mzxml", "json", False)
def op_mgf_to_json(args):   return _write(args, lambda p: _parse_mgf(p.read_text(encoding="utf-8", errors="replace")),
                                          "mgf", "json", False)
def op_mgf_to_csv(args):    return _write(args, lambda p: _parse_mgf(p.read_text(encoding="utf-8", errors="replace")),
                                          "mgf", "csv", True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="proteomics-sidecar",
                                description="Mass spec / proteomics format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("mzml-to-json",   "mzML -> JSON spectra"),
        ("mzml-to-csv",    "mzML -> CSV (one row per spectrum)"),
        ("mzxml-to-json",  "mzXML -> JSON spectra"),
        ("mgf-to-json",    "MGF -> JSON spectra"),
        ("mgf-to-csv",     "MGF -> CSV"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "mzml-to-json":  return op_mzml_to_json(args)
        if args.op == "mzml-to-csv":   return op_mzml_to_csv(args)
        if args.op == "mzxml-to-json": return op_mzxml_to_json(args)
        if args.op == "mgf-to-json":   return op_mgf_to_json(args)
        if args.op == "mgf-to-csv":    return op_mgf_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

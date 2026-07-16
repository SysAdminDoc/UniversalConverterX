"""Oscilloscope waveform converter sidecar.

Convert oscilloscope-vendor binary waveform formats into universal CSV
(time + amplitude per row) so they can be analysed in any tool:

  * Tektronix .wfm / .isf
  * LeCroy .trc (also called .dat / .lcw)
  * Keysight / Agilent .bin / .scp
  * Yokogawa .wdf
  * Rigol .csv with header (already CSV but normalize)
  * NI / Saleae Logic .csv

Operations:
  isf-to-csv     Tektronix .isf (ASCII / curve-array variants) -> CSV.
  wfm-to-csv     Tektronix .wfm v3+ binary -> CSV.
  trc-to-csv     LeCroy .trc -> CSV.
  bin-to-csv     Keysight / Agilent .bin -> CSV.
  scope-info     Probe header of any of the above -> JSON.

Pure stdlib (struct + array). The .wfm v3+ format is documented
publicly by Tektronix (TM-WFMx); .trc by LeCroy.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Tektronix .isf (curve-array ASCII headers) ─────────────────────────

def _parse_isf(data: bytes) -> tuple[dict, list[float]]:
    """ISF: ASCII header followed by `:CURVE #<dlen-digits><dlen-bytes>`."""
    header_end = data.find(b":CURVE #")
    if header_end < 0:
        # Older ISF: ASCII-only with `:CURVE` followed by ASCII numbers
        header_end = data.find(b":CURVE ")
        if header_end < 0:
            raise ValueError("No :CURVE marker.")
    header = data[:header_end].decode("latin-1", errors="replace")
    meta: dict = {}
    for tok in re.findall(r":(\w+(?:\s\w+)*)\s+([^;]+)", header):
        meta[tok[0].strip().upper()] = tok[1].strip()
    if data[header_end + 7:header_end + 8] != b"#":
        # fallback ASCII curve
        ascii_part = data[header_end + 7:].decode("latin-1", errors="replace")
        vals = [float(x) for x in re.split(r"[,\s]+", ascii_part) if x]
        return meta, vals
    p = header_end + 8
    dlen_digit = int(chr(data[p])); p += 1
    dlen = int(data[p:p + dlen_digit].decode("ascii")); p += dlen_digit
    raw = data[p:p + dlen]
    nbits = int(meta.get("BIT_NR", "8"))
    encdg = meta.get("ENCDG", "BIN").upper()
    bytes_per_pt = nbits // 8
    fmt_char = "h" if bytes_per_pt == 2 else "b"
    byte_order = ">" if "MSB" in meta.get("BYT_OR", "") else "<"
    count = len(raw) // bytes_per_pt
    ints = struct.unpack(f"{byte_order}{fmt_char * count}", raw[:count * bytes_per_pt])
    ymult = float(meta.get("YMULT", "1"))
    yoff = float(meta.get("YOFF", "0"))
    yzero = float(meta.get("YZERO", "0"))
    vals = [(v - yoff) * ymult + yzero for v in ints]
    return meta, vals


def op_isf_to_csv(args: argparse.Namespace) -> int:
    return _scope_to_csv(args, _parse_isf, "tektronix-isf")


def op_isf_info(args: argparse.Namespace) -> int:
    return _scope_info(args, _parse_isf, "tektronix-isf")


# ── Tektronix .wfm (v3+ binary) ────────────────────────────────────────

def _parse_wfm(data: bytes) -> tuple[dict, list[float]]:
    if len(data) < 838:
        raise ValueError("Not a Tektronix .wfm v3 (too small).")
    byte_order = struct.unpack(">H", data[0:2])[0]
    bo = ">" if byte_order == 0x0F0F else "<"
    version_text = data[2:9].decode("latin-1", errors="replace")
    n_dig = data[9]
    n_byte = data[10]
    n_marker = data[11]
    # Read selected curve scale + offset:
    explicit_dim_off = 168
    dim_scale = struct.unpack(f"{bo}d", data[explicit_dim_off + 16:explicit_dim_off + 24])[0]
    dim_offset = struct.unpack(f"{bo}d", data[explicit_dim_off + 24:explicit_dim_off + 32])[0]
    # Curve data offset:
    curve_offset = struct.unpack(f"{bo}I", data[16:20])[0]
    pre_charge = struct.unpack(f"{bo}I", data[curve_offset:curve_offset + 4])[0]
    data_start = curve_offset + 4 + pre_charge
    point_count = struct.unpack(f"{bo}I",
                                  data[curve_offset + 8:curve_offset + 12])[0]
    fmt_char = {1: "b", 2: "h", 4: "i"}.get(n_byte, "b")
    raw = data[data_start:data_start + point_count * n_byte]
    if not raw:
        raise ValueError("Empty curve data.")
    count = len(raw) // n_byte
    ints = struct.unpack(f"{bo}{fmt_char * count}", raw[:count * n_byte])
    vals = [v * dim_scale + dim_offset for v in ints]
    meta = {
        "version": version_text.strip(),
        "byte_order": "big" if bo == ">" else "little",
        "bytes_per_point": n_byte,
        "dim_scale": dim_scale,
        "dim_offset": dim_offset,
        "points": count,
    }
    return meta, vals


def op_wfm_to_csv(args: argparse.Namespace) -> int:
    return _scope_to_csv(args, _parse_wfm, "tektronix-wfm")


def op_wfm_info(args: argparse.Namespace) -> int:
    return _scope_info(args, _parse_wfm, "tektronix-wfm")


# ── LeCroy .trc ────────────────────────────────────────────────────────

def _parse_trc(data: bytes) -> tuple[dict, list[float]]:
    """LeCroy waveform template (LECROY 'WAVEDESC' descriptor)."""
    idx = data.find(b"WAVEDESC")
    if idx < 0: raise ValueError("Not a LeCroy .trc (no WAVEDESC).")
    desc = data[idx:idx + 346]
    bo = ">" if desc[34] == 0 else "<"
    wave_array_count = struct.unpack(f"{bo}I", desc[116:120])[0]
    bytes_per_point = 1 if struct.unpack(f"{bo}H", desc[32:34])[0] == 0 else 2
    user_text_len = struct.unpack(f"{bo}I", desc[40:44])[0]
    trigger_time_array_len = struct.unpack(f"{bo}I", desc[48:52])[0]
    ris_time_array_len = struct.unpack(f"{bo}I", desc[52:56])[0]
    res_array1 = struct.unpack(f"{bo}I", desc[60:64])[0]
    wave_array_1_size = struct.unpack(f"{bo}I", desc[60:64])[0]
    vertical_gain = struct.unpack(f"{bo}f", desc[156:160])[0]
    vertical_offset = struct.unpack(f"{bo}f", desc[160:164])[0]
    data_offset = idx + 346 + user_text_len + trigger_time_array_len + ris_time_array_len
    raw = data[data_offset:data_offset + wave_array_1_size]
    count = len(raw) // bytes_per_point
    fmt = "b" if bytes_per_point == 1 else "h"
    ints = struct.unpack(f"{bo}{fmt * count}", raw[:count * bytes_per_point])
    vals = [v * vertical_gain - vertical_offset for v in ints]
    meta = {
        "byte_order": "big" if bo == ">" else "little",
        "bytes_per_point": bytes_per_point,
        "vertical_gain": vertical_gain,
        "vertical_offset": vertical_offset,
        "points": count,
    }
    return meta, vals


def op_trc_to_csv(args: argparse.Namespace) -> int:
    return _scope_to_csv(args, _parse_trc, "lecroy-trc")


# ── Keysight / Agilent .bin ────────────────────────────────────────────

def _parse_keysight_bin(data: bytes) -> tuple[dict, list[float]]:
    """Keysight Infiniium .bin format: 'AG1000\\x00' or 'AG1100\\x00' magic."""
    if not (data.startswith(b"AG1000") or data.startswith(b"AG1100")):
        raise ValueError("Not a Keysight .bin (magic mismatch).")
    file_version = struct.unpack("<I", data[6:10])[0]
    file_size = struct.unpack("<I", data[10:14])[0]
    waveforms = struct.unpack("<I", data[14:18])[0]
    p = 18
    # First waveform header (we extract only the first):
    header_size = struct.unpack("<I", data[p + 0:p + 4])[0]
    waveform_type = struct.unpack("<I", data[p + 4:p + 8])[0]
    n_buffers = struct.unpack("<I", data[p + 8:p + 12])[0]
    points = struct.unpack("<I", data[p + 12:p + 16])[0]
    x_increment = struct.unpack("<d", data[p + 76:p + 84])[0]
    x_origin = struct.unpack("<d", data[p + 84:p + 92])[0]
    y_data_offset = p + header_size
    buf_hdr_size = struct.unpack("<I", data[y_data_offset:y_data_offset + 4])[0]
    buf_type = struct.unpack("<H", data[y_data_offset + 4:y_data_offset + 6])[0]
    bytes_per_pt = struct.unpack("<H", data[y_data_offset + 6:y_data_offset + 8])[0]
    buf_size = struct.unpack("<I", data[y_data_offset + 8:y_data_offset + 12])[0]
    samples_start = y_data_offset + buf_hdr_size
    raw = data[samples_start:samples_start + buf_size]
    if bytes_per_pt == 4:
        count = len(raw) // 4
        floats = struct.unpack(f"<{count}f", raw[:count * 4])
        vals = list(floats)
    else:
        count = len(raw) // bytes_per_pt
        fmt = "h" if bytes_per_pt == 2 else "b"
        ints = struct.unpack(f"<{count}{fmt}", raw[:count * bytes_per_pt])
        vals = [float(v) for v in ints]
    meta = {
        "version": file_version, "waveforms": waveforms,
        "x_increment": x_increment, "x_origin": x_origin,
        "points": count, "bytes_per_point": bytes_per_pt,
    }
    return meta, vals


def op_bin_to_csv(args: argparse.Namespace) -> int:
    return _scope_to_csv(args, _parse_keysight_bin, "keysight-bin")


# ── Shared scope writers ───────────────────────────────────────────────

def _scope_to_csv(args, parser, source) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"scope file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            meta, vals = parser(src.read_bytes())
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["index", "amplitude"])
            for k, v in enumerate(vals): w.writerow([k, v])
        emit("scope_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source=source, points=len(vals))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def _scope_info(args, parser, source) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"scope file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            meta, vals = parser(src.read_bytes())
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        probes.append({"file": str(src), **meta})
        emit("scope_doc",
             input=str(src), output="",
             size_bytes=0, format="json", source=source, points=len(vals))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / (source + "-info.json")
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scope-sidecar",
                                description="Oscilloscope waveform conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("isf-to-csv",  "Tektronix .isf -> CSV"),
        ("wfm-to-csv",  "Tektronix .wfm v3+ -> CSV"),
        ("trc-to-csv",  "LeCroy .trc -> CSV"),
        ("bin-to-csv",  "Keysight / Agilent .bin -> CSV"),
        ("isf-info",    "Tektronix .isf header probe"),
        ("wfm-info",    "Tektronix .wfm header probe"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "isf-to-csv":  return op_isf_to_csv(args)
        if args.op == "wfm-to-csv":  return op_wfm_to_csv(args)
        if args.op == "trc-to-csv":  return op_trc_to_csv(args)
        if args.op == "bin-to-csv":  return op_bin_to_csv(args)
        if args.op == "isf-info":    return op_isf_info(args)
        if args.op == "wfm-info":    return op_wfm_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

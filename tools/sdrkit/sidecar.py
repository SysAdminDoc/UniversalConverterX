"""Software-Defined Radio (SDR) IQ-file format sidecar.

Convert between common IQ (in-phase / quadrature) sample formats used
by SDR receivers (RTL-SDR, HackRF, BladeRF, USRP):

  * .cu8 / .iq8u   — interleaved unsigned 8-bit (RTL-SDR)
  * .cs8 / .iq8s   — interleaved signed 8-bit
  * .cs16 / .iq16  — interleaved signed 16-bit (HackRF / BladeRF)
  * .cf32 / .raw   — interleaved 32-bit float (GNU Radio)
  * SigMF (.sigmf-meta + .sigmf-data) — open SDR metadata standard
  * WAV-IQ — single WAV file holding interleaved I/Q

Operations:
  cu8-to-cs16     8-bit unsigned IQ -> 16-bit signed IQ.
  cs16-to-cf32    16-bit signed IQ -> 32-bit float IQ.
  cf32-to-cs16    32-bit float IQ -> 16-bit signed IQ.
  iq-stats        Compute mean / max / RMS over IQ stream -> JSON.
  sigmf-info      SigMF .sigmf-meta probe -> JSON.

Pure stdlib (struct + array). Streams the file in chunks to avoid OOM
on large captures.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_CHUNK = 1024 * 1024  # 1 MiB I/O chunks


def _convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> int:
    samples = 0
    with src.open("rb") as fin, dst.open("wb") as fout:
        while True:
            buf = fin.read(_CHUNK)
            if not buf: break
            if src_fmt == "cu8":
                # unsigned 8-bit; centred at 127.5
                vals = [(b - 127.5) / 127.5 for b in buf]
            elif src_fmt == "cs8":
                vals = [int.from_bytes(bytes([b]), "little", signed=True) / 128.0
                        for b in buf]
            elif src_fmt == "cs16":
                count = len(buf) // 2
                ints = struct.unpack("<" + "h" * count, buf[:count * 2])
                vals = [v / 32768.0 for v in ints]
            elif src_fmt == "cf32":
                count = len(buf) // 4
                floats = struct.unpack("<" + "f" * count, buf[:count * 4])
                vals = list(floats)
            else:
                raise ValueError(f"Unknown source format: {src_fmt}")
            samples += len(vals)
            if dst_fmt == "cs16":
                out_bytes = struct.pack("<" + "h" * len(vals),
                                         *(max(-32768, min(32767, int(v * 32767)))
                                           for v in vals))
            elif dst_fmt == "cf32":
                out_bytes = struct.pack("<" + "f" * len(vals), *vals)
            elif dst_fmt == "cu8":
                out_bytes = bytes(max(0, min(255, int(round(v * 127.5 + 127.5))))
                                   for v in vals)
            else:
                raise ValueError(f"Unknown dest format: {dst_fmt}")
            fout.write(out_bytes)
    return samples


def _convert_loop(args, src_fmt: str, dst_fmt: str, dst_ext: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"IQ file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + dst_ext)
        try:
            samples = _convert(src, out_path, src_fmt, dst_fmt)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("sdr_iq",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=dst_fmt, source=src_fmt, samples=samples // 2)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_cu8_to_cs16(args):  return _convert_loop(args, "cu8",  "cs16", "iq16")
def op_cs16_to_cf32(args): return _convert_loop(args, "cs16", "cf32", "cf32")
def op_cf32_to_cs16(args): return _convert_loop(args, "cf32", "cs16", "iq16")


def op_iq_stats(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"IQ file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.iq_format.lower()

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            samples = 0
            i_max = q_max = -float("inf")
            i_min = q_min = float("inf")
            i_sum = q_sum = 0.0
            i_sq = q_sq = 0.0
            with src.open("rb") as f:
                while True:
                    buf = f.read(_CHUNK)
                    if not buf: break
                    if fmt == "cu8":
                        vals = [(b - 127.5) / 127.5 for b in buf]
                    elif fmt == "cs16":
                        count = len(buf) // 2
                        ints = struct.unpack("<" + "h" * count, buf[:count * 2])
                        vals = [v / 32768.0 for v in ints]
                    elif fmt == "cf32":
                        count = len(buf) // 4
                        vals = list(struct.unpack("<" + "f" * count,
                                                    buf[:count * 4]))
                    else:
                        raise ValueError(f"Unknown format: {fmt}")
                    for k in range(0, len(vals) - 1, 2):
                        I, Q = vals[k], vals[k + 1]
                        i_max = max(i_max, I); q_max = max(q_max, Q)
                        i_min = min(i_min, I); q_min = min(q_min, Q)
                        i_sum += I; q_sum += Q
                        i_sq += I * I; q_sq += Q * Q
                        samples += 1
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        if samples == 0:
            return fail("empty", f"{src.name}: no IQ samples decoded.")
        stats = {
            "samples": samples,
            "i_max": i_max, "i_min": i_min,
            "i_mean": i_sum / samples, "i_rms": (i_sq / samples) ** 0.5,
            "q_max": q_max, "q_min": q_min,
            "q_mean": q_sum / samples, "q_rms": (q_sq / samples) ** 0.5,
            "format": fmt,
        }
        out_path = out_dir / (src.stem + "_stats.json")
        out_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        emit("sdr_iq",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source=fmt, samples=samples)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_sigmf_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SigMF meta file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            meta = json.loads(src.read_text(encoding="utf-8"))
            global_data = meta.get("global", {})
            captures = meta.get("captures", [])
            annotations = meta.get("annotations", [])
            probes.append({
                "file": str(src),
                "data_format": global_data.get("core:datatype", ""),
                "sample_rate": global_data.get("core:sample_rate"),
                "captures": len(captures),
                "annotations": len(annotations),
                "size_bytes": src.stat().st_size,
            })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("sdr_iq",
             input=str(src), output="",
             size_bytes=0, format="json", source="sigmf",
             captures=len(captures))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "sigmf-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdrkit-sidecar",
                                description="Software-Defined Radio IQ format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("cu8-to-cs16",  "RTL-SDR .cu8 -> 16-bit signed IQ"),
        ("cs16-to-cf32", "16-bit signed IQ -> 32-bit float IQ"),
        ("cf32-to-cs16", "32-bit float IQ -> 16-bit signed IQ"),
        ("sigmf-info",   "SigMF metadata probe"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")

    iq = sub.add_parser("iq-stats", help="Compute IQ stream statistics -> JSON")
    iq.add_argument("--input", nargs="+", required=True)
    iq.add_argument("--output-dir", required=True, dest="output_dir")
    iq.add_argument("--iq-format", required=True, dest="iq_format",
                     help="cu8 / cs16 / cf32")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "cu8-to-cs16":  return op_cu8_to_cs16(args)
        if args.op == "cs16-to-cf32": return op_cs16_to_cf32(args)
        if args.op == "cf32-to-cs16": return op_cf32_to_cs16(args)
        if args.op == "iq-stats":     return op_iq_stats(args)
        if args.op == "sigmf-info":   return op_sigmf_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

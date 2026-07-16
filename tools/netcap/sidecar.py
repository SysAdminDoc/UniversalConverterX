"""Network capture file sidecar.

Convert between PCAP (libpcap classic) and PCAPNG (next-gen) plus quick
JSON / CSV summaries of packet contents.

Backed by `scapy` (GPL-2) for cross-format read/write and protocol probing.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _read_packets(path: Path):
    from scapy.all import rdpcap, PcapNgReader
    if path.suffix.lower() in (".pcapng", ".ntar"):
        with PcapNgReader(str(path)) as r:
            return list(r)
    return rdpcap(str(path))


def _write_packets(packets, out_path: Path) -> None:
    from scapy.all import wrpcap, PcapNgWriter
    if out_path.suffix.lower() in (".pcapng", ".ntar"):
        with PcapNgWriter(str(out_path)) as w:
            for p in packets: w.write(p)
        return
    wrpcap(str(out_path), packets)


def op_convert(args: argparse.Namespace) -> int:
    try:
        import scapy.all  # noqa: F401
    except ImportError as ex:
        return fail("missing_scapy",
                    f"scapy not installed: {ex}. `pip install scapy`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Capture file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="netcap", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            packets = _read_packets(src)
            out_path = out_dir / (src.stem + target_ext)
            _write_packets(packets, out_path)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("net_capture",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."),
             packets=len(packets))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_csv(args: argparse.Namespace) -> int:
    try:
        from scapy.all import IP, IPv6, TCP, UDP, ICMP
    except ImportError as ex:
        return fail("missing_scapy", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Capture file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        packets = _read_packets(src)
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["#", "time", "src", "dst", "protocol", "length",
                         "src_port", "dst_port", "summary"])
            for n, p in enumerate(packets, 1):
                t = float(getattr(p, "time", 0.0) or 0.0)
                src_addr = p[IP].src if IP in p else (p[IPv6].src if IPv6 in p else "")
                dst_addr = p[IP].dst if IP in p else (p[IPv6].dst if IPv6 in p else "")
                proto = ("TCP" if TCP in p else "UDP" if UDP in p
                         else "ICMP" if ICMP in p
                         else (p.lastlayer().name if p else ""))
                sport = p[TCP].sport if TCP in p else (p[UDP].sport if UDP in p else "")
                dport = p[TCP].dport if TCP in p else (p[UDP].dport if UDP in p else "")
                w.writerow([n, f"{t:.6f}", src_addr, dst_addr, proto,
                             len(p), sport, dport, p.summary()])
        emit("net_capture",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", packets=len(packets))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="netcap-sidecar",
                                description="Network capture format conversion (PCAP <-> PCAPNG + summaries).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="PCAP <-> PCAPNG mutual conversion.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True, choices=["pcap", "pcapng"])

    csvp = sub.add_parser("to-csv", help="Flatten packets to a CSV summary.")
    csvp.add_argument("--input", nargs="+", required=True)
    csvp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "to-csv":  return op_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

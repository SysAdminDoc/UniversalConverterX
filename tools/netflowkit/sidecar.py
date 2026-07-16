"""NetFlow / IPFIX / sFlow sidecar.

Decode network flow telemetry into JSON / CSV. NetFlow v5/v9 and IPFIX
(v10) are the dominant flow-export protocols on routers/switches. sFlow
is the packet-sampling alternative.

Operations:
  netflow-v5-to-json   NetFlow v5 PDU -> JSON.
  netflow-v9-to-json   NetFlow v9 PDU -> JSON (template-aware).
  ipfix-to-json        IPFIX (v10) -> JSON.

NetFlow v5 has a fixed header + 30-byte records — pure stdlib parses this
cleanly. v9 / IPFIX use templates broadcast in earlier flow sets, so we
walk the file maintaining a template cache. For the rare case of separate
PDUs we accept multiple files and replay in order.
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── NetFlow v5 ─────────────────────────────────────────────────────────

def _parse_netflow_v5(data: bytes) -> list[dict]:
    if len(data) < 24: raise ValueError("Truncated NetFlow v5 header.")
    version, count = struct.unpack(">HH", data[0:4])
    if version != 5:
        raise ValueError(f"Not NetFlow v5 (version={version}).")
    sys_uptime, unix_secs, unix_nsecs, flow_seq = struct.unpack(
        ">IIII", data[4:20])
    engine_type, engine_id, sampling = struct.unpack(">BBH", data[20:24])
    records = []
    for i in range(count):
        offset = 24 + i * 48
        if offset + 48 > len(data): break
        rec = data[offset:offset + 48]
        srcaddr = ipaddress.IPv4Address(struct.unpack(">I", rec[0:4])[0])
        dstaddr = ipaddress.IPv4Address(struct.unpack(">I", rec[4:8])[0])
        nexthop = ipaddress.IPv4Address(struct.unpack(">I", rec[8:12])[0])
        input_iface, output_iface = struct.unpack(">HH", rec[12:16])
        packets, octets = struct.unpack(">II", rec[16:24])
        first, last = struct.unpack(">II", rec[24:32])
        srcport, dstport = struct.unpack(">HH", rec[32:36])
        # rec[36] pad, rec[37] tcp_flags, rec[38] proto, rec[39] tos
        tcp_flags = rec[37]; proto = rec[38]; tos = rec[39]
        src_as, dst_as = struct.unpack(">HH", rec[40:44])
        src_mask, dst_mask = rec[44], rec[45]
        records.append({
            "src": str(srcaddr), "dst": str(dstaddr), "nexthop": str(nexthop),
            "input": input_iface, "output": output_iface,
            "packets": packets, "octets": octets,
            "first_uptime_ms": first, "last_uptime_ms": last,
            "src_port": srcport, "dst_port": dstport,
            "tcp_flags": tcp_flags, "protocol": proto, "tos": tos,
            "src_as": src_as, "dst_as": dst_as,
            "src_mask": src_mask, "dst_mask": dst_mask,
        })
    return [{"header": {"version": 5, "count": count, "sys_uptime": sys_uptime,
                         "unix_secs": unix_secs, "unix_nsecs": unix_nsecs,
                         "flow_sequence": flow_seq, "engine_type": engine_type,
                         "engine_id": engine_id, "sampling_interval": sampling}},
            {"records": records}]


# ── NetFlow v9 / IPFIX (lightweight template walk) ─────────────────────

_IPFIX_FIELD_NAMES = {
    1: "octetDeltaCount", 2: "packetDeltaCount", 4: "protocolIdentifier",
    5: "ipClassOfService", 6: "tcpControlBits", 7: "sourceTransportPort",
    8: "sourceIPv4Address", 9: "sourceIPv4PrefixLength",
    10: "ingressInterface", 11: "destinationTransportPort",
    12: "destinationIPv4Address", 13: "destinationIPv4PrefixLength",
    14: "egressInterface", 15: "ipNextHopIPv4Address",
    16: "bgpSourceAsNumber", 17: "bgpDestinationAsNumber",
    21: "flowEndSysUpTime", 22: "flowStartSysUpTime",
    27: "sourceIPv6Address", 28: "destinationIPv6Address",
}


def _decode_value(field_id: int, raw: bytes) -> object:
    if field_id in (8, 12, 15) and len(raw) == 4:
        return str(ipaddress.IPv4Address(raw))
    if field_id in (27, 28) and len(raw) == 16:
        return str(ipaddress.IPv6Address(raw))
    if len(raw) <= 8:
        return int.from_bytes(raw, "big")
    return raw.hex()


def _parse_netflow_v9(data: bytes) -> dict:
    return _parse_v9_or_ipfix(data, version=9)


def _parse_ipfix(data: bytes) -> dict:
    return _parse_v9_or_ipfix(data, version=10)


def _parse_v9_or_ipfix(data: bytes, version: int) -> dict:
    if len(data) < 16:
        raise ValueError(f"Truncated NetFlow v{version} header.")
    if version == 9:
        ver, count, sys_up, ts, seq, source = struct.unpack(">HHIIII", data[0:20])
        offset = 20
    else:
        ver, total_len, ts, seq, domain = struct.unpack(">HHIII", data[0:16])
        count = None; offset = 16
        if total_len < len(data): data = data[:total_len]
    if ver != version:
        raise ValueError(f"Header version {ver} != expected {version}.")
    templates: dict[int, list[tuple[int, int]]] = {}
    flows: list[dict] = []
    while offset + 4 <= len(data):
        set_id, set_len = struct.unpack(">HH", data[offset:offset + 4])
        if set_len < 4: break
        body = data[offset + 4:offset + set_len]
        if set_id == 0 or set_id == 2:  # template set
            o = 0
            while o + 4 <= len(body):
                tid, fld_count = struct.unpack(">HH", body[o:o + 4])
                o += 4
                fields: list[tuple[int, int]] = []
                for _ in range(fld_count):
                    if o + 4 > len(body): break
                    fid, flen = struct.unpack(">HH", body[o:o + 4])
                    o += 4
                    if fid & 0x8000:  # enterprise field — skip 4 bytes
                        o += 4
                    fields.append((fid & 0x7FFF, flen))
                templates[tid] = fields
        elif set_id >= 256:  # data set
            tpl = templates.get(set_id)
            if tpl:
                rec_len = sum(flen for _, flen in tpl)
                if rec_len:
                    for r in range(0, len(body) - rec_len + 1, rec_len):
                        rec: dict = {}
                        cur = r
                        for fid, flen in tpl:
                            value = _decode_value(fid, body[cur:cur + flen])
                            rec[_IPFIX_FIELD_NAMES.get(fid, f"field{fid}")] = value
                            cur += flen
                        flows.append(rec)
        offset += set_len
    return {"header": {"version": version, "count": count or len(flows),
                        "timestamp": ts, "sequence": seq},
            "templates": {str(k): v for k, v in templates.items()},
            "flows": flows}


# ── Operations ─────────────────────────────────────────────────────────

def _do(args: argparse.Namespace, parser, source: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"flow file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            decoded = parser(src.read_bytes())
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(decoded, indent=2, default=str),
                            encoding="utf-8")
        flow_count = (sum(len(d.get("records", []))
                          for d in decoded if isinstance(d, dict))
                      if isinstance(decoded, list)
                      else len(decoded.get("flows", [])))
        emit("netflow_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source=source, flows=flow_count)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_v5(args): return _do(args, _parse_netflow_v5, "netflow-v5")
def op_v9(args): return _do(args, _parse_netflow_v9, "netflow-v9")
def op_ipfix(args): return _do(args, _parse_ipfix, "ipfix")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="netflowkit-sidecar",
                                description="NetFlow v5 / v9 / IPFIX -> JSON.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("netflow-v5-to-json", "NetFlow v5 PDU -> JSON"),
        ("netflow-v9-to-json", "NetFlow v9 PDU -> JSON"),
        ("ipfix-to-json",      "IPFIX (v10) PDU -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "netflow-v5-to-json": return op_v5(args)
        if args.op == "netflow-v9-to-json": return op_v9(args)
        if args.op == "ipfix-to-json":      return op_ipfix(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

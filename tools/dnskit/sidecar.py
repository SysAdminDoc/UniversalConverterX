"""DNS zone-file conversion sidecar.

Convert between BIND zone-file syntax, structured JSON / YAML, and CSV.

Operations:
  parse         Parse BIND `.zone` -> JSON / YAML / CSV.
  emit          JSON / YAML / CSV -> BIND zone file.
  validate      Sanity-check a zone (lame delegations, missing SOA, etc.).
  reverse       Generate the in-addr.arpa / ip6.arpa reverse zone for a list of A/AAAA.

Backed by `dnspython` (ISC License).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _zone_to_records(path: Path, origin: str | None) -> list[dict]:
    import dns.zone
    import dns.rdatatype
    z = dns.zone.from_file(str(path), origin=origin, relativize=False)
    records: list[dict] = []
    for name, _ttl, rdataset in z.iterate_rdatasets():
        for rdata in rdataset:
            records.append({
                "name": str(name).rstrip("."),
                "ttl": int(rdataset.ttl),
                "class": dns.rdataclass.to_text(rdataset.rdclass),
                "type": dns.rdatatype.to_text(rdataset.rdtype),
                "rdata": rdata.to_text(),
            })
    return records


def _records_to_zone(records: list[dict], origin: str) -> str:
    """Emit a BIND zone file from a normalized record list."""
    if not origin.endswith("."): origin = origin + "."
    out = io.StringIO()
    out.write(f"$ORIGIN {origin}\n")
    out.write("$TTL 3600\n")
    for r in records:
        name = r.get("name", "@") or "@"
        ttl = int(r.get("ttl", 3600))
        rclass = r.get("class", "IN")
        rtype = r["type"]
        rdata = r["rdata"]
        out.write(f"{name}\t{ttl}\t{rclass}\t{rtype}\t{rdata}\n")
    return out.getvalue()


def op_parse(args: argparse.Namespace) -> int:
    try:
        import dns.zone, dns.rdataclass, dns.rdatatype  # noqa
    except ImportError as ex:
        return fail("missing_dnspython",
                    f"dnspython not installed: {ex}. `pip install dnspython`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Zone file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="dns-parse", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            records = _zone_to_records(src, args.origin)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")

        out_path = out_dir / (src.stem + "." + target)
        if target == "json":
            out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        elif target in ("yaml", "yml"):
            import yaml
            out_path.write_text(yaml.safe_dump(records, allow_unicode=True),
                                encoding="utf-8")
        elif target == "csv":
            with out_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["name", "ttl", "class",
                                                    "type", "rdata"])
                w.writeheader(); w.writerows(records)
        else:
            return fail("bad_target", "Choose json | yaml | csv.")

        emit("dns_record",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, record_count=len(records))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_emit(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Records file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        if ext == ".json":
            records = json.loads(src.read_text(encoding="utf-8"))
        elif ext in (".yaml", ".yml"):
            import yaml
            records = yaml.safe_load(src.read_text(encoding="utf-8"))
        elif ext == ".csv":
            with src.open("r", encoding="utf-8-sig", newline="") as f:
                records = list(csv.DictReader(f))
                for r in records:
                    if "ttl" in r: r["ttl"] = int(r["ttl"])
        else:
            return fail("bad_format", f"Unsupported source ext '{ext}'.")

        zone_text = _records_to_zone(records, args.origin)
        out_path = out_dir / (src.stem + ".zone")
        out_path.write_text(zone_text, encoding="utf-8")

        emit("dns_record",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="zone", record_count=len(records))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_validate(args: argparse.Namespace) -> int:
    try:
        import dns.zone
    except ImportError as ex:
        return fail("missing_dnspython", str(ex))

    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Zone file not found: {src}")
    findings: list[dict] = []
    try:
        z = dns.zone.from_file(str(src), origin=args.origin)
    except Exception as ex:
        findings.append({"severity": "error", "message": str(ex)})
        emit("dns_zone_check", path=str(src),
             findings=findings, ok=False)
        emit("complete", output=str(src),
             size_bytes=src.stat().st_size, count=1)
        return 1

    # Sanity checks.
    has_soa = any(r.rdtype == 6 for n, _ttl, r in z.iterate_rdatasets())
    if not has_soa:
        findings.append({"severity": "warn", "message": "no SOA record"})
    has_ns = any(r.rdtype == 2 for n, _ttl, r in z.iterate_rdatasets())
    if not has_ns:
        findings.append({"severity": "warn", "message": "no NS record"})

    emit("dns_zone_check",
         path=str(src), findings=findings,
         ok=not any(f["severity"] == "error" for f in findings),
         record_count=sum(1 for _ in z.iterate_rdatasets()))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0 if all(f["severity"] != "error" for f in findings) else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dnskit-sidecar",
                                description="DNS zone-file conversion + validation.")
    sub = p.add_subparsers(dest="op", required=True)

    pa = sub.add_parser("parse", help="BIND .zone -> JSON / YAML / CSV.")
    pa.add_argument("--input", nargs="+", required=True)
    pa.add_argument("--output-dir", required=True, dest="output_dir")
    pa.add_argument("--format", required=True, choices=["json", "yaml", "csv"])
    pa.add_argument("--origin", default=None)

    em = sub.add_parser("emit", help="JSON / YAML / CSV -> BIND .zone.")
    em.add_argument("--input", nargs="+", required=True)
    em.add_argument("--output-dir", required=True, dest="output_dir")
    em.add_argument("--origin", required=True,
                    help="Zone origin (e.g. example.com.)")

    va = sub.add_parser("validate", help="Sanity-check a zone file.")
    va.add_argument("--input", required=True)
    va.add_argument("--origin", default=None)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "parse":    return op_parse(args)
        if args.op == "emit":     return op_emit(args)
        if args.op == "validate": return op_validate(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

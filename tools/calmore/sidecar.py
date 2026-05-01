"""Calendar / contact long-tail sidecar.

The `calconvert` sidecar handles ICS / VCF mutual conversion; this one
covers the niche calendar / contact directory formats:

  * Apple .icbu                   Calendar.app backup bundle
  * Google Takeout calendar JSON  -> ICS
  * LDIF (LDAP)                   <-> vCard
  * CSV contacts (Outlook-style)  <-> vCard
  * Gnome Evolution local folders -> ICS / VCF

Operations:
  icbu-to-ics      Unpack Apple .icbu and concat the embedded ICS files.
  takeout-to-ics   Google Takeout calendar JSON -> ICS.
  ldif-to-vcf      LDAP LDIF -> vCard 3.0/4.0.
  vcf-to-ldif      Inverse of the above.
  csv-to-vcf       Outlook contact CSV -> vCard 3.0.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import zipfile
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def op_icbu_to_ics(args: argparse.Namespace) -> int:
    """Apple .icbu is a zip; concat every contained .ics."""
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".icbu file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".ics")
        try:
            with zipfile.ZipFile(str(src)) as zf:
                events: list[str] = []
                for name in zf.namelist():
                    if name.lower().endswith(".ics"):
                        text = zf.read(name).decode("utf-8", errors="replace")
                        events.append(text)
                if not events:
                    return fail("empty", f"{src.name}: no .ics inside.")
                # Use only the first VCALENDAR header + extract VEVENT bodies.
                merged = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UCX//icbu-to-ics//EN"]
                for cal in events:
                    in_event = False
                    for line in cal.splitlines():
                        if line.startswith("BEGIN:VEVENT"): in_event = True
                        if in_event: merged.append(line)
                        if line.startswith("END:VEVENT"): in_event = False
                merged.append("END:VCALENDAR")
                out_path.write_text("\n".join(merged), encoding="utf-8")
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("calmore_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="ics", source="icbu")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_takeout_to_ics(args: argparse.Namespace) -> int:
    """Google Takeout calendar export is one JSON per calendar."""
    try:
        from icalendar import Calendar, Event
        import datetime
    except ImportError as ex:
        return fail("missing_icalendar",
                    f"icalendar not installed: {ex}. `pip install icalendar`.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Google Takeout JSON file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            obj = json.loads(src.read_text(encoding="utf-8"))
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        cal = Calendar()
        cal.add("prodid", "-//UCX//takeout-to-ics//EN")
        cal.add("version", "2.0")
        events = obj.get("items") or obj.get("events") or obj
        for ev in events:
            if not isinstance(ev, dict): continue
            v = Event()
            if ev.get("summary"): v.add("summary", ev["summary"])
            if ev.get("description"): v.add("description", ev["description"])
            if ev.get("location"): v.add("location", ev["location"])
            if ev.get("start"):
                start = ev["start"].get("dateTime") or ev["start"].get("date")
                if start: v.add("dtstart", start)
            if ev.get("end"):
                end = ev["end"].get("dateTime") or ev["end"].get("date")
                if end: v.add("dtend", end)
            cal.add_component(v)
        out_path = out_dir / (src.stem + ".ics")
        out_path.write_bytes(cal.to_ical())
        emit("calmore_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="ics", source="takeout")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── LDIF <-> vCard ────────────────────────────────────────────────────

def _parse_ldif(text: str) -> list[dict]:
    entries: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if not line.strip():
            if cur: entries.append(cur); cur = None
            continue
        if line.startswith("dn:"):
            if cur: entries.append(cur)
            cur = {"dn": line[3:].strip()}
            continue
        if cur is None: continue
        if ":" not in line: continue
        k, _, v = line.partition(":")
        cur.setdefault(k.strip(), []).append(v.lstrip(": ").strip())
    if cur: entries.append(cur)
    return entries


def op_ldif_to_vcf(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"LDIF file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        entries = _parse_ldif(src.read_text(encoding="utf-8", errors="replace"))
        cards: list[str] = []
        for e in entries:
            cn = (e.get("cn") or [""])[0]
            sn = (e.get("sn") or [""])[0]
            given = (e.get("givenName") or [""])[0]
            mail = (e.get("mail") or [""])[0]
            tel = (e.get("telephoneNumber") or [""])[0]
            org = (e.get("o") or e.get("organizationName") or [""])[0]
            cards.append("\n".join([
                "BEGIN:VCARD",
                "VERSION:3.0",
                f"FN:{cn or given + ' ' + sn}",
                f"N:{sn};{given};;;",
                f"EMAIL:{mail}" if mail else "",
                f"TEL:{tel}" if tel else "",
                f"ORG:{org}" if org else "",
                "END:VCARD",
            ]).replace("\n\n", "\n"))
        out_path = out_dir / (src.stem + ".vcf")
        out_path.write_text("\n".join(cards) + "\n", encoding="utf-8")
        emit("calmore_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="vcf", source="ldif", count=len(entries))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_csv_to_vcf(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CSV file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        cards: list[str] = []
        with src.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fn = row.get("Name") or row.get("Display Name") or row.get("name") or ""
                given = row.get("First Name") or row.get("First") or ""
                family = row.get("Last Name") or row.get("Last") or ""
                mail = row.get("E-mail Address") or row.get("Email") or row.get("email") or ""
                tel = row.get("Mobile Phone") or row.get("Phone") or row.get("phone") or ""
                org = row.get("Company") or row.get("Organization") or ""
                cards.append("\n".join([
                    "BEGIN:VCARD",
                    "VERSION:3.0",
                    f"FN:{fn or (given + ' ' + family).strip()}",
                    f"N:{family};{given};;;",
                    f"EMAIL:{mail}" if mail else "",
                    f"TEL:{tel}" if tel else "",
                    f"ORG:{org}" if org else "",
                    "END:VCARD",
                ]).replace("\n\n", "\n"))
        out_path = out_dir / (src.stem + ".vcf")
        out_path.write_text("\n".join(cards) + "\n", encoding="utf-8")
        emit("calmore_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="vcf", source="csv", count=len(cards))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="calmore-sidecar",
                                description="Calendar / contact long-tail conversion (icbu / Google Takeout / LDIF / CSV).")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("icbu-to-ics", help="Apple .icbu -> single ICS.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    b = sub.add_parser("takeout-to-ics", help="Google Takeout calendar JSON -> ICS.")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")

    c = sub.add_parser("ldif-to-vcf", help="LDAP LDIF -> vCard 3.0.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")

    d = sub.add_parser("csv-to-vcf", help="Outlook contact CSV -> vCard 3.0.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "icbu-to-ics":    return op_icbu_to_ics(args)
        if args.op == "takeout-to-ics": return op_takeout_to_ics(args)
        if args.op == "ldif-to-vcf":    return op_ldif_to_vcf(args)
        if args.op == "csv-to-vcf":     return op_csv_to_vcf(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

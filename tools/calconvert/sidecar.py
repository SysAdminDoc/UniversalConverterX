"""Calendar / vCard converter -- ICS / VCF / JSON / CSV via icalendar + vobject.

Operations:
  ical-to-json   ICS -> JSON (event records: summary/start/end/location/desc).
  ical-to-csv    ICS -> CSV (one row per event, useful for spreadsheets).
  json-to-ical   JSON -> ICS (round-trip).
  vcard-to-json  VCF -> JSON (contacts).
  vcard-to-csv   VCF -> CSV (one row per contact).
  json-to-vcard  JSON -> VCF.
"""
from __future__ import annotations

import argparse
import csv
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import sys
from datetime import datetime
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── ICS handling ───────────────────────────────────────────────────────────────


def _parse_ics(path: Path) -> list[dict]:
    try: from icalendar import Calendar
    except ImportError: raise RuntimeError("icalendar not installed.")
    text = path.read_text(encoding="utf-8", errors="replace")
    cal = Calendar.from_ical(text)
    out = []
    for component in cal.walk("VEVENT"):
        rec = {
            "summary":  str(component.get("summary") or ""),
            "start":    str(component.get("dtstart").dt) if component.get("dtstart") else "",
            "end":      str(component.get("dtend").dt) if component.get("dtend") else "",
            "location": str(component.get("location") or ""),
            "description": str(component.get("description") or ""),
            "uid":      str(component.get("uid") or ""),
            "organizer": str(component.get("organizer") or ""),
        }
        out.append(rec)
    return out


def _write_ics(events: list[dict], path: Path) -> None:
    try: from icalendar import Calendar, Event
    except ImportError: raise RuntimeError("icalendar not installed.")
    cal = Calendar()
    cal.add("prodid", "-//UCX//CalConvert//EN")
    cal.add("version", "2.0")
    for r in events:
        ev = Event()
        ev.add("summary", r.get("summary", ""))
        # Best-effort datetime parsing; fall back to string if it fails.
        for k in ("start", "end"):
            v = r.get(k)
            if v:
                try: ev.add("dtstart" if k == "start" else "dtend",
                            datetime.fromisoformat(v.replace(" ", "T")))
                except Exception: pass
        if r.get("location"): ev.add("location", r["location"])
        if r.get("description"): ev.add("description", r["description"])
        if r.get("uid"): ev["uid"] = r["uid"]
        cal.add_component(ev)
    path.write_bytes(cal.to_ical())


# ── VCF handling ───────────────────────────────────────────────────────────────


def _parse_vcf(path: Path) -> list[dict]:
    try: import vobject
    except ImportError: raise RuntimeError("vobject not installed.")
    text = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for card in vobject.readComponents(text):
        rec = {}
        rec["full_name"] = str(card.fn.value) if hasattr(card, "fn") else ""
        if hasattr(card, "n"):
            n = card.n.value
            rec["family"] = getattr(n, "family", "") or ""
            rec["given"]  = getattr(n, "given", "")  or ""
        else:
            rec["family"] = rec["given"] = ""
        rec["emails"] = [str(e.value) for e in getattr(card, "email_list", [])]
        rec["phones"] = [str(t.value) for t in getattr(card, "tel_list", [])]
        rec["org"]    = str(card.org.value[0]) if hasattr(card, "org") else ""
        rec["title"]  = str(card.title.value) if hasattr(card, "title") else ""
        rec["note"]   = str(card.note.value) if hasattr(card, "note") else ""
        out.append(rec)
    return out


def _write_vcf(contacts: list[dict], path: Path) -> None:
    try: import vobject
    except ImportError: raise RuntimeError("vobject not installed.")
    parts = []
    for r in contacts:
        v = vobject.vCard()
        v.add("fn").value = r.get("full_name") or f"{r.get('given','')} {r.get('family','')}".strip()
        n = v.add("n"); n.value = vobject.vcard.Name(family=r.get("family",""), given=r.get("given",""))
        for em in r.get("emails", []) or []:
            v.add("email").value = em
        for ph in r.get("phones", []) or []:
            v.add("tel").value = ph
        if r.get("org"):   v.add("org").value = [r["org"]]
        if r.get("title"): v.add("title").value = r["title"]
        if r.get("note"):  v.add("note").value = r["note"]
        parts.append(v.serialize())
    path.write_text("".join(parts), encoding="utf-8")


# ── ops ────────────────────────────────────────────────────────────────────────


def _emit_records(name: str, records: list[dict], src: Path, out_path: Path) -> None:
    for r in records:
        emit(name, source=str(src), output=str(out_path), record=r)


def op_run(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"File(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    is_ical_src = args.op.startswith("ical")
    is_vcard_src = args.op.startswith("vcard")
    out_kind = args.op.split("-to-")[1]   # 'json' / 'csv' / 'ical' / 'vcard'
    out_ext = {"json": ".json", "csv": ".csv",
               "ical": ".ics", "vcard": ".vcf"}[out_kind]

    total = len(inputs)
    emit("progress", percent=0, stage=args.op, eta_seconds=None)
    for i, src in enumerate(inputs):
        try:
            if is_ical_src or args.op == "ical-to-json" or args.op == "ical-to-csv":
                records = _parse_ics(src)
                event_name = "calendar_event"
            elif is_vcard_src:
                records = _parse_vcf(src)
                event_name = "vcard_contact"
            else:  # json -> ical / vcard
                records = json.loads(src.read_text(encoding="utf-8"))
                event_name = "calendar_event" if args.op == "json-to-ical" else "vcard_contact"
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")

        out_path = out_dir / (src.stem + out_ext)
        try:
            if out_kind == "json":
                out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False, default=str),
                                    encoding="utf-8")
            elif out_kind == "csv":
                if not records:
                    out_path.write_text("", encoding="utf-8")
                else:
                    keys: list[str] = []
                    for r in records:
                        for k in r:
                            if k not in keys: keys.append(k)
                    with out_path.open("w", encoding="utf-8", newline="") as fh:
                        w = csv.DictWriter(fh, fieldnames=keys)
                        w.writeheader()
                        for r in records:
                            w.writerow({k: (",".join(map(str, v)) if isinstance(v, list) else v)
                                        for k, v in r.items()})
            elif out_kind == "ical":
                _write_ics(records, out_path)
            elif out_kind == "vcard":
                _write_vcf(records, out_path)
        except Exception as ex:
            return fail("write_failed", f"{out_path.name}: {ex}")

        _emit_records(event_name, records, src, out_path)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="calconvert-sidecar",
                                description="Calendar (ICS) and vCard (VCF) converter.")
    sub = p.add_subparsers(dest="op", required=True)
    for op_name, desc in [
        ("ical-to-json",   "ICS -> JSON event records"),
        ("ical-to-csv",    "ICS -> CSV (one row per event)"),
        ("json-to-ical",   "JSON event records -> ICS"),
        ("vcard-to-json",  "VCF -> JSON contact records"),
        ("vcard-to-csv",   "VCF -> CSV (one row per contact)"),
        ("json-to-vcard",  "JSON contact records -> VCF"),
    ]:
        cmd = sub.add_parser(op_name, help=desc)
        cmd.add_argument("--input", nargs="+", required=True)
        cmd.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try: return op_run(args)
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

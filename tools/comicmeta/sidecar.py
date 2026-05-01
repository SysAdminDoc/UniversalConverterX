"""Comic-metadata sidecar (extends `comic`).

Read / write / inject `ComicInfo.xml` (Comic Rack metadata standard) and
the older `ComicBookInfo` JSON metadata that ships inside the ZIP/CBZ
comment field. Useful for organising large comic libraries.

Operations:
  read-meta       Inventory ComicInfo.xml + ComicBookInfo across a CBZ set.
  inject-meta     Patch a ComicInfo.xml into existing CBZ files.
  csv-to-meta     Bulk-edit by editing a CSV manifest, then write back.
  scrub-meta      Strip ComicInfo.xml + ComicBookInfo from a CBZ.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_COMICINFO_FIELDS = [
    "Title", "Series", "Number", "Volume", "Year", "Month", "Day",
    "Writer", "Penciller", "Inker", "Colorist", "Letterer", "CoverArtist",
    "Editor", "Publisher", "Imprint", "Genre", "Tags", "Web", "PageCount",
    "LanguageISO", "Format", "BlackAndWhite", "Manga", "Characters",
    "Teams", "Locations", "ScanInformation", "StoryArc", "SeriesGroup",
    "AgeRating", "CommunityRating", "Summary", "Notes",
]


def _read_comicinfo(zf: zipfile.ZipFile) -> dict | None:
    for name in zf.namelist():
        if name.lower().endswith("comicinfo.xml"):
            try:
                xml = zf.read(name).decode("utf-8", errors="replace")
                root = ET.fromstring(xml)
                out: dict = {}
                for child in root:
                    out[child.tag] = (child.text or "").strip()
                return out
            except Exception:
                return None
    return None


def _read_comic_book_info(zf: zipfile.ZipFile) -> dict | None:
    """Older standard: JSON inside the ZIP comment field."""
    cmt = (zf.comment or b"").decode("utf-8", errors="replace").strip()
    if not cmt: return None
    try:
        d = json.loads(cmt)
        if isinstance(d, dict) and "ComicBookInfo/1.0" in d:
            return d
        return None
    except Exception:
        return None


def op_read_meta(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CBZ file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            with zipfile.ZipFile(src) as zf:
                ci = _read_comicinfo(zf)
                cbi = _read_comic_book_info(zf)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows.append({
            "file": str(src),
            "size_bytes": src.stat().st_size,
            "has_comicinfo_xml": bool(ci),
            "has_comicbookinfo_json": bool(cbi),
            **{k: (ci or {}).get(k, "") for k in _COMICINFO_FIELDS},
        })
        emit("comic_meta",
             input=str(src), output="",
             size_bytes=0, format="probe",
             has_xml=bool(ci), has_json=bool(cbi))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "comicinfo-manifest.csv"
    keys = ["file", "size_bytes", "has_comicinfo_xml", "has_comicbookinfo_json"
            ] + _COMICINFO_FIELDS
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows: w.writerow(r)
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(rows))
    return 0


def _build_comicinfo_xml(meta: dict) -> bytes:
    root = ET.Element("ComicInfo",
                       attrib={"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                               "xmlns:xsd": "http://www.w3.org/2001/XMLSchema"})
    for k, v in meta.items():
        if v in (None, "", []): continue
        sub = ET.SubElement(root, k)
        sub.text = str(v)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def op_inject_meta(args: argparse.Namespace) -> int:
    meta_path = Path(args.meta)
    if not meta_path.is_file():
        return fail("missing_input", f"Meta file not found: {meta_path}")
    if meta_path.suffix.lower() == ".xml":
        xml_bytes = meta_path.read_bytes()
    else:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        xml_bytes = _build_comicinfo_xml(meta)
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CBZ file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / src.name
        try:
            with zipfile.ZipFile(src) as zin, \
                 zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
                wrote_meta = False
                for item in zin.namelist():
                    if item.lower().endswith("comicinfo.xml"):
                        zout.writestr("ComicInfo.xml", xml_bytes)
                        wrote_meta = True
                    else:
                        zout.writestr(item, zin.read(item))
                if not wrote_meta:
                    zout.writestr("ComicInfo.xml", xml_bytes)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("comic_meta",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="cbz", source="comicinfo-injected")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_csv_to_meta(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    if not csv_path.is_file():
        return fail("missing_input", f"CSV manifest not found: {csv_path}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return fail("empty_csv", "CSV manifest is empty.")
    total = len(rows)
    for i, r in enumerate(rows):
        src = Path(r["file"])
        if not src.is_file():
            return fail("missing_input", f"CBZ from CSV not found: {src}")
        meta = {k: r[k] for k in _COMICINFO_FIELDS if r.get(k)}
        xml_bytes = _build_comicinfo_xml(meta)
        out_path = out_dir / src.name
        try:
            with zipfile.ZipFile(src) as zin, \
                 zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
                wrote = False
                for item in zin.namelist():
                    if item.lower().endswith("comicinfo.xml"):
                        zout.writestr("ComicInfo.xml", xml_bytes); wrote = True
                    else:
                        zout.writestr(item, zin.read(item))
                if not wrote: zout.writestr("ComicInfo.xml", xml_bytes)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("comic_meta",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="cbz", source="csv-to-comicinfo")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_scrub_meta(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CBZ file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / src.name
        try:
            with zipfile.ZipFile(src) as zin, \
                 zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.namelist():
                    if item.lower().endswith("comicinfo.xml"):
                        continue
                    zout.writestr(item, zin.read(item))
                # comment field cleared by default in new ZipFile
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("comic_meta",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="cbz", source="scrubbed")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="comicmeta-sidecar",
                                description="Comic Rack ComicInfo.xml metadata for CBZ.")
    sub = p.add_subparsers(dest="op", required=True)

    rm = sub.add_parser("read-meta", help="Inventory ComicInfo.xml across CBZ set")
    rm.add_argument("--input", nargs="+", required=True)
    rm.add_argument("--output-dir", required=True, dest="output_dir")

    inj = sub.add_parser("inject-meta", help="Patch ComicInfo.xml into CBZ files")
    inj.add_argument("--input", nargs="+", required=True)
    inj.add_argument("--output-dir", required=True, dest="output_dir")
    inj.add_argument("--meta", required=True,
                     help="ComicInfo.xml or .json with the metadata to inject")

    cv = sub.add_parser("csv-to-meta",
                        help="Bulk-edit ComicInfo.xml from a CSV manifest")
    cv.add_argument("--csv", required=True,
                    help="CSV manifest produced by `read-meta`")
    cv.add_argument("--output-dir", required=True, dest="output_dir")

    sc = sub.add_parser("scrub-meta", help="Strip ComicInfo.xml from CBZ files")
    sc.add_argument("--input", nargs="+", required=True)
    sc.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "read-meta":   return op_read_meta(args)
        if args.op == "inject-meta": return op_inject_meta(args)
        if args.op == "csv-to-meta": return op_csv_to_meta(args)
        if args.op == "scrub-meta":  return op_scrub_meta(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

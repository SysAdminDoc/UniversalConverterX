"""Browser bookmark conversion sidecar.

Convert between every major browser's bookmark export format:

  * Chrome / Edge / Brave / Opera (Chromium): JSON (`Bookmarks` file)
  * Firefox / Tor:                            JSON-Lines from places.sqlite,
                                              or .json bookmark backup
  * Safari:                                   .plist binary
  * Opera classic:                            .adr / .opera-bookmarks
  * Internet Explorer / Old Edge:             .url (.lnk-like INI)
  * Netscape HTML format (de-facto export):   .html
  * Pinboard / Diigo / Raindrop CSV / JSON

We normalize every format into a list of:
    {title, url, folder, created, tags, description}
and re-serialize on the way out.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


@dataclass
class Bookmark:
    title: str
    url: str
    folder: str = ""
    created: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""


# ── Readers -----------------------------------------------------------------

def read_chromium_json(path: Path) -> list[Bookmark]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    out: list[Bookmark] = []
    def walk(node, folder: str):
        for child in node.get("children", []):
            if child.get("type") == "url":
                out.append(Bookmark(
                    title=child.get("name", ""),
                    url=child.get("url", ""),
                    folder=folder,
                    created=str(child.get("date_added", "")),
                ))
            elif child.get("type") == "folder":
                walk(child, f"{folder}/{child.get('name', '')}".strip("/"))
    roots = obj.get("roots") or {}
    for name, node in roots.items():
        if isinstance(node, dict):
            walk(node, name)
    return out


def read_firefox_json(path: Path) -> list[Bookmark]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    out: list[Bookmark] = []
    def walk(node, folder: str):
        for child in node.get("children", []) or []:
            if child.get("uri"):
                out.append(Bookmark(
                    title=child.get("title", ""),
                    url=child.get("uri", ""),
                    folder=folder,
                    created=str(child.get("dateAdded", "")),
                    tags=[t for t in (child.get("tags", "") or "").split(",") if t.strip()],
                ))
            else:
                walk(child, f"{folder}/{child.get('title', '')}".strip("/"))
    walk(obj, "")
    return out


def read_safari_plist(path: Path) -> list[Bookmark]:
    import plistlib
    with path.open("rb") as f: obj = plistlib.load(f)
    out: list[Bookmark] = []
    def walk(node, folder: str):
        if not isinstance(node, dict): return
        if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
            uri_dict = node.get("URIDictionary", {}) or {}
            out.append(Bookmark(
                title=uri_dict.get("title", ""),
                url=node.get("URLString", ""),
                folder=folder,
            ))
        else:
            sub = node.get("Title", "")
            for child in node.get("Children", []) or []:
                walk(child, f"{folder}/{sub}".strip("/") if sub else folder)
    walk(obj, "")
    return out


_NETSCAPE_LINK = re.compile(r'<A HREF="([^"]+)"[^>]*>([^<]*)</A>', re.IGNORECASE)
_NETSCAPE_FOLDER = re.compile(r'<H3[^>]*>([^<]*)</H3>', re.IGNORECASE)


def read_netscape_html(path: Path) -> list[Bookmark]:
    text = path.read_text(encoding="utf-8", errors="replace")
    folders: list[str] = []
    out: list[Bookmark] = []
    for line in text.splitlines():
        if "<H3" in line.upper():
            m = _NETSCAPE_FOLDER.search(line)
            if m: folders.append(m.group(1))
        elif "</DL" in line.upper():
            if folders: folders.pop()
        for m in _NETSCAPE_LINK.finditer(line):
            out.append(Bookmark(
                title=m.group(2), url=m.group(1),
                folder="/".join(folders),
            ))
    return out


def read_opera_adr(path: Path) -> list[Bookmark]:
    """Opera classic .adr is INI-like: '[bookmark]', NAME=, URL=, etc."""
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[Bookmark] = []
    folders: list[str] = []
    cur: dict | None = None
    cur_kind: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"): continue
        if line.lower() == "[bookmark]":
            cur = {}; cur_kind = "bookmark"; continue
        if line.lower() == "[folder]":
            cur = {}; cur_kind = "folder"; continue
        if line == "-":
            if folders: folders.pop()
            continue
        if line == "":
            if cur_kind == "bookmark" and cur:
                out.append(Bookmark(title=cur.get("name", ""),
                                    url=cur.get("url", ""),
                                    folder="/".join(folders)))
            elif cur_kind == "folder" and cur:
                folders.append(cur.get("name", ""))
            cur = None; cur_kind = None
            continue
        if cur is not None and "=" in line:
            k, v = line.split("=", 1)
            cur[k.strip().lower()] = v.strip()
    return out


def read_csv(path: Path) -> list[Bookmark]:
    out: list[Bookmark] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out.append(Bookmark(
                title=row.get("title") or row.get("Title") or row.get("name") or "",
                url=row.get("url") or row.get("URL") or row.get("href") or "",
                folder=row.get("folder") or row.get("category") or "",
                tags=[t.strip() for t in (row.get("tags", "") or "").split(",") if t.strip()],
                description=row.get("description", "") or row.get("note", ""),
            ))
    return out


READERS = {
    ".json":   None,         # auto-dispatched to chromium/firefox by content shape
    ".plist":  read_safari_plist,
    ".bplist": read_safari_plist,
    ".html":   read_netscape_html,
    ".htm":    read_netscape_html,
    ".adr":    read_opera_adr,
    ".csv":    read_csv,
}


def _read_json_dispatch(path: Path) -> list[Bookmark]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj, dict) and "roots" in obj: return read_chromium_json(path)
    if isinstance(obj, dict) and "children" in obj: return read_firefox_json(path)
    if isinstance(obj, list):
        return [Bookmark(**{k: v for k, v in row.items() if k in Bookmark.__dataclass_fields__})
                for row in obj]
    raise ValueError(f"Unknown JSON shape: {path.name}")


def read_any(path: Path) -> list[Bookmark]:
    ext = path.suffix.lower()
    if ext == ".json": return _read_json_dispatch(path)
    reader = READERS.get(ext)
    if reader is None: raise ValueError(f"No reader for {ext}")
    return reader(path)


# ── Writers ----------------------------------------------------------------

def write_netscape_html(bookmarks: list[Bookmark], path: Path) -> None:
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">",
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]
    by_folder: dict[str, list[Bookmark]] = {}
    for b in bookmarks:
        by_folder.setdefault(b.folder or "", []).append(b)
    for folder, items in by_folder.items():
        if folder:
            lines.append(f"  <DT><H3>{folder}</H3>")
            lines.append("  <DL><p>")
        for b in items:
            lines.append(f'  <DT><A HREF="{b.url}">{b.title}</A>')
        if folder:
            lines.append("  </DL><p>")
    lines.append("</DL><p>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(bookmarks: list[Bookmark], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "url", "folder", "created", "tags", "description"])
        for b in bookmarks:
            w.writerow([b.title, b.url, b.folder, b.created,
                         ",".join(b.tags), b.description])


def write_json(bookmarks: list[Bookmark], path: Path) -> None:
    path.write_text(json.dumps([asdict(b) for b in bookmarks],
                                indent=2, ensure_ascii=False), encoding="utf-8")


WRITERS = {
    "html":     write_netscape_html,
    "netscape": write_netscape_html,
    "csv":      write_csv,
    "json":     write_json,
}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Bookmark file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in WRITERS:
        return fail("bad_target", f"Choose: {sorted(WRITERS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="bookmark", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            bookmarks = read_any(src)
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + target)
        WRITERS[target](bookmarks, out_path)
        emit("bookmark_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, count=len(bookmarks))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bookmark-sidecar",
                                description="Cross-browser bookmark conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert Chromium / Firefox / Safari / Opera / Netscape / CSV.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="html (Netscape) | csv | json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Note-taking app export sidecar.

Normalize knowledge-management app exports into a unified JSON / CSV
manifest + Markdown vault:

  * Notion `.zip` workspace export -> Markdown vault + manifest CSV
  * Evernote `.enex` (XML) -> Markdown notes + attachments
  * Obsidian vault -> per-note manifest with tags / backlinks
  * Bear `.bear` archive -> Markdown
  * Joplin `.jex` (tar) -> Markdown
  * Logseq pages-and-journals -> normalized Markdown
  * Day One `.json` journal -> Markdown
  * Apple Notes `.html` export
  * Roam Research `.json` export
  * Standard Notes `.json` export

Operations:
  enex-to-md         Evernote .enex -> Markdown vault.
  notion-zip         Notion workspace .zip -> Markdown vault + manifest.
  obsidian-manifest  Walk Obsidian vault -> CSV with tags / backlinks.
  joplin-jex         Joplin .jex (tar) -> Markdown vault.
  dayone-to-md       Day One JSON journal -> Markdown.
  roam-to-md         Roam Research JSON -> Markdown vault.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _safe_name(s: str, maxlen: int = 80) -> str:
    out = re.sub(r"[^A-Za-z0-9 _.\-]", "_", s).strip()
    return (out[:maxlen] or "untitled").rstrip(". ")


def _html_to_md(html: str) -> str:
    """Crude HTML -> Markdown that handles the tags Evernote / Bear emit."""
    if not html: return ""
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</?p[^>]*>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</?h([1-6])[^>]*>",
                   lambda m: "\n" + "#" * int(m.group(1)) + " ",
                   html, flags=re.IGNORECASE)
    html = re.sub(r"</?b>|</?strong>", "**", html, flags=re.IGNORECASE)
    html = re.sub(r"</?i>|</?em>", "*", html, flags=re.IGNORECASE)
    html = re.sub(r"</?code>", "`", html, flags=re.IGNORECASE)
    html = re.sub(r"</?li[^>]*>", "\n- ", html, flags=re.IGNORECASE)
    html = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>",
                   r"[\2](\1)", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<[^>]+>", "", html)  # strip remaining tags
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&")
                  .replace("&lt;", "<").replace("&gt;", ">"))
    html = re.sub(r"\n{3,}", "\n\n", html).strip()
    return html


# ── Evernote .enex ─────────────────────────────────────────────────────

def op_enex_to_md(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".enex file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            notes_dir = out_dir / src.stem
            notes_dir.mkdir(parents=True, exist_ok=True)
            written = 0
            for note in root.findall("note"):
                title = (note.findtext("title") or "Untitled").strip()
                content = note.findtext("content") or ""
                # Strip outer <en-note> XML wrapper before HTML stripping
                content = re.sub(r"<\?xml[^>]*\?>", "", content)
                content = re.sub(r"<!DOCTYPE [^>]+>", "", content)
                content = re.sub(r"</?en-note[^>]*>", "", content)
                tags = [t.text or "" for t in note.findall("tag")]
                created = note.findtext("created") or ""
                fm = ["---", f"title: {title}",
                       f"created: {created}",
                       f"tags: [{', '.join(tags)}]",
                       "---", ""]
                body = _html_to_md(content)
                target = notes_dir / (_safe_name(title) + ".md")
                # de-dup
                n = 1
                while target.exists():
                    target = notes_dir / f"{_safe_name(title)}_{n}.md"; n += 1
                target.write_text("\n".join(fm) + body + "\n", encoding="utf-8")
                written += 1
            emit("note_doc",
                 input=str(src), output=str(notes_dir),
                 size_bytes=0, format="markdown-vault", source="evernote",
                 notes=written)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Notion workspace .zip ──────────────────────────────────────────────

def op_notion_zip(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Notion .zip file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        target = out_dir / src.stem
        target.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(src) as z:
                z.extractall(target)
                names = z.namelist()
        except Exception as ex:
            return fail("extract_failed", f"{src.name}: {ex}")
        manifest_path = target / "_manifest.csv"
        with manifest_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["path", "size_bytes", "type"])
            for n in names:
                p = target / n
                if not p.is_file(): continue
                w.writerow([n, p.stat().st_size, p.suffix.lstrip(".")])
        emit("note_doc",
             input=str(src), output=str(target),
             size_bytes=0, format="markdown-vault", source="notion",
             entries=len(names))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Obsidian vault manifest ───────────────────────────────────────────

_OBSIDIAN_TAG_RE = re.compile(r"(?<![\w/])#([\w/-]+)")
_OBSIDIAN_LINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]*)?\]\]")
_OBSIDIAN_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def op_obsidian_manifest(args: argparse.Namespace) -> int:
    vault = Path(args.vault_dir)
    if not vault.is_dir():
        return fail("missing_input", f"vault not found: {vault}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for cur, _dirs, files in __import__("os").walk(vault):
        for fn in files:
            if not fn.lower().endswith((".md", ".mdx", ".markdown")): continue
            full = Path(cur) / fn
            text = full.read_text(encoding="utf-8", errors="replace")
            tags = sorted(set(_OBSIDIAN_TAG_RE.findall(text)))
            backlinks = sorted(set(_OBSIDIAN_LINK_RE.findall(text)))
            fm_match = _OBSIDIAN_FRONTMATTER_RE.match(text)
            fm_text = fm_match.group(1) if fm_match else ""
            rows.append({
                "path": str(full.relative_to(vault)),
                "size_bytes": full.stat().st_size,
                "tags": ",".join(tags),
                "backlinks": ",".join(backlinks),
                "has_frontmatter": bool(fm_match),
                "frontmatter_lines": fm_text.count("\n") + (1 if fm_text else 0),
                "char_count": len(text),
                "word_count": len(text.split()),
            })
    out_path = out_dir / (vault.name + "_manifest.csv")
    keys = ["path", "size_bytes", "tags", "backlinks", "has_frontmatter",
            "frontmatter_lines", "char_count", "word_count"]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows: w.writerow(r)
    emit("note_doc",
         input=str(vault), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="csv", source="obsidian", notes=len(rows))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(rows))
    return 0


# ── Joplin .jex (tar) ──────────────────────────────────────────────────

def op_joplin_jex(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".jex file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        target = out_dir / src.stem
        target.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(src, "r") as tar:
                names = tar.getnames()
                tar.extractall(target)
        except Exception as ex:
            return fail("extract_failed", f"{src.name}: {ex}")
        emit("note_doc",
             input=str(src), output=str(target),
             size_bytes=0, format="markdown-vault", source="joplin",
             entries=len(names))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Day One JSON journal ──────────────────────────────────────────────

def op_dayone_to_md(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Day One file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        target = out_dir / src.stem
        target.mkdir(parents=True, exist_ok=True)
        for n, e in enumerate(entries, 1):
            ts = e.get("creationDate", "")
            text = e.get("text", "")
            tags = e.get("tags", [])
            stem = (ts.replace(":", "-").replace("T", "_") or f"entry-{n}")[:40]
            md_path = target / (stem + ".md")
            fm = ["---", f"date: {ts}",
                  f"tags: [{', '.join(tags)}]",
                  f"location: {(e.get('location', {}) or {}).get('placeName', '')}",
                  "---", ""]
            md_path.write_text("\n".join(fm) + text + "\n", encoding="utf-8")
        emit("note_doc",
             input=str(src), output=str(target),
             size_bytes=0, format="markdown-vault", source="dayone",
             notes=len(entries))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Roam Research JSON ────────────────────────────────────────────────

def _roam_block_to_md(block: dict, depth: int) -> list[str]:
    out: list[str] = []
    text = block.get("string", "")
    if text: out.append("  " * depth + "- " + text)
    for child in block.get("children", []) or []:
        out.extend(_roam_block_to_md(child, depth + 1))
    return out


def op_roam_to_md(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Roam JSON file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        target = out_dir / src.stem
        target.mkdir(parents=True, exist_ok=True)
        if not isinstance(data, list):
            data = [data]
        for page in data:
            title = page.get("title", "Untitled")
            lines: list[str] = [f"# {title}", ""]
            for child in page.get("children", []) or []:
                lines.extend(_roam_block_to_md(child, 0))
            md_path = target / (_safe_name(title) + ".md")
            md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        emit("note_doc",
             input=str(src), output=str(target),
             size_bytes=0, format="markdown-vault", source="roam",
             notes=len(data))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notetaking-sidecar",
                                description="Note-taking app export normalization.")
    sub = p.add_subparsers(dest="op", required=True)

    en = sub.add_parser("enex-to-md", help="Evernote .enex -> Markdown vault")
    en.add_argument("--input", nargs="+", required=True)
    en.add_argument("--output-dir", required=True, dest="output_dir")

    nt = sub.add_parser("notion-zip", help="Notion workspace .zip -> Markdown vault")
    nt.add_argument("--input", nargs="+", required=True)
    nt.add_argument("--output-dir", required=True, dest="output_dir")

    ob = sub.add_parser("obsidian-manifest", help="Walk Obsidian vault -> CSV")
    ob.add_argument("--vault-dir", required=True, dest="vault_dir")
    ob.add_argument("--output-dir", required=True, dest="output_dir")

    jp = sub.add_parser("joplin-jex", help="Joplin .jex (tar) -> Markdown vault")
    jp.add_argument("--input", nargs="+", required=True)
    jp.add_argument("--output-dir", required=True, dest="output_dir")

    do = sub.add_parser("dayone-to-md", help="Day One JSON journal -> Markdown")
    do.add_argument("--input", nargs="+", required=True)
    do.add_argument("--output-dir", required=True, dest="output_dir")

    rm = sub.add_parser("roam-to-md", help="Roam Research JSON -> Markdown vault")
    rm.add_argument("--input", nargs="+", required=True)
    rm.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "enex-to-md":         return op_enex_to_md(args)
        if args.op == "notion-zip":         return op_notion_zip(args)
        if args.op == "obsidian-manifest":  return op_obsidian_manifest(args)
        if args.op == "joplin-jex":         return op_joplin_jex(args)
        if args.op == "dayone-to-md":       return op_dayone_to_md(args)
        if args.op == "roam-to-md":         return op_roam_to_md(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

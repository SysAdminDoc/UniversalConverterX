"""Social-media archive sidecar.

Normalize per-platform user-data exports into unified CSV / JSON / HTML:

  * Twitter / X archive (`.zip` with `manifest.js` + `data/` JS files)
  * Mastodon archive (Activity Pub `.tar.gz` + outbox.json)
  * Bluesky CAR archive (CBOR-encoded blocks; we surface metadata only)
  * Reddit user data export (.zip with CSV per category)
  * Discord per-server export (3rd-party DiscordChatExporter JSON)
  * Tumblr `.zip` archive

Operations:
  twitter-tweets-csv     Twitter archive -> CSV of tweets.
  mastodon-outbox-csv    Mastodon outbox.json -> CSV.
  reddit-archive-csv     Reddit data export .zip -> normalized CSV bundle.
  detect                 Probe-only: identify which platform export.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import (
    MAX_ARCHIVE_TOTAL_BYTES,
    emit,
    safe_zip_extract_member,
)




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Twitter archive ───────────────────────────────────────────────────

_TWEET_FILE_RE = re.compile(r"^data/(?:tweet|tweets|tweet-headers)\.js$")


def op_twitter_tweets_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Twitter archive not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tweets: list[dict] = []
            with zipfile.ZipFile(src) as z:
                names = z.namelist()
                for n in names:
                    if not _TWEET_FILE_RE.match(n) and not n.startswith("data/tweet"):
                        continue
                    raw = z.read(n).decode("utf-8", errors="replace")
                    # Twitter archive prefixes JSON with "window.YTD.X.part = "
                    m = re.search(r"=\s*(\[.*\])\s*$", raw, re.DOTALL)
                    if not m: continue
                    try:
                        data = json.loads(m.group(1))
                    except Exception:
                        continue
                    for entry in data:
                        t = entry.get("tweet", entry)
                        tweets.append({
                            "id": t.get("id_str", t.get("id", "")),
                            "created_at": t.get("created_at", ""),
                            "full_text": t.get("full_text",
                                                 t.get("text", ""))[:1000],
                            "favorite_count": t.get("favorite_count", 0),
                            "retweet_count": t.get("retweet_count", 0),
                            "lang": t.get("lang", ""),
                            "in_reply_to_status_id":
                                t.get("in_reply_to_status_id_str", ""),
                            "in_reply_to_screen_name":
                                t.get("in_reply_to_screen_name", ""),
                        })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".tweets.csv")
        keys = ["id", "created_at", "full_text", "favorite_count",
                "retweet_count", "lang", "in_reply_to_status_id",
                "in_reply_to_screen_name"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in tweets: w.writerow(r)
        emit("social_archive",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="twitter", tweets=len(tweets))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Mastodon outbox ───────────────────────────────────────────────────

def op_mastodon_outbox_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Mastodon export not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text: str
            if src.suffix.lower() == ".tar":
                with tarfile.open(src, "r") as tar:
                    f = tar.extractfile("outbox.json")
                    text = f.read().decode("utf-8", errors="replace") if f else ""
            elif src.suffix.lower() in (".gz", ".tgz"):
                with tarfile.open(src, "r:gz") as tar:
                    f = tar.extractfile("outbox.json")
                    text = f.read().decode("utf-8", errors="replace") if f else ""
            else:
                text = src.read_text(encoding="utf-8")
            data = json.loads(text)
            items = data.get("orderedItems", []) or data.get("items", [])
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for it in items:
            obj = (it.get("object", {}) or {})
            rows.append({
                "id": it.get("id", ""),
                "type": it.get("type", ""),
                "published": obj.get("published", ""),
                "content": re.sub(r"<[^>]+>", "",
                                    obj.get("content", ""))[:1000],
                "language": (obj.get("contentMap", {}) or {}).get(
                    "en", obj.get("lang", "")),
                "to": ", ".join(obj.get("to", [])
                                 if isinstance(obj.get("to"), list) else []),
                "tag_count": len(obj.get("tag", []) or []),
                "url": obj.get("url", ""),
            })
        out_path = out_dir / (src.stem + ".mastodon.csv")
        keys = ["id", "type", "published", "content", "language", "to",
                "tag_count", "url"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("social_archive",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="mastodon", posts=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Reddit archive ────────────────────────────────────────────────────

def op_reddit_archive_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Reddit archive not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            written = 0
            with zipfile.ZipFile(src) as z:
                target = out_dir / src.stem
                target.mkdir(parents=True, exist_ok=True)
                members = [
                    info for info in z.infolist()
                    if info.filename.lower().endswith(".csv")
                ]
                if sum(max(0, int(info.file_size)) for info in members) > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ValueError("CSV members exceed the archive extraction safety limit")
                for info in members:
                    safe_zip_extract_member(z, info, target)
                    written += 1
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("social_archive",
             input=str(src), output=str(target),
             size_bytes=0, format="csv-bundle", source="reddit",
             csvs=written)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Detect ────────────────────────────────────────────────────────────

def op_detect(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    for src in inputs:
        kind = "unknown"
        try:
            if src.suffix.lower() == ".zip":
                with zipfile.ZipFile(src) as z:
                    names = set(z.namelist())
                    if "data/tweet.js" in names or "data/tweets.js" in names:
                        kind = "twitter"
                    elif any(n.startswith("data/manifest.js") for n in names):
                        kind = "twitter"
                    elif "comments.csv" in names or "posts.csv" in names:
                        kind = "reddit"
                    elif any(n.endswith("messages.json") for n in names):
                        kind = "discord-export"
                    elif any(n.endswith("outbox.json") for n in names):
                        kind = "mastodon-zip"
            elif src.suffix.lower() in (".tar", ".gz", ".tgz"):
                kind = "mastodon-tar"
            elif src.suffix.lower() == ".car":
                kind = "bluesky-car"
        except Exception:
            pass
        detections.append({"file": str(src), "platform": kind,
                           "size_bytes": src.stat().st_size})
        emit("social_archive",
             input=str(src), output="",
             size_bytes=0, format="detect", source=kind)
    out_path = out_dir / "social-detect.json"
    out_path.write_text(json.dumps(detections, indent=2),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(detections))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="socialarchives-sidecar",
                                description="Social-media user-data export normalization.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("twitter-tweets-csv",   "Twitter / X archive .zip -> tweets CSV"),
        ("mastodon-outbox-csv",  "Mastodon archive -> CSV"),
        ("reddit-archive-csv",   "Reddit data export .zip -> CSV bundle"),
        ("detect",               "Identify social-media export platform"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "twitter-tweets-csv":  return op_twitter_tweets_csv(args)
        if args.op == "mastodon-outbox-csv": return op_mastodon_outbox_csv(args)
        if args.op == "reddit-archive-csv":  return op_reddit_archive_csv(args)
        if args.op == "detect":              return op_detect(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

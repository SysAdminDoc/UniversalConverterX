"""Web archive sidecar -- HAR / WARC conversion via warcio + stdlib json.

  har-to-warc   : Convert browser HAR (JSON) -> WARC.
  warc-to-har   : Convert WARC -> HAR (request/response per record).
  warc-list     : Enumerate WARC records (one 'web_record' event per entry).
  har-extract   : Extract response bodies from a HAR into individual files.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlparse


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def op_har_to_warc(args: argparse.Namespace) -> int:
    try: from warcio.warcwriter import WARCWriter
    except ImportError: return fail("missing_warcio", "warcio not installed.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"HAR not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    har = json.loads(src.read_text(encoding="utf-8"))
    entries = har.get("log", {}).get("entries", []) or []
    written = 0
    with out_path.open("wb") as fh:
        writer = WARCWriter(fh, gzip=True)
        for i, e in enumerate(entries):
            try:
                req = e.get("request", {}) or {}
                resp = e.get("response", {}) or {}
                url = req.get("url") or ""
                method = req.get("method", "GET")
                # Reconstruct request line (warcio expects raw HTTP).
                req_line = f"{method} {urlparse(url).path or '/'} HTTP/1.1\r\n"
                req_headers = "".join(f"{h.get('name','')}: {h.get('value','')}\r\n"
                                      for h in req.get("headers", []) or [])
                req_blob = (req_line + req_headers + "\r\n").encode("utf-8", errors="replace")
                req_record = writer.create_warc_record(
                    url, "request", payload=__import__("io").BytesIO(req_blob),
                    http_headers=None,
                )
                writer.write_record(req_record)

                # Response.
                status = resp.get("status", 200)
                status_text = resp.get("statusText", "OK")
                resp_line = f"HTTP/1.1 {status} {status_text}\r\n"
                resp_headers = "".join(f"{h.get('name','')}: {h.get('value','')}\r\n"
                                       for h in resp.get("headers", []) or [])
                content = resp.get("content", {}) or {}
                body = content.get("text", "") or ""
                if content.get("encoding") == "base64":
                    body_bytes = base64.b64decode(body or "")
                else:
                    body_bytes = body.encode("utf-8", errors="replace")
                resp_blob = (resp_line + resp_headers + "\r\n").encode("utf-8", "replace") + body_bytes
                resp_record = writer.create_warc_record(
                    url, "response", payload=__import__("io").BytesIO(resp_blob),
                    http_headers=None,
                )
                writer.write_record(resp_record)
                written += 1
                emit("web_record", index=i, url=url, status=status, method=method)
            except Exception as ex:
                emit("log", level="warn", message=f"entry #{i}: {ex}")

    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         count=written)
    return 0


def op_warc_to_har(args: argparse.Namespace) -> int:
    try: from warcio.archiveiterator import ArchiveIterator
    except ImportError: return fail("missing_warcio", "warcio not installed.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"WARC not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    cur: dict = {}
    with src.open("rb") as fh:
        for record in ArchiveIterator(fh):
            url = record.rec_headers.get_header("WARC-Target-URI") or ""
            kind = record.rec_type  # 'request' / 'response' / 'metadata'
            try:
                payload = record.content_stream().read().decode("utf-8", errors="replace")
            except Exception:
                payload = ""
            if kind == "request":
                cur = {"request": {"url": url, "method": "GET", "headers": [],
                                   "raw": payload}}
            elif kind == "response":
                cur.setdefault("request", {"url": url, "method": "GET", "headers": []})
                cur["response"] = {"status": 200, "statusText": "OK", "headers": [],
                                   "content": {"text": payload, "size": len(payload)}}
                entries.append(cur); cur = {}
                emit("web_record", url=url, kind="response")

    har = {"log": {"version": "1.2", "creator": {"name": "UCX webarchive", "version": "2.7"},
                   "entries": entries}}
    out_path.write_text(json.dumps(har, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         count=len(entries))
    return 0


def op_warc_list(args: argparse.Namespace) -> int:
    try: from warcio.archiveiterator import ArchiveIterator
    except ImportError: return fail("missing_warcio", "warcio not installed.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"WARC not found: {args.input}")
    n = 0
    with src.open("rb") as fh:
        for record in ArchiveIterator(fh):
            n += 1
            emit("web_record",
                 index=n,
                 type=record.rec_type,
                 url=record.rec_headers.get_header("WARC-Target-URI") or "",
                 length=int(record.rec_headers.get_header("Content-Length") or 0))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=n)
    return 0


def op_har_extract(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"HAR not found: {args.input}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    har = json.loads(src.read_text(encoding="utf-8"))
    entries = har.get("log", {}).get("entries", []) or []
    n = 0
    for i, e in enumerate(entries):
        resp = e.get("response", {}) or {}
        content = resp.get("content", {}) or {}
        body = content.get("text", "") or ""
        if not body: continue
        url = (e.get("request", {}) or {}).get("url", f"entry-{i}")
        name = urlparse(url).path.rsplit("/", 1)[-1] or f"entry-{i:05d}"
        if "." not in name: name += ".bin"
        out_path = out_dir / f"{i:05d}_{name}"
        try:
            if content.get("encoding") == "base64":
                out_path.write_bytes(base64.b64decode(body))
            else:
                out_path.write_text(body, encoding="utf-8", errors="replace")
        except Exception as ex:
            emit("log", level="warn", message=f"entry #{i}: {ex}")
            continue
        n += 1
        emit("web_record", url=url, output=str(out_path),
             size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_dir), size_bytes=0, count=n)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="webarchive-sidecar",
                                description="HAR <-> WARC + extraction.")
    sub = p.add_subparsers(dest="op", required=True)
    a = sub.add_parser("har-to-warc"); a.add_argument("--input", required=True); a.add_argument("--output", required=True)
    b = sub.add_parser("warc-to-har"); b.add_argument("--input", required=True); b.add_argument("--output", required=True)
    c = sub.add_parser("warc-list");   c.add_argument("--input", required=True)
    d = sub.add_parser("har-extract"); d.add_argument("--input", required=True); d.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "har-to-warc": return op_har_to_warc(args)
        if args.op == "warc-to-har": return op_warc_to_har(args)
        if args.op == "warc-list":   return op_warc_list(args)
        if args.op == "har-extract": return op_har_extract(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

"""Single-message + Notes + Windows Live Mail sidecar.

The `mailbox` (mbox/eml/maildir) and `mailimport` (PST/OST) sidecars cover
the bulk-mailbox formats; this one fills in the single-message + niche
ecosystems:

  * Outlook .msg (single message)        extract-msg
  * Windows Live Mail .eml folders       stdlib email
  * Lotus Notes .nsf                     (placeholder -- requires Notes runtime)
  * MailIDX / Eudora .mbx                stdlib email parser
  * Apple Mail .emlx                     stdlib + plist sidecar handling

Operations:
  msg-to-eml     Outlook .msg -> RFC 822 .eml
  msg-to-html    Outlook .msg -> HTML preview
  emlx-to-eml    Apple .emlx -> .eml (strips Apple length-prefix and metadata)
  thread-mbox    Bundle a directory of .eml files into a single .mbox
"""
from __future__ import annotations

import argparse
import email
import email.policy
import json
import mailbox
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def op_msg_to_eml(args: argparse.Namespace) -> int:
    try:
        import extract_msg
    except ImportError as ex:
        return fail("missing_extract_msg",
                    f"extract-msg not installed: {ex}. `pip install extract-msg`.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".msg file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="msg-to-eml", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            with extract_msg.openMsg(str(src)) as msg:
                eml_bytes = msg.save(customPath=str(out_dir),
                                      customFilename=src.stem + ".eml",
                                      asEml=True)
        except Exception as ex:
            return fail("extract_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".eml")
        emit("email_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format="eml", source="msg")
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_msg_to_html(args: argparse.Namespace) -> int:
    try:
        import extract_msg
    except ImportError as ex:
        return fail("missing_extract_msg", str(ex))
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".msg file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            msg = extract_msg.openMsg(str(src))
            body = msg.htmlBody if msg.htmlBody else msg.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "replace")
            wrapper = (
                f"<html><head><meta charset='utf-8'><title>{msg.subject or ''}</title></head>"
                f"<body><h1>{msg.subject or ''}</h1>"
                f"<p><b>From:</b> {msg.sender}<br/>"
                f"<b>To:</b> {msg.to}<br/>"
                f"<b>Date:</b> {msg.date}</p><hr/>"
                f"{body or ''}</body></html>"
            )
            out_path = out_dir / (src.stem + ".html")
            out_path.write_text(wrapper, encoding="utf-8")
            msg.close()
        except Exception as ex:
            return fail("extract_failed", f"{src.name}: {ex}")
        emit("email_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="html", source="msg")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_emlx_to_eml(args: argparse.Namespace) -> int:
    """Apple Mail .emlx = `<length>\\n<RFC 822 message>\\n<plist metadata>`."""
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".emlx file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            raw = src.read_bytes()
            nl = raw.find(b"\n")
            if nl <= 0: return fail("bad_emlx", f"{src.name}: no length prefix.")
            length = int(raw[:nl].strip())
            message_bytes = raw[nl + 1:nl + 1 + length]
            out_path = out_dir / (src.stem + ".eml")
            out_path.write_bytes(message_bytes)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("email_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="eml", source="emlx")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_thread_mbox(args: argparse.Namespace) -> int:
    """Bundle a directory of .eml files into a single .mbox."""
    eml_dir = Path(args.input_dir)
    if not eml_dir.is_dir(): return fail("missing_input", f"Directory not found: {eml_dir}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (eml_dir.name + ".mbox")
    if out_path.exists(): out_path.unlink()
    box = mailbox.mbox(str(out_path))
    box.lock()
    try:
        n = 0
        for eml in sorted(eml_dir.rglob("*.eml")):
            try:
                with eml.open("rb") as f:
                    msg = email.message_from_binary_file(f, policy=email.policy.compat32)
                box.add(msg)
                n += 1
            except Exception as ex:
                emit("log", level="warn", message=f"{eml.name}: {ex}")
        box.flush()
    finally:
        box.unlock(); box.close()

    emit("email_extra",
         input=str(eml_dir), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="mbox", count=n)
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=n)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="emailpro-sidecar",
                                description="Single-message email format conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("msg-to-eml", help="Outlook .msg -> .eml.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    h = sub.add_parser("msg-to-html", help="Outlook .msg -> HTML.")
    h.add_argument("--input", nargs="+", required=True)
    h.add_argument("--output-dir", required=True, dest="output_dir")

    e = sub.add_parser("emlx-to-eml", help="Apple Mail .emlx -> .eml.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")

    t = sub.add_parser("thread-mbox", help="Directory of .eml -> single .mbox.")
    t.add_argument("--input-dir", required=True, dest="input_dir")
    t.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "msg-to-eml":   return op_msg_to_eml(args)
        if args.op == "msg-to-html":  return op_msg_to_html(args)
        if args.op == "emlx-to-eml":  return op_emlx_to_eml(args)
        if args.op == "thread-mbox":  return op_thread_mbox(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

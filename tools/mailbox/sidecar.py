"""Email format converter -- MBOX / EML / Maildir mutual conversion via the
stdlib mailbox + email modules. PST is intentionally out of scope (libpff is
huge and platform-finicky); rely on Outlook's File -> Export -> .pst upstream.

Modes:
  mbox-split  : single MBOX file -> N .eml files in --output-dir (one per msg)
  eml-pack    : N .eml files     -> single MBOX
  mbox-mdir   : single MBOX file -> Maildir tree under --output-dir
  mdir-mbox   : Maildir tree     -> single MBOX
"""
from __future__ import annotations

import argparse
import email
import email.policy
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import mailbox
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _safe_name(s: str, fallback: str) -> str:
    s = (s or fallback).strip()
    bad = '<>:"/\\|?*\r\n\t'
    out = "".join("_" if c in bad else c for c in s)
    return out[:120] or fallback


def op_mbox_split(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"MBOX not found: {args.input}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    box = mailbox.mbox(str(src))
    total = len(box) or 1
    emit("progress", percent=0, stage="split", eta_seconds=None)
    written = 0
    for i, msg in enumerate(box):
        subject = msg.get("Subject", f"msg-{i + 1:05d}")
        out_path = out_dir / f"{i + 1:05d}_{_safe_name(subject, f'msg-{i+1}')}.eml"
        try:
            with out_path.open("wb") as fh:
                gen = email.generator.BytesGenerator(fh, policy=email.policy.default)
                gen.flatten(msg)
        except Exception as ex:
            emit("log", level="warn", message=f"msg #{i+1}: {ex}")
            continue
        written += 1
        emit("email_msg", index=i + 1, subject=str(subject), output=str(out_path),
             size_bytes=out_path.stat().st_size)
        if (i + 1) % max(1, total // 100) == 0 or i == total - 1:
            emit("progress", percent=round((i + 1) / total * 100, 1),
                 stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=written)
    return 0


def op_eml_pack(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"EML(s) not found: {missing}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    box = mailbox.mbox(str(out_path), create=True)
    box.lock()
    try:
        for i, src in enumerate(inputs):
            try:
                with src.open("rb") as fh:
                    msg = email.message_from_binary_file(fh, policy=email.policy.default)
                box.add(msg)
            except Exception as ex:
                emit("log", level="warn", message=f"{src.name}: {ex}")
                continue
            emit("email_msg", index=i + 1, output=str(out_path),
                 source=str(src))
            if (i + 1) % 50 == 0 or i == len(inputs) - 1:
                emit("progress", percent=round((i + 1) / len(inputs) * 100, 1),
                     stage=f"{i+1}/{len(inputs)}", eta_seconds=None)
        box.flush()
    finally:
        box.unlock(); box.close()
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         count=len(inputs))
    return 0


def op_mbox_to_maildir(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"MBOX not found: {args.input}")
    md_dir = Path(args.output_dir).resolve()
    md_dir.mkdir(parents=True, exist_ok=True)

    src_box = mailbox.mbox(str(src))
    md = mailbox.Maildir(str(md_dir), create=True)
    total = len(src_box) or 1
    for i, msg in enumerate(src_box):
        try: md.add(msg)
        except Exception as ex:
            emit("log", level="warn", message=f"msg #{i+1}: {ex}")
            continue
        if (i + 1) % max(1, total // 100) == 0 or i == total - 1:
            emit("progress", percent=round((i + 1) / total * 100, 1),
                 stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(md_dir), size_bytes=0, count=total)
    return 0


def op_maildir_to_mbox(args: argparse.Namespace) -> int:
    src_dir = Path(args.input)
    if not src_dir.is_dir():
        return fail("missing_input", f"Maildir not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists(): out_path.unlink()

    md = mailbox.Maildir(str(src_dir))
    box = mailbox.mbox(str(out_path), create=True); box.lock()
    total = len(md) or 1
    try:
        for i, msg in enumerate(md):
            try: box.add(msg)
            except Exception as ex:
                emit("log", level="warn", message=f"msg #{i+1}: {ex}")
                continue
            if (i + 1) % max(1, total // 100) == 0 or i == total - 1:
                emit("progress", percent=round((i + 1) / total * 100, 1),
                     stage=f"{i+1}/{total}", eta_seconds=None)
        box.flush()
    finally:
        box.unlock(); box.close()
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mailbox-sidecar",
                                description="Email format conversion: MBOX / EML / Maildir.")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("mbox-split", help="Split a single MBOX into .eml files")
    a.add_argument("--input", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    b = sub.add_parser("eml-pack", help="Pack many .eml files into a single MBOX")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output", required=True)

    c = sub.add_parser("mbox-to-maildir", help="MBOX -> Maildir tree")
    c.add_argument("--input", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")

    d = sub.add_parser("maildir-to-mbox", help="Maildir tree -> MBOX")
    d.add_argument("--input", required=True)  # source dir, not file
    d.add_argument("--output", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "mbox-split":       return op_mbox_split(args)
        if args.op == "eml-pack":         return op_eml_pack(args)
        if args.op == "mbox-to-maildir":  return op_mbox_to_maildir(args)
        if args.op == "maildir-to-mbox":  return op_maildir_to_mbox(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

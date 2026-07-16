"""Outlook PST/OST importer sidecar.

Cracks open Microsoft Outlook personal-storage files (.pst / .ost) using the
`libpff` Python bindings (`pypff`) and exports each message as either an
RFC-822 .eml file or appends to a Unix .mbox.

If pypff isn't available we error out with a clear install hint --- there is
no pure-Python fallback for PST.

Operations:
  to-eml    Each message -> <out>/<idx>__<subject>.eml
  to-mbox   All messages -> <out>/<basename>.mbox
  list      Walk the folder tree without writing anything (preview).
"""
from __future__ import annotations

import argparse
import email
import email.utils
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _check():
    try:
        import pypff  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_pypff",
             message=f"libpff/pypff not installed: {ex}. "
                     "Install via `pip install libpff-python`.")
        return False


_INVALID = re.compile(r'[\\/:*?"<>|]+')


def _safe(s: str, n: int = 80) -> str:
    s = _INVALID.sub("_", s or "").strip()
    return (s[:n] or "untitled").strip("._ ")


def _build_eml(msg) -> bytes:
    """Convert a pypff message into RFC-822 bytes."""
    headers = msg.get_transport_headers() or ""
    body_plain = msg.get_plain_text_body()
    body_html = msg.get_html_body()
    body_rtf = None  # RTF rarely useful for export

    if isinstance(body_plain, bytes):
        try: body_plain = body_plain.decode("utf-8", "replace")
        except Exception: body_plain = body_plain.decode("latin-1", "replace")
    if isinstance(body_html, bytes):
        try: body_html = body_html.decode("utf-8", "replace")
        except Exception: body_html = body_html.decode("latin-1", "replace")

    if headers and (body_plain or body_html):
        # libpff already gives us raw transport headers; just append the body.
        raw = headers
        if not raw.endswith("\r\n\r\n") and not raw.endswith("\n\n"):
            raw += "\r\n"
        raw += "\r\n"
        raw += body_plain or body_html or ""
        return raw.encode("utf-8", "replace")

    # Fallback: build a minimal envelope from message attributes.
    em = email.message.EmailMessage()
    try: em["Subject"] = msg.get_subject() or "(no subject)"
    except Exception: em["Subject"] = "(no subject)"
    try: em["From"] = msg.get_sender_name() or ""
    except Exception: pass
    try:
        d = msg.get_delivery_time()
        if d: em["Date"] = email.utils.format_datetime(d)
    except Exception: pass
    if body_plain: em.set_content(body_plain or "")
    elif body_html: em.add_alternative(body_html, subtype="html")
    return em.as_bytes()


def _walk_messages(root):
    """Yield (path-as-list-of-folder-names, message) for every message."""
    def descend(folder, path):
        for i in range(folder.get_number_of_sub_messages()):
            yield path, folder.get_sub_message(i)
        for j in range(folder.get_number_of_sub_folders()):
            sub = folder.get_sub_folder(j)
            yield from descend(sub, path + [sub.get_name() or f"folder_{j}"])
    yield from descend(root, [])


def op_to_eml(args: argparse.Namespace) -> int:
    if not _check(): return 1
    import pypff
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"PST/OST not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    pff = pypff.file()
    try:
        pff.open(str(src))
    except Exception as ex:
        return fail("open_failed", f"{src.name}: {ex}")
    root = pff.get_root_folder()
    started = time.monotonic()
    emit("progress", percent=0, stage="export", eta_seconds=None)

    written = 0
    for path, msg in _walk_messages(root):
        try:
            subj = msg.get_subject() or "(no subject)"
        except Exception:
            subj = "(no subject)"
        rel_dir = out_dir.joinpath(*[_safe(p, 60) for p in path]) if path else out_dir
        rel_dir.mkdir(parents=True, exist_ok=True)
        out_path = rel_dir / f"{written:06d}__{_safe(subj)}.eml"
        try:
            out_path.write_bytes(_build_eml(msg))
        except Exception as ex:
            emit("log", level="warn", message=f"#{written}: {ex}")
            continue
        emit("email_msg",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="eml", folder="/".join(path))
        written += 1
        if written % 25 == 0:
            elapsed = time.monotonic() - started
            emit("progress", percent=None,
                 stage=f"{written} messages",
                 eta_seconds=int(elapsed))

    pff.close()
    emit("complete", output=str(out_dir), size_bytes=0, count=written)
    return 0


def op_to_mbox(args: argparse.Namespace) -> int:
    if not _check(): return 1
    import pypff
    import mailbox
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"PST/OST not found: {src}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (src.stem + ".mbox")
    if out_path.exists(): out_path.unlink()
    box = mailbox.mbox(str(out_path))
    box.lock()

    pff = pypff.file()
    try:
        pff.open(str(src))
    except Exception as ex:
        return fail("open_failed", f"{src.name}: {ex}")
    root = pff.get_root_folder()
    written = 0
    for _path, msg in _walk_messages(root):
        try:
            box.add(_build_eml(msg))
            written += 1
        except Exception as ex:
            emit("log", level="warn", message=f"#{written}: {ex}")
        if written and written % 25 == 0:
            emit("progress", percent=None, stage=f"{written} messages",
                 eta_seconds=None)
    box.flush(); box.unlock(); box.close(); pff.close()
    emit("email_msg", input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size, format="mbox", count=written)
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=written)
    return 0


def op_list(args: argparse.Namespace) -> int:
    if not _check(): return 1
    import pypff
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"PST/OST not found: {src}")
    pff = pypff.file()
    try: pff.open(str(src))
    except Exception as ex: return fail("open_failed", f"{src.name}: {ex}")
    root = pff.get_root_folder()
    folders = {}
    for path, _msg in _walk_messages(root):
        key = "/".join(path) if path else "(root)"
        folders[key] = folders.get(key, 0) + 1
    pff.close()
    emit("email_index",
         path=str(src),
         folders=[{"folder": k, "messages": v} for k, v in folders.items()],
         total=int(sum(folders.values())))
    emit("complete", output=str(src), size_bytes=src.stat().st_size,
         count=int(sum(folders.values())))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mailimport-sidecar",
                                description="Outlook PST/OST importer.")
    sub = p.add_subparsers(dest="op", required=True)
    e = sub.add_parser("to-eml", help="Export every message as a .eml file.")
    e.add_argument("--input", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    m = sub.add_parser("to-mbox", help="Export every message into a single .mbox file.")
    m.add_argument("--input", required=True)
    m.add_argument("--output-dir", required=True, dest="output_dir")
    l = sub.add_parser("list", help="Inventory folders + message counts.")
    l.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-eml":  return op_to_eml(args)
        if args.op == "to-mbox": return op_to_mbox(args)
        if args.op == "list":    return op_list(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

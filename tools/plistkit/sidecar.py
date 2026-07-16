"""Apple Property-list (plist) sidecar.

Convert between binary, XML, JSON, and OpenStep / NeXT plist formats.

Operations:
  to-xml       Any plist -> XML plist (Apple FMT_XML).
  to-binary    Any plist -> binary plist (Apple FMT_BINARY).
  to-json      Any plist -> JSON.
  from-json    JSON -> plist (XML or binary).
"""
from __future__ import annotations

import argparse
import datetime
import json
import plistlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _read_plist(path: Path):
    with path.open("rb") as f:
        return plistlib.load(f)


def _to_jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, bytes):
        import base64
        return {"__bytes__": base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, datetime.datetime):
        return {"__date__": obj.isoformat()}
    return obj


def _from_jsonable(obj):
    import base64
    if isinstance(obj, dict):
        if "__bytes__" in obj and len(obj) == 1:
            return base64.b64decode(obj["__bytes__"])
        if "__date__" in obj and len(obj) == 1:
            return datetime.datetime.fromisoformat(obj["__date__"])
        return {k: _from_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_jsonable(v) for v in obj]
    return obj


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.target.lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="plist", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            if target == "from-json":
                obj = _from_jsonable(json.loads(src.read_text(encoding="utf-8")))
                fmt = plistlib.FMT_BINARY if args.binary else plistlib.FMT_XML
                out_path = out_dir / (src.stem + (".bplist" if args.binary else ".plist"))
                with out_path.open("wb") as f:
                    plistlib.dump(obj, f, fmt=fmt)
            else:
                data = _read_plist(src)
                if target == "to-xml":
                    out_path = out_dir / (src.stem + ".plist")
                    with out_path.open("wb") as f:
                        plistlib.dump(data, f, fmt=plistlib.FMT_XML)
                elif target == "to-binary":
                    out_path = out_dir / (src.stem + ".bplist")
                    with out_path.open("wb") as f:
                        plistlib.dump(data, f, fmt=plistlib.FMT_BINARY)
                elif target == "to-json":
                    out_path = out_dir / (src.stem + ".json")
                    out_path.write_text(
                        json.dumps(_to_jsonable(data), indent=2, ensure_ascii=False),
                        encoding="utf-8")
                else:
                    return fail("bad_target", target)
        except Exception as ex:
            return fail("plist_failed", f"{src.name}: {ex}")

        emit("plist_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             target=target)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="plistkit-sidecar",
                                description="Apple plist conversion (binary <-> XML <-> JSON).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert plist files.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--target", required=True,
                   choices=["to-xml", "to-binary", "to-json", "from-json"])
    c.add_argument("--binary", action="store_true",
                   help="(from-json) Output binary plist instead of XML.")
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

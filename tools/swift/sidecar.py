"""SWIFT MT (banking) sidecar.

SWIFT MT messages are the legacy financial-messaging format used by
banks worldwide (now being migrated to ISO 20022 MX / pacs.* XML).
This sidecar parses MT messages into structured JSON and converts
SWIFT MT camt/pacs message families to ISO 20022 XML where possible.

Operations:
  mt-to-json   SWIFT MT (.fin / .mt / .txt) -> structured JSON.
  mt-to-csv    Flatten MT field tags -> CSV row per field.

MT messages have a strict block structure: {1:...}{2:...}{3:...}{4:...}{5:...}
Block 4 contains the body fields like :20:, :32A:, :50K:, :59:, :70:, :71A:.
We parse without external libraries to keep the sidecar self-contained.
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
import re
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Regex for top-level SWIFT blocks: {N:...}
_BLOCK_RE = re.compile(r"\{(\d):([^{}]*(?:\{[^}]*\}[^{}]*)*)\}", re.DOTALL)
# Regex for body fields in block 4: :TAG:value (until next :TAG: or end)
_FIELD_RE = re.compile(r"^:([0-9A-Z]{2,3}):", re.MULTILINE)


def _parse_blocks(text: str) -> dict:
    blocks: dict[str, str] = {}
    for m in _BLOCK_RE.finditer(text):
        blocks[m.group(1)] = m.group(2)
    return blocks


def _parse_block4(body: str) -> list[dict]:
    body = body.strip()
    if body.endswith("-}"):
        body = body[:-2]
    # find tag boundaries
    matches = list(_FIELD_RE.finditer(body))
    fields: list[dict] = []
    for i, m in enumerate(matches):
        tag = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        value = body[start:end].strip()
        fields.append({"tag": tag, "value": value})
    return fields


def _parse_mt(text: str) -> dict:
    text = text.strip()
    if not text.startswith("{"):
        raise ValueError("Not a SWIFT MT file (must start with '{1:').")
    blocks = _parse_blocks(text)
    msg_type = None
    if "2" in blocks:
        # block 2: I103NNNN... or O103... — type is digits 2-4 of the block.
        m = re.search(r"[IO](\d{3})", blocks["2"])
        if m: msg_type = m.group(1)
    fields = _parse_block4(blocks.get("4", ""))
    return {
        "format": "swift-mt",
        "message_type": msg_type,
        "blocks": blocks,
        "fields": fields,
    }


def op_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            parsed = _parse_mt(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("swift_mt",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", message_type=parsed.get("message_type"),
             field_count=len(parsed["fields"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            parsed = _parse_mt(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["#", "tag", "value"])
            for n, fld in enumerate(parsed["fields"], 1):
                w.writerow([n, fld["tag"], fld["value"].replace("\n", "\\n")])
        emit("swift_mt",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", message_type=parsed.get("message_type"),
             field_count=len(parsed["fields"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="swift-sidecar",
                                description="SWIFT MT (banking) message decoder.")
    sub = p.add_subparsers(dest="op", required=True)

    j = sub.add_parser("mt-to-json", help="SWIFT MT -> JSON.")
    j.add_argument("--input", nargs="+", required=True)
    j.add_argument("--output-dir", required=True, dest="output_dir")

    c = sub.add_parser("mt-to-csv", help="SWIFT MT -> per-field CSV.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "mt-to-json": return op_to_json(args)
        if args.op == "mt-to-csv":  return op_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

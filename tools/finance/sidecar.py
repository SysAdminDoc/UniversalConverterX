"""Personal finance / accounting interchange sidecar.

Convert between bank-export and accounting-software formats:

  * OFX  (Open Financial Exchange, .ofx, .qfx)   Most US bank exports
  * QIF  (Quicken Interchange Format, .qif)      Legacy Quicken / GnuCash
  * IIF  (QuickBooks Interchange, .iif)          QuickBooks Desktop
  * MT940 / MT942                                European banking statements
  * CAMT.052 / CAMT.053                          ISO 20022 banking
  * CSV (normalized: date, payee, amount, memo, category)

We normalize every format into a list of `Transaction` rows and re-emit
on the way out.
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
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path


def emit(event: str, **fields_) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields_}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


@dataclass
class Transaction:
    date: str = ""
    amount: float = 0.0
    payee: str = ""
    memo: str = ""
    category: str = ""
    account: str = ""
    type: str = ""
    fitid: str = ""


# ── OFX ────────────────────────────────────────────────────────────────

def _read_ofx(path: Path) -> list[Transaction]:
    try:
        from ofxparse import OfxParser
    except ImportError as ex:
        raise RuntimeError(f"ofxparse not installed: {ex}. `pip install ofxparse`.") from ex
    with path.open("rb") as f:
        ofx = OfxParser.parse(f)
    out: list[Transaction] = []
    for account in (ofx.accounts or []):
        if not account.statement: continue
        for tx in account.statement.transactions:
            out.append(Transaction(
                date=tx.date.isoformat() if tx.date else "",
                amount=float(tx.amount or 0),
                payee=str(tx.payee or ""),
                memo=str(tx.memo or ""),
                account=str(getattr(account, "number", "") or ""),
                type=str(getattr(tx, "type", "") or ""),
                fitid=str(getattr(tx, "id", "") or ""),
            ))
    return out


# ── QIF ────────────────────────────────────────────────────────────────

def _read_qif(path: Path) -> list[Transaction]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[Transaction] = []
    cur = Transaction()
    for line in text.splitlines():
        if not line: continue
        if line.startswith("!"):
            cur = Transaction(); continue
        if line == "^":
            if cur.date or cur.amount: out.append(cur)
            cur = Transaction(); continue
        code, value = line[0], line[1:]
        if code == "D":   cur.date = value
        elif code == "T": cur.amount = _parse_amount(value)
        elif code == "U": cur.amount = _parse_amount(value)
        elif code == "P": cur.payee = value
        elif code == "M": cur.memo = value
        elif code == "L": cur.category = value
        elif code == "N": cur.fitid = value
    if cur.date or cur.amount: out.append(cur)
    return out


def _parse_amount(s: str) -> float:
    try: return float(s.replace(",", "").replace("$", ""))
    except Exception: return 0.0


# ── IIF (QuickBooks) ────────────────────────────────────────────────────

def _read_iif(path: Path) -> list[Transaction]:
    """IIF is tab-delimited with header rows."""
    out: list[Transaction] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter="\t")
        header: list[str] | None = None
        for row in reader:
            if not row: continue
            if row[0].startswith("!"):
                header = [c.lstrip("!") for c in row]
                continue
            if not header: continue
            d = dict(zip(header, row))
            if d.get("TRNS") or d.get("SPL"):
                out.append(Transaction(
                    date=d.get("DATE", ""),
                    amount=_parse_amount(d.get("AMOUNT", "0")),
                    payee=d.get("NAME", ""),
                    memo=d.get("MEMO", ""),
                    category=d.get("ACCNT", ""),
                ))
    return out


# ── CSV ────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[Transaction]:
    out: list[Transaction] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out.append(Transaction(
                date=row.get("date") or row.get("Date") or "",
                amount=_parse_amount(row.get("amount") or row.get("Amount") or "0"),
                payee=row.get("payee") or row.get("Payee") or "",
                memo=row.get("memo") or row.get("Description") or "",
                category=row.get("category") or row.get("Category") or "",
                account=row.get("account") or "",
                type=row.get("type") or "",
            ))
    return out


# ── MT940 ──────────────────────────────────────────────────────────────

def _read_mt940(path: Path) -> list[Transaction]:
    try:
        import mt940
    except ImportError as ex:
        raise RuntimeError(f"mt-940 not installed: {ex}. `pip install mt-940`.") from ex
    out: list[Transaction] = []
    transactions = mt940.parse(str(path))
    for tx in transactions:
        d = tx.data
        out.append(Transaction(
            date=str(d.get("date") or ""),
            amount=float(d.get("amount").amount) if d.get("amount") else 0.0,
            payee=str(d.get("counter_party") or ""),
            memo=str(d.get("transaction_details") or ""),
            account=str(d.get("account_identification") or ""),
        ))
    return out


READERS = {
    ".ofx": _read_ofx, ".qfx": _read_ofx,
    ".qif": _read_qif,
    ".iif": _read_iif,
    ".csv": _read_csv,
    ".mt940": _read_mt940, ".sta": _read_mt940,
}


# ── Writers ────────────────────────────────────────────────────────────

def write_csv(rows: list[Transaction], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "amount", "payee", "memo", "category",
                     "account", "type", "fitid"])
        for r in rows:
            w.writerow([r.date, r.amount, r.payee, r.memo, r.category,
                         r.account, r.type, r.fitid])


def write_json(rows: list[Transaction], path: Path) -> None:
    path.write_text(json.dumps([asdict(r) for r in rows],
                                indent=2, ensure_ascii=False),
                     encoding="utf-8")


def write_qif(rows: list[Transaction], path: Path) -> None:
    lines = ["!Type:Bank"]
    for r in rows:
        lines.append(f"D{r.date}")
        lines.append(f"T{r.amount}")
        if r.payee:    lines.append(f"P{r.payee}")
        if r.memo:     lines.append(f"M{r.memo}")
        if r.category: lines.append(f"L{r.category}")
        if r.fitid:    lines.append(f"N{r.fitid}")
        lines.append("^")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


WRITERS = {
    "csv": write_csv,
    "json": write_json,
    "qif": write_qif,
}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Finance file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in WRITERS:
        return fail("bad_target", f"Choose: {sorted(WRITERS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="finance", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        reader = READERS.get(ext)
        if not reader:
            return fail("bad_format", f"Unsupported source ext '{ext}'.")
        try:
            rows = reader(src)
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + target)
        WRITERS[target](rows, out_path)

        emit("finance_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, transactions=len(rows))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="finance-sidecar",
                                description="Personal finance / accounting format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert OFX/QFX/QIF/IIF/MT940/CSV.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="csv | json | qif")
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

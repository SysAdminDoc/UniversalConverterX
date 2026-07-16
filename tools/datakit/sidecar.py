"""Data converter sidecar -- JSON / YAML / TOML / XML / CSV mutual conversion.

Pure-Python wrapper using stdlib (json, csv, xml) + PyYAML + tomli/tomli-w.
Lossless when the source format expresses every output type's constraints;
flat CSV->JSON works trivially, JSON->CSV requires uniform record shapes.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Canonical extensions for each format.
EXT_TO_FORMAT = {
    "json": "json", "ndjson": "ndjson", "jsonl": "ndjson",
    "yaml": "yaml", "yml": "yaml",
    "toml": "toml",
    "xml": "xml",
    "csv": "csv", "tsv": "tsv",
}


def _read(path: Path):
    ext = path.suffix.lstrip(".").lower()
    fmt = EXT_TO_FORMAT.get(ext)
    text = path.read_text(encoding="utf-8")
    if fmt == "json":
        return json.loads(text)
    if fmt == "ndjson":
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    if fmt == "yaml":
        try: import yaml
        except ImportError: raise RuntimeError("PyYAML not installed.")
        return yaml.safe_load(text)
    if fmt == "toml":
        try: import tomllib  # py 3.11+
        except ImportError:
            try: import tomli as tomllib  # type: ignore
            except ImportError: raise RuntimeError("tomllib/tomli not installed.")
        return tomllib.loads(text)
    if fmt == "xml":
        try: import xmltodict
        except ImportError: raise RuntimeError("xmltodict not installed.")
        return xmltodict.parse(text)
    if fmt in ("csv", "tsv"):
        delim = "\t" if fmt == "tsv" else ","
        return list(csv.DictReader(StringIO(text), delimiter=delim))
    raise RuntimeError(f"Unrecognised input extension '.{ext}'")


def _write(data, path: Path, fmt: str) -> None:
    fmt = fmt.lstrip(".").lower()
    if fmt == "json":
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return
    if fmt == "ndjson":
        if not isinstance(data, list):
            raise RuntimeError("NDJSON requires a top-level list.")
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in data),
                        encoding="utf-8")
        return
    if fmt == "yaml":
        try: import yaml
        except ImportError: raise RuntimeError("PyYAML not installed.")
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
        return
    if fmt == "toml":
        try: import tomli_w
        except ImportError: raise RuntimeError("tomli_w not installed.")
        if not isinstance(data, dict):
            raise RuntimeError("TOML requires a top-level dict / mapping.")
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
        return
    if fmt == "xml":
        try: import xmltodict
        except ImportError: raise RuntimeError("xmltodict not installed.")
        if isinstance(data, list):
            data = {"root": {"item": data}}
        elif not isinstance(data, dict):
            data = {"root": data}
        path.write_text(xmltodict.unparse(data, pretty=True), encoding="utf-8")
        return
    if fmt in ("csv", "tsv"):
        delim = "\t" if fmt == "tsv" else ","
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise RuntimeError(f"{fmt.upper()} requires a top-level list of uniform-shape records.")
        if not data:
            path.write_text("", encoding="utf-8"); return
        keys: list[str] = []
        for row in data:
            for k in row:
                if k not in keys: keys.append(k)
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, delimiter=delim)
            w.writeheader()
            for row in data: w.writerow(row)
        return
    raise RuntimeError(f"Unrecognised output format '{fmt}'")


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Data file(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    out_ext = "yml" if target == "yaml" else target
    if out_ext == "ndjson": out_ext = "ndjson"

    total = len(inputs)
    emit("log", level="info", message=f"Convert {total} file(s) -> .{target}")
    emit("progress", percent=0, stage="convert", eta_seconds=None)
    started = time.monotonic()
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + out_ext)
        try:
            data = _read(src)
            _write(data, out_path, target)
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("data_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size)
        pct = (i + 1) / total * 100.0
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100.0) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"converted {i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="datakit-sidecar",
                                description="JSON / YAML / TOML / XML / CSV / TSV / NDJSON mutual conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    cv = sub.add_parser("convert", help="Convert data files between formats")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="json | ndjson | yaml | toml | xml | csv | tsv")
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

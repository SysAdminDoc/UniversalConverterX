"""Schema-driven binary wire format conversion sidecar.

Where `wirefmt` handles schemaless binary formats (CBOR / MessagePack /
BSON / Ion), `datawire` handles the schema-driven ones used by gRPC,
microservices, and high-perf RPC:

  * Protocol Buffers   .proto + .pb / .bin
  * Apache Thrift      .thrift + .thrift-bin
  * Apache Avro        .avsc + .avro / .ocf
  * Cap'n Proto        .capnp + binary
  * FlatBuffers        .fbs + binary

These all require schema files. Without them, only structural decoding
(no field names) is possible. Operations that need a schema make that
explicit and tell the user what to provide.

Operations:
  pb-decode-text      .pb / .bin -> JSON (uses `protoc --decode`).
  pb-encode-text      JSON -> .pb (uses `protoc --encode`).
  avro-to-json        Avro Object Container Format (.avro / .ocf) -> JSON.
  json-to-avro        JSON + .avsc schema -> Avro OCF.
  thrift-list-types   List symbols in a .thrift IDL file.
  fbs-list-types      List symbols in a .fbs FlatBuffers schema.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Protocol Buffers via protoc CLI ────────────────────────────────────

def _protoc() -> str | None:
    return shutil.which("protoc") or shutil.which("protoc.exe")


def op_pb_decode_text(args: argparse.Namespace) -> int:
    pc = _protoc()
    if not pc: return fail("missing_dep", "protoc not on PATH.")
    proto = Path(args.proto)
    if not proto.is_file():
        return fail("missing_input", f".proto schema not found: {proto}")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".pb file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        cmd = [pc, f"--proto_path={proto.parent}",
               f"--decode={args.message}", str(proto.name)]
        try:
            with src.open("rb") as f:
                proc = subprocess.run(cmd, input=f.read(),
                                       capture_output=True, timeout=120)
            if proc.returncode != 0:
                return fail("decode_failed",
                            f"{src.name}: protoc exit {proc.returncode}: "
                            f"{proc.stderr.decode('utf-8', 'replace')}")
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".txtpb")
        out_path.write_bytes(proc.stdout)
        emit("datawire_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="protobuf-text", source="protobuf-binary",
             message=args.message)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_pb_encode_text(args: argparse.Namespace) -> int:
    pc = _protoc()
    if not pc: return fail("missing_dep", "protoc not on PATH.")
    proto = Path(args.proto)
    if not proto.is_file():
        return fail("missing_input", f".proto schema not found: {proto}")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".txtpb file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        cmd = [pc, f"--proto_path={proto.parent}",
               f"--encode={args.message}", str(proto.name)]
        try:
            with src.open("rb") as f:
                proc = subprocess.run(cmd, input=f.read(),
                                       capture_output=True, timeout=120)
            if proc.returncode != 0:
                return fail("encode_failed",
                            f"{src.name}: protoc exit {proc.returncode}: "
                            f"{proc.stderr.decode('utf-8', 'replace')}")
        except Exception as ex:
            return fail("encode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".pb")
        out_path.write_bytes(proc.stdout)
        emit("datawire_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="protobuf-binary", source="protobuf-text",
             message=args.message)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Avro (Object Container Format) ─────────────────────────────────────

def op_avro_to_json(args: argparse.Namespace) -> int:
    try:
        import fastavro
    except ImportError:
        return fail("missing_dep",
                    "fastavro not installed (`pip install fastavro`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".avro file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            with src.open("rb") as f:
                reader = fastavro.reader(f)
                records = list(reader)
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(records, indent=2, default=str),
                            encoding="utf-8")
        emit("datawire_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="avro", count=len(records))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_json_to_avro(args: argparse.Namespace) -> int:
    try:
        import fastavro
    except ImportError:
        return fail("missing_dep",
                    "fastavro not installed (`pip install fastavro`).")
    schema_path = Path(args.schema)
    if not schema_path.is_file():
        return fail("missing_input", f".avsc schema not found: {schema_path}")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"JSON file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    parsed = fastavro.parse_schema(schema)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            if isinstance(data, dict): data = [data]
            out_path = out_dir / (src.stem + ".avro")
            with out_path.open("wb") as f:
                fastavro.writer(f, parsed, data)
        except Exception as ex:
            return fail("encode_failed", f"{src.name}: {ex}")
        emit("datawire_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="avro", source="json", count=len(data))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Schema introspection (Thrift IDL / FlatBuffers .fbs) ───────────────

_THRIFT_TYPE_RE = re.compile(
    r"^\s*(struct|enum|service|union|exception|typedef|const)\s+(\w+)",
    re.MULTILINE)
_FBS_TYPE_RE = re.compile(
    r"^\s*(table|struct|enum|union|namespace|root_type)\s+([\w\.]+)",
    re.MULTILINE)


def op_thrift_list_types(args: argparse.Namespace) -> int:
    return _list_schema_types(args, _THRIFT_TYPE_RE, "thrift")


def op_fbs_list_types(args: argparse.Namespace) -> int:
    return _list_schema_types(args, _FBS_TYPE_RE, "flatbuffers")


def _list_schema_types(args: argparse.Namespace, regex: re.Pattern,
                        kind: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"{kind} schema(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            symbols = [{"kind": m.group(1), "name": m.group(2)}
                       for m in regex.finditer(text)]
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + f".{kind}-symbols.json")
        out_path.write_text(json.dumps(symbols, indent=2),
                            encoding="utf-8")
        emit("datawire_schema",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source=kind, count=len(symbols))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="datawire-sidecar",
                                description="Schema-driven binary wire format conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    pd = sub.add_parser("pb-decode-text", help="Protobuf binary -> text-format using protoc.")
    pd.add_argument("--input", nargs="+", required=True)
    pd.add_argument("--output-dir", required=True, dest="output_dir")
    pd.add_argument("--proto", required=True, help=".proto schema file")
    pd.add_argument("--message", required=True, help="fully-qualified message type")

    pe = sub.add_parser("pb-encode-text", help="Protobuf text-format -> binary via protoc.")
    pe.add_argument("--input", nargs="+", required=True)
    pe.add_argument("--output-dir", required=True, dest="output_dir")
    pe.add_argument("--proto", required=True, help=".proto schema file")
    pe.add_argument("--message", required=True, help="fully-qualified message type")

    aj = sub.add_parser("avro-to-json", help="Avro OCF -> JSON.")
    aj.add_argument("--input", nargs="+", required=True)
    aj.add_argument("--output-dir", required=True, dest="output_dir")

    ja = sub.add_parser("json-to-avro", help="JSON + .avsc schema -> Avro OCF.")
    ja.add_argument("--input", nargs="+", required=True)
    ja.add_argument("--output-dir", required=True, dest="output_dir")
    ja.add_argument("--schema", required=True, help=".avsc schema file")

    th = sub.add_parser("thrift-list-types", help="List symbols in a .thrift IDL.")
    th.add_argument("--input", nargs="+", required=True)
    th.add_argument("--output-dir", required=True, dest="output_dir")

    fb = sub.add_parser("fbs-list-types", help="List symbols in a .fbs FlatBuffers schema.")
    fb.add_argument("--input", nargs="+", required=True)
    fb.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "pb-decode-text":    return op_pb_decode_text(args)
        if args.op == "pb-encode-text":    return op_pb_encode_text(args)
        if args.op == "avro-to-json":      return op_avro_to_json(args)
        if args.op == "json-to-avro":      return op_json_to_avro(args)
        if args.op == "thrift-list-types": return op_thrift_list_types(args)
        if args.op == "fbs-list-types":    return op_fbs_list_types(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

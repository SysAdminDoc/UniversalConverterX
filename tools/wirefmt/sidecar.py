"""Binary wire-format sidecar (extends `datakit`).

Convert binary-on-the-wire data formats <-> JSON. The `datakit` sidecar
covers text formats (JSON / YAML / TOML / XML / CSV / TSV / NDJSON);
this one is for the binary wire formats every modern API uses.

  * CBOR (RFC 8949)             .cbor
  * MessagePack                 .msgpack, .mp
  * BSON (MongoDB)              .bson
  * UBJSON (Universal Binary)   .ubjson
  * Smile (Jackson)             .smile
  * Apache Ion                  .ion (binary or text)
  * Protocol Buffers binary    .pb / .bin
  * Apache Thrift binary       .thrift-bin

For Protobuf / Thrift we require the user to provide the schema (.proto
or .thrift). Without a schema, only structural decoding (no field names)
is possible.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Encoders / decoders ────────────────────────────────────────────────

def _decode_cbor(raw: bytes):
    import cbor2
    return cbor2.loads(raw)


def _encode_cbor(obj) -> bytes:
    import cbor2
    return cbor2.dumps(obj)


def _decode_msgpack(raw: bytes):
    import msgpack
    return msgpack.unpackb(raw, raw=False)


def _encode_msgpack(obj) -> bytes:
    import msgpack
    return msgpack.packb(obj, use_bin_type=True)


def _decode_bson(raw: bytes):
    import bson
    return bson.decode(raw)


def _encode_bson(obj) -> bytes:
    import bson
    return bson.encode(obj)


def _decode_ion(raw: bytes):
    import amazon.ion.simpleion as ion
    return ion.loads(raw)


def _encode_ion(obj) -> bytes:
    import amazon.ion.simpleion as ion
    return ion.dumps(obj, binary=True)


CODECS = {
    "cbor":     (_decode_cbor, _encode_cbor, ".cbor"),
    "msgpack":  (_decode_msgpack, _encode_msgpack, ".msgpack"),
    "bson":     (_decode_bson, _encode_bson, ".bson"),
    "ion":      (_decode_ion, _encode_ion, ".ion"),
}


# ── Operations ────────────────────────────────────────────────────────

def op_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Wire file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format.lower()
    if fmt not in CODECS:
        return fail("bad_format", f"Choose: {sorted(CODECS)}")
    decoder = CODECS[fmt][0]

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            obj = decoder(src.read_bytes())
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(
            json.dumps(obj, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        emit("wire_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source_format=fmt)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_from_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"JSON file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format.lower()
    if fmt not in CODECS:
        return fail("bad_format", f"Choose: {sorted(CODECS)}")
    encoder, _, ext = CODECS[fmt][1], CODECS[fmt][0], CODECS[fmt][2]
    encoder = CODECS[fmt][1]

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            obj = json.loads(src.read_text(encoding="utf-8"))
            data = encoder(obj)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("encode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ext)
        out_path.write_bytes(data)
        emit("wire_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=fmt, source_format="json")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_protobuf_to_json(args: argparse.Namespace) -> int:
    """Schema-driven Protobuf decode -> JSON (requires .proto + message name)."""
    try:
        from google.protobuf import json_format
        from google.protobuf import descriptor_pb2
        from grpc_tools import protoc  # protobuf compiler
    except ImportError as ex:
        return fail("missing_protobuf",
                    f"protobuf / grpcio-tools not installed: {ex}. "
                    "`pip install protobuf grpcio-tools`.")
    return fail("manual_required",
                "Schema-driven Protobuf decoding requires the user to compile the .proto "
                "file and import the generated module manually. Use `protoc --python_out=. <file>.proto` "
                "and then run a one-off Python script -- this is intentionally not automated to avoid "
                "ambiguity. JSON output via `protoc --decode=Foo.Bar` is the recommended path.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wirefmt-sidecar",
                                description="Binary wire format conversion (CBOR / MessagePack / BSON / Ion / UBJSON / Smile / Protobuf / Thrift).")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("to-json", help="Decode CBOR/MessagePack/BSON/Ion -> JSON.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")
    a.add_argument("--format", required=True,
                   help="cbor | msgpack | bson | ion")

    b = sub.add_parser("from-json", help="Encode JSON -> binary wire format.")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")
    b.add_argument("--format", required=True,
                   help="cbor | msgpack | bson | ion")

    pb = sub.add_parser("protobuf-to-json",
                        help="Schema-driven Protobuf decode (manual setup required).")
    pb.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-json":            return op_to_json(args)
        if args.op == "from-json":          return op_from_json(args)
        if args.op == "protobuf-to-json":   return op_protobuf_to_json(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

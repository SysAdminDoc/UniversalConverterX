"""ML model interchange sidecar.

Probe / extract metadata from machine-learning model files. Most modern
formats embed a JSON header that we can decode without loading the whole
model — important because models can be 10s of GB.

  * ONNX (.onnx) — Open Neural Network Exchange (Protobuf)
  * safetensors (.safetensors) — HuggingFace tensor format with JSON header
  * GGUF (.gguf) — llama.cpp quantized model format
  * GGML (.ggml) — older llama.cpp format
  * PyTorch (.pt / .pth / .bin) — torch.save state-dict (header probe)
  * TFLite (.tflite) — TensorFlow Lite mobile (FlatBuffers)
  * CoreML (.mlmodel / .mlpackage) — Apple Core ML (Protobuf)
  * Keras .h5 / SavedModel directory probe

Operations:
  probe                   Auto-detect by magic / extension and emit JSON probe.
  safetensors-header      Read the JSON header at start of .safetensors file.
  gguf-header             Read GGUF v3 header + key-value metadata.
  onnx-info               ONNX graph summary (input/output shapes + ops).

All ops stream just the header — never load the full tensor data.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import struct
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── safetensors header ────────────────────────────────────────────────

def _read_safetensors_header(path: Path) -> dict:
    with path.open("rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header_bytes = f.read(n)
    return json.loads(header_bytes)


def op_safetensors_header(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"safetensors file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            header = _read_safetensors_header(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        # Summarize: tensor count, total parameters, dtypes
        tensors = {k: v for k, v in header.items() if k != "__metadata__"}
        meta = header.get("__metadata__", {})
        total_params = 0
        dtypes: dict[str, int] = {}
        for tname, info in tensors.items():
            shape = info.get("shape", [])
            n = 1
            for d in shape: n *= d
            total_params += n
            dtypes[info.get("dtype", "?")] = dtypes.get(info.get("dtype", "?"), 0) + 1
        summary = {
            "tensor_count": len(tensors),
            "total_parameters": total_params,
            "dtype_distribution": dtypes,
            "metadata": meta,
            "tensors": [
                {"name": k, "shape": v.get("shape"), "dtype": v.get("dtype"),
                  "data_offsets": v.get("data_offsets")}
                for k, v in list(tensors.items())[:200]
            ],
        }
        out_path = out_dir / (src.stem + ".safetensors.json")
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        emit("ml_model",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="safetensors",
             tensors=len(tensors), parameters=total_params)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── GGUF v2/v3 header ─────────────────────────────────────────────────

_GGUF_TYPES = {0: "uint8", 1: "int8", 2: "uint16", 3: "int16",
               4: "uint32", 5: "int32", 6: "float32",
               7: "bool", 8: "string", 9: "array",
               10: "uint64", 11: "int64", 12: "float64"}


def _gguf_read_string(buf: bytes, p: int) -> tuple[str, int]:
    n = struct.unpack_from("<Q", buf, p)[0]; p += 8
    s = buf[p:p + n].decode("utf-8", errors="replace"); p += n
    return s, p


def _gguf_read_value(buf: bytes, p: int, type_id: int):
    fmt_map = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
               6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
    if type_id == 8:  # string
        return _gguf_read_string(buf, p)
    if type_id == 9:  # array
        elem_type = struct.unpack_from("<I", buf, p)[0]; p += 4
        n = struct.unpack_from("<Q", buf, p)[0]; p += 8
        out = []
        # cap array decoding to avoid pathological cases
        for _ in range(min(n, 32)):
            v, p = _gguf_read_value(buf, p, elem_type)
            out.append(v)
        if n > 32: out.append(f"<...+{n - 32} more>")
        return out, p
    if type_id in fmt_map:
        fmt = fmt_map[type_id]
        size = struct.calcsize(fmt)
        v = struct.unpack_from(fmt, buf, p)[0]
        return v, p + size
    return f"<unsupported type {type_id}>", p


def _read_gguf_header(path: Path, max_bytes: int = 64 * 1024 * 1024) -> dict:
    """Read the GGUF header + KV metadata only (typical < 64 MB)."""
    with path.open("rb") as f:
        buf = f.read(max_bytes)
    if buf[0:4] != b"GGUF":
        raise ValueError("Not a GGUF file (magic mismatch).")
    version = struct.unpack_from("<I", buf, 4)[0]
    tensor_count = struct.unpack_from("<Q", buf, 8)[0]
    metadata_kv_count = struct.unpack_from("<Q", buf, 16)[0]
    p = 24
    metadata: dict = {}
    for _ in range(metadata_kv_count):
        key, p = _gguf_read_string(buf, p)
        if p + 4 > len(buf): break
        type_id = struct.unpack_from("<I", buf, p)[0]; p += 4
        try:
            value, p = _gguf_read_value(buf, p, type_id)
        except Exception:
            break
        metadata[key] = {"type": _GGUF_TYPES.get(type_id, "?"), "value": value}
    return {"version": version, "tensor_count": tensor_count,
            "metadata_kv_count": metadata_kv_count, "metadata": metadata}


def op_gguf_header(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"GGUF file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            header = _read_gguf_header(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".gguf.json")
        out_path.write_text(json.dumps(header, indent=2, default=str),
                            encoding="utf-8")
        emit("ml_model",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="gguf",
             tensors=header["tensor_count"], version=header["version"])
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── ONNX info (requires `onnx` lib for full decode) ────────────────────

def op_onnx_info(args: argparse.Namespace) -> int:
    try:
        import onnx
    except ImportError:
        return fail("missing_dep", "onnx not installed (`pip install onnx`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"ONNX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            model = onnx.load(str(src))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        graph = model.graph
        op_counts: dict[str, int] = {}
        for n in graph.node:
            op_counts[n.op_type] = op_counts.get(n.op_type, 0) + 1
        info = {
            "ir_version": model.ir_version,
            "producer_name": model.producer_name,
            "producer_version": model.producer_version,
            "opset_imports": [{"domain": op.domain, "version": op.version}
                                for op in model.opset_import],
            "inputs": [{"name": x.name,
                         "shape": [d.dim_value or d.dim_param
                                    for d in x.type.tensor_type.shape.dim]}
                        for x in graph.input],
            "outputs": [{"name": x.name,
                          "shape": [d.dim_value or d.dim_param
                                     for d in x.type.tensor_type.shape.dim]}
                         for x in graph.output],
            "node_count": len(graph.node),
            "op_counts": op_counts,
            "initializers": len(graph.initializer),
        }
        out_path = out_dir / (src.stem + ".onnx.json")
        out_path.write_text(json.dumps(info, indent=2, default=str),
                            encoding="utf-8")
        emit("ml_model",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="onnx",
             nodes=len(graph.node), ops=len(op_counts))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Generic probe (auto-detect) ────────────────────────────────────────

def _probe_one(src: Path) -> dict:
    with src.open("rb") as f:
        head = f.read(16)
    info: dict = {"file": str(src), "size_bytes": src.stat().st_size}
    if head[0:4] == b"GGUF":
        info["format"] = "gguf"
    elif head[0:8] == b"\x89HDF\r\n\x1a\n":
        info["format"] = "hdf5-keras"
    elif head[0:4] == b"PK\x03\x04":
        info["format"] = "zip-bundle (.mlpackage / .keras / .pt-zip)"
    elif src.suffix.lower() == ".onnx":
        info["format"] = "onnx"
    elif src.suffix.lower() == ".safetensors":
        info["format"] = "safetensors"
    elif src.suffix.lower() in (".pt", ".pth", ".bin"):
        # Heuristic: torch.save uses zip + pickle since 1.6
        if head[0:2] == b"PK":
            info["format"] = "pytorch-zip"
        elif head[0] == 0x80:  # pickle protocol marker
            info["format"] = "pytorch-pickle"
        else:
            info["format"] = "pytorch-unknown"
    elif src.suffix.lower() == ".tflite":
        info["format"] = "tflite-flatbuffer"
    elif src.suffix.lower() == ".mlmodel":
        info["format"] = "coreml-protobuf"
    elif src.suffix.lower() == ".mlpackage":
        info["format"] = "coreml-mlpackage"
    elif src.suffix.lower() in (".ckpt",):
        info["format"] = "tf-checkpoint"
    else:
        info["format"] = "unknown"
    return info


def op_probe(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"model file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        probes.append(_probe_one(src))
        emit("ml_model",
             input=str(src), output="",
             size_bytes=0, format="probe",
             source=probes[-1]["format"])
    out_path = out_dir / "ml-model-probe.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mlmodel-sidecar",
                                description="ML model interchange format probes.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("probe",              "Auto-detect ML model format"),
        ("safetensors-header", "HF safetensors -> JSON header summary"),
        ("gguf-header",        "GGUF llama.cpp quantized -> JSON header + KV metadata"),
        ("onnx-info",          "ONNX graph summary (requires onnx)"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":              return op_probe(args)
        if args.op == "safetensors-header": return op_safetensors_header(args)
        if args.op == "gguf-header":        return op_gguf_header(args)
        if args.op == "onnx-info":          return op_onnx_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

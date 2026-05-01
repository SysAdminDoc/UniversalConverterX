"""Scientific / tabular data sidecar -- bidirectional conversion across the
formats data scientists juggle daily:

  CSV / TSV / JSON-Lines / Parquet / Feather / Arrow IPC / Avro / ORC / HDF5
  NumPy .npy / .npz   (single-array + zip-of-arrays)
  Matlab .mat         (read via scipy + write v7.3 via h5py)
  NetCDF .nc          (xarray)
  FITS .fits          (astropy)

The shape of "convert" is dataframe-centric where it makes sense (CSV<->Parquet
etc.) and array-centric for the scientific-stack formats (NPY/MAT/FITS).
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


# ---- format dispatchers ----

DATAFRAME_EXTS = {".csv", ".tsv", ".jsonl", ".ndjson", ".parquet", ".pq",
                  ".feather", ".arrow", ".avro", ".orc", ".h5", ".hdf5"}
ARRAY_EXTS = {".npy", ".npz", ".mat", ".fits", ".nc"}


def _read_dataframe(path: Path):
    import pandas as pd
    ext = path.suffix.lower()
    if ext == ".csv": return pd.read_csv(path)
    if ext == ".tsv": return pd.read_csv(path, sep="\t")
    if ext in (".jsonl", ".ndjson"): return pd.read_json(path, lines=True)
    if ext in (".parquet", ".pq"): return pd.read_parquet(path)
    if ext in (".feather", ".arrow"): return pd.read_feather(path)
    if ext == ".avro":
        import fastavro
        with path.open("rb") as f:
            recs = list(fastavro.reader(f))
        return pd.DataFrame.from_records(recs)
    if ext == ".orc": return pd.read_orc(path)
    if ext in (".h5", ".hdf5"):
        return pd.read_hdf(path, key=None)
    raise ValueError(f"Unsupported dataframe extension: {ext}")


def _write_dataframe(df, path: Path) -> None:
    ext = path.suffix.lower()
    if ext == ".csv": df.to_csv(path, index=False); return
    if ext == ".tsv": df.to_csv(path, sep="\t", index=False); return
    if ext in (".jsonl", ".ndjson"): df.to_json(path, orient="records", lines=True); return
    if ext in (".parquet", ".pq"): df.to_parquet(path, index=False); return
    if ext in (".feather", ".arrow"): df.reset_index(drop=True).to_feather(path); return
    if ext == ".avro":
        import fastavro
        records = df.to_dict(orient="records")
        # Auto-build a permissive schema.
        fields = [{"name": c, "type": ["null", "string", "long", "double", "boolean"]}
                  for c in df.columns]
        schema = {"type": "record", "name": "rows", "fields": fields}
        with path.open("wb") as f:
            fastavro.writer(f, schema, records)
        return
    if ext == ".orc":
        import pyarrow as pa
        import pyarrow.orc as orc
        orc.write_table(pa.Table.from_pandas(df), str(path))
        return
    if ext in (".h5", ".hdf5"):
        df.to_hdf(path, key="df", mode="w"); return
    raise ValueError(f"Unsupported dataframe extension: {ext}")


def op_convert(args: argparse.Namespace) -> int:
    try:
        import pandas as pd  # noqa: F401
    except ImportError as ex:
        return fail("missing_pandas", f"pandas not installed: {ex}")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Data file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = "." + args.format.lower().lstrip(".")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        in_ext = src.suffix.lower()
        out_path = out_dir / (src.stem + target)
        try:
            if in_ext in DATAFRAME_EXTS and target in DATAFRAME_EXTS:
                df = _read_dataframe(src)
                _write_dataframe(df, out_path)
            elif in_ext == ".npy" and target == ".npz":
                import numpy as np
                arr = np.load(src)
                np.savez(out_path, arr=arr)
            elif in_ext == ".npz" and target == ".npy":
                import numpy as np
                z = np.load(src)
                first = list(z.keys())[0]
                np.save(out_path, z[first])
            elif in_ext == ".npy" and target == ".csv":
                import numpy as np, pandas as pd
                arr = np.load(src)
                pd.DataFrame(arr).to_csv(out_path, index=False)
            elif in_ext == ".csv" and target == ".npy":
                import numpy as np, pandas as pd
                arr = pd.read_csv(src).to_numpy()
                np.save(out_path, arr)
            elif in_ext == ".mat" and target in (".csv", ".npz"):
                from scipy.io import loadmat
                import numpy as np
                bag = {k: v for k, v in loadmat(src).items() if not k.startswith("__")}
                if target == ".npz":
                    np.savez(out_path, **bag)
                else:
                    import pandas as pd
                    # take first 2D array as table.
                    for v in bag.values():
                        if hasattr(v, "ndim") and v.ndim == 2:
                            pd.DataFrame(v).to_csv(out_path, index=False); break
                    else:
                        return fail("no_2d_array",
                                    f"{src.name}: no 2D array found to flatten to CSV.")
            elif in_ext == ".fits" and target in (".csv", ".npz"):
                from astropy.io import fits
                import numpy as np
                with fits.open(src) as hdul:
                    if target == ".npz":
                        np.savez(out_path,
                                 **{f"hdu_{n}": (h.data if h.data is not None else np.array([]))
                                    for n, h in enumerate(hdul)})
                    else:
                        import pandas as pd
                        for h in hdul:
                            if h.data is not None and h.data.ndim == 2:
                                pd.DataFrame(h.data).to_csv(out_path, index=False); break
                        else:
                            return fail("no_table", f"{src.name}: no tabular HDU.")
            elif in_ext == ".nc" and target in (".csv", ".parquet"):
                import xarray as xr
                ds = xr.open_dataset(src)
                df = ds.to_dataframe().reset_index()
                _write_dataframe(df, out_path)
            else:
                return fail("unsupported_pair",
                            f"No converter from {in_ext} -> {target}.")
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("data_table",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format=target.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Data file not found: {src}")
    ext = src.suffix.lower()
    info = {"path": str(src), "ext": ext, "size_bytes": src.stat().st_size}
    try:
        if ext in DATAFRAME_EXTS:
            df = _read_dataframe(src)
            info.update(rows=int(df.shape[0]), cols=int(df.shape[1]),
                        columns=list(df.columns)[:64],
                        dtypes={c: str(df[c].dtype) for c in list(df.columns)[:64]})
        elif ext == ".npy":
            import numpy as np
            arr = np.load(src, mmap_mode="r")
            info.update(shape=list(arr.shape), dtype=str(arr.dtype))
        elif ext == ".npz":
            import numpy as np
            z = np.load(src)
            info.update(arrays={k: list(z[k].shape) for k in z.files})
        elif ext == ".mat":
            from scipy.io import whosmat
            info.update(arrays=[{"name": n, "shape": list(s), "dtype": str(t)}
                                for n, s, t in whosmat(src)])
        elif ext == ".fits":
            from astropy.io import fits
            with fits.open(src) as hdul:
                info["hdus"] = [{"name": h.name,
                                 "shape": list(h.data.shape) if h.data is not None else [],
                                 "dtype": str(h.data.dtype) if h.data is not None else "n/a"}
                                for h in hdul]
        elif ext == ".nc":
            import xarray as xr
            ds = xr.open_dataset(src)
            info["dims"] = dict(ds.dims)
            info["vars"] = list(ds.data_vars)
    except Exception as ex:
        return fail("info_failed", f"{src.name}: {ex}")

    emit("data_info", **info)
    emit("complete", output=str(src), size_bytes=info["size_bytes"], count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="datasci-sidecar",
                                description="Scientific/tabular data conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert between data formats.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="Target format: csv, tsv, jsonl, parquet, feather, "
                        "avro, orc, h5, npy, npz")
    info = sub.add_parser("info", help="Probe a data file.")
    info.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "info":    return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

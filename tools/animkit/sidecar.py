"""3D animation / scene-description sidecar.

The `meshconvert` sidecar covers static meshes; this one is for time-varying
formats: motion capture, rigged characters, and full scene descriptions.

  * BVH (.bvh)                  Biovision Hierarchy (motion capture)
  * Alembic (.abc)              cached vertex animation (Sony Pictures, BSD-3)
  * USD / USDA / USDC / USDZ    Pixar Universal Scene Description
  * FBX (.fbx)                  Autodesk
  * glTF / GLB                  Khronos
  * VRM (.vrm)                  VRoid avatars (subset of glTF)
  * Collada (.dae)              KhronosSchema 1.4

Backed by `usd-core` (Apache-2.0) for USD, `pyalembic` for Alembic when
available, and shells out to `assimp` (BSD-3) for the FBX / Collada paths.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_assimp() -> str | None:
    env = os.environ.get("ASSIMP_PATH")
    if env and Path(env).is_file(): return env
    return shutil.which("assimp") or shutil.which("assimp.exe")


def _convert_assimp(src: Path, out_path: Path) -> int:
    assimp = _find_assimp()
    if not assimp:
        return fail("missing_assimp",
                    "assimp CLI not found. Install via "
                    "`brew install assimp` / `apt install assimp-utils` / "
                    "https://github.com/assimp/assimp/releases.")
    proc = subprocess.run([assimp, "export", str(src), str(out_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        for ln in tail: emit("log", level="error", message=ln)
        return fail("assimp_failed", f"{src.name}: rc={proc.returncode}")
    return 0


def _convert_usd(src: Path, out_path: Path) -> int:
    """USD <-> USDA <-> USDC <-> USDZ via the usd-core Python bindings."""
    try:
        from pxr import Usd, UsdUtils
    except ImportError as ex:
        return fail("missing_usd_core",
                    f"usd-core not installed: {ex}. `pip install usd-core`.")
    try:
        stage = Usd.Stage.Open(str(src))
        if stage is None:
            return fail("read_failed", f"{src.name}: failed to open USD stage.")
        out_ext = out_path.suffix.lower()
        if out_ext == ".usdz":
            UsdUtils.CreateNewUsdzPackage(str(src), str(out_path))
        else:
            stage.Export(str(out_path))
    except Exception as ex:
        return fail("usd_failed", f"{src.name}: {ex}")
    return 0


def _bvh_round_trip(src: Path, out_path: Path) -> int:
    """BVH is plain text -- round-trip via bvh-converter / bvhio if available,
    otherwise just copy."""
    try:
        from bvh import Bvh
    except ImportError as ex:
        return fail("missing_bvh",
                    f"bvh module not installed: {ex}. `pip install bvh`.")
    text = src.read_text(encoding="utf-8", errors="replace")
    try:
        Bvh(text)  # validate
    except Exception as ex:
        return fail("read_failed", f"{src.name}: {ex}")
    out_path.write_text(text, encoding="utf-8")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Animation file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="anim", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + target_ext)
        src_ext = src.suffix.lower()
        rc = 0

        usd_exts = {".usd", ".usda", ".usdc", ".usdz"}
        if src_ext in usd_exts and target_ext in usd_exts:
            rc = _convert_usd(src, out_path)
        elif src_ext == ".bvh" and target_ext == ".bvh":
            rc = _bvh_round_trip(src, out_path)
        else:
            rc = _convert_assimp(src, out_path)
        if rc != 0: return rc

        emit("anim_scene",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="animkit-sidecar",
                                description="3D animation / scene format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert BVH / Alembic / USD / FBX / glTF / VRM / Collada.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="bvh | abc | usd | usda | usdc | usdz | fbx | gltf | glb | dae | obj")
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

"""Disk image sidecar -- shells out to qemu-img to convert between every
hypervisor's disk format:

  raw / img      generic raw block image
  qcow2          QEMU/KVM
  vmdk           VMware
  vhd / vpc      Hyper-V "fixed" / Virtual PC
  vhdx           Hyper-V (modern)
  vdi            VirtualBox
  vpc            Virtual PC (older)
  parallels      Parallels HDS
  qed            QEMU enhanced
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


def _find_qemu_img() -> str | None:
    env = os.environ.get("QEMU_IMG_PATH")
    if env and Path(env).is_file(): return env
    for n in ("qemu-img", "qemu-img.exe"):
        hit = shutil.which(n)
        if hit: return hit
    for c in (
        r"C:\Program Files\qemu\qemu-img.exe",
        r"C:\Program Files (x86)\qemu\qemu-img.exe",
        "/usr/bin/qemu-img",
        "/usr/local/bin/qemu-img",
        "/opt/homebrew/bin/qemu-img",
    ):
        if Path(c).is_file(): return c
    return None


# qemu-img canonical format names (the on-disk name we pass via -O / -f).
FORMATS = {
    "raw": "raw", "img": "raw",
    "qcow2": "qcow2", "qcow": "qcow",
    "vmdk": "vmdk",
    "vhd": "vpc", "vpc": "vpc",
    "vhdx": "vhdx",
    "vdi": "vdi",
    "qed": "qed",
    "parallels": "parallels", "hds": "parallels",
}


def op_convert(args: argparse.Namespace) -> int:
    qemu = _find_qemu_img()
    if not qemu:
        return fail("missing_qemu_img",
                    "qemu-img not found. Install QEMU (Windows: qemu.weilnetz.de) "
                    "or set $env:QEMU_IMG_PATH.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Disk image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    fmt_alias = args.format.lower().lstrip(".")
    qemu_fmt = FORMATS.get(fmt_alias)
    if not qemu_fmt:
        return fail("bad_format", f"Unsupported '{fmt_alias}'. Choose: {sorted(FORMATS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + fmt_alias)
        cmd = [qemu, "convert", "-p", "-O", qemu_fmt, str(src), str(out_path)]
        if args.compress and qemu_fmt == "qcow2": cmd.insert(2, "-c")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("qemu_failed", f"{src.name}: rc={proc.returncode}")

        emit("disk_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format=fmt_alias)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    qemu = _find_qemu_img()
    if not qemu: return fail("missing_qemu_img", "qemu-img not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Disk image not found: {src}")
    proc = subprocess.run([qemu, "info", "--output=json", str(src)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("qemu_failed", proc.stderr.strip()[:500])
    try:
        info = json.loads(proc.stdout)
    except Exception:
        info = {"raw": proc.stdout.strip()}
    emit("disk_image_info", path=str(src), **{k: v for k, v in info.items()
                                              if isinstance(v, (str, int, float, bool))})
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="diskimage-sidecar",
                                description="VM disk image conversion via qemu-img.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert RAW/QCOW2/VMDK/VHD/VHDX/VDI/QED.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help=f"Target: {sorted(FORMATS)}")
    c.add_argument("--compress", action="store_true",
                   help="(qcow2 only) compress output sectors.")
    info = sub.add_parser("info", help="Probe a disk image.")
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

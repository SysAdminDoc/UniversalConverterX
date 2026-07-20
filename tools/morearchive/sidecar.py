"""Long-tail archive / package extraction sidecar.

The `archive` sidecar handles 7z / ZIP / TAR / RAR / ISO via 7-Zip; this one
covers the extra-niche / platform-specific archive types that 7z doesn't
support out of the box (or handles awkwardly):

  * SIT / SITX        StuffIt (legacy Mac)             via unar
  * LHA / LZH         legacy Japanese / Amiga          via 7z + lzh extension
  * ARJ               legacy DOS archiver              via unar / 7z
  * ZOO / HA / ARC    deep legacy DOS                  via unar
  * DEB / IPK         Debian / OpenWrt packages        via stdlib + ar(1)
  * RPM               Red Hat / Fedora packages        via rpm2cpio shellout
  * DMG               macOS disk image                 via 7z (read-only)
  * IPA               iOS app bundle                   via stdlib zipfile
  * APK / XAPK / APKS Android app bundle               via stdlib zipfile
  * MSIX / APPX       Windows modern app package       via stdlib zipfile
  * NUPKG             NuGet package                    via stdlib zipfile

Most of these are extract-only (write-back to the original format is rarely
useful and often legally fraught). For DEB / RPM / IPA / APK / MSIX we
also probe metadata.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find(name: str, env: str | None = None) -> str | None:
    if env and (p := os.environ.get(env)) and Path(p).is_file():
        return p
    return shutil.which(name) or shutil.which(name + ".exe")


def _extract_zip_like(src: Path, dest: Path) -> int:
    """ZIP-family containers (APK / IPA / NUPKG / MSIX / XAPK)."""
    try:
        with zipfile.ZipFile(str(src)) as zf:
            zf.extractall(str(dest))
            for info in zf.infolist():
                emit("archive_extra_entry",
                     archive=str(src), path=info.filename,
                     size_bytes=info.file_size,
                     compressed_size=info.compress_size)
    except Exception as ex:
        return fail("zip_failed", f"{src.name}: {ex}")
    return 0


def _extract_with_unar(src: Path, dest: Path) -> int:
    unar = _find("unar")
    if not unar:
        return fail("missing_unar",
                    "`unar` not found. Install The Unarchiver "
                    "(`brew install unar`, `apt install unar`, "
                    "or http://theunarchiver.com/command-line).")
    proc = subprocess.run([unar, "-o", str(dest), "-D", str(src)],
                           capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        return fail("unar_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _extract_with_7z(src: Path, dest: Path) -> int:
    sz = _find("7z") or _find("7za")
    if not sz:
        return fail("missing_7zip", "`7z` not found on PATH.")
    proc = subprocess.run([sz, "x", "-y", f"-o{dest}", str(src)],
                           capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        return fail("7zip_failed", f"{src.name}: rc={proc.returncode}")
    return 0


def _extract_deb(src: Path, dest: Path) -> int:
    """DEB = ar archive containing data.tar.{gz,xz,zst}; use 7z which handles ar."""
    rc = _extract_with_7z(src, dest)
    if rc != 0: return rc
    # 7z drops `control.tar.gz` and `data.tar.<x>` -- unpack data.tar further.
    for inner in dest.glob("data.tar*"):
        sub = dest / "data"
        sub.mkdir(exist_ok=True)
        rc2 = _extract_with_7z(inner, sub)
        if rc2 != 0: return rc2
    return 0


def _extract_rpm(src: Path, dest: Path) -> int:
    """RPM extraction via rpm2cpio + cpio, or via 7z which has rpm support."""
    rc = _extract_with_7z(src, dest)
    if rc != 0: return rc
    # 7z gives us a `<name>.cpio` -- unpack it too.
    for cpio in dest.glob("*.cpio"):
        sub = dest / cpio.stem
        sub.mkdir(exist_ok=True)
        rc2 = _extract_with_7z(cpio, sub)
        if rc2 != 0: return rc2
    return 0


def op_extract(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Archive(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="extract", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower().lstrip(".")
        target = out_dir / src.stem
        target.mkdir(parents=True, exist_ok=True)
        rc = 0

        if ext in {"apk", "xapk", "apks", "ipa", "msix", "appx", "nupkg"}:
            rc = _extract_zip_like(src, target)
        elif ext == "deb" or ext == "ipk":
            rc = _extract_deb(src, target)
        elif ext == "rpm":
            rc = _extract_rpm(src, target)
        elif ext in {"sit", "sitx", "lha", "lzh", "arj", "zoo", "ha", "arc"}:
            rc = _extract_with_unar(src, target)
        elif ext in {"dmg"}:
            rc = _extract_with_7z(src, target)
        else:
            # Generic fallback: try 7z, then unar.
            rc = _extract_with_7z(src, target)
            if rc != 0:
                rc = _extract_with_unar(src, target)
        if rc != 0: return rc

        size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        emit("archive_extra",
             input=str(src), output=str(target),
             size_bytes=size, format=ext)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    """Probe APK / IPA / DEB / RPM / MSIX manifest metadata."""
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")
    ext = src.suffix.lower().lstrip(".")

    info: dict = {"path": str(src), "ext": ext, "size_bytes": src.stat().st_size}

    if ext in {"apk", "xapk", "apks"}:
        with zipfile.ZipFile(str(src)) as zf:
            info["entries"] = len(zf.infolist())
            try:
                info["has_manifest"] = "AndroidManifest.xml" in zf.namelist()
            except Exception:
                pass
    elif ext == "ipa":
        with zipfile.ZipFile(str(src)) as zf:
            info["entries"] = len(zf.infolist())
            info["has_info_plist"] = any(n.endswith("Info.plist") for n in zf.namelist())
    elif ext in {"msix", "appx", "nupkg"}:
        with zipfile.ZipFile(str(src)) as zf:
            info["entries"] = len(zf.infolist())
            info["has_manifest"] = any(n.lower().endswith("appxmanifest.xml")
                                        or n.lower().endswith(".nuspec")
                                        for n in zf.namelist())

    emit("archive_extra_info", **info)
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="morearchive-sidecar",
                                description="Long-tail archive / package extraction.")
    sub = p.add_subparsers(dest="op", required=True)
    e = sub.add_parser("extract", help="Extract SIT/LHA/ARJ/DEB/RPM/DMG/IPA/APK/MSIX/NUPKG.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    i = sub.add_parser("info", help="Probe APK / IPA / DEB / RPM / MSIX metadata.")
    i.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "extract": return op_extract(args)
        if args.op == "info":    return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

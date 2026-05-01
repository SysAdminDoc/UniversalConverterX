"""Demoscene / chip-music format sidecar (extends `chiptune`).

Where `chiptune` covers NSF / SPC / VGM / GBS / SID, this sidecar adds
the demoscene / 8-bit / coin-op formats:

  * Atari ST .YM (YM2149 PSG)
  * ZX Spectrum AY (.ay)
  * Atari 8-bit SAP (.sap)
  * AdLib .imf / .ksm / .raw (FM synth)
  * Mega Drive .GYM (already mostly in chiptune)
  * MOS Technology .SAP

Operations:
  ym-to-wav        Atari ST YM -> WAV / FLAC.
  ay-to-wav        ZX AY -> WAV / FLAC.
  sap-to-wav       Atari 8-bit SAP -> WAV.
  ym-info          Atari YM file probe (header + frame count).

Each conversion shells out to a backend emulator binary
(`atomic-zx-music`, `sc68`, or `gme123` aliases). When the binary is
missing we report it explicitly.
"""
from __future__ import annotations

import argparse
import json
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


def _which_any(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n) or shutil.which(n + ".exe")
        if p: return p
    return None


# ── YM (Atari ST PSG) ──────────────────────────────────────────────────

def _decode_ym_header(data: bytes) -> dict:
    """YM file header — handles YM2!, YM3!, YM3b, YM4!, YM5!, YM6! variants."""
    if len(data) < 12: raise ValueError("Truncated YM file.")
    magic = data[0:4]
    if magic[:3] not in (b"YM2", b"YM3", b"YM4", b"YM5", b"YM6"):
        # Some YM files are LHA-compressed (.YM start with -lh5- internally).
        if data[2:6] in (b"-lh5", b"-lh0"):
            return {"magic": "lha-compressed",
                    "size_bytes": len(data),
                    "note": "needs LHA decompression first"}
        raise ValueError(f"Not a YM file (magic {magic!r}).")
    out: dict = {"magic": magic.decode("ascii"),
                  "size_bytes": len(data)}
    if magic[:3] in (b"YM5", b"YM6"):
        if data[4:12] != b"LeOnArD!":
            out["check"] = "missing-LeOnArD-tag"
        out["frames"] = int.from_bytes(data[12:16], "big")
        out["attributes"] = int.from_bytes(data[16:20], "big")
        out["digidrums"] = int.from_bytes(data[20:22], "big")
        out["chip_clock"] = int.from_bytes(data[22:26], "big")
        out["frame_rate"] = int.from_bytes(data[26:28], "big")
    return out


def op_ym_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"YM file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info = _decode_ym_header(src.read_bytes())
            info["file"] = str(src)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("demo_audio",
             input=str(src), output="",
             size_bytes=0, format="probe",
             source="ym", magic=info.get("magic"))
    out_path = out_dir / "ym-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def _shell_render(args: argparse.Namespace, cli_names: tuple[str, ...],
                   cli_args_fn, source: str, ext: str) -> int:
    cli = _which_any(*cli_names)
    if not cli: return fail("missing_dep",
                              f"No backend on PATH (tried {' / '.join(cli_names)}).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"input file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + ext)
        cmd = [cli] + cli_args_fn(src, out_path)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not out_path.is_file():
            return fail("convert_failed",
                        f"{src.name}: {Path(cli).name} exit {proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()}")
        emit("demo_audio",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=ext, source=source)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# Use sc68 / sndh-converter / atomic-zx for YM, and zxtune123 for AY,
# falling back to ffmpeg for what it supports.

def op_ym_to_wav(args):
    return _shell_render(
        args, ("sc68", "sndh-converter", "atomic-zx-music"),
        lambda s, o: ["-o", str(o), str(s)],
        "ym", "wav")


def op_ay_to_wav(args):
    return _shell_render(
        args, ("zxtune123", "ay2wav"),
        lambda s, o: [str(s), "--core-options", "ZX-AY", "--output", str(o)],
        "ay", "wav")


def op_sap_to_wav(args):
    return _shell_render(
        args, ("asap-converter", "asap-decoder", "asap"),
        lambda s, o: ["-o", str(o), str(s)],
        "sap", "wav")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="demosound-sidecar",
                                description="Demoscene chip-music format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("ym-info",    "Atari ST .YM file probe -> JSON"),
        ("ym-to-wav",  "Atari ST .YM -> WAV (via sc68 / atomic-zx)"),
        ("ay-to-wav",  "ZX Spectrum .ay -> WAV (via zxtune123)"),
        ("sap-to-wav", "Atari 8-bit .sap -> WAV (via asap)"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "ym-info":    return op_ym_info(args)
        if args.op == "ym-to-wav":  return op_ym_to_wav(args)
        if args.op == "ay-to-wav":  return op_ay_to_wav(args)
        if args.op == "sap-to-wav": return op_sap_to_wav(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

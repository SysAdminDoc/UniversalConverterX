"""SVT-AV1-HDR tuning sidecar — wraps the SVT-AV1-HDR community build.

Exposes HDR-specific tuning modes (VQ, Film Grain, IQ, Custom) that the
mainline SVT-AV1 codec path in videocrush does not surface. This is a
parallel sidecar, not a replacement.

Binary: svtav1encapp.exe from Uranite HandBrake-SVT-AV1-HDR community
builds or FFmpeg-Builds. Drop it next to this sidecar or under tools/_bin/.
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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_binary() -> str | None:
    here = Path(__file__).resolve().parent
    for name in ("svtav1encapp", "svtav1encapp.exe", "SvtAv1EncApp", "SvtAv1EncApp.exe"):
        candidate = here / name
        if candidate.is_file():
            return str(candidate)
        bin_candidate = here.parent / "_bin" / name
        if bin_candidate.is_file():
            return str(bin_candidate)
    return shutil.which("svtav1encapp") or shutil.which("SvtAv1EncApp")


def _find_ffmpeg() -> str | None:
    here = Path(__file__).resolve().parent
    for name in ("ffmpeg", "ffmpeg.exe"):
        candidate = here / name
        if candidate.is_file():
            return str(candidate)
        bin_candidate = here.parent / "_bin" / name
        if bin_candidate.is_file():
            return str(bin_candidate)
    return shutil.which("ffmpeg")


TUNE_MODES = {
    "vq": {"tune": "0", "desc": "Visual Quality — detail retention over artifact prevention"},
    "film-grain": {"tune": "5", "desc": "Film Grain — grain preservation, temporal consistency"},
    "iq": {"tune": "3", "desc": "Image Quality — still-image / AVIF / lossless-capable"},
}


def op_encode(args: argparse.Namespace) -> int:
    svt = _find_binary()
    if not svt:
        return fail("missing_svtav1hdr", "svtav1encapp not found. Download from Uranite/HandBrake-SVT-AV1-HDR releases.")

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "ffmpeg is required for input decoding and output muxing.")

    if not os.path.isfile(args.input):
        return fail("input_not_found", f"Input file not found: {args.input}")

    svt_args = [svt, "-i", "stdin", "--irefresh-type", "2"]

    if args.tune_mode in TUNE_MODES:
        svt_args.extend(["--tune", TUNE_MODES[args.tune_mode]["tune"]])

    svt_args.extend(["--crf", str(args.crf)])
    svt_args.extend(["--preset", str(args.preset)])

    if args.cdef_scaling is not None:
        svt_args.extend(["--cdef-scaling", str(args.cdef_scaling)])

    if args.noise is not None:
        svt_args.extend(["--noise", str(args.noise)])

    if args.noise_chroma is not None:
        svt_args.extend(["--noise-chroma", str(args.noise_chroma)])

    if args.variance_boost_strength is not None:
        svt_args.extend(["--variance-boost-strength", str(args.variance_boost_strength)])

    if args.variance_octile is not None:
        svt_args.extend(["--variance-octile", str(args.variance_octile)])

    if args.variance_boost_curve is not None:
        svt_args.extend(["--variance-boost-curve", str(args.variance_boost_curve)])

    output = args.output or str(Path(args.input).with_suffix("").with_name(
        Path(args.input).stem + f"_svtav1hdr-{args.tune_mode}" + ".mkv"))

    svt_args.extend(["-b", "-"])

    decode_cmd = [ffmpeg, "-hide_banner", "-i", args.input,
                  "-f", "yuv4mpegpipe", "-strict", "-1", "-pix_fmt", "yuv420p10le", "-"]
    mux_cmd = [ffmpeg, "-hide_banner", "-y",
               "-i", "-",
               "-i", args.input,
               "-map", "0:v", "-map", "1:a?",
               "-c:v", "copy", "-c:a", "copy",
               output]

    emit("log", level="info", message=f"SVT-AV1-HDR encode: {args.tune_mode} mode, CRF {args.crf}")
    emit("progress", percent=0, stage="encoding")

    try:
        decode = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        encode = subprocess.Popen(svt_args, stdin=decode.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        if decode.stdout:
            decode.stdout.close()

        mux = subprocess.Popen(mux_cmd, stdin=encode.stdout, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
        if encode.stdout:
            encode.stdout.close()

        _, encode_err = encode.communicate()
        _, mux_err = mux.communicate()
        decode.wait()

        if encode.returncode != 0:
            err_text = (encode_err or b"").decode(errors="replace")[-500:]
            return fail("svtav1hdr_failed", f"SVT-AV1-HDR exited {encode.returncode}: {err_text}")

        if mux.returncode != 0:
            err_text = (mux_err or b"").decode(errors="replace")[-500:]
            return fail("mux_failed", f"FFmpeg mux exited {mux.returncode}: {err_text}")

        size = os.path.getsize(output) if os.path.isfile(output) else 0
        emit("progress", percent=100, stage="done")
        emit("complete", output=output, size=size, tune=args.tune_mode, crf=args.crf)
        return 0

    except FileNotFoundError as e:
        return fail("binary_not_found", str(e))


ISO_NOISE_MAP = {
    100: 8, 200: 15, 400: 25, 800: 40, 1600: 55,
    3200: 70, 6400: 85,
}


def op_grain_table(args: argparse.Namespace) -> int:
    """Generate a photon noise grain table calibrated to a camera ISO value.

    The table maps ISO sensitivity to a noise strength that produces
    realistic film grain when injected via --grain-table. Output is a
    .tbl file compatible with SVT-AV1-HDR's --grain-table flag.
    """
    iso = args.iso
    noise = ISO_NOISE_MAP.get(iso)
    if noise is None:
        isos = sorted(ISO_NOISE_MAP.keys())
        lower = max((i for i in isos if i <= iso), default=isos[0])
        upper = min((i for i in isos if i >= iso), default=isos[-1])
        if lower == upper:
            noise = ISO_NOISE_MAP[lower]
        else:
            ratio = (iso - lower) / (upper - lower)
            noise = int(ISO_NOISE_MAP[lower] + ratio * (ISO_NOISE_MAP[upper] - ISO_NOISE_MAP[lower]))

    chroma_noise = noise if args.chroma_grain else 0
    transfer = args.transfer or "bt1886"

    output = args.output or f"grain_iso{iso}_{transfer}.tbl"

    lines = [
        f"# Photon noise table — ISO {iso}, transfer {transfer}",
        f"# Generated by UCX svtav1-hdr grain-table",
        f"# Luma noise: {noise}, Chroma noise: {chroma_noise}",
        f"E 0 {noise} {chroma_noise} 0 0",
    ]

    try:
        Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        return fail("write_failed", f"Could not write grain table: {e}")

    emit("log", level="info",
         message=f"Grain table for ISO {iso}: luma={noise}, chroma={chroma_noise}, transfer={transfer}")
    emit("complete", output=output, iso=iso, noise=noise,
         chroma_noise=chroma_noise, transfer=transfer)
    return 0


def op_presets(args: argparse.Namespace) -> int:
    for key, info in TUNE_MODES.items():
        emit("log", level="info", message=f"  {key}: {info['desc']}")
    emit("complete", presets=list(TUNE_MODES.keys()))
    return 0


def op_probe(args: argparse.Namespace) -> int:
    svt = _find_binary()
    ffmpeg = _find_ffmpeg()
    emit("complete",
         svtav1hdr_available=svt is not None,
         svtav1hdr_path=svt,
         ffmpeg_available=ffmpeg is not None,
         ffmpeg_path=ffmpeg,
         tune_modes=list(TUNE_MODES.keys()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="svtav1-hdr", description="SVT-AV1-HDR tuning sidecar")
    sub = p.add_subparsers(dest="op", required=True)

    enc = sub.add_parser("encode", help="Encode with SVT-AV1-HDR tuning")
    enc.add_argument("--input", required=True, help="Input video path")
    enc.add_argument("--output", help="Output path (default: input_svtav1hdr-<mode>.mkv)")
    enc.add_argument("--tune-mode", choices=["vq", "film-grain", "iq", "custom"], default="vq",
                     help="Tuning mode: vq (detail), film-grain, iq (still), custom")
    enc.add_argument("--crf", type=int, default=30, help="CRF quality target (0-63)")
    enc.add_argument("--preset", type=int, default=6, help="Encoder speed preset (0=slow, 13=fast)")
    enc.add_argument("--cdef-scaling", type=int, help="CDEF filter strength (1-30, default ~12)")
    enc.add_argument("--noise", type=int, help="Film grain noise strength (0-200)")
    enc.add_argument("--noise-chroma", type=int, help="Chroma noise strength (-1 to 200)")
    enc.add_argument("--variance-boost-strength", type=int, help="Adaptive AQ control (1-4)")
    enc.add_argument("--variance-octile", type=int, help="Superblock boost selectivity (1-8)")
    enc.add_argument("--variance-boost-curve", type=int, help="PQ-optimized boost curve (0-3)")

    gt = sub.add_parser("grain-table", help="Generate photon noise grain table")
    gt.add_argument("--iso", type=int, default=800, help="Camera ISO setting (100-6400)")
    gt.add_argument("--chroma-grain", action="store_true", help="Include chroma noise")
    gt.add_argument("--transfer", default="bt1886",
                    help="Transfer function: bt1886, pq, hlg (default: bt1886)")
    gt.add_argument("--output", help="Output .tbl path (default: grain_iso<N>_<transfer>.tbl)")

    sub.add_parser("presets", help="List available tuning modes")
    sub.add_parser("probe", help="Check binary availability")

    return p


def main(argv: list[str] | None = None) -> int:
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()

    args = build_parser().parse_args(argv)
    dispatch = {"encode": op_encode, "grain-table": op_grain_table,
                "presets": op_presets, "probe": op_probe}
    try:
        return dispatch[args.op](args)
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

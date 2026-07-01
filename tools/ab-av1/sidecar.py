"""ab-av1 sidecar — VMAF / XPSNR-guided CRF auto-search wrapper.

ROADMAP Item 67. Wraps the `ab-av1` Rust CLI which binary-searches over CRF
values to land on a user-specified VMAF (or XPSNR) target with the smallest
output file. Supports SVT-AV1, x265, and x264 encoders.

Subcommands:
  auto-encode   Search for a CRF that hits target VMAF, then encode.
  crf-search    Search-only mode: report the recommended CRF without encoding.
  sample-encode Encode a single sample at a given CRF + report VMAF.
  probe         Report whether ab-av1 is on PATH and its version.

Standard NDJSON contract: progress / log / complete / error events on stdout.
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


# ── NDJSON helpers ───────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


# ── ab-av1 discovery ─────────────────────────────────────────────────────────

def _find_ab_av1() -> str | None:
    """PATH-first lookup with fallbacks to a bundled binary next to this
    sidecar or under tools/_bin/."""
    candidates: list[str | None] = [
        os.environ.get("AB_AV1_PATH"),
        shutil.which("ab-av1"),
    ]
    here = Path(__file__).resolve().parent
    candidates += [
        str(here / "ab-av1.exe"),
        str(here / "ab-av1"),
        str(here.parent / "_bin" / "ab-av1.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


# ── Output parsing ───────────────────────────────────────────────────────────

# ab-av1 progress lines look like: "[INFO] crf 24 vmaf 95.6, encoded 5/12 samples (42%)"
_PROGRESS_RE = re.compile(
    r"crf\s+(?P<crf>\d+(?:\.\d+)?).*?vmaf\s+(?P<vmaf>\d+(?:\.\d+)?)",
    re.IGNORECASE)
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
_RECOMMEND_RE = re.compile(
    r"crf\s+(?P<crf>\d+(?:\.\d+)?)\s+(?:.*\s)?vmaf\s+(?P<vmaf>\d+(?:\.\d+)?)",
    re.IGNORECASE)


def _stream(cmd: list[str], stage: str) -> tuple[int, str]:
    """Invoke ab-av1, surface progress, and capture the full stderr+stdout
    transcript so the caller can parse the recommended CRF on completion."""
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    transcript: list[str] = []
    last_pct = -1
    last_crf = None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            transcript.append(line)
            pct_m = _PERCENT_RE.search(line)
            crf_m = _PROGRESS_RE.search(line)
            if crf_m:
                last_crf = float(crf_m.group("crf"))
                emit("progress",
                     percent=int(pct_m.group(1)) if pct_m else last_pct if last_pct >= 0 else 0,
                     stage=stage,
                     crf=last_crf,
                     vmaf=float(crf_m.group("vmaf")),
                     eta_seconds=None)
                continue
            if pct_m:
                pct = int(pct_m.group(1))
                if pct - last_pct >= 1 and 0 <= pct <= 100:
                    last_pct = pct
                    emit("progress", percent=pct, stage=stage, eta_seconds=None)
                    continue
            log("info", line)
    finally:
        proc.wait()
    return proc.returncode, "\n".join(transcript)


# ── Ops ──────────────────────────────────────────────────────────────────────

_ENCODER_ALIASES = {
    "av1": "libsvtav1", "svtav1": "libsvtav1", "libsvtav1": "libsvtav1",
    "h265": "libx265", "hevc": "libx265", "libx265": "libx265", "x265": "libx265",
    "h264": "libx264", "libx264": "libx264", "x264": "libx264",
}


def _canonical_encoder(raw: str | None) -> str:
    if not raw: return "libsvtav1"
    return _ENCODER_ALIASES.get(raw.lower(), raw)


def op_auto_encode(args: argparse.Namespace) -> int:
    binary = _find_ab_av1()
    if not binary:
        return fail("missing_ab_av1",
                    "ab-av1 is not installed. Drop ab-av1.exe next to this "
                    "sidecar or download it from github.com/alexheretic/ab-av1.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    encoder = _canonical_encoder(args.encoder)
    target_vmaf = max(50.0, min(100.0, float(args.target_vmaf)))
    cmd = [binary, "auto-encode",
           "--input", str(src),
           "--output", str(out_path),
           "--encoder", encoder,
           "--min-vmaf", str(target_vmaf)]
    if args.preset is not None:
        cmd += ["--preset", str(args.preset)]
    if args.samples is not None:
        cmd += ["--samples", str(args.samples)]
    if args.min_crf is not None:
        cmd += ["--min-crf", str(args.min_crf)]
    if args.max_crf is not None:
        cmd += ["--max-crf", str(args.max_crf)]
    if args.xpsnr:
        # ab-av1 v0.10+ accepts --xpsnr; older builds will reject it cleanly.
        cmd += ["--xpsnr"]

    log("info", f"auto-encode encoder={encoder} target-vmaf={target_vmaf} -> {out_path.name}")
    emit("progress", percent=0, stage="ab-av1 search", eta_seconds=None)
    rc, transcript = _stream(cmd, "ab-av1 search")
    if rc != 0:
        for ln in transcript.splitlines()[-15:]:
            log("error", ln)
        return fail("ab_av1_failed", f"ab-av1 exited {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")

    # Best-effort: surface the final recommended CRF + VMAF from the transcript.
    final = None
    for ln in reversed(transcript.splitlines()):
        m = _RECOMMEND_RE.search(ln)
        if m:
            final = (float(m.group("crf")), float(m.group("vmaf")))
            break

    payload = {"output": str(out_path), "size_bytes": out_path.stat().st_size,
               "encoder": encoder, "target_vmaf": target_vmaf}
    if final is not None:
        payload["final_crf"] = final[0]
        payload["final_vmaf"] = final[1]
    emit("complete", **payload)
    return 0


def op_crf_search(args: argparse.Namespace) -> int:
    """Search-only mode — emit the recommended CRF without producing the
    final encode. Useful when the user wants to plug the result into a
    different preset XML or capture into a profile."""
    binary = _find_ab_av1()
    if not binary:
        return fail("missing_ab_av1", "ab-av1 is not installed.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    encoder = _canonical_encoder(args.encoder)
    target_vmaf = max(50.0, min(100.0, float(args.target_vmaf)))
    cmd = [binary, "crf-search",
           "--input", str(src),
           "--encoder", encoder,
           "--min-vmaf", str(target_vmaf)]
    if args.samples is not None:
        cmd += ["--samples", str(args.samples)]
    if args.min_crf is not None:
        cmd += ["--min-crf", str(args.min_crf)]
    if args.max_crf is not None:
        cmd += ["--max-crf", str(args.max_crf)]
    if args.xpsnr:
        cmd += ["--xpsnr"]

    log("info", f"crf-search encoder={encoder} target-vmaf={target_vmaf}")
    emit("progress", percent=0, stage="ab-av1 search", eta_seconds=None)
    rc, transcript = _stream(cmd, "ab-av1 search")
    if rc != 0:
        for ln in transcript.splitlines()[-15:]:
            log("error", ln)
        return fail("ab_av1_failed", f"ab-av1 exited {rc}")

    final = None
    for ln in reversed(transcript.splitlines()):
        m = _RECOMMEND_RE.search(ln)
        if m:
            final = (float(m.group("crf")), float(m.group("vmaf")))
            break
    if final is None:
        log("warn", "Could not parse recommended CRF from ab-av1 transcript.")
        emit("complete", output="", size_bytes=0,
             encoder=encoder, target_vmaf=target_vmaf,
             final_crf=None, final_vmaf=None)
        return 0
    log("info", f"Recommended CRF {final[0]} (predicted VMAF {final[1]}).")
    emit("complete", output="", size_bytes=0,
         encoder=encoder, target_vmaf=target_vmaf,
         final_crf=final[0], final_vmaf=final[1])
    return 0


def op_sample_encode(args: argparse.Namespace) -> int:
    """Encode a single sample at an explicit CRF and report VMAF — useful
    for verifying a target before committing to the full encode."""
    binary = _find_ab_av1()
    if not binary:
        return fail("missing_ab_av1", "ab-av1 is not installed.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    encoder = _canonical_encoder(args.encoder)
    cmd = [binary, "sample-encode",
           "--input", str(src),
           "--encoder", encoder,
           "--crf", str(args.crf)]
    if args.samples is not None:
        cmd += ["--samples", str(args.samples)]
    log("info", f"sample-encode encoder={encoder} crf={args.crf}")
    emit("progress", percent=0, stage="ab-av1 sample", eta_seconds=None)
    rc, transcript = _stream(cmd, "ab-av1 sample")
    if rc != 0:
        for ln in transcript.splitlines()[-15:]:
            log("error", ln)
        return fail("ab_av1_failed", f"ab-av1 exited {rc}")
    final_vmaf = None
    for ln in reversed(transcript.splitlines()):
        m = re.search(r"vmaf\s+(\d+(?:\.\d+)?)", ln, re.IGNORECASE)
        if m:
            final_vmaf = float(m.group(1))
            break
    emit("complete", output="", size_bytes=0,
         encoder=encoder, crf=float(args.crf), final_vmaf=final_vmaf)
    return 0


def op_probe(_args: argparse.Namespace) -> int:
    binary = _find_ab_av1()
    if not binary:
        log("warn", "ab-av1 is not on PATH and not bundled.")
        emit("complete", output="", size_bytes=0,
             ab_av1_path=None, ab_av1_version=None)
        return 0
    try:
        result = subprocess.run([binary, "--version"],
                                capture_output=True, text=True, timeout=15)
        version = (result.stdout or result.stderr or "").strip()
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"
    log("info", f"ab-av1 at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         ab_av1_path=binary, ab_av1_version=version)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ab-av1-sidecar",
                                description="VMAF/XPSNR-guided CRF auto-search wrapper around ab-av1.")
    sub = p.add_subparsers(dest="op", required=True)

    ae = sub.add_parser("auto-encode",
                        help="Search for a CRF that hits the target VMAF, then encode.")
    ae.add_argument("--input", required=True)
    ae.add_argument("--output", required=True)
    ae.add_argument("--encoder", default="libsvtav1",
                    help="Encoder: libsvtav1 (default) / libx265 / libx264. "
                         "Aliases av1/h265/hevc/h264 accepted.")
    ae.add_argument("--target-vmaf", type=float, default=93.0, dest="target_vmaf",
                    help="Target VMAF score 50..100 (default 93).")
    ae.add_argument("--preset", default=None,
                    help="Encoder preset (e.g. SVT-AV1 0..13). Forwarded as-is.")
    ae.add_argument("--samples", type=int, default=None,
                    help="Number of sample encodes during the search (default ab-av1 chooses).")
    ae.add_argument("--min-crf", type=float, default=None, dest="min_crf")
    ae.add_argument("--max-crf", type=float, default=None, dest="max_crf")
    ae.add_argument("--xpsnr", action="store_true",
                    help="Use XPSNR instead of VMAF for the search (faster, ab-av1 v0.10+).")

    cs = sub.add_parser("crf-search",
                        help="Search-only mode: emit the recommended CRF without encoding.")
    cs.add_argument("--input", required=True)
    cs.add_argument("--encoder", default="libsvtav1")
    cs.add_argument("--target-vmaf", type=float, default=93.0, dest="target_vmaf")
    cs.add_argument("--samples", type=int, default=None)
    cs.add_argument("--min-crf", type=float, default=None, dest="min_crf")
    cs.add_argument("--max-crf", type=float, default=None, dest="max_crf")
    cs.add_argument("--xpsnr", action="store_true")

    se = sub.add_parser("sample-encode",
                        help="Encode a single sample at an explicit CRF and report VMAF.")
    se.add_argument("--input", required=True)
    se.add_argument("--encoder", default="libsvtav1")
    se.add_argument("--crf", type=float, required=True)
    se.add_argument("--samples", type=int, default=None)

    sub.add_parser("probe", help="Report whether ab-av1 is installed and its version.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "auto-encode":   return op_auto_encode(args)
        if args.op == "crf-search":    return op_crf_search(args)
        if args.op == "sample-encode": return op_sample_encode(args)
        if args.op == "probe":         return op_probe(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

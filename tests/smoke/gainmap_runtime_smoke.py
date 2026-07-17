"""Headless end-to-end smoke using a runtime synthesized gain-map fixture."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "gainmap" / "sidecar.py"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(command: list[str], env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=600, env=env,
        creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vips", required=True)
    parser.add_argument("--avifgainmaputil", required=True)
    args = parser.parse_args()
    env = dict(os.environ)
    env["UCX_VIPS_PATH"] = str(Path(args.vips).resolve())
    env["UCX_AVIFGAINMAPUTIL_PATH"] = str(Path(args.avifgainmaputil).resolve())
    with tempfile.TemporaryDirectory(prefix="ucx-gainmap-smoke-") as temp:
        root = Path(temp)
        base, alternate, output = root / "base.png", root / "alternate.png", root / "fixture.avif"
        coords, red, green, blue = (root / name for name in ("coords.v", "red.v", "green.v", "blue.v"))
        base_float, alternate_float = root / "base.v", root / "alternate.v"
        run([args.vips, "xyz", str(coords), "256", "128"])
        run([args.vips, "extract_band", str(coords), str(red), "0"])
        run([args.vips, "linear", str(red), str(green), "0", "127"])
        run([args.vips, "linear", str(red), str(blue), "0", "63"])
        inputs = " ".join(path.as_posix() for path in (red, green, blue))
        run([args.vips, "bandjoin", inputs, str(base_float)])
        run([args.vips, "cast", str(base_float), str(base), "uchar"])
        run([args.vips, "linear", str(base), str(alternate_float),
             "1.35 1.1 1.5", "20 16 24"])
        run([args.vips, "cast", str(alternate_float), str(alternate), "uchar"])
        protocol = run([
            sys.executable, str(SIDECAR), "create-avif",
            "--base", str(base), "--alternate", str(alternate),
            "--output", str(output), "--gainmap-quality", "100"], env)
        complete = json.loads(protocol.splitlines()[-1])
        if complete.get("event") != "complete" or not complete.get("metadata", {}).get("gainMap"):
            raise RuntimeError(protocol)
        print(json.dumps({"outputBytes": output.stat().st_size, **complete["metadata"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

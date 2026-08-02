"""AlphaCut output-format resolution coverage (ROADMAP Item 49).

Regression guard for the bug where the sidecar validated the UI's short
format tags (webm / mp4 / png_sequence / mov) against AlphaCut's display-name
keys, silently downgrading every video export to the first format.

The full export run needs PyQt6 + rembg + AlphaCut *and* an already-installed
human-seg model. Automatic model downloads are deliberately disabled — packs
install only through the consent-gated, digest-pinned action — so this test
skips rather than reaching for the network when the pack is absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "alphacut" / "sidecar.py"


def _deps_available() -> bool:
    try:
        import PyQt6  # noqa: F401
        import rembg  # noqa: F401
        sys.path.insert(0, str(ROOT / "tools" / "alphacut"))
        import AlphaCut  # noqa: F401
        return bool(getattr(AlphaCut, "OUTPUT_FORMATS", {}))
    except Exception:
        return False


def _ffmpeg() -> str | None:
    import shutil
    return shutil.which("ffmpeg")


def _model_installed(model_key: str) -> bool:
    """True when the pinned pack for ``model_key`` is already on disk.

    Mirrors ``AlphaCutEngine._ensure_model``: a pack counts as installed only
    when the weights file exists and is large enough to be real. Anything else
    would require the consent-gated download, which a test must never trigger.
    """
    try:
        sys.path.insert(0, str(ROOT / "tools" / "alphacut"))
        import AlphaCut

        config = AlphaCut.MODELS[model_key]
        path = Path(AlphaCut.MODELS_DIR) / config["file"]
        return path.is_file() and path.stat().st_size > 1_000_000
    except Exception:
        return False


def _events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines()
            if line.strip().startswith("{")]


class AlphaCutFormatTests(unittest.TestCase):
    def test_format_codes_include_ui_targets(self) -> None:
        if not _deps_available():
            self.skipTest("PyQt6/rembg/AlphaCut not available")
        sys.path.insert(0, str(ROOT / "tools" / "alphacut"))
        import AlphaCut
        codes = set(AlphaCut.OUTPUT_FORMATS.values())
        # The sidecar maps the UI tags onto these codes; all must exist.
        for code in ("mp4", "webm", "png_seq", "prores"):
            self.assertIn(code, codes)

    def test_webm_and_png_sequence_export(self) -> None:
        ffmpeg = _ffmpeg()
        if not ffmpeg or not _deps_available():
            self.skipTest("FFmpeg/PyQt6/rembg/AlphaCut not available")
        if not _model_installed("u2net_human_seg"):
            self.skipTest(
                "u2net_human_seg pack is not installed; automatic model "
                "downloads are disabled by design")
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            clip = Path(temp) / "subj.mp4"
            gen = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1:r=6",
                 "-filter_complex", "drawbox=x=50:y=30:w=60:h=60:color=pink@1.0:t=fill",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                capture_output=True, text=True, timeout=60)
            if gen.returncode != 0:
                self.skipTest("FFmpeg could not synthesise a test clip")

            webm = Path(temp) / "out.webm"
            run = subprocess.run(
                [sys.executable, str(SIDECAR), "--input", str(clip),
                 "--output", str(webm), "--format", "webm",
                 "--model", "u2net_human_seg"],
                capture_output=True, text=True, timeout=300)
            events = _events(run.stdout)
            self.assertTrue(any(e.get("event") == "complete" for e in events),
                            msg=run.stdout + run.stderr)
            self.assertTrue(webm.is_file() and webm.stat().st_size > 0)

            seq = Path(temp) / "frames"
            run = subprocess.run(
                [sys.executable, str(SIDECAR), "--input", str(clip),
                 "--output", str(seq), "--format", "png_sequence",
                 "--model", "u2net_human_seg"],
                capture_output=True, text=True, timeout=300)
            events = _events(run.stdout)
            complete = next((e for e in events if e.get("event") == "complete"), None)
            self.assertIsNotNone(complete, msg=run.stdout + run.stderr)
            self.assertGreaterEqual(complete.get("count", 0), 1)


if __name__ == "__main__":
    unittest.main()

"""VIDEO_TS ripping coverage for the dvdrip sidecar."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "dvdrip" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("dvdrip", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _events(func, args) -> tuple[int, list[dict]]:
    parsed = SIDECAR.build_parser().parse_args(args)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = func(parsed)
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return code, events


def _make_video_ts(root: Path) -> bool:
    ffmpeg = SIDECAR.find_ffmpeg(SIDECAR_PATH.parent)
    if not ffmpeg:
        return False
    video_ts = root / "VIDEO_TS"
    video_ts.mkdir(parents=True, exist_ok=True)
    specs = [
        ("VTS_01_1.VOB", 2, 300),
        ("VTS_01_2.VOB", 2, 500),
        ("VTS_02_1.VOB", 3, 700),
    ]
    for name, dur, freq in specs:
        result = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"testsrc=duration={dur}:size=352x288:rate=25",
             "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}",
             "-target", "ntsc-dvd", "-aspect", "4:3", str(video_ts / name)],
            capture_output=True, text=True, timeout=90)
        if result.returncode != 0 or not (video_ts / name).is_file():
            return False
    return True


class DvdRipTests(unittest.TestCase):
    def test_resolve_and_enumerate_skips_menu_vob(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            video_ts = Path(temp) / "VIDEO_TS"
            video_ts.mkdir()
            for name in ("VTS_01_0.VOB", "VTS_01_1.VOB", "VTS_01_2.VOB", "VTS_02_1.VOB"):
                (video_ts / name).write_bytes(b"\x00")
            # Accept the parent folder too.
            self.assertEqual(SIDECAR.resolve_video_ts(temp), video_ts)
            titles = SIDECAR.enumerate_titles(video_ts)
            self.assertEqual(sorted(titles), [1, 2])
            # Menu part 0 excluded; only content parts remain, in order.
            self.assertEqual([p.name for p in titles[1]], ["VTS_01_1.VOB", "VTS_01_2.VOB"])

    def test_missing_input_fails(self) -> None:
        code, events = _events(SIDECAR.op_probe,
                               ["probe", "--input", "/no/such/video_ts"])
        self.assertEqual(1, code)
        self.assertEqual("missing_input", events[-1]["code"])

    def test_probe_and_rip_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            if not _make_video_ts(Path(temp)):
                self.skipTest("FFmpeg cannot synthesise a DVD VIDEO_TS here")

            code, events = _events(SIDECAR.op_probe, ["probe", "--input", temp])
            self.assertEqual(0, code, events)
            titles = {e["index"]: e for e in events if e["event"] == "title"}
            self.assertEqual(sorted(titles), [1, 2])
            self.assertTrue(titles[1]["readable"])
            self.assertEqual(titles[1]["parts"], 2)
            self.assertGreater(titles[1]["duration_seconds"], 3.5)  # 2 + 2 seconds

            output = Path(temp) / "title1.mp4"
            code, events = _events(
                SIDECAR.op_rip,
                ["rip", "--input", temp, "--title", "1",
                 "--output", str(output), "--mode", "h264"])
            self.assertEqual(0, code, events)
            self.assertTrue(output.is_file())
            self.assertEqual("complete", events[-1]["event"])

            ffprobe = SIDECAR.find_ffprobe(SIDECAR_PATH.parent)
            dur = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(output)],
                capture_output=True, text=True, timeout=30).stdout.strip()
            self.assertGreater(float(dur), 3.5)


if __name__ == "__main__":
    unittest.main()

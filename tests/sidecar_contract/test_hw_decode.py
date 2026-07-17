"""Hardware-accelerated decode helper coverage (ROADMAP Item 98).

Verifies the shared tools/_lib/hw_decode.py NVDEC path: it decodes every frame,
matches OpenCV's frame count, honours the UCX_HWDECODE kill switch, and reports
a sane backend label. NVDEC-specific assertions run only when a CUDA device is
present; everything else exercises the software fallback so the suite passes on
CPU-only machines.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "tools" / "_lib"


def _load_hw_decode():
    spec = importlib.util.spec_from_file_location("hw_decode", LIB / "hw_decode.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ffmpeg() -> str | None:
    import shutil
    return shutil.which("ffmpeg")


def _make_clip(path: Path, ffmpeg: str, *, seconds: int = 2) -> bool:
    proc = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, text=True, timeout=60)
    return proc.returncode == 0 and path.is_file()


class HwDecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hw = _load_hw_decode()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("UCX_HWDECODE", None)
        self.hw._cuda_probe = None

    def test_backend_label_is_known(self) -> None:
        self.assertIn(self.hw.decode_backend(), ("nvdec", "pyav-software", "opencv"))

    def test_kill_switch_forces_software(self) -> None:
        if not self.hw.pyav_available():
            self.skipTest("PyAV not installed")
        os.environ["UCX_HWDECODE"] = "0"
        self.hw._cuda_probe = None
        self.assertFalse(self.hw.cuda_decode_available())
        self.assertEqual(self.hw.decode_backend(), "pyav-software")

    def test_decodes_all_frames(self) -> None:
        if not self.hw.pyav_available():
            self.skipTest("PyAV not installed")
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg not available")
        clip = self.dir / "clip.mp4"
        if not _make_clip(clip, ffmpeg, seconds=2):
            self.skipTest("could not synthesise clip")
        frames = list(self.hw.iter_frames(clip, pix_fmt="bgr24"))
        self.assertEqual(len(frames), 30)  # 15 fps * 2s
        idx, arr = frames[0]
        self.assertEqual(idx, 0)
        self.assertEqual(arr.shape, (240, 320, 3))

    def test_frames_or_opencv_matches(self) -> None:
        import cv2  # noqa: PLC0415
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg not available")
        clip = self.dir / "clip.mp4"
        if not _make_clip(clip, ffmpeg, seconds=2):
            self.skipTest("could not synthesise clip")

        # The convenience wrapper must yield the same frame count as a bare
        # OpenCV read loop, whichever decode backend it selects.
        wrapped = list(self.hw.frames_or_opencv(clip, cv2))
        cap = cv2.VideoCapture(str(clip))
        cv_count = 0
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            cv_count += 1
        cap.release()
        self.assertEqual(len(wrapped), cv_count)
        self.assertEqual(wrapped[0][0], 0)
        self.assertEqual(wrapped[0][1].shape, (240, 320, 3))

    def test_producer_opt_out_forces_opencv(self) -> None:
        import cv2  # noqa: PLC0415
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg not available")
        clip = self.dir / "clip.mp4"
        if not _make_clip(clip, ffmpeg, seconds=1):
            self.skipTest("could not synthesise clip")

        with (
            mock.patch.object(self.hw, "cuda_decode_available", return_value=True),
            mock.patch.object(
                self.hw,
                "iter_frames",
                side_effect=AssertionError("hardware decode must remain opt-in"),
            ),
        ):
            frames = list(self.hw.frames_or_opencv(clip, cv2, allow_hw=False))

        self.assertEqual(len(frames), 15)
        self.assertEqual(self.hw.frames_backend(allow_hw=False), "opencv")

    def test_partial_hardware_failure_resumes_without_duplicates(self) -> None:
        import numpy as np  # noqa: PLC0415

        class FakeCapture:
            def __init__(self, _path):
                self._frames = iter([
                    np.full((1, 1, 3), 10, dtype=np.uint8),
                    np.full((1, 1, 3), 20, dtype=np.uint8),
                    np.full((1, 1, 3), 30, dtype=np.uint8),
                ])

            def isOpened(self):
                return True

            def read(self):
                try:
                    return True, next(self._frames)
                except StopIteration:
                    return False, None

            def release(self):
                return None

        class FakeCv2:
            VideoCapture = FakeCapture

        def partial_decode(*_args, **_kwargs):
            yield 0, np.full((1, 1, 3), 1, dtype=np.uint8)
            raise RuntimeError("simulated mid-stream NVDEC failure")

        with (
            mock.patch.object(self.hw, "cuda_decode_available", return_value=True),
            mock.patch.object(self.hw, "iter_frames", side_effect=partial_decode),
        ):
            frames = list(self.hw.frames_or_opencv("ignored.mp4", FakeCv2()))

        self.assertEqual([index for index, _ in frames], [0, 1, 2])
        self.assertEqual([int(frame[0, 0, 0]) for _, frame in frames], [1, 20, 30])

    def test_hw_and_sw_agree_on_count(self) -> None:
        if not self.hw.pyav_available():
            self.skipTest("PyAV not installed")
        ffmpeg = _ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg not available")
        clip = self.dir / "clip.mp4"
        if not _make_clip(clip, ffmpeg, seconds=2):
            self.skipTest("could not synthesise clip")

        # Software (kill switch on)
        os.environ["UCX_HWDECODE"] = "0"
        self.hw._cuda_probe = None
        sw = list(self.hw.iter_frames(clip, pix_fmt="bgr24"))

        # Whatever hardware is available (kill switch off)
        os.environ.pop("UCX_HWDECODE", None)
        self.hw._cuda_probe = None
        hw = list(self.hw.iter_frames(clip, pix_fmt="bgr24"))

        self.assertEqual(len(sw), len(hw))


if __name__ == "__main__":
    unittest.main()

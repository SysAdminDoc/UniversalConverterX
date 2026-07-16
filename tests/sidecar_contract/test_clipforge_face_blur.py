"""Offline face-blur privacy filter coverage for ClipForge."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "clipforge" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("clipforge_face_blur", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


class _Detector:
    def __init__(self, boxes) -> None:
        self.boxes = boxes

    def detectMultiScale(self, *_args, **_kwargs):
        return self.boxes


class ClipForgeFaceBlurTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import cv2  # type: ignore  # noqa: F401
            import numpy  # type: ignore  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("OpenCV face-blur dependencies are not installed")
        if not SIDECAR.find_ffmpeg() or not SIDECAR.find_ffprobe():
            raise unittest.SkipTest("FFmpeg/FFprobe are not installed")

    def test_box_expansion_is_clamped_to_frame(self) -> None:
        self.assertEqual(
            (0, 0, 35, 35),
            SIDECAR._expand_face_box((5, 5, 20, 20), 100, 80, 50),
        )

    def test_blur_reduces_detected_region_detail(self) -> None:
        import numpy as np  # type: ignore

        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        checker = (np.indices((32, 32)).sum(axis=0) % 2 * 255).astype(np.uint8)
        frame[16:48, 20:52] = np.repeat(checker[:, :, None], 3, axis=2)
        before = float(frame[16:48, 20:52].var())

        boxes = SIDECAR._blur_face_regions(frame, [(20, 16, 32, 32)], 90, 0)

        self.assertEqual([(20, 16, 32, 32)], boxes)
        self.assertLess(float(frame[16:48, 20:52].var()), before * 0.25)
        self.assertEqual(0, int(frame[0, 0, 0]))

    def test_clip_blurs_every_detected_frame_and_preserves_output(self) -> None:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "privacy-source.avi"
            output = directory / "privacy-output.mp4"
            frame_count = self._write_test_clip(source)
            detector = _Detector(np.array([[20, 16, 32, 32]], dtype=np.int32))
            args = SIDECAR.build_parser().parse_args(
                [
                    "face-blur", "--input", str(source), "--output", str(output),
                    "--strength", "90", "--padding", "0", "--preset", "ultrafast",
                ]
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                result = SIDECAR.op_face_blur(args, detector_override=detector)

            self.assertEqual(0, result, stdout.getvalue())
            events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
            final = events[-1]
            self.assertEqual("complete", final["event"])
            self.assertEqual(frame_count, final["frames"])
            self.assertEqual(frame_count, final["faces_detected"])
            self.assertEqual(frame_count, final["frames_with_faces"])
            capture = cv2.VideoCapture(str(output))
            ok, frame = capture.read()
            capture.release()
            self.assertTrue(ok)
            self.assertLess(float(frame[16:48, 20:52].var()), 5000)

    def test_no_detection_fails_closed_and_preserves_existing_output(self) -> None:
        import numpy as np  # type: ignore

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "source.avi"
            output = directory / "should-not-exist.mp4"
            self._write_test_clip(source)
            output.write_bytes(b"existing output must survive a failed privacy pass")
            args = SIDECAR.build_parser().parse_args(
                ["face-blur", "--input", str(source), "--output", str(output)]
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                result = SIDECAR.op_face_blur(
                    args, detector_override=_Detector(np.empty((0, 4), dtype=np.int32)))

            self.assertEqual(1, result)
            self.assertEqual(
                b"existing output must survive a failed privacy pass",
                output.read_bytes(),
            )
            self.assertEqual(
                "no_faces_detected",
                json.loads(stdout.getvalue().splitlines()[-1])["code"],
            )

    @staticmethod
    def _write_test_clip(path: Path) -> int:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"MJPG"), 6.0, (96, 64))
        if not writer.isOpened():
            raise unittest.SkipTest("OpenCV MJPG test encoder is unavailable")
        checker = (np.indices((32, 32)).sum(axis=0) % 2 * 255).astype(np.uint8)
        for _ in range(8):
            frame = np.zeros((64, 96, 3), dtype=np.uint8)
            frame[16:48, 20:52] = np.repeat(checker[:, :, None], 3, axis=2)
            writer.write(frame)
        writer.release()
        return 8


if __name__ == "__main__":
    unittest.main()

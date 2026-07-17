"""Safety, geometry, and report tests for offline AI video tagging."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("videotag_sidecar", ROOT / "tools" / "videotag" / "sidecar.py")
assert SPEC and SPEC.loader
videotag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(videotag)


def run_operation(operation, arguments: list[str]) -> tuple[int, list[dict]]:
    args = videotag.build_parser().parse_args(arguments)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = operation(args)
    return code, [json.loads(line) for line in stdout.getvalue().splitlines() if line]


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int) -> bytes:
        return self.payload.read(size)


class VideoTagTests(unittest.TestCase):
    def test_anchor_layout_matches_efficientdet_lite0(self) -> None:
        anchors = videotag.generate_anchors()
        self.assertEqual((19_206, 4), anchors.shape)
        self.assertTrue(np.allclose([-8.0, -8.0, 16.0, 16.0], anchors[0]))

    def test_zero_box_deltas_decode_to_anchors(self) -> None:
        anchors = np.asarray([[1.0, 2.0, 9.0, 14.0], [5.0, 6.0, 15.0, 26.0]], dtype=np.float32)
        decoded = videotag.decode_boxes(np.zeros((2, 4), dtype=np.float32), anchors)
        self.assertTrue(np.allclose(anchors, decoded))

    def test_nms_suppresses_overlap_and_keeps_separate_box(self) -> None:
        boxes = np.asarray([[0, 0, 10, 10], [1, 1, 9, 9], [20, 20, 30, 30]], dtype=np.float32)
        scores = np.asarray([0.9, 0.8, 0.7], dtype=np.float32)
        self.assertEqual([0, 2], videotag.non_max_suppression(boxes, scores))

    def test_download_requires_explicit_license_consent(self) -> None:
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
                videotag.urllib.request, "urlopen") as urlopen:
            code, events = run_operation(
                videotag.op_download_model, ["download-model", "--model-dir", temp])
        self.assertEqual(1, code)
        self.assertEqual("license_not_accepted", events[-1]["code"])
        urlopen.assert_not_called()

    def test_download_rejects_digest_mismatch_without_promotion(self) -> None:
        payload = b"not-the-model"
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(videotag, "MODEL_SIZE", len(payload)), \
                mock.patch.object(videotag, "MODEL_SHA256", "0" * 63 + "1"), \
                mock.patch.object(videotag.urllib.request, "urlopen", return_value=FakeResponse(payload)):
            destination = Path(temp) / videotag.MODEL_FILE
            self.assertFalse(videotag._download_model(destination))
            self.assertFalse(destination.exists())
            self.assertEqual([], list(Path(temp).glob("*.part")))

    def test_download_promotes_exact_pinned_payload(self) -> None:
        payload = b"verified-model"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(videotag, "MODEL_SIZE", len(payload)), \
                mock.patch.object(videotag, "MODEL_SHA256", digest), \
                mock.patch.object(videotag.urllib.request, "urlopen", return_value=FakeResponse(payload)):
            destination = Path(temp) / videotag.MODEL_FILE
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.assertTrue(videotag._download_model(destination))
            self.assertEqual(payload, destination.read_bytes())

    def test_tag_fails_closed_when_model_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.mp4"
            source.write_bytes(b"video")
            code, events = run_operation(videotag.op_tag, [
                "tag", "--input", str(source), "--output", str(Path(temp) / "tags.json"),
                "--model-dir", str(Path(temp) / "models"),
            ])
        self.assertEqual(1, code)
        self.assertEqual("missing_model", events[-1]["code"])

    def test_embedded_model_labels_are_read_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.tflite"
            with zipfile.ZipFile(model, "w") as archive:
                archive.writestr("labels.txt", "\n".join(f"label-{index}" for index in range(90)))
            labels = videotag._labels(model)
        self.assertEqual("label-89", labels[-1])

    def test_aggregate_counts_frames_separately_from_detections(self) -> None:
        frames = [
            {"timestampSeconds": 0.0, "detections": [
                {"label": "person", "score": 0.7}, {"label": "person", "score": 0.9},
            ]},
            {"timestampSeconds": 2.0, "detections": [{"label": "dog", "score": 0.8}]},
        ]
        summary = {item["label"]: item for item in videotag.aggregate_tags(frames)}
        self.assertEqual(1, summary["person"]["frames"])
        self.assertEqual(2, summary["person"]["detections"])
        self.assertEqual(0.9, summary["person"]["maxScore"])
        self.assertEqual(2.0, summary["dog"]["firstSeenSeconds"])

    def test_atomic_writer_preserves_existing_output_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "tags.json"
            output.write_text("old", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                videotag._write_atomic(output, {"new": True}, overwrite=False)
            self.assertEqual("old", output.read_text(encoding="utf-8"))

    def test_parser_bounds_sampling_and_threshold(self) -> None:
        for arguments in (
            ["tag", "--input", "in", "--output", "out.json", "--threshold", "0"],
            ["tag", "--input", "in", "--output", "out.json", "--max-frames", "10001"],
        ):
            with self.assertRaises(SystemExit):
                videotag.build_parser().parse_args(arguments)

    def test_preset_exposes_tag_operation(self) -> None:
        preset = (ROOT / "presets" / "video-ai-tags-json.preset.xml").read_text(encoding="utf-8")
        self.assertIn("<Engine>videotag</Engine>", preset)
        self.assertIn("<Arg>tag</Arg>", preset)
        self.assertIn("<OutputExtension>json</OutputExtension>", preset)


if __name__ == "__main__":
    unittest.main()

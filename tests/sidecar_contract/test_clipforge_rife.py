"""Contract coverage for ClipForge's managed RIFE workflow."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "clipforge" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("clipforge_rife", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _events(callable_, args) -> tuple[int, list[dict]]:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = callable_(args)
    return code, [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


class _FakeOutput:
    def __iter__(self):
        return iter(["interpolating 50%\n", "interpolating 100%\n"])

    def close(self) -> None:
        return None


class _FakeRifeProcess:
    def __init__(self, command, **_kwargs):
        output_dir = Path(command[command.index("-o") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "frame_000001.png").write_bytes(b"frame-1")
        (output_dir / "frame_000002.png").write_bytes(b"frame-2")
        self.stdout = _FakeOutput()
        self.returncode = 0

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class ClipForgeRifeTests(unittest.TestCase):
    def test_parser_pins_model_and_accepts_target_fps(self) -> None:
        args = SIDECAR.build_parser().parse_args([
            "rife", "--input", "source.mp4", "--output", "result.mp4", "--target-fps", "60",
        ])
        self.assertEqual("rife-v4.6", args.model)
        self.assertEqual(60.0, args.target_fps)

    def test_same_path_is_rejected_before_work_starts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.mp4"
            source.write_bytes(b"source")
            args = SIDECAR.build_parser().parse_args([
                "rife", "--input", str(source), "--output", str(source), "--target-fps", "60",
            ])
            with mock.patch.object(SIDECAR, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(SIDECAR, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(SIDECAR, "find_rife", return_value="rife.exe"):
                code, events = _events(SIDECAR.op_rife, args)
        self.assertEqual(1, code)
        self.assertEqual("output_same_as_input", events[-1]["code"])

    def test_target_below_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.mp4"
            output = Path(temp) / "result.mp4"
            source.write_bytes(b"source")
            args = SIDECAR.build_parser().parse_args([
                "rife", "--input", str(source), "--output", str(output), "--target-fps", "24",
            ])
            with mock.patch.object(SIDECAR, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(SIDECAR, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(SIDECAR, "find_rife", return_value="rife.exe"), \
                    mock.patch.object(SIDECAR, "probe", return_value={
                        "format": {"duration": "1"},
                        "streams": [{"codec_type": "video", "avg_frame_rate": "30/1"}],
                    }):
                code, events = _events(SIDECAR.op_rife, args)
        self.assertEqual(1, code)
        self.assertEqual("target_below_source", events[-1]["code"])

    def test_success_stages_output_and_reports_source_preserving_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            output = root / "result.mp4"
            source.write_bytes(b"source bytes")

            input_probe = {
                "format": {"duration": "1"},
                "streams": [{"codec_type": "video", "avg_frame_rate": "30/1"}],
            }
            output_probe = {
                "format": {"duration": "1"},
                "streams": [{"codec_type": "video", "avg_frame_rate": "60/1"}],
            }

            def fake_probe(_ffprobe, path):
                return output_probe if Path(path).suffix == ".part" else input_probe

            def fake_run(command, *_args, **_kwargs):
                target = Path(command[-1])
                if target.suffix == ".png":
                    target.parent.mkdir(parents=True, exist_ok=True)
                    (target.parent / "frame_00000001.png").write_bytes(b"input-1")
                    (target.parent / "frame_00000002.png").write_bytes(b"input-2")
                else:
                    target.write_bytes(b"encoded output")
                return 0

            args = SIDECAR.build_parser().parse_args([
                "rife", "--input", str(source), "--output", str(output), "--target-fps", "60",
            ])
            with mock.patch.object(SIDECAR, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(SIDECAR, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(SIDECAR, "find_rife", return_value=str(root / "rife.exe")), \
                    mock.patch.object(SIDECAR, "probe", side_effect=fake_probe), \
                    mock.patch.object(SIDECAR, "run_ffmpeg", side_effect=fake_run), \
                    mock.patch.object(SIDECAR.subprocess, "Popen", _FakeRifeProcess):
                Path(root / "rife.exe").write_bytes(b"runtime")
                source_before = source.read_bytes()
                code, events = _events(SIDECAR.op_rife, args)

            self.assertEqual(0, code, events)
            self.assertTrue(output.is_file())
            self.assertEqual(b"encoded output", output.read_bytes())
            self.assertEqual(source_before, source.read_bytes())
            complete = next(event for event in events if event["event"] == "complete")
            self.assertTrue(complete["source_preserving"])
            self.assertEqual(60.0, complete["target_fps"])
            self.assertTrue(complete["artifact_manifest"]["source_preserved"])

    def test_status_reports_a_structured_missing_runtime_error(self) -> None:
        args = SIDECAR.build_parser().parse_args(["rife-status"])
        with mock.patch.object(SIDECAR, "find_rife", return_value=None):
            code, events = _events(SIDECAR.op_rife_status, args)
        self.assertEqual(1, code)
        self.assertEqual("missing_rife", events[-1]["code"])

    def test_manifest_and_catalog_preset_declare_the_managed_vulkan_workflow(self) -> None:
        manifest = json.loads(
            (ROOT / "tools" / "clipforge" / "ucx.sidecar.json").read_text(encoding="utf-8"))
        self.assertEqual("vulkan", manifest["gpu"])
        rife_tool = next(tool for tool in manifest["tools"] if tool["id"] == "rife-ncnn-vulkan")
        self.assertTrue(rife_tool["managed"])
        self.assertEqual("rife", rife_tool["whenArgContains"])

        preset = (ROOT / "presets" / "video-rife-60fps.preset.xml").read_text(encoding="utf-8")
        self.assertIn("<Engine>clipforge</Engine>", preset)
        self.assertIn("<Arg>rife</Arg>", preset)
        self.assertIn("<Arg>60</Arg>", preset)


if __name__ == "__main__":
    unittest.main()

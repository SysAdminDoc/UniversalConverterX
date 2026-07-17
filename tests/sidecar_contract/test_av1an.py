"""Regression tests for the offline Av1an bridge."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "av1an" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("av1an_sidecar", SIDECAR)
assert SPEC and SPEC.loader
av1an = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = av1an
SPEC.loader.exec_module(av1an)


def encode_args(root: Path, **changes: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "input": str(root / "in.mkv"),
        "output": str(root / "out.mkv"),
        "encoder": "svt-av1",
        "workers": 4,
        "chunk_method": "hybrid",
        "concat_method": "ffmpeg",
        "split_method": "av-scenechange",
        "min_scene_len": 24,
        "extra_split_sec": 10,
        "video_params": "--preset 6 --crf 30",
        "audio_params": "-c:a copy",
        "scenes": None,
        "target_quality": None,
        "target_metric": "vmaf",
        "probes": 4,
        "temp": None,
        "resume": True,
        "keep_temp": False,
        "overwrite": False,
    }
    values.update(changes)
    return argparse.Namespace(**values)


class Av1anTests(unittest.TestCase):
    def test_command_uses_current_cli_and_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = encode_args(
                root, target_quality=95.0, scenes=str(root / "scenes.json"),
                temp=str(root / "chunks"), keep_temp=True,
            )
            command = av1an.build_encode_command(args, "av1an.exe", root / ".out.ucx-av1an.mkv")

        self.assertEqual("av1an.exe", command[0])
        self.assertEqual("svt-av1", command[command.index("--encoder") + 1])
        self.assertEqual("4", command[command.index("--workers") + 1])
        self.assertEqual("hybrid", command[command.index("--chunk-method") + 1])
        self.assertEqual("ffmpeg", command[command.index("--concat") + 1])
        self.assertEqual("95.0", command[command.index("--target-quality") + 1])
        self.assertIn("--resume", command)
        self.assertIn("--keep", command)
        self.assertNotIn("--overwrite", command)

    def test_encode_atomically_promotes_staged_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "in.mkv"
            source.write_bytes(b"source")
            output = root / "out.mkv"
            args = encode_args(root)

            def fake_run(command: list[str], _: str) -> tuple[int, list[str]]:
                staged = Path(command[command.index("-o") + 1])
                staged.write_bytes(b"encoded")
                return 0, []

            with mock.patch.object(av1an, "_validate_runtime", return_value=("av1an.exe", "SvtAv1EncApp.exe")), \
                    mock.patch.object(av1an, "_run", side_effect=fake_run):
                result = av1an.op_encode(args)

            self.assertEqual(0, result)
            self.assertEqual(b"encoded", output.read_bytes())
            self.assertFalse((root / ".out.ucx-av1an.mkv").exists())

    def test_failed_encode_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "in.mkv").write_bytes(b"source")
            output = root / "out.mkv"
            output.write_bytes(b"old")
            args = encode_args(root, overwrite=True)

            def fake_run(command: list[str], _: str) -> tuple[int, list[str]]:
                Path(command[command.index("-o") + 1]).write_bytes(b"partial")
                return 2, ["encoder failed"]

            with mock.patch.object(av1an, "_validate_runtime", return_value=("av1an.exe", "SvtAv1EncApp.exe")), \
                    mock.patch.object(av1an, "_run", side_effect=fake_run):
                result = av1an.op_encode(args)

            self.assertEqual(1, result)
            self.assertEqual(b"old", output.read_bytes())
            self.assertFalse((root / ".out.ucx-av1an.mkv").exists())

    def test_probe_requires_complete_runtime(self) -> None:
        with mock.patch.object(av1an, "_find_av1an", return_value="av1an.exe"), \
                mock.patch.object(av1an, "_version", return_value="av1an 0.5.2"), \
                mock.patch.object(av1an, "find_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch.object(av1an, "_find_vspipe", return_value=None), \
                mock.patch.object(av1an, "_find_encoder", return_value="encoder.exe"):
            status = av1an.runtime_status()
        self.assertFalse(status["available"])
        self.assertIsNone(status["vspipe"])

    def test_current_version_floor_rejects_older_cli(self) -> None:
        self.assertTrue(av1an._supported_version("av1an 0.5.2"))
        self.assertTrue(av1an._supported_version("Av1an v0.6.0-nightly"))
        self.assertFalse(av1an._supported_version("av1an 0.5.1"))
        self.assertFalse(av1an._supported_version("unknown"))

    def test_manifest_declares_selected_encoder_readiness(self) -> None:
        manifest = json.loads((ROOT / "tools" / "av1an" / "ucx.sidecar.json").read_text(encoding="utf-8"))
        svt = next(tool for tool in manifest["tools"] if tool["id"] == "svtav1encapp")
        self.assertEqual("svt-av1", svt["whenArgContains"])
        self.assertFalse(svt["managed"])

    def test_parser_defaults_to_resumable_ffmpeg_backed_chunking(self) -> None:
        args = av1an.build_parser().parse_args([
            "encode", "--input", "in.mkv", "--output", "out.mkv",
        ])
        self.assertTrue(args.resume)
        self.assertEqual("hybrid", args.chunk_method)
        self.assertEqual("ffmpeg", args.concat_method)
        self.assertEqual(0, args.workers)

    def test_scene_output_requires_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "in.mkv"
            source.write_bytes(b"source")
            args = argparse.Namespace(
                input=str(source), output=str(root / "scenes.txt"), overwrite=False,
                split_method="av-scenechange", min_scene_len=24, extra_split_sec=10,
            )
            with mock.patch.object(av1an, "_find_av1an", return_value="av1an.exe"), \
                    mock.patch.object(av1an, "_version", return_value="av1an 0.5.2"), \
                    mock.patch.object(av1an, "find_ffmpeg", return_value="ffmpeg.exe"), \
                    mock.patch.object(av1an, "_find_vspipe", return_value="vspipe.exe"):
                result = av1an.op_scenes(args)
        self.assertEqual(1, result)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the explicit-trust VapourSynth bridge."""

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
SIDECAR = ROOT / "tools" / "vapoursynth" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("vapoursynth_sidecar", SIDECAR)
assert SPEC and SPEC.loader
vapoursynth = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = vapoursynth
SPEC.loader.exec_module(vapoursynth)


def render_args(root: Path, **changes: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "input": str(root / "trusted.vpy"),
        "output": str(root / "out.mkv"),
        "acknowledge_script_code": True,
        "script_arg": [],
        "output_index": 0,
        "codec": "h264",
        "crf": None,
        "start_frame": None,
        "end_frame": None,
        "requests": None,
        "audio_source": None,
        "audio_mode": "copy",
        "overwrite": False,
    }
    values.update(changes)
    return argparse.Namespace(**values)


class VapourSynthTests(unittest.TestCase):
    def test_script_execution_requires_explicit_trust(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "local.vpy"
            script.write_text("raise SystemExit", encoding="utf-8")
            args = argparse.Namespace(input=str(script), acknowledge_script_code=False)
            self.assertIsNone(vapoursynth._trusted_script(args))

    def test_script_arguments_are_validated_without_shell_parsing(self) -> None:
        self.assertEqual(
            ["--arg", "source=C:/media/a b.mkv", "--arg", "mode=clean"],
            vapoursynth._script_arguments(["source=C:/media/a b.mkv", "mode=clean"]),
        )
        with self.assertRaisesRegex(ValueError, "key=value"):
            vapoursynth._script_arguments(["missing-separator"])
        with self.assertRaisesRegex(ValueError, "Invalid.*key"):
            vapoursynth._script_arguments(["bad-key=value"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            vapoursynth._script_arguments(["source=a", "SOURCE=b"])

    def test_vspipe_command_matches_r76_option_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = render_args(
                root, script_arg=["source=C:/media/input.mkv"], output_index=2,
                start_frame=5, end_frame=100, requests=4,
            )
            command = vapoursynth.build_vspipe_command(
                "vspipe.exe", root / "trusted.vpy", "-", args, operation="render",
            )
        self.assertEqual("vspipe.exe", command[0])
        self.assertEqual(["--container", "y4m", "--progress"], command[1:4])
        self.assertLess(command.index("--arg"), command.index(str(root / "trusted.vpy")))
        self.assertEqual("2", command[command.index("--outputindex") + 1])
        self.assertEqual("-", command[-1])

    def test_ffmpeg_command_maps_optional_audio_as_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "source file.mkv"
            args = render_args(root, codec="hevc", audio_source=str(audio), audio_mode="aac")
            command = vapoursynth.build_ffmpeg_command(args, "ffmpeg.exe", root / ".out.mkv")
        self.assertEqual("ffmpeg.exe", command[0])
        self.assertIn("pipe:0", command)
        self.assertIn(str(audio.resolve()), command)
        self.assertEqual("libx265", command[command.index("-c:v") + 1])
        self.assertEqual("aac", command[command.index("-c:a") + 1])
        self.assertNotIn("|", command)

    def test_render_atomically_promotes_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "trusted.vpy"
            script.write_text("# reviewed", encoding="utf-8")
            output = root / "out.mkv"
            args = render_args(root)

            def fake_pipeline(_: list[str], ffmpeg: list[str]) -> tuple[int, int, list[str]]:
                Path(ffmpeg[-1]).write_bytes(b"encoded")
                return 0, 0, []

            with mock.patch.object(vapoursynth, "_base_args", return_value=(script, "vspipe.exe")), \
                    mock.patch.object(vapoursynth, "find_ffmpeg", return_value="ffmpeg.exe"), \
                    mock.patch.object(vapoursynth, "_run_pipeline", side_effect=fake_pipeline):
                result = vapoursynth.op_render(args)
            output_bytes = output.read_bytes()
        self.assertEqual(0, result)
        self.assertEqual(b"encoded", output_bytes)

    def test_failed_render_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "trusted.vpy"
            script.write_text("# reviewed", encoding="utf-8")
            output = root / "out.mkv"
            output.write_bytes(b"old")
            args = render_args(root, overwrite=True)

            def fake_pipeline(_: list[str], ffmpeg: list[str]) -> tuple[int, int, list[str]]:
                Path(ffmpeg[-1]).write_bytes(b"partial")
                return 1, 0, ["script failed"]

            with mock.patch.object(vapoursynth, "_base_args", return_value=(script, "vspipe.exe")), \
                    mock.patch.object(vapoursynth, "find_ffmpeg", return_value="ffmpeg.exe"), \
                    mock.patch.object(vapoursynth, "_run_pipeline", side_effect=fake_pipeline):
                result = vapoursynth.op_render(args)
            output_bytes = output.read_bytes()
            staged_exists = (root / ".out.ucx-vapoursynth.mkv").exists()
        self.assertEqual(1, result)
        self.assertEqual(b"old", output_bytes)
        self.assertFalse(staged_exists)

    def test_current_vspipe_version_floor(self) -> None:
        self.assertTrue(vapoursynth._supported_version("Core R76 | API R4.2"))
        self.assertTrue(vapoursynth._supported_version("VapourSynth R80"))
        self.assertFalse(vapoursynth._supported_version("Core R75"))
        self.assertFalse(vapoursynth._supported_version("unknown"))

    def test_preset_warns_and_acknowledges_executable_script(self) -> None:
        preset = ROOT / "presets" / "vapoursynth-trusted-script-h264.preset.xml"
        text = preset.read_text(encoding="utf-8")
        self.assertIn("executable Python", text)
        self.assertIn("--acknowledge-script-code", text)

    def test_manifest_keeps_runtime_external(self) -> None:
        manifest = json.loads((ROOT / "tools" / "vapoursynth" / "ucx.sidecar.json").read_text(encoding="utf-8"))
        vspipe = next(tool for tool in manifest["tools"] if tool["id"] == "vspipe")
        self.assertFalse(vspipe["managed"])


if __name__ == "__main__":
    unittest.main()

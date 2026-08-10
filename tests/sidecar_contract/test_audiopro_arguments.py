"""Argument and output-safety coverage for the audiopro sidecar."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "audiopro" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ucx_audiopro_sidecar", SIDECAR_PATH)
assert SPEC and SPEC.loader
AUDIOPRO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIOPRO)


class AudioProArgumentTests(unittest.TestCase):
    def test_fdk_aac_vbr_and_advanced_flags_reach_ffmpeg(self) -> None:
        command = self._run(
            "fdk-aac",
            "--vbr-quality", "2",
            "--fdk-cutoff", "20000",
            "--fdk-afterburner", "true",
            "--fdk-profile", "aac_low",
        )

        self.assertIn("libfdk_aac", command)
        self.assertInSequence(["-vbr", "4"], command)
        self.assertInSequence(["-cutoff", "20000"], command)
        self.assertInSequence(["-afterburner", "1"], command)
        self.assertInSequence(["-profile:a", "aac_low"], command)

    def test_managed_vorbis_uses_bounded_bitrate_flags(self) -> None:
        command = self._run("vorbis", "--bitrate", "160k", "--vorbis-managed")

        self.assertIn("libvorbis", command)
        self.assertInSequence(["-b:a", "160k", "-minrate", "64k", "-maxrate", "160k"], command)
        self.assertTrue(str(command[-1]).endswith(".ogg"))

    def test_opus_rejects_rates_outside_bundled_encoder(self) -> None:
        for sample_rate in ("44100", "96000"):
            with self.subTest(sample_rate=sample_rate), tempfile.TemporaryDirectory() as temp:
                temp_path = Path(temp)
                source = temp_path / "source.wav"
                source.write_bytes(b"input")
                args = AUDIOPRO.build_parser().parse_args([
                    "convert", "--format", "opus", "--sample-rate", sample_rate,
                    "--output-dir", str(temp_path / "output"), "--input", str(source),
                ])
                with patch.object(AUDIOPRO, "_find_ffmpeg", return_value="ffmpeg"), \
                     patch.object(AUDIOPRO.subprocess, "run") as run:
                    result = AUDIOPRO.op_convert(args)

                self.assertEqual(1, result)
                run.assert_not_called()

    def test_existing_output_gets_unique_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            source = temp_path / "song.wav"
            source.write_bytes(b"input")
            output_dir = temp_path / "output"
            output_dir.mkdir()
            (output_dir / "song.mp3").write_bytes(b"existing")
            captured: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
                captured.extend(command)
                Path(command[-1]).write_bytes(b"converted")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            args = AUDIOPRO.build_parser().parse_args([
                "convert", "--format", "mp3", "--output-dir", str(output_dir),
                "--input", str(source),
            ])
            with patch.object(AUDIOPRO, "_find_ffmpeg", return_value="ffmpeg"), \
                 patch.object(AUDIOPRO.subprocess, "run", side_effect=fake_run):
                result = AUDIOPRO.op_convert(args)

            self.assertEqual(0, result)
            self.assertEqual("song (1).mp3", Path(captured[-1]).name)
            self.assertEqual(b"existing", (output_dir / "song.mp3").read_bytes())

    def _run(self, format_name: str, *extra: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            source = temp_path / "source.wav"
            source.write_bytes(b"input")
            output_dir = temp_path / "output"
            captured: list[str] = []

            def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
                captured.extend(command)
                Path(command[-1]).write_bytes(b"converted")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            args = AUDIOPRO.build_parser().parse_args([
                "convert", "--format", format_name, *extra,
                "--output-dir", str(output_dir), "--input", str(source),
            ])
            with patch.object(AUDIOPRO, "_find_ffmpeg", return_value="ffmpeg"), \
                 patch.object(AUDIOPRO.subprocess, "run", side_effect=fake_run):
                result = AUDIOPRO.op_convert(args)

            self.assertEqual(0, result)
            return captured

    def assertInSequence(self, expected: list[str], actual: list[str]) -> None:
        width = len(expected)
        self.assertTrue(
            any(actual[index:index + width] == expected for index in range(len(actual) - width + 1)),
            f"{expected!r} is not contiguous in {actual!r}",
        )


if __name__ == "__main__":
    unittest.main()

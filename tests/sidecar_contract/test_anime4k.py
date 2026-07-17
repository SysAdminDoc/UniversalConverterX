"""Focused tests for the optional Anime4K GLSL video backend."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "anime-upscale" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("anime_upscale_sidecar", SIDECAR)
assert SPEC and SPEC.loader
anime4k = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = anime4k
SPEC.loader.exec_module(anime4k)


class Anime4KTests(unittest.TestCase):
    def test_profiles_reference_the_complete_required_set(self) -> None:
        referenced = {name for chain in anime4k._ANIME4K_CHAINS.values() for name in chain}

        self.assertEqual(referenced, set(anime4k._ANIME4K_REQUIRED_FILES))
        self.assertEqual({"a", "b", "c"}, set(anime4k._ANIME4K_CHAINS))

    def test_command_is_isolated_and_applies_profile_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.dict(os.environ, {"UCX_ANIME4K_SHADERS": temp}):
            source = Path(temp) / "source.mp4"
            output = Path(temp) / "result.mp4"
            command = anime4k._anime4k_command(
                "mpv", source, output, "a", 640, 360, 18)

        self.assertIn("--no-config", command)
        self.assertIn("--no-input-default-bindings", command)
        self.assertEqual(6, len([arg for arg in command if arg.startswith("--glsl-shader=")]))
        self.assertIn("--vf=gpu=w=1280:h=720", command)
        self.assertIn(f"--o={output}", command)
        self.assertEqual(str(source), command[-1])

    def test_shader_status_fails_cleanly_without_mpv(self) -> None:
        protocol = io.StringIO()
        with mock.patch.object(anime4k, "_find_mpv", return_value=None), \
                redirect_stdout(protocol):
            code = anime4k.main(["shader-status"])

        self.assertEqual(1, code)
        events = [json.loads(line) for line in protocol.getvalue().splitlines()]
        self.assertEqual("missing_mpv", events[-1]["code"])

    def test_archive_install_extracts_only_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "pack.zip"
            destination = root / "installed"
            with zipfile.ZipFile(archive, "w") as bundle:
                for name in anime4k._ANIME4K_REQUIRED_FILES:
                    bundle.writestr(f"Anime4K/glsl/{name}", f"shader:{name}")
                bundle.writestr("Anime4K/extra.txt", "not installed")

            anime4k._install_shader_archive(archive, destination)

            self.assertEqual(
                set(anime4k._ANIME4K_REQUIRED_FILES) | {"pack.json"},
                {path.name for path in destination.iterdir()},
            )
            metadata = json.loads((destination / "pack.json").read_text(encoding="utf-8"))
            self.assertEqual("4.0.1", metadata["version"])

    def test_archive_install_rejects_missing_required_shader(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "pack.zip"
            destination = root / "installed"
            with zipfile.ZipFile(archive, "w") as bundle:
                for name in anime4k._ANIME4K_REQUIRED_FILES[1:]:
                    bundle.writestr(name, "shader")

            with self.assertRaises(ValueError):
                anime4k._install_shader_archive(archive, destination)
            self.assertFalse(destination.exists())

    def test_video_parser_defaults_to_realesrgan_and_accepts_anime_profile(self) -> None:
        parser = anime4k.build_parser()

        defaults = parser.parse_args(["video", "--input", "in.mp4", "--output", "out.mp4"])
        selected = parser.parse_args([
            "video", "--input", "in.mp4", "--output", "out.mp4",
            "--backend", "anime4k", "--profile", "c",
        ])

        self.assertEqual("realesrgan", defaults.backend)
        self.assertEqual("a", defaults.profile)
        self.assertEqual("anime4k", selected.backend)
        self.assertEqual("c", selected.profile)


if __name__ == "__main__":
    unittest.main()

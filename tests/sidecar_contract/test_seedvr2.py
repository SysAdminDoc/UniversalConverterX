"""Focused tests for the opt-in SeedVR2 pack and CUDA boundary."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "seedvr2" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("seedvr2_sidecar", SIDECAR)
assert SPEC and SPEC.loader
seedvr2 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = seedvr2
SPEC.loader.exec_module(seedvr2)


class SeedVr2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol = io.StringIO()
        self.stdout = seedvr2._PROTOCOL_STDOUT
        seedvr2._PROTOCOL_STDOUT = self.protocol

    def tearDown(self) -> None:
        seedvr2._PROTOCOL_STDOUT = self.stdout

    def events(self) -> list[dict]:
        return [json.loads(line) for line in self.protocol.getvalue().splitlines()]

    def test_download_requires_explicit_license_acceptance(self) -> None:
        code = seedvr2.main(["download-model"])

        self.assertEqual(1, code)
        self.assertEqual("license_acceptance_required", self.events()[-1]["code"])

    def test_pack_directory_is_scoped_below_shared_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            expected = (Path(temp) / "seedvr2").resolve()

            self.assertEqual(expected, seedvr2.resolve_pack_dir(temp))
            self.assertEqual(expected, seedvr2.resolve_pack_dir(expected))

    def test_safe_runtime_extract_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("root/../../escape.py", "bad")

            with self.assertRaises(ValueError):
                seedvr2.safe_extract_runtime(archive, Path(temp) / "runtime")

    def test_runtime_hash_ignores_only_generated_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / "inference_cli.py").write_text("original", encoding="utf-8")
            expected = seedvr2.tree_sha256(runtime)
            cache = runtime / "__pycache__"
            cache.mkdir()
            (cache / "inference_cli.cpython-311.pyc").write_bytes(b"generated")

            self.assertEqual(expected, seedvr2.tree_sha256(runtime))
            (runtime / "inference_cli.py").write_text("modified", encoding="utf-8")
            self.assertNotEqual(expected, seedvr2.tree_sha256(runtime))

    def test_restore_blocks_before_cuda_when_model_pack_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "clip.mp4"
            source.write_bytes(b"video")

            code = seedvr2.main([
                "restore", "--input", str(source),
                "--output", str(Path(temp) / "restored.mp4"),
                "--model-dir", str(Path(temp) / "missing"),
            ])

        self.assertEqual(1, code)
        self.assertEqual("model_not_installed", self.events()[-1]["code"])

    def test_restore_cleanly_blocks_without_cuda(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "clip.mp4"
            source.write_bytes(b"video")
            with mock.patch.object(seedvr2, "validate_pack", return_value=[]), \
                    mock.patch.object(seedvr2, "cuda_device", return_value=(None, "No CUDA")):
                code = seedvr2.main([
                    "restore", "--input", str(source),
                    "--output", str(Path(temp) / "restored.mp4"),
                    "--model-dir", temp,
                ])

        self.assertEqual(1, code)
        self.assertEqual("cuda_required", self.events()[-1]["code"])

    def test_restore_invokes_verified_offline_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "clip.mp4"
            output = Path(temp) / "restored.mp4"
            source.write_bytes(b"video")
            device = seedvr2.DeviceInfo("Test CUDA", 16 * 1024**3)

            def fake_runtime(_pack: Path, argv: list[str]) -> int:
                self.assertIn("--model_dir", argv)
                self.assertIn("--dit_model", argv)
                self.assertIn("--blocks_to_swap", argv)
                Path(argv[argv.index("--output") + 1]).write_bytes(b"restored")
                return 0

            def fake_remux(_ffmpeg: str, _source: Path, _video: Path, target: Path):
                target.write_bytes(b"restored with audio")
                return True, ""

            with mock.patch.object(seedvr2, "validate_pack", return_value=[]), \
                    mock.patch.object(seedvr2, "cuda_device", return_value=(device, None)), \
                    mock.patch.object(seedvr2, "find_ffmpeg", return_value=sys.executable), \
                    mock.patch.object(seedvr2, "_run_upstream", side_effect=fake_runtime), \
                    mock.patch.object(seedvr2, "remux_source_audio", side_effect=fake_remux):
                code = seedvr2.main([
                    "restore", "--input", str(source),
                    "--output", str(output),
                    "--model-dir", temp,
                    "--resolution", "540",
                ])

        self.assertEqual(0, code)
        self.assertEqual("complete", self.events()[-1]["event"])


if __name__ == "__main__":
    unittest.main()

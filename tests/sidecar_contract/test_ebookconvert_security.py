from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "ebookconvert" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ebookconvert_sidecar", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


class _FakeProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = iter(["10% staged conversion\n"])

    def wait(self) -> None:
        return None


class EbookConvertSecurityTests(unittest.TestCase):
    def test_environment_is_isolated_and_disables_python_templates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            job_dir = Path(raw_dir)
            polluted = {
                "CALIBRE_CONFIG_DIRECTORY": "unsafe-config",
                "CALIBRE_DEVELOP_FROM": "unsafe-source",
                "PYTHONHOME": "unsafe-python",
                "PYTHONPATH": "unsafe-path",
            }
            with mock.patch.dict(os.environ, polluted):
                env = SIDECAR.build_calibre_environment(job_dir)

            self.assertEqual(env["CALIBRE_ALLOW_PYTHON_TEMPLATES"], "0")
            self.assertNotIn("CALIBRE_DEVELOP_FROM", env)
            self.assertNotIn("PYTHONHOME", env)
            self.assertNotIn("PYTHONPATH", env)
            for name in (
                "CALIBRE_CONFIG_DIRECTORY",
                "CALIBRE_CACHE_DIRECTORY",
                "CALIBRE_TEMP_DIR",
            ):
                directory = Path(env[name])
                self.assertTrue(directory.is_dir())
                self.assertEqual(directory.parent, job_dir)

    def test_conversion_rejects_target_format_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "input.epub"
            source.write_bytes(b"source")
            args = argparse.Namespace(
                input=[str(source)],
                output_dir=str(root / "out"),
                format="../../outside",
                title=None,
                authors=None,
                language=None,
            )

            with (
                mock.patch.object(SIDECAR, "find_calibre", return_value="fake-calibre"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = SIDECAR.op_convert(args)

            self.assertEqual(result, 1)
            self.assertFalse((root / "outside").exists())

    def test_conversion_uses_staging_and_atomically_promotes_valid_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "input.epub"
            output_dir = root / "out"
            output_dir.mkdir()
            source.write_bytes(b"source")
            destination = output_dir / "input.pdf"
            destination.write_bytes(b"old-output")
            observed: dict[str, object] = {}

            def fake_popen(command, **kwargs):
                observed["command"] = command
                observed["kwargs"] = kwargs
                staged_input = Path(command[1])
                staged_output = Path(command[2])
                self.assertNotEqual(staged_input.parent, source.parent)
                self.assertEqual(staged_input.parent.parent, Path(kwargs["cwd"]))
                self.assertEqual(staged_output.parent.parent, Path(kwargs["cwd"]))
                self.assertEqual(destination.read_bytes(), b"old-output")
                staged_output.write_bytes(b"converted")
                return _FakeProcess()

            args = argparse.Namespace(
                input=[str(source)],
                output_dir=str(output_dir),
                format="pdf",
                title=None,
                authors=None,
                language=None,
            )
            with (
                mock.patch.object(SIDECAR, "find_calibre", return_value="fake-calibre"),
                mock.patch.object(SIDECAR.subprocess, "Popen", side_effect=fake_popen),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = SIDECAR.op_convert(args)

            self.assertEqual(result, 0)
            self.assertEqual(destination.read_bytes(), b"converted")
            environment = observed["kwargs"]["env"]
            self.assertEqual(environment["CALIBRE_ALLOW_PYTHON_TEMPLATES"], "0")
            self.assertIs(observed["kwargs"]["stdin"], SIDECAR.subprocess.DEVNULL)

    def test_failed_conversion_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "input.epub"
            output_dir = root / "out"
            output_dir.mkdir()
            source.write_bytes(b"source")
            destination = output_dir / "input.pdf"
            destination.write_bytes(b"keep-me")
            args = argparse.Namespace(
                input=[str(source)],
                output_dir=str(output_dir),
                format="pdf",
                title=None,
                authors=None,
                language=None,
            )

            with (
                mock.patch.object(SIDECAR, "find_calibre", return_value="fake-calibre"),
                mock.patch.object(
                    SIDECAR.subprocess,
                    "Popen",
                    return_value=_FakeProcess(returncode=2),
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = SIDECAR.op_convert(args)

            self.assertEqual(result, 1)
            self.assertEqual(destination.read_bytes(), b"keep-me")


if __name__ == "__main__":
    unittest.main()

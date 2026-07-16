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
SIDECAR_PATH = ROOT / "tools" / "archive" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("archive_sidecar", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


@unittest.skipUnless(os.name == "nt", "Mark-of-the-Web uses Windows alternate data streams")
class ArchiveMarkOfTheWebTests(unittest.TestCase):
    def test_unpack_stages_then_propagates_mark_to_extracted_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            archive = root / "downloaded.rar"
            archive.write_bytes(b"archive")
            zone_data = b"[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=https://example.test/\r\n"
            Path(str(archive) + ":Zone.Identifier").write_bytes(zone_data)
            output_dir = root / "output"
            existing = output_dir / "nested" / "result.txt"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"old")

            def fake_stream(command: list[str], stage: str) -> int:
                self.assertEqual(stage, "unpack")
                staging = Path(next(arg[2:] for arg in command if arg.startswith("-o")))
                self.assertNotEqual(staging, output_dir)
                self.assertEqual(existing.read_bytes(), b"old")
                extracted = staging / "nested" / "result.txt"
                extracted.parent.mkdir(parents=True)
                extracted.write_bytes(b"new")
                return 0

            args = argparse.Namespace(
                input=str(archive),
                output_dir=str(output_dir),
                password=None,
            )
            with (
                mock.patch.object(SIDECAR, "find_7z", return_value="fake-7z"),
                mock.patch.object(SIDECAR, "_stream_7z", side_effect=fake_stream),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = SIDECAR.op_unpack(args)

            self.assertEqual(result, 0)
            self.assertEqual(existing.read_bytes(), b"new")
            self.assertEqual(
                Path(str(existing) + ":Zone.Identifier").read_bytes(),
                zone_data,
            )

    def test_failed_unpack_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            archive = root / "downloaded.rar"
            archive.write_bytes(b"archive")
            output_dir = root / "output"
            output_dir.mkdir()
            existing = output_dir / "result.txt"
            existing.write_bytes(b"keep")

            def failing_stream(command: list[str], stage: str) -> int:
                staging = Path(next(arg[2:] for arg in command if arg.startswith("-o")))
                (staging / "result.txt").write_bytes(b"partial")
                return 2

            args = argparse.Namespace(
                input=str(archive),
                output_dir=str(output_dir),
                password=None,
            )
            with (
                mock.patch.object(SIDECAR, "find_7z", return_value="fake-7z"),
                mock.patch.object(SIDECAR, "_stream_7z", side_effect=failing_stream),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = SIDECAR.op_unpack(args)

            self.assertEqual(result, 1)
            self.assertEqual(existing.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()

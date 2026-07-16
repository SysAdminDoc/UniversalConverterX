"""Exact timestamp and safe muxing tests for the ChapterMark sidecar."""

from __future__ import annotations

from decimal import Decimal
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "chaptermark" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("chaptermark_sidecar", SIDECAR)
assert SPEC and SPEC.loader
chaptermark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chaptermark
SPEC.loader.exec_module(chaptermark)


class ChapterMarkTests(unittest.TestCase):
    def test_normalize_preserves_integer_pts_and_time_base(self) -> None:
        chapters = chaptermark._normalize_chapters([{
            "start_pts": 1001,
            "end_pts": 2002,
            "time_base": "1/30000",
            "title": "Exact",
        }])

        self.assertEqual(1001, chapters[0]["start_pts"])
        self.assertEqual(2002, chapters[0]["end_pts"])
        self.assertEqual(30000, chapters[0]["time_base_den"])
        metadata = chaptermark._build_ffmetadata(chapters)
        self.assertIn("TIMEBASE=1/30000", metadata)
        self.assertIn("START=1001", metadata)

    def test_missing_end_uses_next_exact_start_or_duration(self) -> None:
        chapters = chaptermark._normalize_chapters([
            {"start_pts": 0, "time_base": "1/1000", "title": "One"},
            {"start_pts": 1234, "time_base": "1/1000", "title": "Two"},
        ], Decimal("3.5"))

        self.assertEqual(1234, chapters[0]["end_pts"])
        self.assertEqual(3500, chapters[1]["end_pts"])

    def test_ffmetadata_escapes_titles_that_could_inject_fields(self) -> None:
        chapters = chaptermark._normalize_chapters([{
            "start": "0",
            "end": "1",
            "title": "Intro=1;#tag\\name\nnext",
        }])

        metadata = chaptermark._build_ffmetadata(chapters)

        self.assertIn(r"title=Intro\=1\;\#tag\\name\nnext", metadata)
        self.assertEqual(1, metadata.count("[CHAPTER]"))

    def test_matroska_xml_round_trip_preserves_nanoseconds(self) -> None:
        chapters = chaptermark._normalize_chapters([{
            "start_pts": 1_234_567_891,
            "end_pts": 2_345_678_912,
            "time_base": "1/1000000000",
            "title": "Opening",
        }])
        xml = chaptermark._build_matroska_xml(chapters).decode("utf-8")

        restored = chaptermark._parse_matroska_xml(xml)

        self.assertEqual(1_234_567_891, restored[0]["start_pts"])
        self.assertEqual(2_345_678_912, restored[0]["end_pts"])
        self.assertEqual("Opening", restored[0]["title"])

    def test_simple_export_refuses_silent_sub_millisecond_rounding(self) -> None:
        chapters = chaptermark._normalize_chapters([{
            "start_pts": 1,
            "end_pts": 2_000_001,
            "time_base": "1/1000000",
            "title": "Precise",
        }])

        with self.assertRaisesRegex(ValueError, "cannot preserve"):
            chaptermark._simple_export(chapters)

    def test_mkv_write_uses_mkvmerge_97_and_verifies_before_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mkv"
            output = root / "output.mkv"
            chapters_file = root / "chapters.json"
            source.write_bytes(b"source")
            chapters_file.write_text(json.dumps([{
                "start_pts": 0,
                "end_pts": 1000,
                "time_base": "1/1000",
                "title": "Intro",
            }]), encoding="utf-8")
            expected = chaptermark._normalize_chapters(json.loads(chapters_file.read_text()))
            commands: list[list[str]] = []

            def fake_run(command: list[str], _timeout: int):
                commands.append(command)
                staged = Path(command[command.index("-o") + 1])
                staged.write_bytes(b"muxed")
                return subprocess.CompletedProcess(command, 0, "", "")

            args = chaptermark.build_parser().parse_args([
                "write", "--input", str(source), "--output", str(output),
                "--chapters-json", str(chapters_file),
            ])
            with mock.patch.object(chaptermark, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(chaptermark, "find_tool", return_value="mkvmerge"), \
                    mock.patch.object(chaptermark, "_mkvmerge_major", return_value=(97, "mkvmerge v97.0")), \
                    mock.patch.object(chaptermark, "_probe_duration", return_value=Decimal("1")), \
                    mock.patch.object(chaptermark, "_probe_chapters", return_value=expected), \
                    mock.patch.object(chaptermark, "_run", side_effect=fake_run):
                code = chaptermark.op_write(args)

            self.assertEqual(0, code)
            self.assertEqual(b"muxed", output.read_bytes())
            self.assertIn("--chapters", commands[0])

    def test_duplicate_start_times_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            chaptermark._normalize_chapters([
                {"start": "1", "end": "2", "title": "A"},
                {"start": "1", "end": "3", "title": "B"},
            ])

    def test_mp4_write_rejects_nonzero_first_chapter_before_muxing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            output = root / "output.mp4"
            chapters_file = root / "chapters.json"
            source.write_bytes(b"source")
            chapters_file.write_text(
                '[{"start": "0.5", "end": "1.5", "title": "Late"}]',
                encoding="utf-8")
            args = chaptermark.build_parser().parse_args([
                "write", "--input", str(source), "--output", str(output),
                "--chapters-json", str(chapters_file),
            ])
            with mock.patch.object(chaptermark, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(chaptermark, "_probe_duration", return_value=Decimal("2")), \
                    mock.patch.object(chaptermark, "_run") as run:
                code = chaptermark.op_write(args)

            self.assertEqual(1, code)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

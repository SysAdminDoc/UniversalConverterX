"""Headless coverage for IMAPI2 data images and DVD-Video authoring."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "discburn" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("discburn", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _events(func, args) -> tuple[int, list[dict]]:
    parsed = SIDECAR.build_parser().parse_args(args)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = func(parsed)
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return code, events


class DiscBurnTests(unittest.TestCase):
    def test_volume_label_is_imapi_safe_and_bounded(self) -> None:
        self.assertEqual("MY_DISC_2026", SIDECAR.normalize_label("My disc: 2026"))
        self.assertEqual("UNIVERSAL_X", SIDECAR.normalize_label("***"))
        self.assertEqual(32, len(SIDECAR.normalize_label("a" * 80)))

    def test_missing_data_source_fails_before_imapi(self) -> None:
        code, events = _events(
            SIDECAR.op_image_data,
            ["image-data", "--input", "/missing/disc-source", "--output", "out.iso"],
        )
        self.assertEqual(1, code)
        self.assertEqual("missing_input", events[-1]["code"])

    @unittest.skipUnless(SIDECAR.find_powershell(), "Windows IMAPI2 is unavailable")
    def test_data_iso_roundtrip_has_primary_volume_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "hello.txt").write_text("UniversalConverterX disc test\n", encoding="utf-8")
            output = root / "data.iso"

            code, events = _events(
                SIDECAR.op_image_data,
                [
                    "image-data", "--input", str(source), "--output", str(output),
                    "--media", "dvd", "--label", "UCX TEST",
                ],
            )

            self.assertEqual(0, code, events)
            self.assertTrue(output.is_file())
            data = output.read_bytes()
            self.assertEqual(b"CD001", data[32769:32774])
            self.assertIn(b"HELLO.TXT", data.upper())
            self.assertEqual("complete", events[-1]["event"])
            self.assertEqual(output.stat().st_size, events[-1]["size_bytes"])

    def test_multi_title_dvd_authoring_writes_one_pgc_per_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = [root / "one.mp4", root / "two.mkv"]
            for source in sources:
                source.write_bytes(b"video")
            workspace = root / "workspace"

            def fake_run(command: list[str], _stage: str) -> str | None:
                if command[0] == "ffmpeg.exe":
                    Path(command[-1]).write_bytes(b"mpeg")
                else:
                    document = ET.parse(command[-1])
                    authored = Path(document.getroot().attrib["dest"])
                    video_ts = authored / "VIDEO_TS"
                    video_ts.mkdir(parents=True)
                    (video_ts / "VIDEO_TS.IFO").write_bytes(b"ifo")
                return None

            with (
                mock.patch.object(SIDECAR, "find_ffmpeg", return_value="ffmpeg.exe"),
                mock.patch.object(SIDECAR, "find_dvdauthor", return_value="dvdauthor.exe"),
                mock.patch.object(SIDECAR, "_run_tool", side_effect=fake_run),
            ):
                error = SIDECAR._author_dvd(
                    [str(path) for path in sources], "ntsc", workspace
                )

            self.assertIsNone(error)
            document = ET.parse(workspace / "dvdauthor.xml")
            self.assertEqual(2, len(document.findall("./titleset/titles/pgc")))
            self.assertTrue((workspace / "authored" / "VIDEO_TS" / "VIDEO_TS.IFO").is_file())

    def test_dvd_parser_accepts_repeated_titles(self) -> None:
        args = SIDECAR.build_parser().parse_args(
            [
                "image-dvd", "--input", "one.mp4", "--input", "two.mp4",
                "--output", "movie.iso", "--standard", "pal",
            ]
        )
        self.assertEqual(["one.mp4", "two.mp4"], args.input)
        self.assertEqual("pal", args.standard)


if __name__ == "__main__":
    unittest.main()

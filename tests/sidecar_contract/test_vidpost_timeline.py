"""Regression tests for EDL and XML timeline import workflows."""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "vidpost" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("vidpost_sidecar", SIDECAR)
assert SPEC and SPEC.loader
vidpost = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = vidpost
SPEC.loader.exec_module(vidpost)


class VidpostTimelineTests(unittest.TestCase):
    def test_edl_import_writes_structured_csv(self) -> None:
        edl = """TITLE: UCX CUT
FCM: NON-DROP FRAME

001 AX V C 00:00:01:00 00:00:03:12 00:00:00:00 00:00:02:12
002 B002 A C 00:02:10:05 00:02:12:05 00:00:02:12 00:00:04:12
"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "cut.edl"
            output = root / "out"
            source.write_text(edl, encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()) as captured:
                result = vidpost.main([
                    "edl-to-csv", "--input", str(source),
                    "--output-dir", str(output),
                ])

            with (output / "cut.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            events = [json.loads(line) for line in captured.getvalue().splitlines()]

        self.assertEqual(0, result)
        self.assertEqual(["001", "002"], [row["num"] for row in rows])
        self.assertEqual("B002", rows[1]["reel"])
        self.assertEqual("00:02:10:05", rows[1]["tcin"])
        self.assertTrue(any(event.get("event") == "vidpost_doc" and event.get("events") == 2
                            for event in events))
        self.assertEqual("complete", events[-1]["event"])

    def test_fcpxml_import_reports_assets_and_sequence(self) -> None:
        fcpxml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.11">
  <resources>
    <format id="r1" name="FFVideoFormat1080p30" width="1920" height="1080" frameDuration="1/30s"/>
    <asset id="r2" name="scene.mov" src="file:///scene.mov" duration="90/30s" format="r1"/>
  </resources>
  <library><event name="UCX"><project name="Import Test"><sequence duration="90/30s" format="r1"><spine><clip name="scene"/></spine></sequence></project></event></library>
</fcpxml>
"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "timeline.fcpxml"
            output = root / "out"
            source.write_text(fcpxml, encoding="utf-8")

            result = vidpost.main([
                "fcpxml-info", "--input", str(source),
                "--output-dir", str(output),
            ])
            payload = json.loads((output / "fcpxml-info.json").read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual("1.11", payload[0]["version"])
        self.assertEqual(1, payload[0]["asset_count"])
        self.assertEqual("Import Test", payload[0]["sequences"][0]["project"])
        self.assertEqual(1, payload[0]["sequences"][0]["clip_count"])


if __name__ == "__main__":
    unittest.main()

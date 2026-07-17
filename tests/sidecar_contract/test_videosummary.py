"""Video Summarizer sidecar coverage (ROADMAP Item 55).

The extractive engine is pure standard library, so the transcript -> summary
+ chapters path runs everywhere with no models, GPU, or network. The
media-transcription and highlight-reel paths need whisper-stt / FFmpeg and
skip when unavailable.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "videosummary" / "sidecar.py"

SRT = """1
00:00:00,000 --> 00:00:06,000
Welcome to the workshop on renewable energy and solar panel installation.

2
00:00:06,000 --> 00:00:12,000
Solar panels convert sunlight into electricity using photovoltaic cells.

3
00:00:12,000 --> 00:00:18,000
Battery storage lets you keep solar electricity for use after sunset.

4
00:00:18,000 --> 00:00:24,000
Wind turbines are another renewable source that complements solar power.

5
00:00:24,000 --> 00:00:30,000
Combining wind and solar with battery storage gives a reliable off-grid system.

6
00:00:30,000 --> 00:00:36,000
Thank you for attending this renewable energy workshop today.
"""


def _events(output: str) -> list[dict]:
    events = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def _run(*extra: str, transcript: Path, out: Path) -> tuple[list[dict], str]:
    cmd = [sys.executable, str(SIDECAR), "summarize",
           "--transcript", str(transcript), "--output", str(out), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return _events(proc.stdout), proc.stdout + proc.stderr


class VideoSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.srt = self.dir / "talk.srt"
        self.srt.write_text(SRT, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plain_summary(self) -> None:
        out = self.dir / "summary.txt"
        events, diag = _run("--summary-length", "brief", transcript=self.srt, out=out)
        complete = next((e for e in events if e.get("event") == "complete"), None)
        self.assertIsNotNone(complete, msg=diag)
        self.assertEqual(complete.get("engine"), "extractive")
        self.assertTrue(out.is_file())
        text = out.read_text(encoding="utf-8")
        self.assertGreater(len(text.strip()), 0)
        # Extractive summary should surface the dominant topic.
        self.assertIn("solar", text.lower() + " renewable")

    def test_markdown_has_chapters(self) -> None:
        out = self.dir / "summary.md"
        events, diag = _run("--summary-format", "markdown", transcript=self.srt, out=out)
        complete = next((e for e in events if e.get("event") == "complete"), None)
        self.assertIsNotNone(complete, msg=diag)
        self.assertGreaterEqual(complete.get("chapters", 0), 1)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# Summary", text)
        self.assertIn("## Chapters", text)

    def test_youtube_chapters_start_at_zero(self) -> None:
        out = self.dir / "yt.txt"
        events, diag = _run("--summary-format", "youtube", transcript=self.srt, out=out)
        complete = next((e for e in events if e.get("event") == "complete"), None)
        self.assertIsNotNone(complete, msg=diag)
        text = out.read_text(encoding="utf-8")
        self.assertIn("Chapters:", text)
        # YouTube requires the first chapter timestamp to be 00:00.
        chapter_lines = [ln for ln in text.splitlines() if ln.strip().startswith(("00:00", "0:00"))]
        self.assertTrue(chapter_lines, msg=text)

    def test_no_chapters_flag(self) -> None:
        out = self.dir / "plain.txt"
        events, diag = _run("--no-chapters", transcript=self.srt, out=out)
        complete = next((e for e in events if e.get("event") == "complete"), None)
        self.assertIsNotNone(complete, msg=diag)
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("Chapters:", text)

    def test_export_transcript(self) -> None:
        out = self.dir / "s.txt"
        tx = self.dir / "transcript.txt"
        events, diag = _run("--export-transcript", str(tx), transcript=self.srt, out=out)
        complete = next((e for e in events if e.get("event") == "complete"), None)
        self.assertIsNotNone(complete, msg=diag)
        self.assertTrue(tx.is_file())
        self.assertIn("[00:00]", tx.read_text(encoding="utf-8"))

    def test_missing_input_errors(self) -> None:
        cmd = [sys.executable, str(SIDECAR), "summarize", "--output", str(self.dir / "x.txt")]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        events = _events(proc.stdout)
        err = next((e for e in events if e.get("event") == "error"), None)
        self.assertIsNotNone(err, msg=proc.stdout + proc.stderr)
        self.assertEqual(err.get("code"), "missing_input")


if __name__ == "__main__":
    unittest.main()

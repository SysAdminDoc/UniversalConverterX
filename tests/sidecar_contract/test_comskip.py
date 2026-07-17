import argparse
import importlib.util
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock


SIDECAR_PATH = Path(__file__).resolve().parents[2] / "tools" / "comskip" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ucx_comskip_sidecar", SIDECAR_PATH)
comskip = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(comskip)


class ComskipSidecarTests(TestCase):
    def test_parse_edl_and_keep_ranges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.edl"
            path.write_text("10.0 20.0 0\n40.5 45.0 0\n", encoding="utf-8")

            commercials = comskip.parse_edl(path)
            keep = comskip.keep_ranges(commercials, 60.0)

        self.assertEqual([
            {"start": 10.0, "end": 20.0, "action": "commercial"},
            {"start": 40.5, "end": 45.0, "action": "commercial"},
        ], commercials)
        self.assertEqual([
            {"start": 0.0, "end": 10.0},
            {"start": 20.0, "end": 40.5},
            {"start": 45.0, "end": 60.0},
        ], keep)

    def test_analyze_writes_non_destructive_report_edl_and_chapters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "recording.ts"
            source.write_bytes(b"original recording bytes")
            original = source.read_bytes()
            report = root / "result.json"

            def fake_comskip(command):
                work = Path(command[command.index("--output") + 1])
                name = command[command.index("--output-filename") + 1]
                (work / f"{name}.edl").write_text(
                    "10.000 20.000 0\n40.000 45.000 0\n", encoding="utf-8")
                return 0, ["100% complete"]

            args = argparse.Namespace(
                input=str(source), output=str(report), ini=None, comskip=None,
                threads=2, export_clean=None,
            )
            media = {
                "format": {"duration": "60.0"},
                "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            }
            with (
                mock.patch.object(comskip, "find_comskip", return_value="comskip.exe"),
                mock.patch.object(comskip, "find_ffprobe", return_value="ffprobe.exe"),
                mock.patch.object(comskip, "probe_media", return_value=media),
                mock.patch.object(comskip, "_run_comskip", side_effect=fake_comskip),
            ):
                result = comskip.op_analyze(args)

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(0, result)
            self.assertEqual(original, source.read_bytes())
            self.assertFalse(payload["sourceModified"])
            self.assertEqual(2, len(payload["commercialRanges"]))
            self.assertEqual(3, len(payload["keepRanges"]))
            self.assertTrue(report.with_suffix(".edl").is_file())
            chapters = report.with_suffix(".ffmeta").read_text(encoding="utf-8")
            self.assertIn("title=Commercial 1", chapters)
            self.assertIn("START=10000", chapters)

    def test_export_failure_retains_non_destructive_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "recording.ts"
            source.write_bytes(b"source")
            report = root / "result.json"
            clean = root / "clean.mp4"

            def fake_comskip(command):
                work = Path(command[command.index("--output") + 1])
                name = command[command.index("--output-filename") + 1]
                (work / f"{name}.edl").write_text("1 2 0\n", encoding="utf-8")
                return 0, []

            args = argparse.Namespace(
                input=str(source), output=str(report), ini=None, comskip=None,
                threads=None, export_clean=str(clean),
            )
            media = {"format": {"duration": "4"}, "streams": [{"codec_type": "video"}]}
            with (
                mock.patch.object(comskip, "find_comskip", return_value="comskip.exe"),
                mock.patch.object(comskip, "find_ffprobe", return_value="ffprobe.exe"),
                mock.patch.object(comskip, "find_ffmpeg", return_value="ffmpeg.exe"),
                mock.patch.object(comskip, "probe_media", return_value=media),
                mock.patch.object(comskip, "_run_comskip", side_effect=fake_comskip),
                mock.patch.object(comskip, "_export_clean", return_value=(False, "synthetic failure")),
            ):
                result = comskip.op_analyze(args)

            self.assertEqual(1, result)
            self.assertTrue(report.is_file())
            self.assertTrue(report.with_suffix(".edl").is_file())
            self.assertTrue(report.with_suffix(".ffmeta").is_file())
            self.assertFalse(clean.exists())

    def test_runtime_manifest_pins_every_build_input(self):
        manifest_path = SIDECAR_PATH.parent / "runtime-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual("55b0bcd018ddb9dacfad79addc48df55c1411073", manifest["sourceCommit"])
        self.assertEqual("GPL-2.0-only", manifest["license"])
        self.assertEqual(3, len(manifest["buildInputs"]))
        for build_input in manifest["buildInputs"]:
            self.assertGreater(build_input["size"], 0)
            self.assertRegex(build_input["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(build_input["url"].startswith("https://"))

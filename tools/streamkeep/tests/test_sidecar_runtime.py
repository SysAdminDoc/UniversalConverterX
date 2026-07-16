import argparse
import importlib.util
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock


SIDECAR_PATH = Path(__file__).resolve().parents[1] / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ucx_streamkeep_sidecar", SIDECAR_PATH)
sidecar = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sidecar)


class _FakeYoutubeDL:
    options = None

    def __init__(self, options):
        type(self).options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, _url, download=False):
        assert download is False
        return {
            "title": "Runtime probe",
            "extractor": "youtube",
            "formats": [{"format_id": "18", "height": 360}],
        }


class SidecarRuntimeTests(TestCase):
    def test_output_fallback_ignores_directories_and_preexisting_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            existing = output_dir / "older-download.mp4"
            existing.write_bytes(b"old")
            before = sidecar._snapshot_output_files(output_dir)
            (output_dir / "newest-directory").mkdir()
            downloaded = output_dir / "current-download.mp4"
            downloaded.write_bytes(b"current")

            selected = sidecar._select_download_output(output_dir, before)

        self.assertEqual(downloaded.resolve(), selected)

    def test_output_fallback_detects_overwritten_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            downloaded = output_dir / "same-name.mp4"
            downloaded.write_bytes(b"old")
            before = sidecar._snapshot_output_files(output_dir)
            downloaded.write_bytes(b"new-content-with-different-size")

            selected = sidecar._select_download_output(output_dir, before)

        self.assertEqual(downloaded.resolve(), selected)

    def test_reported_output_wins_over_newer_auxiliary_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            before = sidecar._snapshot_output_files(output_dir)
            downloaded = output_dir / "video.mp4"
            downloaded.write_bytes(b"video")
            (output_dir / "video.en.vtt").write_text("WEBVTT", encoding="utf-8")

            selected = sidecar._select_download_output(
                output_dir,
                before,
                str(downloaded))

        self.assertEqual(downloaded.resolve(), selected)

    def test_output_fallback_rejects_partial_and_unchanged_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            existing = output_dir / "existing.mp4"
            existing.write_bytes(b"existing")
            before = sidecar._snapshot_output_files(output_dir)
            (output_dir / "unfinished.webm.part").write_bytes(b"partial")

            selected = sidecar._select_download_output(output_dir, before)

        self.assertIsNone(selected)

    def test_missing_deno_has_actionable_warning(self):
        with mock.patch.object(sidecar, "find_deno", return_value=None):
            status = sidecar.deno_runtime_status()

        self.assertFalse(status["active"])
        self.assertEqual("2.3.0", status["minimum_version"])
        self.assertIn("Settings > Converter Tools", status["detail"])

    def test_probe_reports_active_deno_and_configures_yt_dlp(self):
        runtime = {
            "runtime": "deno",
            "active": True,
            "path": "C:/ucx/tools/bin/deno.exe",
            "version": "2.9.3",
            "minimum_version": "2.3.0",
            "detail": "Deno 2.9.3 is active for yt-dlp EJS challenges.",
        }
        fake_module = SimpleNamespace(
            YoutubeDL=_FakeYoutubeDL,
            utils=SimpleNamespace(DownloadError=RuntimeError),
        )
        output = io.StringIO()
        with (
            mock.patch.object(sidecar, "yt_dlp", fake_module),
            mock.patch.object(sidecar, "find_ytdlp", return_value=None),
            mock.patch.object(sidecar, "deno_runtime_status", return_value=runtime),
            mock.patch.object(sidecar, "_cookie_file", return_value=None),
            mock.patch.object(sidecar.sys, "stdout", output),
        ):
            result = sidecar.op_probe(argparse.Namespace(url="https://youtube.test/watch?v=1"))

        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(0, result)
        self.assertTrue(events[0]["active"])
        self.assertTrue(events[-1]["probe"]["js_runtime"]["active"])
        self.assertEqual(
            {"deno": {"path": runtime["path"]}},
            _FakeYoutubeDL.options["js_runtimes"],
        )

    def test_external_invocation_never_delegates_to_aria2c(self):
        runtime = {"active": True, "path": "C:/ucx/tools/bin/deno.exe"}
        with (
            mock.patch.object(sidecar, "find_ffmpeg", return_value=None),
            mock.patch.object(sidecar, "_cookie_file", return_value=None),
        ):
            arguments = sidecar._external_base_args(runtime)

        self.assertNotIn("--downloader", arguments)
        self.assertNotIn("aria2c", arguments)
        self.assertEqual("deno:C:/ucx/tools/bin/deno.exe", arguments[-1])

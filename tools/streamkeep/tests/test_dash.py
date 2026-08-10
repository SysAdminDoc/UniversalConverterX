import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep.dash import parse_mpd_xml_details
from streamkeep.models import QualityInfo
from streamkeep.scrape import _dash_stream_info


FIXTURE = Path(__file__).parent / "fixtures" / "dynamic_live.mpd"


class DashRecordingTests(unittest.TestCase):
    def test_dynamic_fixture_exposes_bounded_recording_metadata(self):
        qualities, manifest = parse_mpd_xml_details(
            FIXTURE.read_text(encoding="utf-8"),
            "https://cdn.example.test/live/manifest.mpd",
        )

        self.assertEqual(3, len(qualities))
        self.assertTrue(manifest.is_dynamic)
        self.assertEqual(2.0, manifest.minimum_update_period_secs)
        self.assertEqual(30.0, manifest.time_shift_buffer_depth_secs)
        self.assertEqual(2.0, qualities[0].segment_duration_secs)
        self.assertTrue(all(q.is_dynamic for q in qualities))
        self.assertTrue(all(q.url.endswith("manifest.mpd") for q in qualities))

    def test_dynamic_manifest_without_segment_addressing_is_rejected_precisely(self):
        logs = []
        xml = """
        <MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="dynamic">
          <Period><AdaptationSet mimeType="video/mp4">
            <Representation id="bare" width="640" height="360" />
          </AdaptationSet></Period>
        </MPD>
        """

        qualities, manifest = parse_mpd_xml_details(
            xml, "https://cdn.example.test/live/manifest.mpd", logs.append
        )

        self.assertEqual([], qualities)
        self.assertIn("no usable SegmentTemplate or SegmentList", manifest.unsupported_reason)
        self.assertTrue(any("no SegmentTemplate or SegmentList" in line for line in logs))

    def test_scrape_metadata_marks_dynamic_stream_as_live_and_bounded(self):
        quality = QualityInfo(
            name="720p",
            url="https://cdn.example.test/live/manifest.mpd",
            format_type="dash",
            is_dynamic=True,
            segment_duration_secs=2.0,
            minimum_update_period_secs=2.0,
            time_shift_buffer_depth_secs=30.0,
        )

        info = _dash_stream_info(
            quality.url, "manifest.mpd", "channel", [quality]
        )

        self.assertTrue(info.is_live)
        self.assertTrue(info.is_dynamic)
        self.assertEqual("Live (bounded recording)", info.duration_str)
        self.assertEqual(2.0, info.segment_duration_secs)

    def test_dynamic_worker_rejects_unbounded_capture_before_output(self):
        from streamkeep.workers.download import DownloadWorker

        with tempfile.TemporaryDirectory() as tmpdir:
            errors = []
            worker = DownloadWorker(
                "https://cdn.example.test/live/manifest.mpd",
                [(0, "live", 0, 0)],
                tmpdir,
                "dash",
            )
            worker.dynamic_manifest = True
            worker.error.connect(lambda _idx, message: errors.append(message))
            with mock.patch("streamkeep.workers.download.subprocess.Popen") as popen:
                worker.run()

            popen.assert_not_called()
            self.assertEqual([], list(Path(tmpdir).iterdir()))
            self.assertIn("requires a positive duration", errors[0])

    def test_dynamic_worker_builds_reconnect_options(self):
        from streamkeep.workers.download import DownloadWorker

        worker = DownloadWorker("manifest.mpd", [], ".", "dash")
        self.assertEqual([], worker._dash_input_options())
        worker.dynamic_manifest = True
        options = worker._dash_input_options()
        self.assertIn("-reconnect_streamed", options)
        self.assertIn("-reconnect_on_network_error", options)
        self.assertIn("-reconnect_on_http_error", options)
        self.assertIn("-fflags", options)

    def test_bounded_dynamic_worker_passes_duration_and_recovery_to_ffmpeg(self):
        from streamkeep.workers.download import DownloadWorker

        with tempfile.TemporaryDirectory() as tmpdir:
            commands = []

            class _Process:
                returncode = 0
                stderr = []

                def wait(self):
                    return self.returncode

            def fake_popen(command, **_kwargs):
                commands.append(command)
                (Path(tmpdir) / "live.mp4").write_bytes(b"bounded capture")
                return _Process()

            worker = DownloadWorker(
                "https://cdn.example.test/live/manifest.mpd",
                [(0, "live", 0, 6)],
                tmpdir,
                "dash",
            )
            worker.dynamic_manifest = True
            worker.max_retries = 0
            with mock.patch(
                "streamkeep.workers.download.subprocess.Popen", side_effect=fake_popen
            ):
                worker.run()

            self.assertEqual(1, len(commands))
            self.assertIn("-reconnect_streamed", commands[0])
            self.assertIn("-reconnect_on_http_error", commands[0])
            self.assertIn(["-t", "6"], [commands[0][i:i + 2] for i in range(len(commands[0]) - 1)])
            self.assertTrue((Path(tmpdir) / "live.mp4").is_file())

    def test_cli_exposes_finite_duration_and_segment_bounds(self):
        from streamkeep.cli import build_parser

        args = build_parser().parse_args(
            ["download", "https://cdn.example.test/live.mpd", "--record-segments", "5"]
        )
        self.assertEqual(5, args.record_segments)
        self.assertEqual(0, args.record_seconds)
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                ["download", "https://cdn.example.test/live.mpd", "--record-seconds", "0"]
            )


if __name__ == "__main__":
    unittest.main()

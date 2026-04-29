import unittest
from unittest import mock

from streamkeep.models import QualityInfo
from streamkeep.scrape import detect_direct_media


class ScrapeTests(unittest.TestCase):
    @mock.patch("streamkeep.scrape.http_probe")
    def test_detect_direct_media_uses_redirected_playlist_extension(self, mock_probe):
        mock_probe.return_value = {
            "status": 200,
            "content_type": "",
            "final_url": "https://cdn.example.com/channel/master.m3u8?token=abc",
        }

        info = detect_direct_media("https://example.com/watch?id=123")

        self.assertIsNotNone(info)
        self.assertEqual(info.url, "https://cdn.example.com/channel/master.m3u8?token=abc")
        self.assertEqual(info.qualities[0].format_type, "hls")

    @mock.patch("streamkeep.dash.parse_mpd")
    @mock.patch("streamkeep.scrape.http_probe")
    def test_detect_direct_media_parses_redirected_dash_manifests(
        self,
        mock_probe,
        mock_parse_mpd,
    ):
        mock_probe.return_value = {
            "status": 200,
            "content_type": "application/octet-stream",
            "final_url": "https://cdn.example.com/channel/manifest.mpd",
        }
        mock_parse_mpd.return_value = [
            QualityInfo(name="1080p", url="https://cdn.example.com/seg.m4s", format_type="dash")
        ]

        info = detect_direct_media("https://example.com/watch?id=456")

        self.assertIsNotNone(info)
        mock_parse_mpd.assert_called_once_with(
            "https://cdn.example.com/channel/manifest.mpd",
            log_fn=None,
        )
        self.assertEqual(info.url, "https://cdn.example.com/channel/manifest.mpd")
        self.assertEqual(info.qualities, mock_parse_mpd.return_value)


if __name__ == "__main__":
    unittest.main()

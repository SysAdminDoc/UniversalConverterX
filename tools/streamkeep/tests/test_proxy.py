import os
import unittest
from types import SimpleNamespace
from unittest import mock

from streamkeep import proxy


class ProxyTests(unittest.TestCase):
    def tearDown(self):
        proxy.set_pool([])
        proxy.set_fallback("")

    def test_resolve_proxy_normalizes_platform_names(self):
        proxy.set_pool([
            {
                "url": "http://proxy.local:8080",
                "platforms": [" Twitch ", "KICK"],
                "enabled": True,
            }
        ])

        resolved = proxy.resolve_proxy("https://www.twitch.tv/example")

        self.assertEqual(resolved, "http://proxy.local:8080")

    def test_health_check_uses_platform_null_device(self):
        completed = SimpleNamespace(returncode=0, stdout=b"0.125", stderr=b"")
        with mock.patch("streamkeep.proxy.subprocess.run", return_value=completed) as run:
            ok, latency = proxy.health_check("http://proxy.local:8080")

        self.assertTrue(ok)
        self.assertEqual(latency, 125)
        cmd = run.call_args.args[0]
        self.assertIn(os.devnull, cmd)


if __name__ == "__main__":
    unittest.main()

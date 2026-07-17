"""Supply-chain integrity coverage for shared verified asset downloads."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "_lib" / "ucx_assets.py"
SPEC = importlib.util.spec_from_file_location("ucx_assets_contract", MODULE_PATH)
assert SPEC and SPEC.loader
ASSETS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ASSETS
SPEC.loader.exec_module(ASSETS)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return None


class VerifiedAssetTests(unittest.TestCase):
    def test_offline_guard_blocks_socket_connections(self) -> None:
        script = f"""
import socket, sys
sys.path.insert(0, {str((ROOT / 'tools' / '_lib')).__repr__()})
from ucx_assets import NetworkDisabled, enforce_offline
enforce_offline()
try:
    socket.create_connection(('127.0.0.1', 9))
except NetworkDisabled:
    raise SystemExit(0)
raise SystemExit(1)
"""
        result = __import__("subprocess").run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_license_gate_runs_before_network_access(self) -> None:
        asset = ASSETS.VerifiedAsset(
            "fixture", "fixture.bin", "https://127.0.0.1:1/never",
            3, hashlib.sha256(b"abc").hexdigest(), "MIT")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ASSETS.LicenseNotAccepted):
                ASSETS.download_verified(Path(temp), asset, accept_license=False)
            self.assertEqual([], list(Path(temp).iterdir()))

    def test_exact_download_is_promoted_and_reverified(self) -> None:
        payload = b"verified fixture payload"
        with tempfile.TemporaryDirectory() as source_temp, tempfile.TemporaryDirectory() as cache_temp:
            source = Path(source_temp)
            (source / "fixture.bin").write_bytes(payload)
            handler = lambda *args, **kwargs: _QuietHandler(  # noqa: E731
                *args, directory=source, **kwargs)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                asset = ASSETS.VerifiedAsset(
                    "fixture",
                    "fixture.bin",
                    f"https://example.invalid/fixture.bin",
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                    "MIT",
                )
                # Keep production metadata HTTPS-only; redirect the test request
                # through the local server without weakening that constructor.
                local_asset = object.__new__(ASSETS.VerifiedAsset)
                for key, value in asset.__dict__.items():
                    object.__setattr__(local_asset, key, value)
                object.__setattr__(
                    local_asset, "url",
                    f"http://127.0.0.1:{server.server_port}/fixture.bin")

                installed = ASSETS.download_verified(
                    Path(cache_temp), local_asset, accept_license=True)
                self.assertEqual(payload, installed.read_bytes())
                ASSETS.validate_asset(installed, asset)
                installed.write_bytes(b"tampered")
                self.assertIsNone(ASSETS.cached_asset(Path(cache_temp), asset))
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_hash_mismatch_never_replaces_existing_file(self) -> None:
        payload = b"wrong payload"
        with tempfile.TemporaryDirectory() as source_temp, tempfile.TemporaryDirectory() as cache_temp:
            source = Path(source_temp)
            cache = Path(cache_temp)
            (source / "fixture.bin").write_bytes(payload)
            existing = cache / "fixture.bin"
            existing.write_bytes(b"existing")
            handler = lambda *args, **kwargs: _QuietHandler(  # noqa: E731
                *args, directory=source, **kwargs)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                asset = ASSETS.VerifiedAsset(
                    "fixture", "fixture.bin", "https://example.invalid/fixture.bin",
                    len(payload), hashlib.sha256(b"expected").hexdigest(), "MIT")
                object.__setattr__(
                    asset, "url",
                    f"http://127.0.0.1:{server.server_port}/fixture.bin")
                with self.assertRaises(ASSETS.IntegrityError):
                    ASSETS.download_verified(cache, asset, accept_license=True)
                self.assertEqual(b"existing", existing.read_bytes())
                self.assertFalse(any(path.suffix == ".part" for path in cache.iterdir()))
            finally:
                server.shutdown()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

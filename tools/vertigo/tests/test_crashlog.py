"""Coverage for the frozen-safe crash log sink."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import crashlog


class CrashLogPathTests(unittest.TestCase):
    """Path resolution must honour the override and pick the right OS home."""

    def setUp(self) -> None:
        self._override = os.environ.pop("VERTIGO_CRASH_LOG", None)

    def tearDown(self) -> None:
        os.environ.pop("VERTIGO_CRASH_LOG", None)
        if self._override is not None:
            os.environ["VERTIGO_CRASH_LOG"] = self._override

    def test_env_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "custom.log"
            os.environ["VERTIGO_CRASH_LOG"] = str(target)
            self.assertEqual(crashlog.crash_log_path(), target)

    def test_windows_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(crashlog.sys, "platform", "win32"):
            os.environ["LOCALAPPDATA"] = tmp
            path = crashlog.crash_log_path()
            self.assertTrue(str(path).startswith(tmp))
            self.assertEqual(path.name, "crash.log")

    def test_macos_path(self) -> None:
        with mock.patch.object(crashlog.sys, "platform", "darwin"):
            path = crashlog.crash_log_path()
            self.assertIn("Library/Logs/Vertigo", str(path).replace("\\", "/"))
            self.assertEqual(path.name, "crash.log")

    def test_linux_xdg_state_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(crashlog.sys, "platform", "linux"):
            os.environ["XDG_STATE_HOME"] = tmp
            try:
                path = crashlog.crash_log_path()
                self.assertTrue(str(path).startswith(tmp))
                self.assertEqual(path.name, "crash.log")
                # Case must match vertigo.py::_log_dir exactly — "Vertigo",
                # not "vertigo". Mixing up case used to split the bootstrap
                # log and the runtime log into two different directories.
                self.assertIn("Vertigo", path.parts)
            finally:
                os.environ.pop("XDG_STATE_HOME", None)

    def test_windows_appdata_fallback_when_localappdata_unset(self) -> None:
        """APPDATA should be used when LOCALAPPDATA is missing — matches
        the bootstrap's `_log_dir` resolution order."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(crashlog.sys, "platform", "win32"):
            had_local = os.environ.pop("LOCALAPPDATA", None)
            os.environ["APPDATA"] = tmp
            try:
                path = crashlog.crash_log_path()
                self.assertTrue(
                    str(path).startswith(tmp),
                    f"APPDATA fallback ignored: {path}",
                )
            finally:
                os.environ.pop("APPDATA", None)
                if had_local is not None:
                    os.environ["LOCALAPPDATA"] = had_local

    def test_never_writes_into_meipass(self) -> None:
        # A PyInstaller one-file build sets ``sys._MEIPASS``. Force each
        # platform's native base dir to point *inside* that staging path
        # and confirm the guard refuses — that's the only way this test
        # actually proves the frozen-build contract. The prior form
        # passed for unrelated reasons (none of the defaults landed in
        # the mocked tmp).
        with tempfile.TemporaryDirectory() as tmp:
            meipass = str(Path(tmp).resolve())

            # win32 — LOCALAPPDATA aimed at MEIPASS
            with mock.patch.object(crashlog.sys, "_MEIPASS", meipass, create=True), \
                 mock.patch.object(crashlog.sys, "platform", "win32"):
                os.environ["LOCALAPPDATA"] = meipass
                try:
                    path = crashlog.crash_log_path()
                    self.assertFalse(
                        crashlog._is_under(path, Path(meipass)),
                        f"win32 path {path} fell inside MEIPASS {meipass}",
                    )
                finally:
                    os.environ.pop("LOCALAPPDATA", None)

            # linux — XDG_STATE_HOME aimed at MEIPASS
            with mock.patch.object(crashlog.sys, "_MEIPASS", meipass, create=True), \
                 mock.patch.object(crashlog.sys, "platform", "linux"):
                os.environ["XDG_STATE_HOME"] = meipass
                try:
                    path = crashlog.crash_log_path()
                    self.assertFalse(
                        crashlog._is_under(path, Path(meipass)),
                        f"linux path {path} fell inside MEIPASS {meipass}",
                    )
                finally:
                    os.environ.pop("XDG_STATE_HOME", None)

            # override env pointed directly at MEIPASS must also bounce
            with mock.patch.object(crashlog.sys, "_MEIPASS", meipass, create=True):
                os.environ["VERTIGO_CRASH_LOG"] = str(Path(meipass) / "crash.log")
                try:
                    path = crashlog.crash_log_path()
                    self.assertFalse(
                        crashlog._is_under(path, Path(meipass)),
                        f"override path {path} bypassed the MEIPASS guard",
                    )
                finally:
                    os.environ.pop("VERTIGO_CRASH_LOG", None)


class CrashLogAppendTests(unittest.TestCase):
    """Append semantics — timestamped, rotation-capped, never raises."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target = Path(self._tmp.name) / "crash.log"
        os.environ["VERTIGO_CRASH_LOG"] = str(self.target)
        self.addCleanup(lambda: os.environ.pop("VERTIGO_CRASH_LOG", None))

    def test_append_writes_and_timestamps(self) -> None:
        result = crashlog.append("hello world")
        self.assertEqual(result, self.target)
        body = self.target.read_text(encoding="utf-8")
        self.assertIn("hello world", body)
        self.assertRegex(body, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

    def test_append_falls_back_to_temp_on_bad_parent(self) -> None:
        """Primary path fails mkdir → append lands in the TEMP fallback.

        The older behaviour was "return None silently" — but losing the
        breadcrumb on a sandboxed environment was the exact failure
        mode R8 harmonises against the bootstrap's TEMP escape hatch.
        """
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fake_dir = f.name
        self.addCleanup(lambda: os.unlink(fake_dir))
        os.environ["VERTIGO_CRASH_LOG"] = str(Path(fake_dir) / "crash.log")
        result = crashlog.append("temp-fallback breadcrumb")
        # Either the TEMP fallback caught it, or both writers hit the
        # same unwritable mount — the None branch is still valid but
        # in practice TEMP should succeed on every supported platform.
        if result is None:
            self.skipTest("TEMP fallback unwritable on this host")
        self.assertTrue(result.exists())
        body = result.read_text(encoding="utf-8")
        self.assertIn("temp-fallback breadcrumb", body)
        # Tidy — the fallback lives in %TEMP% which we don't own.
        try:
            result.unlink()
        except Exception:
            pass

    def test_rotation_caps_file_size(self) -> None:
        # Pre-seed with twice the cap then append; the rotator should
        # truncate to the tail window.
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(b"x" * (crashlog._MAX_BYTES * 2))
        crashlog.append("after rotation")
        size = self.target.stat().st_size
        self.assertLessEqual(size, crashlog._MAX_BYTES)
        self.assertIn(b"after rotation", self.target.read_bytes())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

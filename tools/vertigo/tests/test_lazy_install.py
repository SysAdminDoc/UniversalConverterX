"""Regression tests for the unified ``core._lazy`` install helper.

Pins two contracts:

* **v0.12.0 fork-bomb fix.** Every opt-in ``core/*`` module that
  pip-installs on demand must route through
  :func:`core._lazy.pip_install` *and* that helper must short-circuit
  when :func:`core._lazy.is_frozen` is True. If a future change
  re-introduces the per-module copy of ``_try_pip_install`` using
  ``[sys.executable, "-m", "pip", ...]``, this test will fail.
* **v0.12.3 R7 crashlog-breadcrumb contract.** The every-strategy-failed
  path lands in the persistent crash log, never in a stderr handle
  that PyInstaller's GUI bundle discards. The frozen short-circuit
  stays quiet — no crashlog noise from binaries that merely decline
  to install.

Why this matters: ``sys.executable`` in a PyInstaller build is
``Vertigo.exe`` itself, so spawning it with ``-m pip`` does not run pip
— it launches another GUI instance, which then re-hits the same code
path, forking until the OS reaps it. ``vertigo.py::_pip_install`` has
guarded this at the bootstrap layer since v0.1; the eight opt-in
modules hadn't, until now.
"""
from __future__ import annotations

import importlib
import subprocess
import unittest
from unittest import mock


OPT_IN_MODULES = (
    "core.subtitles",
    "core.vad",
    "core.animated_captions",
    "core.tracker_boxmot",
    "core.highlights",
    "core.keyframes",
    "core.diarize",
    "core.broll",
)

OPT_IN_ENSURE_FUNCS: tuple[tuple[str, str], ...] = (
    ("core.subtitles", "ensure_installed"),
    ("core.vad", "ensure_installed"),
    ("core.animated_captions", "ensure_installed"),
    ("core.tracker_boxmot", "ensure_installed"),
    ("core.highlights", "ensure_installed"),
    ("core.keyframes", "ensure_installed"),
    ("core.diarize", "ensure_installed"),
    # broll has three separate ensure_* entry points, each for a different optional dep.
    ("core.broll", "ensure_pypexels_installed"),
    ("core.broll", "ensure_keybert_installed"),
    ("core.broll", "ensure_open_clip_installed"),
)


class LazyInstallFrozenGuardTests(unittest.TestCase):
    """Frozen-build must never spawn pip subprocesses."""

    def test_pip_install_returns_false_when_frozen(self) -> None:
        from core import _lazy

        with mock.patch.object(_lazy, "is_frozen", return_value=True):
            sentinel = mock.MagicMock(return_value=0)
            with mock.patch.object(_lazy, "_pip_runner", sentinel):
                self.assertFalse(_lazy.pip_install("doesnotmatter>=0"))
                sentinel.assert_not_called()

    def test_pip_install_runs_commands_when_not_frozen(self) -> None:
        from core import _lazy

        # success on the first strategy
        runner = mock.MagicMock(return_value=0)
        with mock.patch.object(_lazy, "is_frozen", return_value=False):
            with mock.patch.object(_lazy, "_pip_runner", runner):
                self.assertTrue(_lazy.pip_install("fakepkg>=0"))
        self.assertEqual(runner.call_count, 1)
        cmd = runner.call_args[0][0]
        self.assertIn("pip", cmd)
        self.assertIn("install", cmd)
        self.assertEqual(cmd[-1], "fakepkg>=0")

    def test_pip_install_tries_all_three_strategies(self) -> None:
        from core import _lazy

        # non-zero return from each → three attempts
        runner = mock.MagicMock(return_value=1)
        with mock.patch.object(_lazy, "is_frozen", return_value=False):
            with mock.patch.object(_lazy, "_pip_runner", runner):
                self.assertFalse(_lazy.pip_install("fakepkg>=0"))
        self.assertEqual(runner.call_count, 3)

    def test_pip_install_swallows_subprocess_errors(self) -> None:
        from core import _lazy

        runner = mock.MagicMock(side_effect=OSError("boom"))
        with mock.patch.object(_lazy, "is_frozen", return_value=False):
            with mock.patch.object(_lazy, "_pip_runner", runner):
                self.assertFalse(_lazy.pip_install("fakepkg>=0"))
        self.assertEqual(runner.call_count, 3)

    def test_pip_install_failure_breadcrumbs_crashlog(self) -> None:
        """Every-strategy-failed path must leave a crumb in crash.log.

        Frozen builds drop stderr, so the old ``print(file=sys.stderr)``
        branch was effectively invisible on the very binaries where the
        forensic value was highest. R7 routes through ``core.crashlog``
        instead; pin that here so a regression that reverts to stderr
        fails loudly.
        """
        import os
        import tempfile
        from core import _lazy

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "crash.log")
            os.environ["VERTIGO_CRASH_LOG"] = target
            try:
                runner = mock.MagicMock(side_effect=OSError("pip missing"))
                with mock.patch.object(_lazy, "is_frozen", return_value=False):
                    with mock.patch.object(_lazy, "_pip_runner", runner):
                        self.assertFalse(_lazy.pip_install("fakepkg>=0"))
                self.assertTrue(os.path.exists(target), "crash.log was not created")
                body = open(target, encoding="utf-8").read()
                self.assertIn("fakepkg>=0", body)
                self.assertIn("OSError", body)
            finally:
                os.environ.pop("VERTIGO_CRASH_LOG", None)

    def test_frozen_path_writes_nothing_to_crashlog(self) -> None:
        """Frozen short-circuit must never touch crash.log either —
        we don't want a binary that *declines* to install to still
        leave log detritus on every opt-in call."""
        import os
        import tempfile
        from core import _lazy

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "crash.log")
            os.environ["VERTIGO_CRASH_LOG"] = target
            try:
                with mock.patch.object(_lazy, "is_frozen", return_value=True):
                    self.assertFalse(_lazy.pip_install("frozendep>=0"))
                self.assertFalse(
                    os.path.exists(target),
                    "frozen path created a crash.log entry",
                )
            finally:
                os.environ.pop("VERTIGO_CRASH_LOG", None)

    def test_default_runner_is_subprocess_call(self) -> None:
        from core import _lazy

        self.assertIs(_lazy._pip_runner, subprocess.call)

    def test_no_private_try_pip_install_leftover(self) -> None:
        """No module should re-carry the deprecated per-file helper."""
        for mod_name in OPT_IN_MODULES:
            mod = importlib.import_module(mod_name)
            self.assertFalse(
                hasattr(mod, "_try_pip_install"),
                f"{mod_name} still exposes _try_pip_install — should route via core._lazy.",
            )

    def test_opt_in_ensure_funcs_block_install_when_frozen(self) -> None:
        """Every ensure_installed entry point must surface a False when frozen
        and the dep is absent. We force is_available → False so the code path
        reaches pip_install; then assert pip_install never actually ran.
        """
        from core import _lazy

        for mod_name, func_name in OPT_IN_ENSURE_FUNCS:
            with self.subTest(module=mod_name, func=func_name):
                mod = importlib.import_module(mod_name)
                func = getattr(mod, func_name)

                availability_fn_name = _availability_fn_for(mod_name, func_name)
                availability_fn = getattr(mod, availability_fn_name)

                with mock.patch.object(mod, availability_fn_name, return_value=False):
                    runner = mock.MagicMock(return_value=0)
                    with mock.patch.object(_lazy, "is_frozen", return_value=True), \
                         mock.patch.object(_lazy, "_pip_runner", runner):
                        result = func()
                    self.assertFalse(result, f"{mod_name}.{func_name}() returned True under frozen build")
                    self.assertEqual(
                        runner.call_count,
                        0,
                        f"{mod_name}.{func_name}() spawned pip while frozen — fork-bomb hazard",
                    )
                # sanity — availability fn still exists and is callable
                self.assertTrue(callable(availability_fn))


def _availability_fn_for(mod_name: str, func_name: str) -> str:
    """Map an ensure_* function to the is_available()-style check it gates on."""
    if mod_name == "core.broll":
        return {
            "ensure_pypexels_installed": "_pypexels_available",
            "ensure_keybert_installed": "is_keybert_available",
            "ensure_open_clip_installed": "is_clip_available",
        }[func_name]
    # core.subtitles historically exposes both is_installed() and also relies on a
    # bare import inside ensure_installed(); patch the import-level fn it actually calls.
    if mod_name == "core.subtitles":
        return "is_installed"
    return "is_available"


if __name__ == "__main__":
    unittest.main()

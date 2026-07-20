"""Unit tests for the shared UniversalConverterX sidecar primitives."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ucx_sidecar as u  # noqa: E402


class RunTimeoutTests(unittest.TestCase):
    def test_success_path_returns_completed_process(self):
        result = u.run([sys.executable, "-c", "print('hi')"], timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hi", result.stdout)

    def test_timeout_raises_subprocess_timeout(self):
        with self.assertRaises(u.SubprocessTimeout) as ctx:
            u.run(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=0.3,
            )
        self.assertIn("timeout", str(ctx.exception).lower())

    def test_default_timeout_is_applied(self):
        # The stdlib default is None (wait forever); the wrapper must always
        # pass a concrete ceiling.
        self.assertEqual(u.DEFAULT_SUBPROCESS_TIMEOUT, 600)

    def test_nonzero_exit_is_not_raised_without_check(self):
        result = u.run([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
        self.assertEqual(result.returncode, 3)

    def test_check_true_raises_on_nonzero_exit(self):
        import subprocess
        with self.assertRaises(subprocess.CalledProcessError):
            u.run(
                [sys.executable, "-c", "import sys; sys.exit(4)"],
                timeout=30,
                check=True,
            )


if __name__ == "__main__":
    unittest.main()

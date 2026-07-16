"""Regression tests for sidecars that must not mutate Python at runtime."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SIDECARS = (
    REPO / "tools" / "whisper-stt" / "sidecar.py",
    REPO / "tools" / "heicshift" / "sidecar.py",
)


class RuntimeDependencyPolicyTests(unittest.TestCase):
    def test_sidecars_never_invoke_pip(self) -> None:
        for path in SIDECARS:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            with self.subTest(sidecar=path.parent.name):
                self.assertNotIn("--break-system-packages", source)
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.List, ast.Tuple)):
                        continue
                    values = {
                        item.value
                        for item in node.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    }
                    self.assertFalse(
                        {"pip", "install"}.issubset(values),
                        f"{path} invokes pip at runtime on line {node.lineno}",
                    )

    def test_missing_dependencies_have_actionable_non_installing_errors(self) -> None:
        for path in SIDECARS:
            source = path.read_text(encoding="utf-8")
            with self.subTest(sidecar=path.parent.name):
                self.assertIn('"missing_dep"', source)
                self.assertIn("Provision ", source)
                self.assertIn("environment, then retry.", source)
                self.assertNotIn("installing...", source.lower())


if __name__ == "__main__":
    unittest.main()

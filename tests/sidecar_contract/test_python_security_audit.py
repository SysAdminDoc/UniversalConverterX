"""Static regression checks for the Python sidecar security boundary."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"


def _calls(tree: ast.AST, names: set[str]):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in names:
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
            yield node


class PythonSecurityAuditTests(unittest.TestCase):
    def test_sidecar_capture_subprocesses_have_timeouts(self):
        violations: list[str] = []
        for path in TOOLS.rglob("sidecar.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in _calls(tree, {"run", "call", "check_call", "check_output"}):
                if not any(keyword.arg == "timeout" for keyword in node.keywords):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations, "unbounded sidecar subprocesses: " + ", ".join(violations))

    def test_clipforge_operation_modules_have_timeouts(self):
        violations: list[str] = []
        for path in (TOOLS / "clipforge" / "clipforge_ops").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in _calls(tree, {"run", "call", "check_call", "check_output"}):
                if not any(keyword.arg == "timeout" for keyword in node.keywords):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations, "unbounded ClipForge operation subprocesses: " + ", ".join(violations))

    def test_sidecars_do_not_call_archive_extract_directly(self):
        violations: list[str] = []
        for path in TOOLS.rglob("sidecar.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr in {"extract", "extractall"}:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations, "unsafe direct archive extraction: " + ", ".join(violations))

    def test_archive_write_paths_use_shared_guards(self):
        expected = {
            "tools/comic/sidecar.py": "safe_zip_extractall",
            "tools/diagrammore/sidecar.py": "safe_zip_extractall",
            "tools/gameasset/sidecar.py": "safe_zip_extractall",
            "tools/gistiles/sidecar.py": "safe_zip_extractall",
            "tools/morearchive/sidecar.py": "safe_zip_extractall",
            "tools/notetaking/sidecar.py": "safe_zip_extractall",
            "tools/socialarchives/sidecar.py": "safe_zip_extract_member",
        }
        for relative, symbol in expected.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(symbol, source, relative)


class PureParserSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = TOOLS / "gameasset" / "sidecar.py"
        spec = importlib.util.spec_from_file_location("ucx_gameasset_security", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path}")
        cls.gameasset = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gameasset)

    def test_pak_directory_must_fit_inside_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.pak"
            path.write_bytes(b"PACK" + struct.pack("<II", 12, 64))
            with self.assertRaises(ValueError):
                self.gameasset._read_pak(path)

    def test_wad_directory_must_fit_inside_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.wad"
            path.write_bytes(b"PWAD" + struct.pack("<II", 1, 12))
            with self.assertRaises(ValueError):
                self.gameasset._read_wad(path)

    def test_pck_entry_count_cannot_overrun_header(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.pck"
            path.write_bytes(
                b"GDPC"
                + struct.pack("<I", 1)
                + b"\0" * 12
                + b"\0" * 4
                + b"\0" * 8
                + b"\0" * 64
                + struct.pack("<I", 0xFFFFFFFF)
            )
            with self.assertRaises(ValueError):
                self.gameasset._read_pck(path)


if __name__ == "__main__":
    unittest.main()

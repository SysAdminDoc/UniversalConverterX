import json
import sys
import tempfile
import unittest
from pathlib import Path

from streamkeep import plugins


class PluginTests(unittest.TestCase):
    def test_load_plugin_appends_parent_path_without_prepending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            plugin_dir = base / "example_plugin"
            plugin_dir.mkdir()
            (plugin_dir / "plugin.json").write_text(
                json.dumps({"id": "example", "enabled": True}),
                encoding="utf-8",
            )
            (plugin_dir / "__init__.py").write_text("LOADED = True\n", encoding="utf-8")
            info = {
                "id": "example",
                "enabled": True,
                "path": str(plugin_dir),
                "version": "1.0.0",
            }

            original_sys_path = list(sys.path)
            try:
                loaded = plugins.load_plugin(info)
                self.assertTrue(loaded)
                self.assertEqual(sys.path[0], original_sys_path[0])
                self.assertEqual(sys.path[-1], str(base))
            finally:
                sys.path[:] = original_sys_path


if __name__ == "__main__":
    unittest.main()

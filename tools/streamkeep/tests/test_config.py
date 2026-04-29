import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep import config


class ConfigTests(unittest.TestCase):
    def test_load_config_falls_back_to_backup_when_primary_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            backup_file = config_dir / "config.json.bak"
            config_file.write_text("{not valid json", encoding="utf-8")
            backup_file.write_text('{"theme": "dark"}', encoding="utf-8")

            with mock.patch.object(config, "CONFIG_DIR", config_dir), mock.patch.object(
                config, "CONFIG_FILE", config_file
            ):
                data = config.load_config()

            self.assertEqual(data, {"theme": "dark"})


if __name__ == "__main__":
    unittest.main()

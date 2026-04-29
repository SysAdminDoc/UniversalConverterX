import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep import db


class DbMigrationTests(unittest.TestCase):
    def test_migrate_from_config_skips_when_non_history_tables_already_have_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "library.db"
            cfg = {
                "monitor_channels": [
                    {"url": "https://kick.com/example", "platform": "Kick"}
                ]
            }

            with mock.patch.object(db, "DB_PATH", db_path):
                db.init_db()
                db.save_queue([{"url": "https://example.com/video"}])
                migrated = db.migrate_from_config(cfg)
                queue = db.load_queue()
                channels = db.load_monitor_channels()

            self.assertFalse(migrated)
            self.assertEqual(len(queue), 1)
            self.assertEqual(channels, [])
            self.assertNotIn("monitor_channels", cfg)


if __name__ == "__main__":
    unittest.main()

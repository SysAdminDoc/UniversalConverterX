import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep.notifications import NotificationCenter
import streamkeep.notifications as notifications_mod


class NotificationTests(unittest.TestCase):
    def test_notification_log_is_compacted_when_it_grows_too_large(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "notifications.jsonl"
            center = NotificationCenter(capacity=10)

            with mock.patch.object(notifications_mod, "NOTIF_LOG", log_path), \
                 mock.patch.object(notifications_mod, "NOTIF_LOG_MAX_BYTES", 1), \
                 mock.patch.object(notifications_mod, "NOTIF_LOG_KEEP_LINES", 2):
                center.push("first", "info")
                center.push("second", "warning")
                center.push("third", "error")
                history = center.load_history(limit=10)

            self.assertEqual([entry["text"] for entry in history], ["second", "third"])


if __name__ == "__main__":
    unittest.main()

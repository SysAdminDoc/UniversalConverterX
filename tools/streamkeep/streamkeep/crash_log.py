"""Global crash handler. Writes tracebacks to crash.log and shows a MessageBox."""

import sys
from datetime import datetime

from . import VERSION
from .paths import CONFIG_DIR, CRASH_LOG


def setup_crash_logging():
    """Install a global exception handler. Safe to call multiple times."""
    def handler(exc_type, exc_value, exc_tb):
        import traceback
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(
                    f"StreamKeep v{VERSION} crash at "
                    f"{datetime.now().isoformat()}\n"
                )
                f.write(tb_str)
        except Exception:
            pass
        # Show MessageBox if a QApplication already exists
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app:
                QMessageBox.critical(
                    None,
                    "StreamKeep — Crash",
                    f"An unexpected error occurred:\n\n{exc_value}\n\n"
                    f"Details logged to:\n{CRASH_LOG}",
                )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handler

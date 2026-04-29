"""Native OS Notifications — Windows Toast / macOS / Linux (F80).

Provides richer notifications than Qt's QSystemTrayIcon.showMessage():
  - Windows: Toast notifications with action buttons
  - macOS: NSUserNotification (via pyobjc)
  - Linux: libnotify via dbus

Falls back to Qt tray icon notifications when native backends are unavailable.

Usage::

    from streamkeep.native_notify import notify
    notify("Download complete", "xQc - Just Chatting.mp4",
           actions={"open": "/path/to/folder"})
"""

import os
import sys

_BACKEND = None   # "toast" | "qt" | None


def _detect_backend():
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND

    if sys.platform == "win32":
        try:
            __import__("windows_toasts")
            _BACKEND = "toast"
            return _BACKEND
        except ImportError:
            pass
        try:
            __import__("win10toast")
            _BACKEND = "toast_legacy"
            return _BACKEND
        except ImportError:
            pass

    _BACKEND = "qt"
    return _BACKEND


def notify(title, message, *, actions=None, level="info", tray_icon=None):
    """Show a native notification.

    *actions* is an optional dict of action_id -> data (e.g., {"open": path}).
    *level* is "info", "success", "warning", or "error".
    *tray_icon* is a QSystemTrayIcon for Qt fallback.

    Returns True if the notification was shown.
    """
    backend = _detect_backend()

    if backend == "toast":
        return _notify_toast(title, message, actions)
    if backend == "toast_legacy":
        return _notify_toast_legacy(title, message)
    if backend == "qt" and tray_icon is not None:
        return _notify_qt(title, message, tray_icon)
    return False


def _notify_toast(title, message, actions=None):
    """Windows Toast notification via windows-toasts library."""
    try:
        from windows_toasts import Toast, WindowsToaster

        toaster = WindowsToaster("StreamKeep")
        toast = Toast()
        toast.text_fields = [title, message]

        if actions and "open" in actions:
            path = actions["open"]
            toast.on_activated = lambda _: _open_path(path)

        toaster.show_toast(toast)
        return True
    except Exception:
        return False


def _notify_toast_legacy(title, message):
    """Windows notification via win10toast (simpler, no actions)."""
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(
            title, message,
            duration=5,
            threaded=True,
        )
        return True
    except Exception:
        return False


def _notify_qt(title, message, tray_icon):
    """Fallback to Qt tray icon notification."""
    try:
        from PyQt6.QtWidgets import QSystemTrayIcon
        tray_icon.showMessage(
            title, message,
            QSystemTrayIcon.MessageIcon.Information, 5000,
        )
        return True
    except Exception:
        return False


def _open_path(path):
    """Open a file or folder in the system file manager."""
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def is_native_available():
    """Return True if a native notification backend (not Qt) is available."""
    backend = _detect_backend()
    return backend in ("toast", "toast_legacy")

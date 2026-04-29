"""Event hook system — run user-configured shell commands on lifecycle events.

Commands execute as fire-and-forget subprocesses with context passed as
environment variables (SK_EVENT, SK_TITLE, SK_CHANNEL, SK_PLATFORM,
SK_PATH, SK_URL, SK_QUALITY).  Hooks are configured via
``config["hooks"]``  — a dict of ``event_name -> command_string``.
"""

import os
import subprocess
import threading

from .paths import _CREATE_NO_WINDOW

HOOK_TIMEOUT = 30

HOOK_EVENTS = [
    "download_complete",
    "download_error",
    "channel_live",
    "auto_record_start",
    "auto_record_end",
    "transcode_complete",
]


def fire_hook(event, context, hooks_config, log_fn=None):
    """Fire the configured hook for *event*, if any.

    *context* is a dict whose keys become ``SK_<KEY>`` env vars.
    Runs in a daemon thread so the UI never blocks.
    """
    cmd = (hooks_config or {}).get(event, "").strip()
    if not cmd:
        return

    env = dict(os.environ)
    env["SK_EVENT"] = str(event)
    for key, value in (context or {}).items():
        env[f"SK_{key.upper()}"] = str(value or "")

    def _run():
        try:
            proc = subprocess.run(
                cmd, shell=True, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=HOOK_TIMEOUT,
                creationflags=_CREATE_NO_WINDOW,
            )
            if proc.returncode != 0 and log_fn:
                stderr = (proc.stderr or b"").decode(
                    "utf-8", errors="replace").strip()
                log_fn(
                    f"[HOOK] {event} exited {proc.returncode}: "
                    f"{stderr[:200]}")
        except subprocess.TimeoutExpired:
            if log_fn:
                log_fn(f"[HOOK] {event} timed out after {HOOK_TIMEOUT}s")
        except Exception as e:
            if log_fn:
                log_fn(f"[HOOK] {event} error: {e}")

    threading.Thread(target=_run, daemon=True).start()

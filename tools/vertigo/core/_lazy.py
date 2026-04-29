"""Shared lazy-install helper for opt-in ``core/*`` modules.

Vertigo's optional integrations (faster-whisper, silero-vad, pycaps,
boxmot, pyannote, keybert, katna, lighthouse, etc.) are heavy, so each
module follows the same ``is_installed() -> bool`` / ``ensure_installed()
-> bool`` contract and pip-installs on first use.

Until v0.12.0 every module carried its own private ``_try_pip_install``
helper that shelled out to ``[sys.executable, "-m", "pip", ...]``. In a
PyInstaller build ``sys.executable`` is ``Vertigo.exe`` itself, so a
missing opt-in dep would have relaunched the GUI recursively — the same
fork-bomb class that ``vertigo.py::_pip_install`` already guards
against. This module collapses eight copies into one guarded helper.

The public surface is intentionally tiny:

    * :func:`is_frozen` — one source of truth for the frozen check.
    * :func:`pip_install` — the only place that spawns pip.

Tests monkey-patch :data:`_pip_runner` to simulate both success and
failure without actually reaching the network.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from typing import Callable, Sequence


def is_frozen() -> bool:
    """True when running inside a PyInstaller (or py2exe) bundle.

    ``sys.frozen`` is the documented attribute; ``_MEIPASS`` is
    PyInstaller's onefile extract marker. Checking both matches the
    guard the top-level ``vertigo.py`` bootstrap uses.
    """
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


# Seam for tests: injected in place of ``subprocess.call`` so a
# regression test can assert the non-frozen path fires without hitting
# the network, and the frozen path *never* fires.
_pip_runner: Callable[[Sequence[str]], int] = subprocess.call

# Serialises concurrent ``ensure_installed()`` calls so two worker
# threads that both discover a missing opt-in dep don't run parallel
# ``pip install`` against the same site-packages (known to corrupt
# metadata). The lock is process-local; it does not protect against
# other Python processes installing at the same time.
_install_lock = threading.Lock()


def _install_commands(spec: str) -> list[list[str]]:
    """Three install strategies in order: default, --user, --break-system-packages.

    Matches the ordering ``vertigo.py::_pip_install`` uses so behaviour
    is consistent between the bootstrap pass and on-demand opt-in
    installs.
    """
    return [
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", spec],
        [sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check", spec],
        [sys.executable, "-m", "pip", "install", "--break-system-packages", "--disable-pip-version-check", spec],
    ]


def pip_install(spec: str) -> bool:
    """Attempt to pip-install ``spec``. Returns True on success.

    **Frozen short-circuit.** When :func:`is_frozen` is True this
    function returns False immediately without constructing a
    subprocess command. This prevents the PyInstaller fork-bomb
    scenario where the GUI relaunches itself instead of running pip.
    Callers (every ``ensure_installed`` in ``core/``) interpret a
    False return as "dependency unavailable" and surface the install
    hint to the user.
    """
    if is_frozen():
        return False
    last_error: str | None = None
    with _install_lock:
        for cmd in _install_commands(spec):
            try:
                if _pip_runner(cmd) == 0:
                    return True
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                continue
    if last_error is not None:
        # Breadcrumb for the persistent crash log — quiet on stdout when
        # the runner merely returned non-zero; loud only when *every*
        # strategy hit an exception (typically pip itself missing). The
        # frozen-build stderr drop means the old print() here was
        # effectively invisible exactly when forensic value was highest.
        from . import crashlog
        crashlog.append(f"pip_install({spec!r}) failed: {last_error}")
    return False

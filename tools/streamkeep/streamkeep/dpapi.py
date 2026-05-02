"""Windows DPAPI wrapper — at-rest encryption for sensitive sidecar files.

Uses ctypes against ``Crypt32.dll`` rather than pywin32 / cryptography to keep
the StreamKeep dependency footprint minimal (these are stdlib-only). The
underlying primitives are the same ones backing the C# ``ProtectedData.Protect``
/ ``Unprotect`` APIs that ROADMAP Item 9 cites.

Scope: ``LocalMachine`` — the encrypted blob can be decrypted by any user on
the same Windows install. That's the right scope for a desktop converter app
where multiple OS user profiles may share a single UCX install (matches
YoutubeDownloader v1.14+'s machine-scoped DPAPI cookie handling).

Linux / macOS: ``encrypt`` and ``decrypt`` raise ``DpapiUnavailable``; callers
are expected to fall back to plaintext storage and log a warning. UCX targets
Windows 10 21H2+ per charter, so this is acceptable graceful degradation
rather than a real platform gap.

Format:
    | "DPAPI1\\n" (8 bytes magic)  | <ciphertext bytes...>

The 8-byte magic header lets ``cookies.py`` (and any future at-rest store)
detect whether a file on disk is encrypted, plain UTF-8, or a stale
intermediate format. Detection is byte-prefix only — no probe / heuristic.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


MAGIC = b"DPAPI1\n"


class DpapiUnavailable(RuntimeError):
    """DPAPI is not callable in the current process (non-Windows host, or
    Crypt32.dll missing / locked down by GPO)."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


# CRYPTPROTECT_LOCAL_MACHINE: encrypt-as-machine, decryptable by any user on
# this Windows install. The right scope for UCX (multi-user desktop tool).
_CRYPTPROTECT_LOCAL_MACHINE = 0x4
# CRYPTPROTECT_UI_FORBIDDEN: never show a UI prompt; just fail if creds are
# missing. Important for sidecar context where there is no UI thread.
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _crypt32():
    if sys.platform != "win32":
        raise DpapiUnavailable("DPAPI is Windows-only — current platform is "
                               f"{sys.platform!r}.")
    try:
        return ctypes.WinDLL("Crypt32.dll")
    except (OSError, AttributeError) as exc:
        raise DpapiUnavailable(f"Crypt32.dll could not be loaded: {exc}") from exc


def encrypt(plaintext: bytes, description: str = "UCX-StreamKeep") -> bytes:
    """Encrypt *plaintext* via DPAPI (LocalMachine scope). Returns the encrypted
    blob with the :data:`MAGIC` prefix already attached so callers can write it
    straight to disk and detect it later.

    Raises :class:`DpapiUnavailable` on non-Windows or when ``Crypt32.dll``
    can't be loaded. All other errors raise ``OSError`` with the underlying
    Win32 error code.
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError(f"encrypt expects bytes, got {type(plaintext).__name__}")

    crypt32 = _crypt32()
    src_array = (ctypes.c_char * len(plaintext)).from_buffer_copy(bytes(plaintext))
    src = _DataBlob(len(plaintext), ctypes.cast(src_array, ctypes.POINTER(ctypes.c_char)))
    dst = _DataBlob(0, None)

    desc = ctypes.c_wchar_p(description) if description else None
    flags = _CRYPTPROTECT_LOCAL_MACHINE | _CRYPTPROTECT_UI_FORBIDDEN

    if not crypt32.CryptProtectData(
        ctypes.byref(src), desc, None, None, None, flags, ctypes.byref(dst)
    ):
        raise OSError(ctypes.get_last_error(),
                      "CryptProtectData failed (LocalMachine scope).")

    try:
        return MAGIC + ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        # Crypt32 allocates dst.pbData via LocalAlloc — must release with LocalFree
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def decrypt(blob: bytes) -> bytes:
    """Decrypt a blob previously produced by :func:`encrypt`. The blob MUST
    start with :data:`MAGIC`; otherwise raises ``ValueError``.

    Raises :class:`DpapiUnavailable` on non-Windows or when Crypt32 won't load.
    Raises ``OSError`` on Win32 failure (most commonly: blob was encrypted on
    a different Windows install, or the install was reimaged after the blob
    was written).
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise TypeError(f"decrypt expects bytes, got {type(blob).__name__}")
    if not blob.startswith(MAGIC):
        raise ValueError("blob is not in DPAPI1 format (missing magic header).")

    payload = bytes(blob[len(MAGIC):])

    crypt32 = _crypt32()
    src_array = (ctypes.c_char * len(payload)).from_buffer_copy(payload)
    src = _DataBlob(len(payload), ctypes.cast(src_array, ctypes.POINTER(ctypes.c_char)))
    dst = _DataBlob(0, None)
    flags = _CRYPTPROTECT_LOCAL_MACHINE | _CRYPTPROTECT_UI_FORBIDDEN

    if not crypt32.CryptUnprotectData(
        ctypes.byref(src), None, None, None, None, flags, ctypes.byref(dst)
    ):
        raise OSError(ctypes.get_last_error(),
                      "CryptUnprotectData failed (likely re-imaged Windows or "
                      "the blob was written under a different machine key).")

    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def is_encrypted(blob: bytes) -> bool:
    """Return True if *blob* starts with the DPAPI1 magic header."""
    return isinstance(blob, (bytes, bytearray)) and blob.startswith(MAGIC)


def available() -> bool:
    """Return True if DPAPI calls would succeed on this host."""
    try:
        _crypt32()
        return True
    except DpapiUnavailable:
        return False

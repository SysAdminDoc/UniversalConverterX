"""Fail-closed Windows DPAPI protection for StreamKeep secrets.

The implementation uses ``ctypes`` so the sidecar stays stdlib-only. New
ciphertext is protected for the current Windows user with deterministic,
application-specific optional entropy and a versioned header. ``DPAPI1`` and
``dpapi:`` values from older releases remain decryptable for migration.

Binary format::

    | "DPAPI2\n" (7 bytes magic) | <ciphertext bytes...>

Text format::

    dpapi2:<base64 ciphertext>

DPAPI failures raise an exception. Callers must report the failure and leave
the previous stored value intact; plaintext and base64 are never substituted.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import sys
from ctypes import wintypes


MAGIC = b"DPAPI2\n"
LEGACY_MAGIC = b"DPAPI1\n"
TEXT_PREFIX = "dpapi2:"
LEGACY_TEXT_PREFIX = "dpapi:"
_ENTROPY = hashlib.sha256(b"UniversalConverterX.DPAPI.v2").digest()


class DpapiUnavailable(RuntimeError):
    """DPAPI cannot be called in the current process."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _crypt32():
    if sys.platform != "win32":
        raise DpapiUnavailable(
            f"DPAPI is Windows-only; current platform is {sys.platform!r}."
        )
    try:
        return ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    except (OSError, AttributeError) as exc:
        raise DpapiUnavailable(f"Crypt32.dll could not be loaded: {exc}") from exc


def _data_blob(data: bytes):
    """Return a DATA_BLOB and the backing buffer that must remain in scope."""
    buffer = ctypes.create_string_buffer(data, max(len(data), 1))
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)),
    )
    return blob, buffer


def encrypt(plaintext: bytes, description: str = "UCX-StreamKeep") -> bytes:
    """Protect bytes for the current Windows user and return ``DPAPI2`` data."""
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError(f"encrypt expects bytes, got {type(plaintext).__name__}")

    crypt32 = _crypt32()
    src, src_buffer = _data_blob(bytes(plaintext))
    entropy, entropy_buffer = _data_blob(_ENTROPY)
    dst = _DataBlob(0, None)
    desc = ctypes.c_wchar_p(description) if description else None

    # Keep the backing buffers alive for the duration of the native call.
    _ = src_buffer, entropy_buffer
    if not crypt32.CryptProtectData(
        ctypes.byref(src),
        desc,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(dst),
    ):
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed.")

    try:
        return MAGIC + ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def decrypt(blob: bytes) -> bytes:
    """Unprotect current or legacy binary DPAPI data.

    Legacy ``DPAPI1`` values are retried without entropy and should be
    re-encrypted by the consumer on its next write.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise TypeError(f"decrypt expects bytes, got {type(blob).__name__}")

    raw = bytes(blob)
    if raw.startswith(MAGIC):
        payload = raw[len(MAGIC):]
        entropy_bytes = _ENTROPY
    elif raw.startswith(LEGACY_MAGIC):
        payload = raw[len(LEGACY_MAGIC):]
        entropy_bytes = None
    else:
        raise ValueError("blob is not in a supported DPAPI format.")

    crypt32 = _crypt32()
    src, src_buffer = _data_blob(payload)
    dst = _DataBlob(0, None)
    entropy = None
    entropy_buffer = None
    entropy_pointer = None
    if entropy_bytes is not None:
        entropy, entropy_buffer = _data_blob(entropy_bytes)
        entropy_pointer = ctypes.byref(entropy)

    _ = src_buffer, entropy_buffer
    if not crypt32.CryptUnprotectData(
        ctypes.byref(src),
        None,
        entropy_pointer,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(dst),
    ):
        raise OSError(
            ctypes.get_last_error(),
            "CryptUnprotectData failed; the data may be corrupt or from another user.",
        )

    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def encrypt_text(plaintext: str, description: str = "UCX-StreamKeep secret") -> str:
    """Protect a string and return the versioned text storage format."""
    if not isinstance(plaintext, str):
        raise TypeError(f"encrypt_text expects str, got {type(plaintext).__name__}")
    protected = encrypt(plaintext.encode("utf-8"), description)
    payload = protected[len(MAGIC):]
    return TEXT_PREFIX + base64.b64encode(payload).decode("ascii")


def decrypt_text(stored: str) -> str:
    """Decrypt current ``dpapi2:`` or legacy ``dpapi:`` text storage."""
    if not isinstance(stored, str):
        raise TypeError(f"decrypt_text expects str, got {type(stored).__name__}")
    if stored.startswith(TEXT_PREFIX):
        magic = MAGIC
        encoded = stored[len(TEXT_PREFIX):]
    elif stored.startswith(LEGACY_TEXT_PREFIX):
        magic = LEGACY_MAGIC
        encoded = stored[len(LEGACY_TEXT_PREFIX):]
    else:
        raise ValueError("value is not in a supported DPAPI text format.")

    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("DPAPI text payload is not valid base64.") from exc
    return decrypt(magic + payload).decode("utf-8", errors="strict")


def is_encrypted(blob: bytes) -> bool:
    """Return true for current and legacy binary DPAPI formats."""
    return isinstance(blob, (bytes, bytearray)) and (
        blob.startswith(MAGIC) or blob.startswith(LEGACY_MAGIC)
    )


def is_legacy(blob: bytes) -> bool:
    """Return true when binary data needs migration to entropy-bound DPAPI2."""
    return isinstance(blob, (bytes, bytearray)) and blob.startswith(LEGACY_MAGIC)


def is_encrypted_text(value: str) -> bool:
    """Return true for current and legacy DPAPI text formats."""
    return isinstance(value, str) and value.startswith((TEXT_PREFIX, LEGACY_TEXT_PREFIX))


def available() -> bool:
    """Return true when the Windows DPAPI library is callable."""
    try:
        _crypt32()
        return True
    except DpapiUnavailable:
        return False

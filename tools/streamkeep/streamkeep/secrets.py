"""Fail-closed encrypted storage for sensitive StreamKeep config fields.

New values use the shared entropy-bound DPAPI2 format. Legacy ``dpapi:``,
``b64:``, and raw values remain readable, but protection never substitutes
base64 or plaintext when DPAPI is unavailable.
"""

import base64

from . import dpapi


SENSITIVE_FIELDS = frozenset({
    "webhook_url",
    "proxy",
    "companion_token",
    "media_server_token",
    "media_server_url",
})


def try_protect(plaintext):
    """Return ``(succeeded, protected_value, error)`` without weakening storage."""
    if not plaintext:
        return True, "", None
    try:
        return True, dpapi.encrypt_text(plaintext, "UCX-StreamKeep config"), None
    except (dpapi.DpapiUnavailable, OSError) as exc:
        return False, None, f"DPAPI protection failed: {exc}"


def protect(plaintext):
    """Protect a string or raise when DPAPI cannot secure it."""
    succeeded, value, error = try_protect(plaintext)
    if not succeeded:
        raise dpapi.DpapiUnavailable(error)
    return value


def unprotect(stored):
    """Decrypt current storage while retaining read support for legacy values."""
    if not stored:
        return ""
    if dpapi.is_encrypted_text(stored):
        return dpapi.decrypt_text(stored)
    if stored.startswith("b64:"):
        return base64.b64decode(stored[4:], validate=True).decode("utf-8")
    return stored


def is_protected(value):
    """Return true if *value* uses a recognized protected or legacy format."""
    return bool(value) and (
        dpapi.is_encrypted_text(value) or value.startswith("b64:")
    )


def protect_config_fields(cfg):
    """Protect sensitive fields atomically and return ``(succeeded, error)``."""
    updates = {}
    for key in SENSITIVE_FIELDS:
        value = cfg.get(key, "")
        if not value or is_protected(value):
            continue
        succeeded, protected, error = try_protect(value)
        if not succeeded:
            return False, error
        updates[key] = protected
    cfg.update(updates)
    return True, None


def unprotect_config_fields(cfg):
    """Decrypt recognized sensitive fields in place."""
    for key in SENSITIVE_FIELDS:
        value = cfg.get(key, "")
        if value and is_protected(value):
            cfg[key] = unprotect(value)

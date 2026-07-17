"""Pinned, consent-gated downloads for UCX model and binary assets."""
from __future__ import annotations

import hashlib
import os
import socket
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect


class AssetError(RuntimeError):
    """Base error for a verified asset operation."""


class LicenseNotAccepted(AssetError):
    """Raised before network access when the asset license was not accepted."""


class IntegrityError(AssetError):
    """Raised when a downloaded or cached asset fails exact validation."""


class NetworkDisabled(AssetError):
    """Raised when an inference process attempts undeclared network access."""


@dataclass(frozen=True)
class VerifiedAsset:
    asset_id: str
    filename: str
    url: str
    size_bytes: int
    sha256: str
    license: str

    def __post_init__(self) -> None:
        digest = self.sha256.lower()
        if (
            not self.asset_id
            or Path(self.filename).name != self.filename
            or not self.url.startswith("https://")
            or self.size_bytes <= 0
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not self.license
        ):
            raise ValueError(f"Invalid verified asset metadata: {self.asset_id!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_asset(path: Path, asset: VerifiedAsset) -> None:
    if not path.is_file():
        raise IntegrityError(f"Verified asset is not installed: {asset.asset_id}")
    actual_size = path.stat().st_size
    if actual_size != asset.size_bytes:
        raise IntegrityError(
            f"{asset.asset_id} size mismatch: expected {asset.size_bytes}, got {actual_size}")
    actual_hash = sha256_file(path)
    if actual_hash.lower() != asset.sha256.lower():
        raise IntegrityError(
            f"{asset.asset_id} SHA-256 mismatch: expected {asset.sha256}, got {actual_hash}")


def cached_asset(root: Path, asset: VerifiedAsset) -> Path | None:
    path = root / asset.filename
    try:
        validate_asset(path, asset)
    except IntegrityError:
        return None
    return path


def download_verified(
    root: Path,
    asset: VerifiedAsset,
    *,
    accept_license: bool,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download to a private staging file, validate, then atomically promote."""
    root.mkdir(parents=True, exist_ok=True)
    installed = cached_asset(root, asset)
    if installed is not None:
        return installed
    if not accept_license:
        raise LicenseNotAccepted(
            f"Accept {asset.license} before downloading {asset.asset_id}.")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{asset.filename}-", suffix=".part", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        request = urllib.request.Request(
            asset.url, headers={"User-Agent": "UniversalConverterX/verified-assets"})
        downloaded = 0
        previous_create_connection = socket.create_connection
        previous_socket_connect = socket.socket.connect
        try:
            # Explicit verified downloads are the sole exception to the
            # inference process network guard.
            socket.create_connection = _ORIGINAL_CREATE_CONNECTION
            socket.socket.connect = _ORIGINAL_SOCKET_CONNECT
            with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, asset.size_bytes)
                output.flush()
                os.fsync(output.fileno())
        finally:
            socket.create_connection = previous_create_connection
            socket.socket.connect = previous_socket_connect
        validate_asset(temporary, asset)
        destination = root / asset.filename
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def enforce_offline() -> None:
    """Disable Python socket creation for the remainder of an inference process."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["DIFFUSERS_OFFLINE"] = "1"

    def denied(*_args, **_kwargs):
        raise NetworkDisabled(
            "Network access is disabled during inference. Install a consent-gated verified asset first.")

    socket.create_connection = denied
    socket.socket.connect = denied

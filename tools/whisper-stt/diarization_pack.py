"""Consent-gated, hash-verified offline pack for pyannote diarization 3.1.

The pack deliberately contains the two model files needed by the pyannote
3.1 pipeline plus a local pipeline configuration.  The inference path never
resolves a Hugging Face identifier: it validates this manifest, changes into
the pack directory for pyannote's relative paths, and loads only local files.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


PACK_ID = "pyannote-speaker-diarization-3.1"
PACK_SCHEMA_VERSION = 1
PACK_LICENSE = "MIT"
PACK_TERMS_URL = "https://huggingface.co/pyannote/speaker-diarization-3.1"

PIPELINE_REPO = "pyannote/speaker-diarization-3.1"
PIPELINE_REVISION = "84fd25912480287da0247647c3d2b4853cb3ee5d"
SEGMENTATION_REPO = "pyannote/segmentation-3.0"
SEGMENTATION_REVISION = "e66f3d3b9eb0873085418a7b813d3b369bf160bb"
EMBEDDING_REPO = "pyannote/wespeaker-voxceleb-resnet34-LM"
EMBEDDING_REVISION = "837717ddb9ff5507820346191109dc79c958d614"

CONFIG_FILENAME = "pyannote_diarization_config.yaml"
MANIFEST_FILENAME = "manifest.json"
SEGMENTATION_FILENAME = "pyannote_model_segmentation-3.0.bin"
EMBEDDING_FILENAME = "pyannote_model_wespeaker-voxceleb-resnet34-LM.bin"
PACK_FILES = (CONFIG_FILENAME, SEGMENTATION_FILENAME, EMBEDDING_FILENAME)

LOCAL_CONFIG = f"""version: 3.1.0

pipeline:
  name: pyannote.audio.pipelines.SpeakerDiarization
  params:
    clustering: AgglomerativeClustering
    embedding: {EMBEDDING_FILENAME}
    embedding_batch_size: 32
    embedding_exclude_overlap: true
    segmentation: {SEGMENTATION_FILENAME}
    segmentation_batch_size: 32

params:
  clustering:
    method: centroid
    min_cluster_size: 12
    threshold: 0.7045654963945799
  segmentation:
    min_duration_off: 0.0
"""


def resolve_pack_dir(root: str | Path | None = None) -> Path:
    configured = (
        root
        or os.environ.get("UCX_DIARIZATION_MODEL_DIR")
        or os.environ.get("UCX_MODEL_DIR")
    )
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.name == PACK_ID or (candidate / MANIFEST_FILENAME).is_file():
            return candidate.resolve()
        return (candidate / PACK_ID).resolve()

    runtime_dir = (
        Path(__file__).resolve().parent
        if not getattr(sys, "frozen", False)
        else Path(sys.executable).resolve().parent
    )
    return (runtime_dir / "models" / PACK_ID).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_pack_file(pack_dir: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    raw = pack_dir / candidate
    if raw.is_symlink():
        return None
    resolved_root = pack_dir.resolve()
    resolved = (pack_dir / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _manifest_error(manifest: Any, pack_dir: Path) -> str | None:
    if not isinstance(manifest, dict):
        return "manifest is not a JSON object"
    if manifest.get("schemaVersion") != PACK_SCHEMA_VERSION:
        return "manifest schema is unsupported"
    if manifest.get("packId") != PACK_ID:
        return "manifest pack id does not match"
    if manifest.get("license") != PACK_LICENSE:
        return "manifest license does not match"
    revisions = manifest.get("revisions")
    expected_revisions = {
        "pipeline": PIPELINE_REVISION,
        "segmentation": SEGMENTATION_REVISION,
        "embedding": EMBEDDING_REVISION,
    }
    if not isinstance(revisions, dict) or any(
        revisions.get(key) != value for key, value in expected_revisions.items()
    ):
        return "manifest revisions do not match the pinned pack"

    entries = manifest.get("files")
    if not isinstance(entries, list):
        return "manifest files are missing"
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            return "manifest contains an invalid file entry"
        if entry["path"] in by_path:
            return "manifest contains duplicate file entries"
        by_path[entry["path"]] = entry

    for required in PACK_FILES:
        entry = by_path.get(required)
        if entry is None:
            return f"manifest is missing {required}"
        path = _safe_pack_file(pack_dir, required)
        if path is None or not path.is_file():
            return f"pack file is missing or unsafe: {required}"
        try:
            expected_size = int(entry["sizeBytes"])
            expected_hash = str(entry["sha256"]).lower()
        except (KeyError, TypeError, ValueError):
            return f"manifest integrity data is invalid for {required}"
        if expected_size <= 0 or len(expected_hash) != 64:
            return f"manifest integrity data is invalid for {required}"
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            return f"{required} size mismatch"
        if sha256_file(path) != expected_hash:
            return f"{required} SHA-256 mismatch"
    return None


def validate_pack(pack_dir: Path) -> tuple[bool, str]:
    manifest_path = pack_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return False, "manifest.json is missing"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, f"manifest could not be read: {exc}"
    error = _manifest_error(manifest, pack_dir)
    return (error is None, error or "ready")


def _file_entry(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {
        "path": relative,
        "sizeBytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_manifest(pack_dir: Path) -> None:
    manifest = {
        "schemaVersion": PACK_SCHEMA_VERSION,
        "packId": PACK_ID,
        "license": PACK_LICENSE,
        "termsUrl": PACK_TERMS_URL,
        "revisions": {
            "pipeline": PIPELINE_REVISION,
            "segmentation": SEGMENTATION_REVISION,
            "embedding": EMBEDDING_REVISION,
        },
        "sources": {
            "pipeline": PIPELINE_REPO,
            "segmentation": SEGMENTATION_REPO,
            "embedding": EMBEDDING_REPO,
        },
        "files": [_file_entry(pack_dir / name, pack_dir) for name in PACK_FILES],
    }
    (pack_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _promote(stage: Path, target: Path) -> None:
    backup = target.with_name(target.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(stage, target)
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def download_pack(target: Path, token: str) -> None:
    """Download both gated model files into a verified, atomic local pack."""
    from huggingface_hub import snapshot_download  # type: ignore

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{PACK_ID}-", dir=target.parent))
    downloads = stage / ".downloads"
    try:
        for repo, revision, filename, destination in (
            (SEGMENTATION_REPO, SEGMENTATION_REVISION, "pytorch_model.bin", SEGMENTATION_FILENAME),
            (EMBEDDING_REPO, EMBEDDING_REVISION, "pytorch_model.bin", EMBEDDING_FILENAME),
        ):
            source_dir = downloads / destination
            source_dir.mkdir(parents=True, exist_ok=True)
            snapshot_download(
                repo_id=repo,
                revision=revision,
                token=token,
                local_dir=str(source_dir),
                allow_patterns=[filename],
            )
            source = source_dir / filename
            if not source.is_file():
                raise RuntimeError(f"Hugging Face snapshot did not contain {repo}/{filename}")
            shutil.copy2(source, stage / destination)

        (stage / CONFIG_FILENAME).write_text(LOCAL_CONFIG, encoding="utf-8")
        _write_manifest(stage)
        ready, reason = validate_pack(stage)
        if not ready:
            raise RuntimeError(f"Downloaded model pack failed validation: {reason}")
        _promote(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)

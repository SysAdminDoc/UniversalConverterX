#!/usr/bin/env python3
"""Stage and verify architecture-specific UCX sidecar release readiness.

Release packages must not infer bundled engines from whatever happens to be in
tools/*/dist on a developer machine.  This tool accepts only artifacts named in
one explicit build report, verifies every byte against that report, stages the
authenticated files, and writes the complete availability catalog consumed by
the installed app.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
BUILD_REPORT_SCHEMA_VERSION = 2
MANIFEST_NAME = "sidecar-readiness.json"
INFRASTRUCTURE_TOOL_DIRECTORIES = {
    "_bin",
    "_models",
    "bin",
    "ffmpeg",
    "ffmpeg-proxy",
}


class ReadinessError(RuntimeError):
    """A release-readiness contract violation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"Could not read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReadinessError(f"Expected a JSON object in {path}.")
    return payload


def _relative_path(value: str, label: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or ":" in relative.parts[0]
    ):
        raise ReadinessError(f"{label} must be a safe relative path: {value!r}")
    return relative


def _contained(root: Path, relative: str, label: str) -> Path:
    rel = _relative_path(relative, label)
    root_resolved = root.resolve()
    candidate = (root_resolved / Path(*rel.parts)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ReadinessError(f"{label} escapes {root_resolved}: {relative}") from exc
    return candidate


def _source_manifests(source_tools: Path) -> dict[str, Path]:
    source_tools = source_tools.resolve()
    if not source_tools.is_dir():
        raise ReadinessError(f"Sidecar source root does not exist: {source_tools}")

    manifests: dict[str, Path] = {}
    for directory in sorted(source_tools.iterdir(), key=lambda item: item.name.lower()):
        manifest = directory / "ucx.sidecar.json"
        if not directory.is_dir() or not manifest.is_file():
            continue
        engine = directory.name
        if (
            engine in {".", ".."}
            or any(character in engine for character in "/\\:\0")
            or engine.startswith((".", "_"))
        ):
            raise ReadinessError(f"Unsafe engine directory name: {engine!r}")
        if engine.lower() in {key.lower() for key in manifests}:
            raise ReadinessError(f"Duplicate sidecar engine name: {engine}")
        manifests[engine] = manifest

    if not manifests:
        raise ReadinessError(f"No ucx.sidecar.json files found under {source_tools}.")
    return manifests


def _git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and len(value) == 40 else None


def _load_build_artifacts(
    report_path: Path | None,
    *,
    repo_root: Path,
    architecture: str,
    source_commit: str | None,
    allow_dirty_report: bool,
) -> dict[str, dict[str, Any]]:
    if report_path is None:
        return {}
    report_path = report_path.resolve()
    report = _load_json(report_path)
    if report.get("schemaVersion") != BUILD_REPORT_SCHEMA_VERSION:
        raise ReadinessError(
            f"{report_path} must use build-report schema "
            f"{BUILD_REPORT_SCHEMA_VERSION}."
        )
    if report.get("architecture") != architecture:
        raise ReadinessError(
            f"Build report architecture {report.get('architecture')!r} does not "
            f"match {architecture!r}."
        )

    reported_root = Path(str(report.get("repoRoot", ""))).resolve()
    if reported_root != repo_root.resolve():
        raise ReadinessError(
            f"Build report repository {reported_root} does not match {repo_root.resolve()}."
        )
    if source_commit and report.get("sourceCommit", "").lower() != source_commit.lower():
        raise ReadinessError(
            "Build report source commit does not match the release source commit."
        )
    if report.get("sourceDirty") and not allow_dirty_report:
        raise ReadinessError(
            "Build report was produced from a dirty source tree; release staging "
            "requires a committed source state."
        )
    if report.get("clean") is not True:
        raise ReadinessError(
            "Build report did not come from a clean sidecar build."
        )

    targets = report.get("targets")
    results = report.get("results")
    if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
        raise ReadinessError("Build report targets must be a string array.")
    if not isinstance(results, list):
        raise ReadinessError("Build report results must be an array.")

    by_engine: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            raise ReadinessError("Every build result must be an object.")
        engine = result.get("tool")
        if not isinstance(engine, str) or not engine:
            raise ReadinessError("Every build result must identify its tool.")
        if engine in by_engine:
            raise ReadinessError(f"Duplicate build result for {engine}.")
        if result.get("exitCode") != 0:
            raise ReadinessError(f"Build report contains a failed target: {engine}.")
        artifact = result.get("artifact")
        if not isinstance(artifact, dict):
            raise ReadinessError(f"Successful build result has no artifact: {engine}.")
        by_engine[engine] = artifact

    if sorted(targets, key=str.lower) != sorted(by_engine, key=str.lower):
        raise ReadinessError("Build report targets and successful results do not match.")

    for engine, artifact in by_engine.items():
        layout = artifact.get("layout")
        if layout not in {"onefile", "onedir"}:
            raise ReadinessError(f"Unsupported artifact layout for {engine}: {layout!r}")
        root_path = artifact.get("rootPath")
        entrypoint = artifact.get("entrypoint")
        files = artifact.get("files")
        if not isinstance(root_path, str) or not isinstance(entrypoint, str):
            raise ReadinessError(f"Artifact paths are incomplete for {engine}.")
        if not isinstance(files, list) or not files:
            raise ReadinessError(f"Artifact file inventory is empty for {engine}.")

        artifact_root = _contained(repo_root, root_path, f"{engine} artifact root")
        if not artifact_root.is_dir() or artifact_root.is_symlink():
            raise ReadinessError(f"Artifact root is not a regular directory: {artifact_root}")
        entrypoint_path = _contained(
            artifact_root, entrypoint, f"{engine} entrypoint"
        )
        if not entrypoint_path.is_file() or entrypoint_path.is_symlink():
            raise ReadinessError(f"Sidecar entrypoint is missing: {entrypoint_path}")
        if entrypoint_path.suffix.lower() != ".exe":
            raise ReadinessError(f"Sidecar entrypoint is not an executable: {entrypoint}")

        reported_files: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                raise ReadinessError(f"Invalid artifact file record for {engine}.")
            relative = item.get("path")
            sha256 = item.get("sha256")
            size = item.get("sizeBytes")
            if not isinstance(relative, str) or not isinstance(sha256, str):
                raise ReadinessError(f"Incomplete artifact file record for {engine}.")
            path = _contained(artifact_root, relative, f"{engine} artifact file")
            if not path.is_file() or path.is_symlink():
                raise ReadinessError(f"Artifact file is missing or linked: {path}")
            normalized = _relative_path(relative, "artifact file").as_posix()
            if normalized in reported_files:
                raise ReadinessError(f"Duplicate artifact file for {engine}: {normalized}")
            reported_files.add(normalized)
            if path.stat().st_size != size:
                raise ReadinessError(f"Artifact size changed after build: {path}")
            if _sha256(path) != sha256.lower():
                raise ReadinessError(f"Artifact digest changed after build: {path}")

        actual_files = {
            path.relative_to(artifact_root).as_posix()
            for path in artifact_root.rglob("*")
            if path.is_file()
        }
        if actual_files != reported_files:
            missing = sorted(actual_files - reported_files)
            extra = sorted(reported_files - actual_files)
            raise ReadinessError(
                f"Artifact inventory drift for {engine}; unreported={missing}, "
                f"missing={extra}."
            )
        if _relative_path(entrypoint, "entrypoint").as_posix() not in reported_files:
            raise ReadinessError(f"Entrypoint is not inventoried for {engine}.")

        artifact["_resolvedRoot"] = artifact_root
    return by_engine


def _copy_artifact(
    stage_root: Path,
    engine: str,
    artifact: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    source_root: Path = artifact["_resolvedRoot"]
    entrypoint = _relative_path(artifact["entrypoint"], "entrypoint")
    layout = artifact["layout"]
    engine_root = stage_root / "tools" / engine
    if layout == "onedir":
        destination_root = engine_root / "dist" / Path(entrypoint.name).stem
    else:
        destination_root = engine_root

    staged_files: list[dict[str, Any]] = []
    for item in artifact["files"]:
        relative = _relative_path(item["path"], "artifact file")
        source = _contained(source_root, relative.as_posix(), "artifact file")
        destination = destination_root / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        stage_relative = destination.relative_to(stage_root).as_posix()
        staged_files.append(
            {
                "path": stage_relative,
                "sizeBytes": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )

    staged_entrypoint = (
        destination_root / Path(*entrypoint.parts)
    ).relative_to(stage_root).as_posix()
    return staged_entrypoint, sorted(staged_files, key=lambda item: item["path"].lower())


def stage_release(
    *,
    repo_root: Path,
    stage_root: Path,
    source_tools: Path,
    architecture: str,
    product_version: str,
    build_report: Path | None = None,
    source_commit: str | None = None,
    allow_dirty_report: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stage_root = stage_root.resolve()
    source_tools = source_tools.resolve()
    manifests = _source_manifests(source_tools)
    if source_commit is None:
        source_commit = _git_commit(repo_root)
    artifacts = _load_build_artifacts(
        build_report,
        repo_root=repo_root,
        architecture=architecture,
        source_commit=source_commit,
        allow_dirty_report=allow_dirty_report,
    )
    unknown = sorted(set(artifacts) - set(manifests))
    if unknown:
        raise ReadinessError(
            f"Build report contains engines without source manifests: {unknown}"
        )

    tools_destination = stage_root / "tools"
    tools_destination.mkdir(parents=True, exist_ok=True)
    for engine in manifests:
        destination = tools_destination / engine
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise ReadinessError(f"Unsafe sidecar stage destination: {destination}")
            shutil.rmtree(destination)

    entries: list[dict[str, Any]] = []
    for engine, source_manifest in manifests.items():
        engine_destination = tools_destination / engine
        engine_destination.mkdir(parents=True, exist_ok=True)
        staged_manifest = engine_destination / "ucx.sidecar.json"
        shutil.copy2(source_manifest, staged_manifest)
        entry: dict[str, Any] = {
            "id": engine,
            "status": "unavailable",
            "sourceManifest": staged_manifest.relative_to(stage_root).as_posix(),
            "sourceManifestSha256": _sha256(staged_manifest),
            "entrypoint": None,
            "files": [],
            "reason": (
                f"No authenticated {architecture} sidecar artifact was supplied "
                "for this release."
            ),
        }
        artifact = artifacts.get(engine)
        if artifact is not None:
            entrypoint, files = _copy_artifact(stage_root, engine, artifact)
            entry.update(
                {
                    "status": "bundled",
                    "entrypoint": entrypoint,
                    "files": files,
                    "reason": "Authenticated sidecar artifact is bundled.",
                }
            )
        entries.append(entry)

    counts = {
        status: sum(entry["status"] == status for entry in entries)
        for status in ("bundled", "on-demand", "unavailable")
    }
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "productVersion": product_version,
        "architecture": architecture,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceCommit": source_commit,
        "counts": counts,
        "engines": entries,
    }
    output = stage_root / MANIFEST_NAME
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, output)
    verify_release(
        stage_root=stage_root,
        source_tools=source_tools,
        expected_architecture=architecture,
    )
    return payload


def verify_release(
    *,
    stage_root: Path,
    source_tools: Path | None = None,
    expected_architecture: str | None = None,
) -> dict[str, Any]:
    stage_root = stage_root.resolve()
    manifest_path = stage_root / MANIFEST_NAME
    payload = _load_json(manifest_path)
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ReadinessError(
            f"{manifest_path} must use schema {SCHEMA_VERSION}."
        )
    if expected_architecture and payload.get("architecture") != expected_architecture:
        raise ReadinessError(
            f"Readiness architecture {payload.get('architecture')!r} does not "
            f"match {expected_architecture!r}."
        )
    engines = payload.get("engines")
    if not isinstance(engines, list) or not engines:
        raise ReadinessError("Readiness manifest has no engines.")

    expected_manifests = (
        _source_manifests(source_tools) if source_tools is not None else None
    )
    ids: set[str] = set()
    all_allowed_files = {MANIFEST_NAME}
    counts = {"bundled": 0, "on-demand": 0, "unavailable": 0}
    for entry in engines:
        if not isinstance(entry, dict):
            raise ReadinessError("Every readiness engine must be an object.")
        engine = entry.get("id")
        status = entry.get("status")
        if not isinstance(engine, str) or not engine or engine in ids:
            raise ReadinessError(f"Invalid or duplicate readiness engine: {engine!r}")
        ids.add(engine)
        if status not in counts:
            raise ReadinessError(f"Invalid readiness status for {engine}: {status!r}")
        counts[status] += 1

        source_manifest_rel = entry.get("sourceManifest")
        source_manifest_hash = entry.get("sourceManifestSha256")
        if not isinstance(source_manifest_rel, str) or not isinstance(
            source_manifest_hash, str
        ):
            raise ReadinessError(f"Manifest provenance is missing for {engine}.")
        source_manifest = _contained(
            stage_root, source_manifest_rel, f"{engine} staged manifest"
        )
        if (
            not source_manifest.is_file()
            or source_manifest.is_symlink()
            or _sha256(source_manifest) != source_manifest_hash.lower()
        ):
            raise ReadinessError(f"Staged source manifest is invalid for {engine}.")
        all_allowed_files.add(source_manifest.relative_to(stage_root).as_posix())

        files = entry.get("files")
        entrypoint_rel = entry.get("entrypoint")
        if not isinstance(files, list):
            raise ReadinessError(f"File inventory is invalid for {engine}.")
        if status == "bundled" and (
            not isinstance(entrypoint_rel, str) or not files
        ):
            raise ReadinessError(f"Bundled engine has no entrypoint/files: {engine}.")
        if status != "bundled" and (entrypoint_rel is not None or files):
            raise ReadinessError(
                f"Non-bundled engine carries executable files: {engine}."
            )

        file_paths: set[str] = set()
        for file_record in files:
            if not isinstance(file_record, dict):
                raise ReadinessError(f"Invalid staged file record for {engine}.")
            relative = file_record.get("path")
            if not isinstance(relative, str):
                raise ReadinessError(f"Missing staged file path for {engine}.")
            path = _contained(stage_root, relative, f"{engine} staged file")
            normalized = path.relative_to(stage_root).as_posix()
            if normalized in file_paths:
                raise ReadinessError(f"Duplicate staged file for {engine}: {normalized}")
            file_paths.add(normalized)
            if not path.is_file() or path.is_symlink():
                raise ReadinessError(f"Staged artifact is missing or linked: {path}")
            if path.stat().st_size != file_record.get("sizeBytes"):
                raise ReadinessError(f"Staged artifact size mismatch: {path}")
            if _sha256(path) != str(file_record.get("sha256", "")).lower():
                raise ReadinessError(f"Staged artifact digest mismatch: {path}")
            all_allowed_files.add(normalized)
        if status == "bundled":
            entrypoint = _contained(stage_root, entrypoint_rel, f"{engine} entrypoint")
            if entrypoint.relative_to(stage_root).as_posix() not in file_paths:
                raise ReadinessError(
                    f"Bundled entrypoint is outside the file inventory: {engine}."
                )

    if expected_manifests is not None and ids != set(expected_manifests):
        missing = sorted(set(expected_manifests) - ids)
        extra = sorted(ids - set(expected_manifests))
        raise ReadinessError(
            f"Readiness coverage differs from source manifests; missing={missing}, "
            f"extra={extra}."
        )
    if payload.get("counts") != counts:
        raise ReadinessError(
            f"Readiness summary counts are stale: {payload.get('counts')} != {counts}."
        )

    tools_root = stage_root / "tools"
    if tools_root.is_dir():
        for path in tools_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(stage_root).as_posix()
            parts = path.relative_to(tools_root).parts
            infrastructure = bool(parts) and parts[0] in INFRASTRUCTURE_TOOL_DIRECTORIES
            if not infrastructure and relative not in all_allowed_files:
                raise ReadinessError(
                    f"Untracked sidecar payload would leak into the release: {relative}"
                )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser("stage")
    stage.add_argument("--repo-root", type=Path, required=True)
    stage.add_argument("--stage-root", type=Path, required=True)
    stage.add_argument("--source-tools", type=Path, required=True)
    stage.add_argument("--architecture", required=True)
    stage.add_argument("--product-version", required=True)
    stage.add_argument("--build-report", type=Path)
    stage.add_argument("--source-commit")
    stage.add_argument("--allow-dirty-report", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--stage-root", type=Path, required=True)
    verify.add_argument("--source-tools", type=Path)
    verify.add_argument("--architecture")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "stage":
            payload = stage_release(
                repo_root=args.repo_root,
                stage_root=args.stage_root,
                source_tools=args.source_tools,
                architecture=args.architecture,
                product_version=args.product_version,
                build_report=args.build_report,
                source_commit=args.source_commit,
                allow_dirty_report=args.allow_dirty_report,
            )
        else:
            payload = verify_release(
                stage_root=args.stage_root,
                source_tools=args.source_tools,
                expected_architecture=args.architecture,
            )
    except ReadinessError as exc:
        print(json.dumps({"event": "sidecar_readiness_error", "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "event": f"sidecar_readiness_{args.command}",
                "architecture": payload["architecture"],
                "counts": payload["counts"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

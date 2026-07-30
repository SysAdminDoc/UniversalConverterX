#!/usr/bin/env python3
"""Prepare and verify offline Python sidecar builds and staged SBOMs.

The connected ``prepare`` command resolves one independent environment per
sidecar and records the exact wheel URL, size, and SHA-256. ``verify`` rejects
requirement drift, incompatible hosts, modified/missing/extra wheelhouse files,
and unsafe torch resolutions before emitting exact per-tool constraints.

The ``sbom`` command inventories the staged release tree and reconciles it with
the Python lock, NuGet restore assets, sidecar manifests, native runtime
manifests, and model-pack manifests in CycloneDX 1.7 JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


LOCK_SCHEMA_VERSION = 1
CYCLONEDX_SPEC_VERSION = "1.7"
MAX_DISTRIBUTION_BYTES = 8 * 1024 * 1024 * 1024
BUILD_REQUIREMENTS = Path("tools/dependencies/build-requirements.txt")
REQUIREMENTS_PATTERN = re.compile(
    r"requirements(?:-[A-Za-z0-9_.-]+)?\.txt", re.IGNORECASE)
EXACT_REQUIREMENT_PATTERN = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?)"
    r"==([^;\s]+)(?:\s*;\s*.+)?$")
HEX_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_TOOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SPDX_PATTERN = re.compile(r"^[A-Za-z0-9.+-]+(?:-or-later)?$")
PACKAGE_TOKEN_PATTERN = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:[<>=!~].*)?$")
BUILD_PACKAGE_NAMES = {"pip", "pyinstaller", "setuptools", "wheel"}


class DependencyError(RuntimeError):
    """Raised when dependency provenance or SBOM reconciliation fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _safe_relative(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise DependencyError(f"path escapes root {resolved_root}: {resolved}") from exc
    return resolved


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DependencyError(f"cannot read JSON {path}: {exc}") from exc


def _environment() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "pythonVersion": platform.python_version(),
        "pythonTag": sys.implementation.cache_tag,
        "platform": sys.platform,
        "machine": platform.machine().lower(),
    }


def _validate_build_requirements(repo_root: Path) -> tuple[Path, list[str]]:
    path = _safe_relative(repo_root, repo_root / BUILD_REQUIREMENTS)
    if not path.is_file():
        raise DependencyError(f"missing build-tool lock: {path}")

    exact: list[str] = []
    names: set[str] = set()
    for line_number, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = EXACT_REQUIREMENT_PATTERN.fullmatch(line)
        if not match:
            raise DependencyError(
                f"{path}:{line_number}: build tools must use exact == pins")
        name = _canonical_name(match.group(1).split("[", 1)[0])
        names.add(name)
        exact.append(line)

    missing = {"pip", "pyinstaller"} - names
    if missing:
        raise DependencyError(
            "build-tool lock is missing exact pins for: "
            + ", ".join(sorted(missing)))
    return path, exact


def _tool_requirement_paths(repo_root: Path, tool: str) -> list[Path]:
    if not SAFE_TOOL_PATTERN.fullmatch(tool):
        raise DependencyError(f"invalid sidecar name: {tool!r}")
    tool_dir = _safe_relative(repo_root, repo_root / "tools" / tool)
    build_script = tool_dir / "build.ps1"
    if not tool_dir.is_dir() or not build_script.is_file():
        raise DependencyError(f"sidecar does not have a build.ps1: {tool}")

    build_text = build_script.read_text(encoding="utf-8")
    names = sorted(set(REQUIREMENTS_PATTERN.findall(build_text)),
                   key=str.lower)
    default = tool_dir / "requirements.txt"
    if not names and default.is_file():
        names = ["requirements.txt"]

    paths: list[Path] = []
    for name in names:
        candidate = _safe_relative(tool_dir, tool_dir / name)
        if not candidate.is_file():
            # Most generated sidecar builders use an optional Test-Path guard
            # even when the tool has no runtime dependencies.
            continue
        paths.append(candidate)
    declared = _declared_requirement_names(paths)
    inline = _inline_install_names(build_text)
    missing = inline - declared
    if missing:
        raise DependencyError(
            f"{tool} installs undeclared Python packages in build.ps1: "
            + ", ".join(sorted(missing)))
    return paths


def _declared_requirement_names(paths: Iterable[Path]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            direct_name = line.split("@", 1)[0].strip()
            match = PACKAGE_TOKEN_PATTERN.match(direct_name)
            if match:
                names.add(_canonical_name(match.group(1)))
    return names


def _inline_install_names(build_text: str) -> set[str]:
    flattened = re.sub(r"`\r?\n\s*", " ", build_text)
    names: set[str] = set()
    token_pattern = re.compile(r"'([^']*)'|\"([^\"]*)\"|(\S+)")
    for line in flattened.splitlines():
        match = re.search(r"(?i)-m\s+pip\s+install\b(.*)", line)
        if not match:
            continue
        tail = match.group(1)
        requirement_option = re.search(
            r"(?i)(?:^|\s)(?:-r|--requirement)(?:\s|=)", tail)
        if requirement_option:
            tail = tail[:requirement_option.start()]
        skip_next = False
        for groups in token_pattern.findall(tail):
            token = next(value for value in groups if value)
            if skip_next:
                skip_next = False
                continue
            if token in {
                "--index-url",
                "--extra-index-url",
                "--find-links",
                "-f",
            }:
                skip_next = True
                continue
            if token in {"|", ";"}:
                break
            if (token.startswith("-") or token.startswith("$")
                    or token.startswith("2>")
                    or token == "`"):
                continue
            package_match = PACKAGE_TOKEN_PATTERN.fullmatch(token)
            if not package_match:
                continue
            name = _canonical_name(package_match.group(1))
            if name not in BUILD_PACKAGE_NAMES:
                names.add(name)
    return names


def _requirements_record(repo_root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(paths):
        records.append({
            "path": path.relative_to(repo_root).as_posix(),
            "sizeBytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        })
    return records


def _run_pip_report(
    repo_root: Path,
    build_requirements: Path,
    requirement_paths: list[Path],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ucx-pip-report-") as temporary:
        report_path = Path(temporary) / "report.json"
        command = [
            sys.executable,
            "-m",
            "pip",
            "--isolated",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--disable-pip-version-check",
            "--report",
            str(report_path),
            "-r",
            str(build_requirements),
        ]
        for path in requirement_paths:
            command.extend(["-r", str(path)])

        environment = os.environ.copy()
        environment["PIP_CONFIG_FILE"] = os.devnull
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
        )
        if completed.returncode != 0:
            output = completed.stdout.strip()
            raise DependencyError(
                f"pip could not resolve this sidecar environment:\n{output}")
        if not report_path.is_file():
            raise DependencyError("pip completed without writing its JSON report")
        return _read_json(report_path)


def _report_packages(report: dict[str, Any]) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for item in report.get("install", []):
        metadata = item.get("metadata") or {}
        name = metadata.get("name")
        version = metadata.get("version")
        download = item.get("download_info") or {}
        url = download.get("url")
        archive = download.get("archive_info") or {}
        hashes = archive.get("hashes") or {}
        source_sha256 = str(hashes.get("sha256", "")).lower()
        vcs = download.get("vcs_info") or {}
        if not name or not version or not url:
            raise DependencyError("pip report contains an incomplete distribution")
        parsed = urllib.parse.urlsplit(url)
        source_file_name = Path(urllib.parse.unquote(parsed.path)).name
        scheme = parsed.scheme.lower()
        is_vcs = scheme == "git+https"
        if scheme not in {"https", "git+https"} or not parsed.netloc:
            raise DependencyError(
                f"{name} {version} does not resolve to an authenticated HTTPS artifact")
        if parsed.username or parsed.password:
            raise DependencyError(f"{name} {version} URL contains credentials")
        if is_vcs:
            commit = str(vcs.get("commit_id") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise DependencyError(
                    f"{name} {version} VCS dependency lacks a full commit id")
            artifact_kind = "vcs"
        elif source_file_name.lower().endswith(".whl"):
            if not HEX_SHA256_PATTERN.fullmatch(source_sha256):
                raise DependencyError(
                    f"{name} {version} report is missing a wheel SHA-256")
            artifact_kind = "wheel"
            commit = None
        else:
            if not HEX_SHA256_PATTERN.fullmatch(source_sha256):
                raise DependencyError(
                    f"{name} {version} source archive is missing a SHA-256")
            artifact_kind = "source"
            commit = None
        if artifact_kind == "source" and not source_file_name:
            raise DependencyError(
                f"{name} {version} source URL has no filename")

        license_value = (
            metadata.get("license_expression")
            or metadata.get("license")
            or None
        )
        package = {
            "name": name,
            "canonicalName": _canonical_name(name),
            "version": version,
            "sourceUrl": url,
            "sourceSha256": source_sha256 or None,
            "sourceRevision": commit,
            "artifactKind": artifact_kind,
            "sourceFileName": source_file_name or None,
            "license": license_value,
        }
        if artifact_kind == "wheel":
            package["fileName"] = source_file_name
            package["sha256"] = source_sha256
        packages.append(package)
    if not packages:
        raise DependencyError("pip resolution produced no build distributions")
    return packages


def _download_https(url: str, destination: Path, expected: str) -> int:
    temporary = destination.with_name(
        f".{destination.name}.partial-{uuid.uuid4().hex}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "UniversalConverterX dependency preparer/1"},
    )
    size = 0
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=60) as response, \
                temporary.open("xb") as output:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme.lower() != "https":
                raise DependencyError(
                    f"distribution redirected outside HTTPS: {response.geturl()}")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_DISTRIBUTION_BYTES:
                raise DependencyError(
                    f"distribution exceeds {MAX_DISTRIBUTION_BYTES} bytes: "
                    f"{destination.name}")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DISTRIBUTION_BYTES:
                    raise DependencyError(
                        f"distribution exceeded size ceiling: {destination.name}")
                digest.update(chunk)
                output.write(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise DependencyError(
                f"download digest mismatch for {destination.name}: "
                f"expected {expected}, got {actual}")
        os.replace(temporary, destination)
        return size
    finally:
        temporary.unlink(missing_ok=True)


def _wheel_name_version(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_names = [
                name for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise DependencyError(
                    f"wheel has {len(metadata_names)} METADATA files: {path.name}")
            text = archive.read(metadata_names[0]).decode("utf-8", errors="strict")
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise DependencyError(f"cannot inspect built wheel {path.name}: {exc}") from exc
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields.setdefault(key, value)
        if "Name" in fields and "Version" in fields:
            break
    if "Name" not in fields or "Version" not in fields:
        raise DependencyError(f"built wheel lacks Name/Version: {path.name}")
    return fields["Name"], fields["Version"]


def _build_source_wheel(
    package: dict[str, Any],
    wheelhouse: Path,
) -> Path:
    with tempfile.TemporaryDirectory(prefix="ucx-wheel-build-") as temporary:
        temporary_path = Path(temporary)
        source_argument = package["sourceUrl"]
        if package["artifactKind"] == "source":
            source_name = package["sourceFileName"]
            source_path = temporary_path / source_name
            _download_https(
                package["sourceUrl"], source_path, package["sourceSha256"])
            source_argument = str(source_path)
        elif package["artifactKind"] == "vcs":
            base, separator, fragment = package["sourceUrl"].partition("#")
            if "@" in base:
                base = base.rsplit("@", 1)[0]
            source_argument = f"{base}@{package['sourceRevision']}"
            if separator:
                source_argument += f"#{fragment}"

        output_dir = temporary_path / "wheel"
        output_dir.mkdir()
        command = [
            sys.executable,
            "-m",
            "pip",
            "--isolated",
            "wheel",
            "--disable-pip-version-check",
            "--no-deps",
            "--wheel-dir",
            str(output_dir),
            source_argument,
        ]
        environment = os.environ.copy()
        environment["PIP_CONFIG_FILE"] = os.devnull
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        completed = subprocess.run(
            command,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
        )
        wheels = list(output_dir.glob("*.whl"))
        if completed.returncode != 0 or len(wheels) != 1:
            raise DependencyError(
                f"could not build one wheel for {package['name']} "
                f"{package['version']}:\n{completed.stdout.strip()}")
        built = wheels[0]
        wheel_name, wheel_version = _wheel_name_version(built)
        if (_canonical_name(wheel_name) != package["canonicalName"]
                or wheel_version != package["version"]):
            raise DependencyError(
                f"built wheel identity mismatch for {package['name']} "
                f"{package['version']}: {wheel_name} {wheel_version}")
        destination = wheelhouse / built.name
        digest = _sha256_file(built)
        if destination.exists() and _sha256_file(destination) != digest:
            raise DependencyError(
                f"locally built wheel is not reproducible with existing "
                f"{destination.name}")
        if not destination.exists():
            temporary_destination = wheelhouse / (
                f".{built.name}.partial-{uuid.uuid4().hex}")
            temporary_destination.write_bytes(built.read_bytes())
            os.replace(temporary_destination, destination)
        package["fileName"] = destination.name
        package["sha256"] = digest
        package["sizeBytes"] = destination.stat().st_size
        return destination


def _download_distribution(package: dict[str, Any], wheelhouse: Path) -> None:
    if package["artifactKind"] != "wheel":
        _build_source_wheel(package, wheelhouse)
        return

    file_name = package["fileName"]
    if Path(file_name).name != file_name:
        raise DependencyError(f"unsafe wheel filename: {file_name!r}")
    destination = wheelhouse / file_name
    expected = package["sha256"]
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise DependencyError(f"wheel is not a regular file: {destination}")
        actual = _sha256_file(destination)
        if actual != expected:
            raise DependencyError(
                f"existing wheel digest mismatch for {file_name}: "
                f"expected {expected}, got {actual}")
        package["sizeBytes"] = destination.stat().st_size
        return
    package["sizeBytes"] = _download_https(
        package["sourceUrl"], destination, expected)


def _source_identity(package: dict[str, Any]) -> tuple[Any, ...]:
    return (
        package.get("canonicalName"),
        package.get("version"),
        package.get("sourceUrl"),
        package.get("sourceSha256"),
        package.get("sourceRevision"),
        package.get("artifactKind"),
    )


def _version_triplet(version: str) -> tuple[int, int, int]:
    public = version.split("+", 1)[0]
    numbers = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", public)
    if not numbers:
        raise DependencyError(f"cannot evaluate package version: {version}")
    return (
        int(numbers.group(1)),
        int(numbers.group(2)),
        int(numbers.group(3) or 0),
    )


def _validate_torch(packages: Iterable[dict[str, Any]]) -> None:
    for package in packages:
        if package["canonicalName"] != "torch":
            continue
        if _version_triplet(package["version"]) < (2, 6, 0):
            raise DependencyError(
                "torch resolution is affected by GHSA-53q9-r3pm-6pq6; "
                f"resolved {package['version']}, require 2.6.0 or newer")


def _lock_environment_matches(lock: dict[str, Any]) -> None:
    expected = lock.get("environment") or {}
    actual = _environment()
    for field in ("implementation", "pythonTag", "platform", "machine"):
        if str(expected.get(field, "")).lower() != str(actual[field]).lower():
            raise DependencyError(
                f"dependency lock targets {field}={expected.get(field)!r}, "
                f"current host is {actual[field]!r}")


def _package_map(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = {}
    for package in lock.get("packages", []):
        identifier = package.get("id")
        if not identifier or identifier in packages:
            raise DependencyError("dependency lock has a missing/duplicate package id")
        packages[identifier] = package
    return packages


def _tool_map(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for item in lock.get("tools", []):
        name = item.get("name")
        if not name or name in tools:
            raise DependencyError("dependency lock has a missing/duplicate tool name")
        tools[name] = item
    return tools


def _validate_lock_header(lock: dict[str, Any], repo_root: Path) -> None:
    if lock.get("schemaVersion") != LOCK_SCHEMA_VERSION:
        raise DependencyError(
            f"unsupported dependency-lock schema: {lock.get('schemaVersion')!r}")
    _lock_environment_matches(lock)
    build_path, _ = _validate_build_requirements(repo_root)
    recorded = lock.get("buildRequirements") or {}
    expected_path = build_path.relative_to(repo_root).as_posix()
    if recorded.get("path") != expected_path:
        raise DependencyError("dependency lock references the wrong build-tool file")
    digest = _sha256_file(build_path)
    if recorded.get("sha256") != digest:
        raise DependencyError("build-tool pins changed after dependency preparation")


def _validate_tool_requirements(
    repo_root: Path,
    tool: str,
    record: dict[str, Any],
) -> None:
    current = _requirements_record(
        repo_root, _tool_requirement_paths(repo_root, tool))
    if record.get("requirements") != current:
        raise DependencyError(
            f"{tool} requirements changed after dependency preparation")


def prepare(
    repo_root: Path,
    wheelhouse: Path,
    lock_path: Path,
    tools: list[str],
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    wheelhouse = wheelhouse.resolve()
    lock_path = lock_path.resolve()
    wheelhouse.mkdir(parents=True, exist_ok=True)
    build_path, _ = _validate_build_requirements(repo_root)

    if lock_path.exists():
        lock = _read_json(lock_path)
        _validate_lock_header(lock, repo_root)
    else:
        lock = {
            "schemaVersion": LOCK_SCHEMA_VERSION,
            "generatedAtUtc": _utc_now(),
            "environment": _environment(),
            "buildRequirements": {
                "path": build_path.relative_to(repo_root).as_posix(),
                "sha256": _sha256_file(build_path),
            },
            "tools": [],
            "packages": [],
        }

    existing_tools = _tool_map(lock)
    all_packages = _package_map(lock)
    for tool in sorted(set(tools), key=str.lower):
        requirement_paths = _tool_requirement_paths(repo_root, tool)
        report = _run_pip_report(repo_root, build_path, requirement_paths)
        resolved = _report_packages(report)
        _validate_torch(resolved)
        for package in resolved:
            reusable = next(
                (
                    existing
                    for existing in all_packages.values()
                    if _source_identity(existing) == _source_identity(package)
                ),
                None,
            )
            if reusable is not None:
                path = wheelhouse / reusable["fileName"]
                if (not path.is_file() or path.is_symlink()
                        or path.stat().st_size != reusable["sizeBytes"]
                        or _sha256_file(path) != reusable["sha256"]):
                    raise DependencyError(
                        f"recorded wheel is missing or modified: {path.name}")
                package = dict(reusable)
            else:
                _download_distribution(package, wheelhouse)
                package["id"] = (
                    f"{package['canonicalName']}=={package['version']}"
                    f"#{package['sha256']}"
                )
            existing = all_packages.get(package["id"])
            if existing and existing != package:
                raise DependencyError(
                    f"conflicting provenance for {package['id']}")
            all_packages[package["id"]] = package
        existing_tools[tool] = {
            "name": tool,
            "requirements": _requirements_record(repo_root, requirement_paths),
            "packages": sorted(package["id"] for package in resolved),
        }

    referenced = {
        package_id
        for tool in existing_tools.values()
        for package_id in tool["packages"]
    }
    lock["generatedAtUtc"] = _utc_now()
    lock["tools"] = sorted(existing_tools.values(), key=lambda item: item["name"])
    lock["packages"] = sorted(
        (package for identifier, package in all_packages.items()
         if identifier in referenced),
        key=lambda item: (
            item["canonicalName"], item["version"], item["fileName"]),
    )
    _atomic_json(lock_path, lock)
    verify(repo_root, wheelhouse, lock_path, tools, None)
    return lock


def verify(
    repo_root: Path,
    wheelhouse: Path,
    lock_path: Path,
    tools: list[str],
    constraints_dir: Path | None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    wheelhouse = wheelhouse.resolve()
    lock = _read_json(lock_path.resolve())
    _validate_lock_header(lock, repo_root)
    packages = _package_map(lock)
    tool_records = _tool_map(lock)

    selected = sorted(set(tools or tool_records), key=str.lower)
    if not selected:
        raise DependencyError("dependency lock has no sidecars")
    referenced: set[str] = set()
    for tool in selected:
        record = tool_records.get(tool)
        if record is None:
            raise DependencyError(f"sidecar is absent from dependency lock: {tool}")
        _validate_tool_requirements(repo_root, tool, record)
        for package_id in record.get("packages", []):
            if package_id not in packages:
                raise DependencyError(
                    f"{tool} references missing locked package: {package_id}")
            referenced.add(package_id)

    _validate_torch(packages[identifier] for identifier in referenced)
    expected_files: dict[str, dict[str, Any]] = {}
    for package in packages.values():
        name = package.get("fileName")
        if not name or Path(name).name != name:
            raise DependencyError("dependency lock contains an unsafe filename")
        if name in expected_files and expected_files[name]["sha256"] != package["sha256"]:
            raise DependencyError(f"wheel filename has conflicting digests: {name}")
        expected_files[name] = package

    if not wheelhouse.is_dir():
        raise DependencyError(f"wheelhouse does not exist: {wheelhouse}")
    actual_files: set[str] = set()
    for path in wheelhouse.iterdir():
        if path.name.startswith(".") and ".partial-" in path.name:
            raise DependencyError(f"incomplete wheelhouse download remains: {path.name}")
        if path.is_symlink() or not path.is_file():
            raise DependencyError(f"wheelhouse entry is not a regular file: {path.name}")
        actual_files.add(path.name)
    extra = actual_files - set(expected_files)
    missing = set(expected_files) - actual_files
    if missing:
        raise DependencyError("wheelhouse is missing: " + ", ".join(sorted(missing)))
    if extra:
        raise DependencyError(
            "wheelhouse contains non-lock artifacts: " + ", ".join(sorted(extra)))

    for name, package in expected_files.items():
        path = wheelhouse / name
        size = path.stat().st_size
        if size != package.get("sizeBytes"):
            raise DependencyError(
                f"wheel size mismatch for {name}: expected "
                f"{package.get('sizeBytes')}, got {size}")
        digest = _sha256_file(path)
        if digest != package.get("sha256"):
            raise DependencyError(
                f"wheel SHA-256 mismatch for {name}: "
                f"expected {package.get('sha256')}, got {digest}")

    if constraints_dir is not None:
        constraints_dir = constraints_dir.resolve()
        constraints_dir.mkdir(parents=True, exist_ok=True)
        for tool in selected:
            package_rows = [packages[item] for item in tool_records[tool]["packages"]]
            names: dict[str, str] = {}
            for package in package_rows:
                canonical = package["canonicalName"]
                version = package["version"]
                if canonical in names and names[canonical] != version:
                    raise DependencyError(
                        f"{tool} resolves multiple versions of {canonical}")
                names[canonical] = version
            content = "".join(
                f"{name}=={version}\n"
                for name, version in sorted(names.items())
            )
            target = constraints_dir / f"{tool}.txt"
            target.write_text(content, encoding="utf-8", newline="\n")
            locked_content = "".join(
                f"{package['canonicalName']}=={package['version']} "
                f"--hash=sha256:{package['sha256']}\n"
                for package in sorted(
                    package_rows,
                    key=lambda item: (
                        item["canonicalName"], item["version"], item["sha256"]),
                )
            )
            locked_target = constraints_dir / f"{tool}.requirements.txt"
            locked_target.write_text(
                locked_content, encoding="utf-8", newline="\n")

    return lock


def audit_manifests(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    _validate_build_requirements(repo_root)
    tools_root = repo_root / "tools"
    tools = sorted(
        path.name
        for path in tools_root.iterdir()
        if path.is_dir() and (path / "build.ps1").is_file()
    )
    errors: list[str] = []
    for tool in tools:
        try:
            _tool_requirement_paths(repo_root, tool)
        except DependencyError as exc:
            errors.append(str(exc))
    if errors:
        raise DependencyError(
            "Python build manifest audit failed:\n- " + "\n- ".join(errors))
    return tools


def _license_entries(value: Any) -> list[dict[str, Any]] | None:
    if not value or not isinstance(value, str):
        return None
    compact = value.strip()
    if not compact:
        return None
    if SPDX_PATTERN.fullmatch(compact):
        return [{"license": {"id": compact}}]
    return [{"license": {"name": compact[:512]}}]


def _property(name: str, value: Any) -> dict[str, str]:
    return {"name": name, "value": str(value)}


def _component_hash(sha256: str) -> list[dict[str, str]]:
    return [{"alg": "SHA-256", "content": sha256}]


def _purl_escape(value: str) -> str:
    return urllib.parse.quote(value, safe="._-~")


def _stage_contains_name(stage_names: set[str], name: str) -> bool:
    needle = _canonical_name(name)
    return any(
        needle in _canonical_name(Path(candidate).stem)
        for candidate in stage_names
    )


def _add_component(
    components: dict[str, dict[str, Any]],
    component: dict[str, Any],
) -> None:
    reference = component["bom-ref"]
    existing = components.get(reference)
    if existing is not None and existing != component:
        raise DependencyError(f"conflicting SBOM component: {reference}")
    components[reference] = component


def _dotnet_components(repo_root: Path) -> Iterable[dict[str, Any]]:
    packages: dict[tuple[str, str], None] = {}
    for assets_path in sorted((repo_root / "src").glob("**/obj/project.assets.json")):
        try:
            assets = _read_json(assets_path)
        except DependencyError:
            continue
        for identifier, metadata in (assets.get("libraries") or {}).items():
            if (metadata or {}).get("type") != "package" or "/" not in identifier:
                continue
            name, version = identifier.rsplit("/", 1)
            packages[(name, version)] = None
    for name, version in sorted(packages):
        canonical = name.lower()
        yield {
            "type": "library",
            "bom-ref": f"nuget:{canonical}@{version}",
            "group": "nuget",
            "name": name,
            "version": version,
            "purl": f"pkg:nuget/{_purl_escape(name)}@{_purl_escape(version)}",
        }


def _python_components(lock: dict[str, Any]) -> Iterable[dict[str, Any]]:
    required_by: dict[str, list[str]] = {}
    for tool in lock.get("tools", []):
        for identifier in tool.get("packages", []):
            required_by.setdefault(identifier, []).append(tool["name"])
    for package in lock.get("packages", []):
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": f"python:{package['id']}",
            "group": "pypi",
            "name": package["name"],
            "version": package["version"],
            "hashes": _component_hash(package["sha256"]),
            "purl": (
                f"pkg:pypi/{_purl_escape(package['canonicalName'])}"
                f"@{_purl_escape(package['version'])}"
            ),
            "externalReferences": [{
                "type": "distribution",
                "url": package["sourceUrl"],
                "hashes": _component_hash(package["sha256"]),
            }],
            "properties": [
                _property("ucx:wheel-file", package["fileName"]),
                _property("ucx:size-bytes", package["sizeBytes"]),
                _property(
                    "ucx:required-by-sidecars",
                    ",".join(sorted(required_by.get(package["id"], []))),
                ),
            ],
        }
        licenses = _license_entries(package.get("license"))
        if licenses:
            component["licenses"] = licenses
        yield component


def _native_components(
    repo_root: Path,
    stage_names: set[str],
) -> Iterable[dict[str, Any]]:
    ffmpeg_manifest = repo_root / "tools" / "ffmpeg" / "bundle.json"
    if ffmpeg_manifest.is_file():
        manifest = _read_json(ffmpeg_manifest)
        tool = manifest.get("tool")
        version = manifest.get("version")
        if tool and version:
            component: dict[str, Any] = {
                "type": "application",
                "bom-ref": f"native:{tool}@{version}",
                "group": "native",
                "name": tool,
                "version": version,
                "scope": "required" if _stage_contains_name(stage_names, tool) else "excluded",
                "properties": [
                    _property("ucx:manifest", ffmpeg_manifest.relative_to(repo_root).as_posix()),
                    _property("ucx:build", manifest.get("build", "")),
                ],
            }
            licenses = _license_entries(manifest.get("license"))
            if licenses:
                component["licenses"] = licenses
            references = []
            for platform_name, artifact in sorted(
                    (manifest.get("platforms") or {}).items()):
                if artifact.get("url"):
                    reference: dict[str, Any] = {
                        "type": "distribution",
                        "url": artifact["url"],
                        "comment": platform_name,
                    }
                    if HEX_SHA256_PATTERN.fullmatch(
                            str(artifact.get("sha256", "")).lower()):
                        reference["hashes"] = _component_hash(
                            artifact["sha256"].lower())
                    references.append(reference)
            if references:
                component["externalReferences"] = references
            yield component

    for manifest_path in sorted(
            (repo_root / "tools").glob("**/runtime.bundle.json")):
        manifest = _read_json(manifest_path)
        for artifact in manifest.get("artifacts", []):
            name = artifact.get("id")
            version = artifact.get("version")
            if not name or not version:
                continue
            component = {
                "type": "application",
                "bom-ref": f"runtime:{name}@{version}",
                "group": "runtime",
                "name": name,
                "version": version,
                "scope": "required" if _stage_contains_name(stage_names, name) else "excluded",
                "properties": [
                    _property("ucx:manifest", manifest_path.relative_to(repo_root).as_posix()),
                    _property("ucx:size-bytes", artifact.get("bytes", "")),
                ],
            }
            sha256 = str(artifact.get("sha256", "")).lower()
            if HEX_SHA256_PATTERN.fullmatch(sha256):
                component["hashes"] = _component_hash(sha256)
            if artifact.get("url"):
                component["externalReferences"] = [{
                    "type": "distribution",
                    "url": artifact["url"],
                    **({"hashes": _component_hash(sha256)}
                       if HEX_SHA256_PATTERN.fullmatch(sha256) else {}),
                }]
            licenses = _license_entries(artifact.get("license"))
            if licenses:
                component["licenses"] = licenses
            yield component

    for manifest_path in sorted((repo_root / "tools").glob("**/model-packs.json")):
        manifest = _read_json(manifest_path)
        for pack in manifest.get("packs", []):
            model_id = pack.get("modelId")
            revision = pack.get("revision")
            if not model_id or not revision:
                continue
            properties = [
                _property("ucx:manifest", manifest_path.relative_to(repo_root).as_posix()),
                _property("ucx:backend", pack.get("backend", "")),
                _property("ucx:gated", str(bool(pack.get("gated"))).lower()),
            ]
            for item in pack.get("files", []):
                digest = item.get("sha256") or item.get("gitBlobSha1") or ""
                properties.append(_property(
                    f"ucx:model-file:{item.get('path', '')}",
                    f"{item.get('bytes', '')}:{digest}",
                ))
            component = {
                "type": "machine-learning-model",
                "bom-ref": f"model:{model_id}@{revision}",
                "group": "model",
                "name": model_id,
                "version": revision,
                "scope": "required" if _stage_contains_name(
                    stage_names, pack.get("backend", "")) else "excluded",
                "properties": properties,
            }
            licenses = _license_entries(pack.get("license"))
            if licenses:
                component["licenses"] = licenses
            if pack.get("licenseUrl"):
                component["externalReferences"] = [{
                    "type": "license",
                    "url": pack["licenseUrl"],
                }]
            yield component


def _sidecar_components(
    repo_root: Path,
    stage_names: set[str],
) -> Iterable[dict[str, Any]]:
    for manifest_path in sorted((repo_root / "tools").glob("*/ucx.sidecar.json")):
        manifest = _read_json(manifest_path)
        engine = manifest.get("engine")
        if not engine:
            raise DependencyError(f"sidecar manifest lacks engine: {manifest_path}")
        version = str(manifest.get("engineVersion") or "unversioned")
        yield {
            "type": "application",
            "bom-ref": f"sidecar:{engine}@{version}",
            "group": "sidecar",
            "name": engine,
            "version": version,
            "scope": "required" if _stage_contains_name(stage_names, engine) else "excluded",
            "properties": [
                _property("ucx:manifest", manifest_path.relative_to(repo_root).as_posix()),
                _property("ucx:models", str(bool(manifest.get("models"))).lower()),
            ],
        }


def create_sbom(
    repo_root: Path,
    stage_root: Path,
    output_path: Path,
    product_version: str,
    lock_path: Path | None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stage_root = stage_root.resolve()
    output_path = output_path.resolve()
    if not stage_root.is_dir():
        raise DependencyError(f"staged root does not exist: {stage_root}")
    if not product_version.strip():
        raise DependencyError("product version must not be empty")

    components: dict[str, dict[str, Any]] = {}
    stage_names: set[str] = set()
    output_path.unlink(missing_ok=True)
    for path in sorted(stage_root.rglob("*")):
        if path.is_symlink():
            raise DependencyError(f"staged tree contains a symlink: {path}")
        if not path.is_file() or path.resolve() == output_path:
            continue
        _safe_relative(stage_root, path)
        relative = path.relative_to(stage_root).as_posix()
        stage_names.add(relative)
        digest = _sha256_file(path)
        _add_component(components, {
            "type": "file",
            "bom-ref": f"file:{relative}",
            "name": path.name,
            "version": digest[:12],
            "hashes": _component_hash(digest),
            "properties": [
                _property("ucx:staged-path", relative),
                _property("ucx:size-bytes", path.stat().st_size),
            ],
        })

    for component in _dotnet_components(repo_root):
        _add_component(components, component)

    lock: dict[str, Any] | None = None
    if lock_path is not None:
        lock = _read_json(lock_path.resolve())
        _validate_lock_header(lock, repo_root)
        for component in _python_components(lock):
            _add_component(components, component)

    for component in _native_components(repo_root, stage_names):
        _add_component(components, component)
    for component in _sidecar_components(repo_root, stage_names):
        _add_component(components, component)

    root_ref = f"pkg:generic/UniversalConverterX@{_purl_escape(product_version)}"
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": _utc_now(),
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": "UniversalConverterX",
                "version": product_version,
                "purl": root_ref,
            },
            "properties": [
                _property("ucx:staged-root", str(stage_root)),
                _property("ucx:python-lock-sha256",
                          _sha256_file(lock_path.resolve()) if lock_path else ""),
            ],
        },
        "components": sorted(
            components.values(), key=lambda item: item["bom-ref"]),
        "dependencies": [{
            "ref": root_ref,
            "dependsOn": sorted(components),
        }],
    }
    _atomic_json(output_path, payload)
    verify_sbom(stage_root, output_path, lock)
    return payload


def verify_sbom(
    stage_root: Path,
    sbom_path: Path,
    lock: dict[str, Any] | None,
) -> None:
    stage_root = stage_root.resolve()
    sbom_path = sbom_path.resolve()
    payload = _read_json(sbom_path)
    if (payload.get("bomFormat") != "CycloneDX"
            or payload.get("specVersion") != CYCLONEDX_SPEC_VERSION):
        raise DependencyError("SBOM is not CycloneDX 1.7")

    components = {
        component.get("bom-ref"): component
        for component in payload.get("components", [])
    }
    if None in components or len(components) != len(payload.get("components", [])):
        raise DependencyError("SBOM has missing or duplicate component references")
    staged_records: dict[str, dict[str, Any]] = {}
    for component in components.values():
        properties = {
            item.get("name"): item.get("value")
            for item in component.get("properties", [])
        }
        relative = properties.get("ucx:staged-path")
        if relative:
            staged_records[relative] = component

    for path in sorted(stage_root.rglob("*")):
        if not path.is_file() or path.resolve() == sbom_path:
            continue
        relative = path.relative_to(stage_root).as_posix()
        component = staged_records.get(relative)
        if component is None:
            raise DependencyError(f"staged file is absent from SBOM: {relative}")
        hashes = {
            item.get("alg"): item.get("content")
            for item in component.get("hashes", [])
        }
        if hashes.get("SHA-256") != _sha256_file(path):
            raise DependencyError(f"staged file digest mismatch in SBOM: {relative}")
    expected_paths = {
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if path.is_file() and path.resolve() != sbom_path
    }
    extra = set(staged_records) - expected_paths
    if extra:
        raise DependencyError(
            "SBOM lists absent staged files: " + ", ".join(sorted(extra)))

    if lock is not None:
        for package in lock.get("packages", []):
            reference = f"python:{package['id']}"
            component = components.get(reference)
            if component is None:
                raise DependencyError(
                    f"locked Python distribution is absent from SBOM: {reference}")
            hashes = {
                item.get("alg"): item.get("content")
                for item in component.get("hashes", [])
            }
            if hashes.get("SHA-256") != package["sha256"]:
                raise DependencyError(
                    f"locked Python digest mismatch in SBOM: {reference}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UCX locked sidecar dependency and SBOM pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("prepare", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--repo-root", type=Path, required=True)
        command.add_argument("--wheelhouse", type=Path, required=True)
        command.add_argument("--lock", type=Path, required=True)
        command.add_argument("--tool", action="append", dest="tools", default=[])
        if name == "verify":
            command.add_argument("--constraints-dir", type=Path)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--repo-root", type=Path, required=True)

    sbom = subparsers.add_parser("sbom")
    sbom.add_argument("--repo-root", type=Path, required=True)
    sbom.add_argument("--stage-root", type=Path, required=True)
    sbom.add_argument("--output", type=Path, required=True)
    sbom.add_argument("--product-version", required=True)
    sbom.add_argument("--lock", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            if not args.tools:
                raise DependencyError("prepare requires at least one --tool")
            lock = prepare(
                args.repo_root, args.wheelhouse, args.lock, args.tools)
            print(json.dumps({
                "event": "dependency_lock_prepared",
                "tools": sorted(args.tools),
                "packages": len(lock["packages"]),
                "lock": str(args.lock.resolve()),
                "wheelhouse": str(args.wheelhouse.resolve()),
            }))
        elif args.command == "verify":
            lock = verify(
                args.repo_root,
                args.wheelhouse,
                args.lock,
                args.tools,
                args.constraints_dir,
            )
            print(json.dumps({
                "event": "dependency_lock_verified",
                "tools": sorted(args.tools or [
                    item["name"] for item in lock["tools"]]),
                "packages": len(lock["packages"]),
            }))
        elif args.command == "audit":
            tools = audit_manifests(args.repo_root)
            print(json.dumps({
                "event": "dependency_manifests_audited",
                "tools": len(tools),
            }))
        else:
            payload = create_sbom(
                args.repo_root,
                args.stage_root,
                args.output,
                args.product_version,
                args.lock,
            )
            print(json.dumps({
                "event": "sbom_written",
                "components": len(payload["components"]),
                "output": str(args.output.resolve()),
            }))
        return 0
    except (DependencyError, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

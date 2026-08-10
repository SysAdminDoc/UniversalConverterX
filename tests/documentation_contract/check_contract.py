"""Validate active documentation against release and platform metadata."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
REQUIRED_MANIFEST_FIELDS = {
    "schemaVersion",
    "engine",
    "engineVersion",
    "minHostVersion",
    "maxHostVersion",
    "capabilities",
    "architectures",
    "migration",
}


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def element_value(tree: ET.ElementTree, name: str) -> str | None:
    values = [element.text.strip() for element in tree.iter() if local_name(element) == name and element.text]
    return values[0] if len(values) == 1 else None


def tracked_markdown() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", "*.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        relative = line.strip().replace("/", "\\")
        if relative.lower().startswith("docs\\archive\\") or relative.lower().startswith("publish\\"):
            continue
        paths.append(ROOT / relative)
    return paths


def check_local_links(errors: list[str]) -> None:
    for path in tracked_markdown():
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for target in MARKDOWN_LINK.findall(text):
            target = unquote(target.strip().split("#", 1)[0].split("?", 1)[0])
            if not target or target.startswith(("http://", "https://", "mailto:", "app://", "#")):
                continue
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                errors.append(f"broken local link: {path.relative_to(ROOT)} -> {target}")


def check_platform_and_release_contract(errors: list[str]) -> tuple[str, int]:
    props = ET.parse(ROOT / "Directory.Build.props")
    version = element_value(props, "Version")
    if version is None or not VERSION_PATTERN.fullmatch(version):
        errors.append("Directory.Build.props must declare one semantic three-part Version")
        version = "0.0.0"
    for name in ("AssemblyVersion", "FileVersion"):
        if element_value(props, name) != f"{version}.0":
            errors.append(f"Directory.Build.props {name} must be {version}.0")
    if element_value(props, "DotnetServicingPackageVersion") != "10.0.10":
        errors.append("Directory.Build.props must pin .NET servicing packages to 10.0.10")
    if element_value(props, "WindowsAppSdkPackageVersion") != "2.3.1":
        errors.append("Directory.Build.props must pin Windows App SDK to 2.3.1")

    readme = read("README.md")
    changelog = read("CHANGELOG.md")
    roadmap = read("ROADMAP.md")
    if f"version-{version}-blue" not in readme:
        errors.append("README version badge does not match Directory.Build.props")
    if f"Status:** v{version}" not in roadmap:
        errors.append("ROADMAP status does not match Directory.Build.props")
    if len(re.findall(r"^## \[Unreleased\]$", changelog, re.MULTILINE)) != 1:
        errors.append("CHANGELOG.md must contain exactly one Unreleased section")
    if not re.search(rf"^## \[{re.escape(version)}\] - ", changelog, re.MULTILINE):
        errors.append(f"CHANGELOG.md has no release heading for {version}")
    if re.search(r"^- \[[xX]\]", roadmap, re.MULTILINE):
        errors.append("ROADMAP.md contains a completed checkbox; completed items must be deleted")
    if re.search(r"CONTRIBUTING\.md", readme, re.IGNORECASE):
        errors.append("README.md links to the removed CONTRIBUTING.md guide")

    required_readme_fragments = (
        "Supported platform and release matrix",
        "Windows 10 21H2 (build 19044)",
        "Portable ZIP / WinGet",
        "MSIX",
        "MSI",
        "ARM64 publish",
        "self-contained",
        "212",
        "reinstall",
        "unsigned",
        ".NET 10.0.10",
        "Windows App SDK 2.3.1",
    )
    for fragment in required_readme_fragments:
        if fragment not in readme:
            errors.append(f"README.md platform matrix is missing {fragment!r}")
    for stale in ("Windows 10 version 1809", "19041.0", ".NET 10 Runtime"):
        if stale in readme:
            errors.append(f"README.md retains stale platform/runtime claim {stale!r}")

    four_part = f"{version}.0"
    active_files = {
        "installer/build-installer.ps1": (f"Version = '{four_part}'", "--self-contained true"),
        "installer/wix/Product.wxs": (four_part, "WindowsBuildNumber", "19044"),
        "installer/msix/Package.appxmanifest": (f'Version="{four_part}"', "10.0.19044.0"),
        "src/UniversalConverterX.UI/app.manifest": (f'version="{four_part}"', "21H2"),
        "build.ps1": ("net10.0-windows10.0.22621.0",),
        "tests/ui_smoke/Invoke-UiSmoke.ps1": ("net10.0-windows10.0.22621.0",),
        "tools/gates/Invoke-Gates.ps1": ("net10.0-windows10.0.22621.0",),
    }
    for relative, fragments in active_files.items():
        text = read(relative)
        for fragment in fragments:
            if fragment not in text:
                errors.append(f"{relative} is missing required release/platform value {fragment!r}")

    project_expectations = {
        "src/UniversalConverterX.UI/UniversalConverterX.UI.csproj": {
            "TargetFramework": "net10.0-windows10.0.22621.0",
            "TargetPlatformMinVersion": "10.0.19044.0",
            "RuntimeIdentifiers": "win-x64;win-arm64",
            "WindowsAppSDKSelfContained": "true",
        },
        "src/UniversalConverterX.ShellExtension/UniversalConverterX.ShellExtension.csproj": {
            "TargetFramework": "net10.0-windows10.0.22621.0",
            "TargetPlatformMinVersion": "10.0.19044.0",
            "RuntimeIdentifiers": "win-x64;win-arm64",
        },
        "tests/UniversalConverterX.VideoScalerSmoke/UniversalConverterX.VideoScalerSmoke.csproj": {
            "TargetFramework": "net10.0-windows10.0.22621.0",
            "TargetPlatformMinVersion": "10.0.19044.0",
            "RuntimeIdentifier": "win-x64",
        },
    }
    for relative, expectations in project_expectations.items():
        tree = ET.parse(ROOT / relative)
        for name, expected in expectations.items():
            if element_value(tree, name) != expected:
                errors.append(f"{relative} {name} must be {expected!r}")

    manifest_paths = sorted((ROOT / "tools").glob("*/ucx.sidecar.json"))
    for manifest_path in manifest_paths:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            errors.append(f"invalid sidecar manifest {manifest_path.relative_to(ROOT)}: {exc}")
            continue
        missing = sorted(REQUIRED_MANIFEST_FIELDS - payload.keys())
        if missing:
            errors.append(f"{manifest_path.relative_to(ROOT)} missing v2 fields: {', '.join(missing)}")
        if payload.get("schemaVersion") != 2:
            errors.append(f"{manifest_path.relative_to(ROOT)} is not schema v2")
        architectures = payload.get("architectures")
        if not isinstance(architectures, list) or "win-x64" not in architectures:
            errors.append(f"{manifest_path.relative_to(ROOT)} must advertise win-x64")
    if len(manifest_paths) != 212:
        errors.append(f"expected 212 sidecar manifests, found {len(manifest_paths)}")

    return version, len(manifest_paths)


def main() -> int:
    errors: list[str] = []
    check_local_links(errors)
    version, sidecar_count = check_platform_and_release_contract(errors)
    if errors:
        print("Documentation/platform contract failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        f"OK — documentation/platform contract is consistent "
        f"(v{version}, Windows 10 21H2+, {sidecar_count} sidecars)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

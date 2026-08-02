#!/usr/bin/env python3
"""NuGet vulnerability, deprecation, and allowlist-expiry gates.

`dotnet restore` already fails on an audited vulnerability, but that only
covers what NuGetAudit scores. This gate reads the explicit vulnerability and
deprecation reports so a finding has to be either fixed or written down with an
owner and an expiry date. Suppressions that outlive their expiry fail the gate,
so an allowlist cannot silently become permanent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ALLOWLIST_SCHEMA_VERSION = 1
REQUIRED_ENTRY_FIELDS = ("package", "reason", "expiresUtc", "owner")
# A suppression that outlives this window stops being a stopgap.
MAXIMUM_SUPPRESSION_DAYS = 180


class GateError(RuntimeError):
    """A dependency-gate contract violation."""


def _load_allowlist(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        raise GateError(f"Allowlist not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"Could not read allowlist {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateError(f"Allowlist must be a JSON object: {path}")
    if payload.get("schemaVersion") != ALLOWLIST_SCHEMA_VERSION:
        raise GateError(
            f"Allowlist must use schema {ALLOWLIST_SCHEMA_VERSION}: {path}"
        )

    sections: dict[str, list[dict[str, Any]]] = {}
    for section in ("vulnerabilities", "deprecations"):
        entries = payload.get(section, [])
        if not isinstance(entries, list):
            raise GateError(f"Allowlist section {section} must be an array.")
        for entry in entries:
            if not isinstance(entry, dict):
                raise GateError(f"Allowlist entry in {section} must be an object.")
            missing = [field for field in REQUIRED_ENTRY_FIELDS if not entry.get(field)]
            if missing:
                raise GateError(
                    f"Allowlist entry in {section} is missing {missing}: {entry}"
                )
        sections[section] = entries
    return sections


def _parse_expiry(value: str, context: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise GateError(
            f"{context} has an unparsable expiresUtc {value!r}; use YYYY-MM-DD."
        ) from exc


def check_allowlist(path: Path, today: date) -> list[str]:
    """Returns the expired entries; an empty list means the allowlist is healthy."""
    sections = _load_allowlist(path)
    expired: list[str] = []
    for section, entries in sections.items():
        for entry in entries:
            context = f"{section} entry for {entry['package']}"
            expires = _parse_expiry(entry["expiresUtc"], context)
            if expires < today:
                expired.append(
                    f"{context} expired on {expires.isoformat()} "
                    f"(owner {entry['owner']})"
                )
            elif (expires - today).days > MAXIMUM_SUPPRESSION_DAYS:
                expired.append(
                    f"{context} expires {expires.isoformat()}, more than "
                    f"{MAXIMUM_SUPPRESSION_DAYS} days out; shorten it."
                )
    return expired


def _run_dotnet_list(solution: Path, mode: str) -> dict[str, Any]:
    command = [
        "dotnet",
        "list",
        str(solution),
        "package",
        f"--{mode}",
        "--include-transitive",
        "--format",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateError(f"Could not run `dotnet list package --{mode}`: {exc}") from exc
    if result.returncode != 0:
        raise GateError(
            f"`dotnet list package --{mode}` failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(f"`dotnet list package --{mode}` emitted invalid JSON: {exc}") from exc


def _iter_packages(report: dict[str, Any]):
    for project in report.get("projects") or []:
        project_path = project.get("path", "<unknown>")
        for framework in project.get("frameworks") or []:
            moniker = framework.get("framework", "<unknown>")
            for key in ("topLevelPackages", "transitivePackages"):
                for package in framework.get(key) or []:
                    yield project_path, moniker, package


def _allowed(
    entries: list[dict[str, Any]],
    package_id: str,
    today: date,
    advisory_urls: set[str] | None = None,
) -> bool:
    for entry in entries:
        if str(entry["package"]).lower() != package_id.lower():
            continue
        if _parse_expiry(entry["expiresUtc"], f"allowlist entry for {package_id}") < today:
            continue
        advisory = entry.get("advisoryUrl")
        if advisory and advisory_urls is not None and advisory not in advisory_urls:
            continue
        return True
    return False


def check_nuget(solution: Path, allowlist_path: Path, today: date) -> list[str]:
    sections = _load_allowlist(allowlist_path)
    failures: list[str] = []

    vulnerable = _run_dotnet_list(solution, "vulnerable")
    for project, moniker, package in _iter_packages(vulnerable):
        package_id = str(package.get("id", "<unknown>"))
        advisories = {
            str(item.get("advisoryurl") or item.get("advisoryUrl") or "")
            for item in package.get("vulnerabilities") or []
        }
        if _allowed(sections["vulnerabilities"], package_id, today, advisories):
            continue
        failures.append(
            f"vulnerable: {package_id} {package.get('resolvedVersion')} "
            f"in {Path(project).name} [{moniker}] "
            f"({', '.join(sorted(advisories)) or 'no advisory url'})"
        )

    deprecated = _run_dotnet_list(solution, "deprecated")
    for project, moniker, package in _iter_packages(deprecated):
        package_id = str(package.get("id", "<unknown>"))
        if _allowed(sections["deprecations"], package_id, today):
            continue
        reasons = package.get("deprecationReasons") or []
        failures.append(
            f"deprecated: {package_id} {package.get('resolvedVersion')} "
            f"in {Path(project).name} [{moniker}] "
            f"({', '.join(str(reason) for reason in reasons) or 'no reason given'})"
        )

    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("nuget", "allowlist"),
        help="nuget = vulnerability + deprecation report; allowlist = expiry check",
    )
    parser.add_argument("--solution", type=Path)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument(
        "--today",
        help="Override today's date (YYYY-MM-DD) for deterministic tests.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    today = (
        date.fromisoformat(args.today)
        if args.today
        else datetime.now(timezone.utc).date()
    )
    try:
        if args.command == "allowlist":
            failures = check_allowlist(args.allowlist, today)
        else:
            if args.solution is None:
                raise GateError("--solution is required for the nuget command.")
            failures = check_nuget(args.solution, args.allowlist, today)
    except GateError as exc:
        print(json.dumps({"event": "dependency_gate_error", "error": str(exc)}))
        return 2

    print(
        json.dumps(
            {
                "event": f"dependency_gate_{args.command}",
                "failures": failures,
                "passed": not failures,
            },
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

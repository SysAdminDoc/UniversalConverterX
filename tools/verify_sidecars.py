#!/usr/bin/env python3
"""Local manifest, import, help, and optional freeze verification for UCX sidecars."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
CONTRACT_DIR = REPO / "tests" / "sidecar_contract"
sys.path.insert(0, str(CONTRACT_DIR))
from check_contract import check_health_manifest  # noqa: E402

FAST_ENGINES = (
    "colorfmt",
    "coordfmt",
    "hashkit",
    "textencode",
    "videosummary",
)


@dataclass(frozen=True)
class VerificationFailure:
    phase: str
    detail: str


@dataclass
class SidecarVerification:
    engine: str
    operations: tuple[str, ...] = ()
    failures: list[VerificationFailure] = field(default_factory=list)
    duration_seconds: float = 0

    @property
    def passed(self) -> bool:
        return not self.failures


def discover_sidecars() -> list[Path]:
    return sorted(TOOLS.glob("*/sidecar.py"), key=lambda item: item.parent.name.casefold())


def extract_operations(source: str) -> tuple[str, ...]:
    """Extract argparse command choices without importing or running the sidecar."""
    operations: set[str] = set()
    has_parser = False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if name == "ArgumentParser":
            has_parser = True
        if name == "add_parser" and node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                operations.add(value)
        if name == "add_argument":
            positional = bool(
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and not node.args[0].value.startswith("-")
            )
            if not positional:
                continue
            for keyword in node.keywords:
                if keyword.arg != "choices" or not isinstance(keyword.value, (ast.List, ast.Tuple)):
                    continue
                for item in keyword.value.elts:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        operations.add(item.value)

    if not operations and has_parser:
        operations.add("<single-command>")
    return tuple(sorted(operations))


def _run(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "UCX_SIDECAR_VERIFY": "1",
        }
    )
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout or "no output").strip().replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text)[:500]


def verify_sidecar(
    sidecar: Path,
    *,
    timeout: int = 15,
    check_import: bool = True,
    check_help: bool = True,
    require_build: bool = True,
) -> SidecarVerification:
    started = time.monotonic()
    engine = sidecar.parent.name
    result = SidecarVerification(engine=engine)

    for violation in check_health_manifest(sidecar):
        result.failures.append(VerificationFailure("manifest", violation.detail))

    build_script = sidecar.parent / "build.ps1"
    if require_build and not build_script.is_file():
        result.failures.append(VerificationFailure("build-entry", "missing build.ps1"))

    try:
        source = sidecar.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        result.failures.append(VerificationFailure("source", str(exc)))
        result.duration_seconds = time.monotonic() - started
        return result

    result.operations = extract_operations(source)
    if not result.operations:
        result.failures.append(VerificationFailure("operations", "no argparse operation surface found"))

    if check_import:
        importer = """
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(path.parent))
sys.path.insert(0, str(path.parent.parent / '_lib'))
name = '_ucx_verify_' + path.parent.name.replace('-', '_')
spec = importlib.util.spec_from_file_location(name, path)
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
assert spec.loader is not None
spec.loader.exec_module(module)
"""
        try:
            imported = _run([sys.executable, "-I", "-c", importer, str(sidecar)], sidecar.parent, timeout)
            if imported.returncode != 0:
                result.failures.append(
                    VerificationFailure("import", f"exit {imported.returncode}: {_diagnostic(imported)}")
                )
        except subprocess.TimeoutExpired:
            result.failures.append(VerificationFailure("import", f"timed out after {timeout}s"))

    if check_help:
        try:
            helped = _run([sys.executable, str(sidecar), "--help"], sidecar.parent, timeout)
            combined = f"{helped.stdout}\n{helped.stderr}"
            if helped.returncode != 0:
                result.failures.append(
                    VerificationFailure("help", f"exit {helped.returncode}: {_diagnostic(helped)}")
                )
            elif "traceback" in combined.casefold():
                result.failures.append(VerificationFailure("help", "help emitted a Python traceback"))
            elif "usage" not in combined.casefold() and not any(
                operation.casefold() in combined.casefold()
                for operation in result.operations
                if not operation.startswith("<")
            ):
                result.failures.append(VerificationFailure("help", "help did not expose usage or an operation"))
        except subprocess.TimeoutExpired:
            result.failures.append(VerificationFailure("help", f"timed out after {timeout}s"))

    result.duration_seconds = time.monotonic() - started
    return result


def freeze_sidecar(sidecar: Path, timeout: int) -> VerificationFailure | None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        return VerificationFailure("freeze", "PowerShell is not available")
    build_script = sidecar.parent / "build.ps1"
    if not build_script.is_file():
        return VerificationFailure("freeze", "missing build.ps1")
    try:
        built = _run([shell, "-NoProfile", "-File", str(build_script)], sidecar.parent, timeout)
    except subprocess.TimeoutExpired:
        return VerificationFailure("freeze", f"timed out after {timeout}s")
    if built.returncode != 0:
        return VerificationFailure("freeze", f"exit {built.returncode}: {_diagnostic(built)}")
    executables = sorted(sidecar.parent.glob("*.exe"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not executables:
        return VerificationFailure("freeze", "build succeeded but produced no root sidecar executable")
    try:
        helped = _run([str(executables[0]), "--help"], sidecar.parent, min(timeout, 60))
    except subprocess.TimeoutExpired:
        return VerificationFailure("frozen-help", "frozen executable help timed out")
    if helped.returncode != 0:
        return VerificationFailure("frozen-help", f"exit {helped.returncode}: {_diagnostic(helped)}")
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fast", "all"), default="all")
    parser.add_argument("--engine", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--freeze", action="store_true", help="Run each selected build.ps1 and frozen --help")
    parser.add_argument("--freeze-timeout", type=int, default=900)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sidecars = discover_sidecars()
    selected_names = set(args.engine or (FAST_ENGINES if args.mode == "fast" else ()))
    if selected_names:
        sidecars = [item for item in sidecars if item.parent.name in selected_names]
        missing = sorted(selected_names - {item.parent.name for item in sidecars})
        if missing:
            print(f"unknown engine(s): {', '.join(missing)}", file=sys.stderr)
            return 2

    manifest_count = len(list(TOOLS.glob("*/ucx.sidecar.json")))
    source_count = len(discover_sidecars())
    results: list[SidecarVerification] = []
    for sidecar in sidecars:
        verification = verify_sidecar(sidecar, timeout=max(1, args.timeout))
        if args.freeze and verification.passed:
            failure = freeze_sidecar(sidecar, max(30, args.freeze_timeout))
            if failure:
                verification.failures.append(failure)
        results.append(verification)

    payload = {
        "coverage": {"sidecars": source_count, "manifests": manifest_count},
        "selected": len(results),
        "passed": sum(item.passed for item in results),
        "failed": sum(not item.passed for item in results),
        "results": [
            {
                "engine": item.engine,
                "operations": list(item.operations),
                "durationSeconds": round(item.duration_seconds, 3),
                "failures": [failure.__dict__ for failure in item.failures],
            }
            for item in results
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for item in results:
            marker = "PASS" if item.passed else "FAIL"
            operations = ", ".join(item.operations)
            print(f"[{marker}] {item.engine} ({operations}) {item.duration_seconds:.2f}s")
            for failure in item.failures:
                print(f"       {failure.phase}: {failure.detail}")
        print(
            f"Coverage: {manifest_count}/{source_count} manifests; "
            f"verified {payload['passed']}/{len(results)} selected sidecars."
        )
    return 0 if manifest_count == source_count and payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

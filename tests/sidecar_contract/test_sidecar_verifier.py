"""Fast contract coverage for the local all-sidecar verification harness."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "tools" / "verify_sidecars.py"
SPEC = importlib.util.spec_from_file_location("ucx_sidecar_verifier", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


def test_every_sidecar_has_manifest_and_build_entrypoint() -> None:
    sidecars = VERIFIER.discover_sidecars()
    assert sidecars
    assert len(sidecars) == len(list((ROOT / "tools").glob("*/ucx.sidecar.json")))
    assert not [path.parent.name for path in sidecars if not (path.parent / "build.ps1").is_file()]


@pytest.mark.parametrize("engine", VERIFIER.FAST_ENGINES)
def test_fast_sidecar_import_help_and_operation_surface(engine: str) -> None:
    result = VERIFIER.verify_sidecar(ROOT / "tools" / engine / "sidecar.py", timeout=20)
    assert result.operations
    assert not result.failures, [f"{failure.phase}: {failure.detail}" for failure in result.failures]


def test_operation_extraction_handles_subcommands_and_single_command() -> None:
    subcommands = """
import argparse
parser = argparse.ArgumentParser()
sub = parser.add_subparsers()
sub.add_parser('inspect')
sub.add_parser('convert')
"""
    assert VERIFIER.extract_operations(subcommands) == ("convert", "inspect")
    assert VERIFIER.extract_operations("import argparse\nargparse.ArgumentParser()") == ("<single-command>",)

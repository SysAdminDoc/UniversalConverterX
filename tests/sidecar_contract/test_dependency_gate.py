"""Expiry semantics for the dependency-gate allowlist (ROADMAP Item 152).

A suppression that never expires is indistinguishable from an unfixed finding,
so the gate must fail on a lapsed entry, refuse an entry that is missing its
owner or reason, and refuse one parked years into the future.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "tools" / "gates" / "dependency_gate.py"
SHIPPED_ALLOWLIST = ROOT / "tools" / "gates" / "allowlist.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("ucx_dependency_gate", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_module()


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _entry(**overrides) -> dict:
    entry = {
        "package": "Some.Package",
        "reason": "tracked as ROADMAP Item 999",
        "expiresUtc": "2026-09-01",
        "owner": "SysAdminDoc",
    }
    entry.update(overrides)
    return entry


def _allowlist(**sections) -> dict:
    return {
        "schemaVersion": 1,
        "vulnerabilities": sections.get("vulnerabilities", []),
        "deprecations": sections.get("deprecations", []),
    }


def test_unexpired_entry_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, _allowlist(deprecations=[_entry()]))
    assert gate.check_allowlist(path, date(2026, 8, 2)) == []


def test_expired_entry_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, _allowlist(deprecations=[_entry()]))
    failures = gate.check_allowlist(path, date(2026, 9, 2))
    assert len(failures) == 1
    assert "expired on 2026-09-01" in failures[0]
    assert "SysAdminDoc" in failures[0]


def test_entry_parked_too_far_out_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path, _allowlist(vulnerabilities=[_entry(expiresUtc="2030-01-01")]))
    failures = gate.check_allowlist(path, date(2026, 8, 2))
    assert len(failures) == 1
    assert "shorten it" in failures[0]


@pytest.mark.parametrize("missing", ["package", "reason", "expiresUtc", "owner"])
def test_incomplete_entry_is_rejected(tmp_path: Path, missing: str) -> None:
    entry = _entry()
    del entry[missing]
    path = _write(tmp_path, _allowlist(deprecations=[entry]))
    with pytest.raises(gate.GateError, match="missing"):
        gate.check_allowlist(path, date(2026, 8, 2))


def test_unparsable_expiry_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _allowlist(deprecations=[_entry(expiresUtc="soon")]))
    with pytest.raises(gate.GateError, match="unparsable"):
        gate.check_allowlist(path, date(2026, 8, 2))


def test_wrong_schema_version_is_rejected(tmp_path: Path) -> None:
    payload = _allowlist()
    payload["schemaVersion"] = 99
    path = _write(tmp_path, payload)
    with pytest.raises(gate.GateError, match="schema"):
        gate.check_allowlist(path, date(2026, 8, 2))


def test_expired_entry_no_longer_suppresses_a_finding(tmp_path: Path) -> None:
    path = _write(tmp_path, _allowlist(deprecations=[_entry()]))
    sections = gate._load_allowlist(path)
    assert gate._allowed(
        sections["deprecations"], "some.package", date(2026, 8, 2)) is True
    assert gate._allowed(
        sections["deprecations"], "some.package", date(2026, 9, 2)) is False


def test_shipped_allowlist_is_healthy_today() -> None:
    # The repository's own allowlist must always be in a state the gate accepts;
    # this is the check that turns a forgotten suppression into a build failure.
    from datetime import datetime, timezone

    failures = gate.check_allowlist(
        SHIPPED_ALLOWLIST, datetime.now(timezone.utc).date())
    assert failures == [], failures

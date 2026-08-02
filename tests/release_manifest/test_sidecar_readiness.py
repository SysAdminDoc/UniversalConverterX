from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "release" / "sidecar_readiness.py"
SPEC = importlib.util.spec_from_file_location("sidecar_readiness", SCRIPT)
assert SPEC and SPEC.loader
READINESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READINESS)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(tools: Path, engine: str) -> None:
    directory = tools / engine
    directory.mkdir(parents=True)
    (directory / "ucx.sidecar.json").write_text(
        json.dumps({"engine": engine}) + "\n",
        encoding="utf-8",
    )


def _build_report(
    root: Path,
    artifact: Path,
    *,
    source_commit: str = "1" * 40,
) -> Path:
    report = root / "build-report.json"
    report.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "architecture": "win-x64",
                "repoRoot": str(root),
                "sourceCommit": source_commit,
                "sourceDirty": False,
                "clean": True,
                "targets": ["demo"],
                "results": [
                    {
                        "tool": "demo",
                        "exitCode": 0,
                        "durationS": 1,
                        "artifact": {
                            "layout": "onefile",
                            "rootPath": "tools/demo/dist",
                            "entrypoint": "demo.exe",
                            "files": [
                                {
                                    "path": "demo.exe",
                                    "sizeBytes": artifact.stat().st_size,
                                    "sha256": _sha256(artifact),
                                }
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return report


def test_stage_marks_every_unbuilt_engine_unavailable_and_cleans_old_output() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        tools = root / "tools"
        stage = root / "stage"
        _write_manifest(tools, "demo")
        _write_manifest(tools, "other")
        stale = stage / "tools" / "demo" / "demo.exe"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"stale")
        ffmpeg = stage / "tools" / "bin" / "ffmpeg.exe"
        ffmpeg.parent.mkdir(parents=True)
        ffmpeg.write_bytes(b"infrastructure")

        payload = READINESS.stage_release(
            repo_root=root,
            stage_root=stage,
            source_tools=tools,
            architecture="win-x64",
            product_version="9.8.7",
            source_commit="1" * 40,
        )

        assert payload["counts"] == {
            "bundled": 0,
            "on-demand": 0,
            "unavailable": 2,
        }
        assert not stale.exists()
        assert ffmpeg.exists()
        assert {
            entry["id"] for entry in payload["engines"]
        } == {"demo", "other"}


def test_authenticated_build_report_is_staged_and_tampering_fails_verification() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        tools = root / "tools"
        stage = root / "stage"
        _write_manifest(tools, "demo")
        artifact = tools / "demo" / "dist" / "demo.exe"
        artifact.parent.mkdir()
        artifact.write_bytes(b"frozen-sidecar")
        report = _build_report(root, artifact)

        payload = READINESS.stage_release(
            repo_root=root,
            stage_root=stage,
            source_tools=tools,
            architecture="win-x64",
            product_version="9.8.7",
            build_report=report,
            source_commit="1" * 40,
        )

        entry = payload["engines"][0]
        assert entry["status"] == "bundled"
        staged = stage / entry["entrypoint"]
        assert staged.read_bytes() == b"frozen-sidecar"
        READINESS.verify_release(
            stage_root=stage,
            source_tools=tools,
            expected_architecture="win-x64",
        )
        staged.write_bytes(b"tampered")
        with pytest.raises(READINESS.ReadinessError, match="size mismatch"):
            READINESS.verify_release(stage_root=stage, source_tools=tools)


def test_verify_rejects_untracked_stale_sidecar_executable() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        tools = root / "tools"
        stage = root / "stage"
        _write_manifest(tools, "demo")
        READINESS.stage_release(
            repo_root=root,
            stage_root=stage,
            source_tools=tools,
            architecture="win-x64",
            product_version="9.8.7",
            source_commit="1" * 40,
        )
        (stage / "tools" / "demo" / "demo.exe").write_bytes(b"stale")

        with pytest.raises(
            READINESS.ReadinessError,
            match="Untracked sidecar payload",
        ):
            READINESS.verify_release(stage_root=stage, source_tools=tools)


def test_stage_rejects_report_from_another_commit() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        tools = root / "tools"
        stage = root / "stage"
        _write_manifest(tools, "demo")
        artifact = tools / "demo" / "dist" / "demo.exe"
        artifact.parent.mkdir()
        artifact.write_bytes(b"frozen-sidecar")
        report = _build_report(root, artifact, source_commit="2" * 40)

        with pytest.raises(READINESS.ReadinessError, match="source commit"):
            READINESS.stage_release(
                repo_root=root,
                stage_root=stage,
                source_tools=tools,
                architecture="win-x64",
                product_version="9.8.7",
                build_report=report,
                source_commit="1" * 40,
            )

"""Tests for locked sidecar builds and staged CycloneDX reconciliation."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "dependencies" / "sidecar_dependencies.py"
SPEC = importlib.util.spec_from_file_location("sidecar_dependencies", SCRIPT)
assert SPEC and SPEC.loader
dependencies = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dependencies
SPEC.loader.exec_module(dependencies)


class SidecarDependencyTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, dict]:
        build_requirements = root / "tools" / "dependencies"
        build_requirements.mkdir(parents=True)
        (build_requirements / "build-requirements.txt").write_text(
            "pip==26.2\npyinstaller==6.21.0\n",
            encoding="utf-8",
        )
        tool = root / "tools" / "demo"
        tool.mkdir(parents=True)
        (tool / "build.ps1").write_text(
            "& python -m pip install -r requirements.txt\n",
            encoding="utf-8",
        )
        (tool / "requirements.txt").write_text(
            "demo>=1\n",
            encoding="utf-8",
        )
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()

        packages = []
        for name, version, file_name in (
            ("demo", "1.0", "demo-1.0-py3-none-any.whl"),
            ("pip", "26.2", "pip-26.2-py3-none-any.whl"),
            ("pyinstaller", "6.21.0",
             "pyinstaller-6.21.0-py3-none-any.whl"),
        ):
            wheel = wheelhouse / file_name
            wheel.write_bytes(f"{name}-{version}".encode("ascii"))
            digest = dependencies._sha256_file(wheel)
            packages.append({
                "id": f"{name}=={version}#{digest}",
                "name": name,
                "canonicalName": name,
                "version": version,
                "fileName": file_name,
                "sourceUrl": f"https://files.pythonhosted.org/{file_name}",
                "sizeBytes": wheel.stat().st_size,
                "sha256": digest,
                "license": "MIT",
            })

        build_file = build_requirements / "build-requirements.txt"
        lock = {
            "schemaVersion": 1,
            "generatedAtUtc": "2026-07-29T00:00:00Z",
            "environment": dependencies._environment(),
            "buildRequirements": {
                "path": "tools/dependencies/build-requirements.txt",
                "sha256": dependencies._sha256_file(build_file),
            },
            "tools": [{
                "name": "demo",
                "requirements": dependencies._requirements_record(
                    root, [tool / "requirements.txt"]),
                "packages": sorted(package["id"] for package in packages),
            }],
            "packages": packages,
        }
        lock_path = root / "sidecar-lock.json"
        dependencies._atomic_json(lock_path, lock)
        return wheelhouse, lock_path, lock

    def test_verify_emits_exact_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse, lock_path, _ = self._fixture(root)
            constraints = root / "constraints"

            dependencies.verify(
                root, wheelhouse, lock_path, ["demo"], constraints)

            self.assertEqual(
                "demo==1.0\npip==26.2\npyinstaller==6.21.0\n",
                (constraints / "demo.txt").read_text(encoding="utf-8"),
            )
            locked = (
                constraints / "demo.requirements.txt"
            ).read_text(encoding="utf-8")
            for package in ("demo==1.0", "pip==26.2", "pyinstaller==6.21.0"):
                with self.subTest(package=package):
                    self.assertRegex(
                        locked,
                        rf"(?m)^{re.escape(package)} --hash=sha256:[0-9a-f]{{64}}$")

    def test_verify_rejects_drift_tampering_and_extra_wheels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse, lock_path, lock = self._fixture(root)
            requirements = root / "tools" / "demo" / "requirements.txt"
            requirements.write_text("demo>=2\n", encoding="utf-8")
            with self.assertRaisesRegex(
                    dependencies.DependencyError, "requirements changed"):
                dependencies.verify(
                    root, wheelhouse, lock_path, ["demo"], None)

            requirements.write_text("demo>=1\n", encoding="utf-8")
            target = wheelhouse / lock["packages"][0]["fileName"]
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(
                    dependencies.DependencyError, "size mismatch|SHA-256 mismatch"):
                dependencies.verify(
                    root, wheelhouse, lock_path, ["demo"], None)

            target.write_bytes(
                f"{lock['packages'][0]['name']}-"
                f"{lock['packages'][0]['version']}".encode("ascii"))
            (wheelhouse / "poison-9.9-py3-none-any.whl").write_bytes(b"x")
            with self.assertRaisesRegex(
                    dependencies.DependencyError, "non-lock artifacts"):
                dependencies.verify(
                    root, wheelhouse, lock_path, ["demo"], None)

    def test_unpinned_build_tool_and_affected_torch_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse, lock_path, lock = self._fixture(root)
            build_file = (
                root / "tools" / "dependencies" / "build-requirements.txt")
            build_file.write_text(
                "pip==26.2\npyinstaller>=6.21\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                    dependencies.DependencyError, "exact == pins"):
                dependencies.verify(
                    root, wheelhouse, lock_path, ["demo"], None)

            build_file.write_text(
                "pip==26.2\npyinstaller==6.21.0\n",
                encoding="utf-8",
            )
            lock["buildRequirements"]["sha256"] = dependencies._sha256_file(
                build_file)
            torch_file = wheelhouse / "torch-2.5.1-py3-none-any.whl"
            torch_file.write_bytes(b"affected torch")
            digest = dependencies._sha256_file(torch_file)
            package = {
                "id": f"torch==2.5.1#{digest}",
                "name": "torch",
                "canonicalName": "torch",
                "version": "2.5.1",
                "fileName": torch_file.name,
                "sourceUrl": f"https://files.pythonhosted.org/{torch_file.name}",
                "sizeBytes": torch_file.stat().st_size,
                "sha256": digest,
                "license": "BSD-3-Clause",
            }
            lock["packages"].append(package)
            lock["tools"][0]["packages"].append(package["id"])
            dependencies._atomic_json(lock_path, lock)

            with self.assertRaisesRegex(
                    dependencies.DependencyError, "GHSA-53q9-r3pm-6pq6"):
                dependencies.verify(
                    root, wheelhouse, lock_path, ["demo"], None)

    def test_manifest_audit_rejects_inline_dependency_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            build = root / "tools" / "demo" / "build.ps1"
            build.write_text(
                "& python -m pip install -r requirements.txt\n"
                "& python -m pip install requests\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                    dependencies.DependencyError, "undeclared.*requests"):
                dependencies.audit_manifests(root)

        self.assertEqual(212, len(dependencies.audit_manifests(ROOT)))

    def test_vcs_package_is_rebuilt_from_reported_full_commit(self) -> None:
        commit = "a" * 40
        report = {
            "install": [{
                "metadata": {
                    "name": "demo-vcs",
                    "version": "1.0",
                    "license_expression": "MIT",
                },
                "download_info": {
                    "url": "git+https://github.com/example/demo.git@main",
                    "vcs_info": {
                        "vcs": "git",
                        "requested_revision": "main",
                        "commit_id": commit,
                    },
                },
            }],
        }
        package = dependencies._report_packages(report)[0]
        captured: dict[str, object] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            wheel = wheel_dir / "demo_vcs-1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "demo_vcs-1.0.dist-info/METADATA",
                    "Metadata-Version: 2.1\n"
                    "Name: demo-vcs\n"
                    "Version: 1.0\n",
                )
            return types.SimpleNamespace(returncode=0, stdout="")

        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(
                    dependencies.subprocess, "run", side_effect=fake_run):
            wheelhouse = Path(temporary)
            dependencies._download_distribution(package, wheelhouse)
            output = wheelhouse / package["fileName"]

            self.assertTrue(output.is_file())
            self.assertEqual(dependencies._sha256_file(output), package["sha256"])
            self.assertEqual(output.stat().st_size, package["sizeBytes"])

        command = captured["command"]
        self.assertIn(
            f"git+https://github.com/example/demo.git@{commit}", command)
        self.assertNotIn(
            "git+https://github.com/example/demo.git@main", command)

    def test_staged_sbom_reconciles_all_component_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, lock_path, _ = self._fixture(root)
            stage = root / "stage"
            (stage / "tools").mkdir(parents=True)
            (stage / "UniversalConverterX.exe").write_bytes(b"app")
            (stage / "tools" / "ffmpeg.exe").write_bytes(b"ffmpeg")
            (stage / "tools" / "demo.exe").write_bytes(b"sidecar")

            assets = root / "src" / "Demo" / "obj"
            assets.mkdir(parents=True)
            (assets / "project.assets.json").write_text(json.dumps({
                "libraries": {
                    "Example.Package/1.2.3": {"type": "package"},
                },
            }), encoding="utf-8")

            ffmpeg = root / "tools" / "ffmpeg"
            ffmpeg.mkdir()
            (ffmpeg / "bundle.json").write_text(json.dumps({
                "schemaVersion": 1,
                "tool": "ffmpeg",
                "version": "8.1.2",
                "license": "GPL-3.0-or-later",
                "platforms": {
                    "windows-x64": {
                        "url": "https://example.invalid/ffmpeg.zip",
                        "sha256": "a" * 64,
                    },
                },
            }), encoding="utf-8")
            runtime = root / "tools" / "runtime"
            runtime.mkdir()
            (runtime / "runtime.bundle.json").write_text(json.dumps({
                "schemaVersion": 1,
                "artifacts": [{
                    "id": "native-runtime",
                    "version": "1.0",
                    "license": "MIT",
                    "url": "https://example.invalid/runtime.zip",
                    "bytes": 10,
                    "sha256": "b" * 64,
                }],
            }), encoding="utf-8")
            model = root / "tools" / "model"
            model.mkdir()
            (model / "model-packs.json").write_text(json.dumps({
                "schemaVersion": 1,
                "packs": [{
                    "backend": "model",
                    "modelId": "example/model",
                    "revision": "c" * 40,
                    "license": "MIT",
                    "licenseUrl": "https://example.invalid/license",
                    "files": [{
                        "path": "model.safetensors",
                        "bytes": 20,
                        "sha256": "d" * 64,
                    }],
                }],
            }), encoding="utf-8")
            (root / "tools" / "demo" / "ucx.sidecar.json").write_text(
                '{"engine":"demo"}\n', encoding="utf-8")

            output = stage / "UniversalConverterX.cdx.json"
            payload = dependencies.create_sbom(
                root, stage, output, "9.9.9", lock_path)
            references = {
                component["bom-ref"]: component
                for component in payload["components"]
            }

            self.assertEqual("1.7", payload["specVersion"])
            self.assertIn("file:UniversalConverterX.exe", references)
            self.assertIn("nuget:example.package@1.2.3", references)
            self.assertTrue(
                any(reference.startswith("python:demo==1.0#")
                    for reference in references))
            self.assertEqual("required", references["native:ffmpeg@8.1.2"]["scope"])
            self.assertEqual(
                "excluded", references["runtime:native-runtime@1.0"]["scope"])
            self.assertEqual(
                "excluded",
                references[f"model:example/model@{'c' * 40}"]["scope"],
            )
            self.assertEqual(
                "required", references["sidecar:demo@unversioned"]["scope"])

            (stage / "UniversalConverterX.exe").write_bytes(b"changed")
            with self.assertRaisesRegex(
                    dependencies.DependencyError, "digest mismatch"):
                dependencies.verify_sbom(
                    stage, output, dependencies._read_json(lock_path))

    def test_build_and_installer_scripts_enforce_pipeline(self) -> None:
        build = (ROOT / "tools" / "build-all.ps1").read_text(encoding="utf-8")
        installer = (
            ROOT / "installer" / "build-installer.ps1"
        ).read_text(encoding="utf-8")

        for marker in (
            "PrepareDependencies",
            "PIP_CONSTRAINT",
            "PIP_NO_INDEX",
            "PIP_ONLY_BINARY",
            "--require-hashes",
            "sidecar_dependencies.py",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, build)
        self.assertNotIn("build-report.md", build)
        self.assertIn("UniversalConverterX.cdx.json", installer)
        self.assertIn("sidecar_dependencies.py", installer)


if __name__ == "__main__":
    unittest.main()

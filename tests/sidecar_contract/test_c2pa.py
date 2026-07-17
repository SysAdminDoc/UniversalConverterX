"""Tests for the offline read-only C2PA bridge."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "c2pa" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("c2pa_sidecar", SIDECAR)
assert SPEC and SPEC.loader
c2pa = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = c2pa
SPEC.loader.exec_module(c2pa)


def inspect_args(root: Path, **changes: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "input": str(root / "asset.jpg"),
        "output": str(root / "report.json"),
        "mode": "manifest",
        "external_manifest": None,
        "overwrite": False,
    }
    values.update(changes)
    return argparse.Namespace(**values)


class C2paTests(unittest.TestCase):
    def test_settings_disable_every_network_fetch(self) -> None:
        self.assertFalse(c2pa.OFFLINE_SETTINGS["verify"]["remote_manifest_fetch"])
        self.assertFalse(c2pa.OFFLINE_SETTINGS["verify"]["ocsp_fetch"])
        self.assertEqual([], c2pa.OFFLINE_SETTINGS["core"]["allowed_network_hosts"])

    def test_command_is_read_only_and_uses_explicit_settings(self) -> None:
        command = c2pa.build_command(
            "c2patool.exe", Path("asset.jpg"), Path("offline.json"), "tree", None,
        )
        self.assertIn("--settings", command)
        self.assertIn("--tree", command)
        for forbidden in (
            "--manifest", "--config", "--create", "--update", "--remote",
            "--signer-path", "--identity-signer-path", "--output",
        ):
            self.assertNotIn(forbidden, command)

    def test_external_manifest_is_local_argument(self) -> None:
        command = c2pa.build_command(
            "c2patool.exe", Path("asset.jpg"), Path("offline.json"),
            "manifest", Path("asset.c2pa"),
        )
        self.assertEqual("asset.c2pa", command[command.index("--external-manifest") + 1])

    def test_environment_ignores_inherited_trust_urls(self) -> None:
        with mock.patch.dict(
            c2pa.os.environ,
            {"C2PATOOL_TRUST_ANCHORS": "https://example.invalid/anchors.pem"},
        ):
            environment = c2pa._isolated_environment(Path("settings.json"), Path("config"))
        self.assertNotIn("C2PATOOL_TRUST_ANCHORS", environment)
        self.assertEqual("settings.json", environment["C2PATOOL_SETTINGS"])

    def test_success_atomically_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "asset.jpg").write_bytes(b"jpg")
            args = inspect_args(root)
            with mock.patch.object(c2pa, "_find_c2patool", return_value="c2patool.exe"), \
                    mock.patch.object(c2pa, "_version", return_value="c2patool 0.27.0"), \
                    mock.patch.object(c2pa, "_bounded_run", return_value=(0, b'{"active_manifest":"x"}', b"", None)):
                result = c2pa.op_inspect(args)
            self.assertEqual(0, result)
            self.assertEqual("x", json.loads((root / "report.json").read_text())["active_manifest"])

    def test_failure_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "asset.jpg").write_bytes(b"jpg")
            output = root / "report.json"
            output.write_bytes(b"old")
            args = inspect_args(root, overwrite=True)
            with mock.patch.object(c2pa, "_find_c2patool", return_value="c2patool.exe"), \
                    mock.patch.object(c2pa, "_version", return_value="c2patool 0.27.0"), \
                    mock.patch.object(c2pa, "_bounded_run", return_value=(1, b"", b"bad asset", None)):
                result = c2pa.op_inspect(args)
            self.assertEqual(1, result)
            self.assertEqual(b"old", output.read_bytes())

    def test_external_manifest_is_bounded_and_requires_c2pa_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "asset.jpg").write_bytes(b"jpg")
            invalid = root / "remote.url"
            invalid.write_text("https://example.invalid/manifest", encoding="utf-8")
            result = c2pa.op_inspect(inspect_args(root, external_manifest=str(invalid)))
            self.assertEqual(1, result)
            self.assertFalse((root / "report.json").exists())

    def test_version_floor_manifest_and_preset(self) -> None:
        self.assertTrue(c2pa._supported_version("c2patool 0.27.0"))
        self.assertFalse(c2pa._supported_version("c2patool 0.26.72"))
        manifest = json.loads(
            (ROOT / "tools" / "c2pa" / "ucx.sidecar.json").read_text(encoding="utf-8"),
        )
        self.assertFalse(manifest["tools"][0]["managed"])
        preset = (ROOT / "presets" / "c2pa-content-credentials-json.preset.xml").read_text(encoding="utf-8")
        self.assertIn("<Engine>c2pa</Engine>", preset)
        self.assertIn("<Arg>manifest</Arg>", preset)


if __name__ == "__main__":
    unittest.main()

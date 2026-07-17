"""Security and output-contract tests for the confined Pkl preset compiler."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "pkl-preset" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("pkl_preset_sidecar", SIDECAR)
assert SPEC and SPEC.loader
pkl_preset = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pkl_preset
SPEC.loader.exec_module(pkl_preset)


def valid_payload() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "name": "Fast & Safe H.264",
        "folder": "Video/Local",
        "description": "A <reviewed> preset.",
        "inputExtensions": ["mkv", ".mp4"],
        "outputFileNameTemplate": "{dir}/{stem}_safe",
        "outputExtension": "mkv",
        "engine": "clipforge",
        "invocationMode": "per-file",
        "args": ["proxy", "--height", "720"],
    }


class PklPresetTests(unittest.TestCase):
    def test_command_confines_modules_and_denies_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "local preset.pkl"
            command = pkl_preset.build_pkl_command("pkl.exe", source)

        self.assertEqual(["pkl.exe", "eval"], command[:2])
        self.assertEqual("json", command[command.index("--format") + 1])
        self.assertEqual("pkl:,file:", command[command.index("--allowed-modules") + 1])
        self.assertEqual(r"^prop:pkl\.outputFormat$", command[command.index("--allowed-resources") + 1])
        self.assertEqual("pkl:settings", command[command.index("--settings") + 1])
        self.assertIn("--no-cache", command)
        self.assertIn("--no-project", command)
        self.assertEqual(source.name, command[-1])
        self.assertNotIn("--module-output-separator", command)

    def test_schema_rejects_unknown_fields_traversal_and_duplicate_extensions(self) -> None:
        payload = valid_payload()
        payload["command"] = "powershell.exe"
        with self.assertRaisesRegex(ValueError, "Unknown fields: command"):
            pkl_preset.validate_payload(payload)

        payload = valid_payload()
        payload["folder"] = "Video/../Escape"
        with self.assertRaisesRegex(ValueError, "safe relative"):
            pkl_preset.validate_payload(payload)

        payload = valid_payload()
        payload["outputFileNameTemplate"] = "C:/outside/{stem}"
        with self.assertRaisesRegex(ValueError, "begin with"):
            pkl_preset.validate_payload(payload)

        payload = valid_payload()
        payload["inputExtensions"] = ["mkv", ".MKV"]
        with self.assertRaisesRegex(ValueError, "Duplicate input extension"):
            pkl_preset.validate_payload(payload)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key: name"):
            json.loads('{"name":"one","name":"two"}', object_pairs_hook=pkl_preset._no_duplicate_object)

    def test_rendered_xml_is_namespaced_escaped_and_parseable(self) -> None:
        normalized = pkl_preset.validate_payload(valid_payload())
        rendered = pkl_preset.render_preset_xml(normalized)
        root = ET.fromstring(rendered)
        namespace = {"ucx": pkl_preset.PRESET_NAMESPACE}

        self.assertEqual("Fast & Safe H.264", root.findtext("ucx:Name", namespaces=namespace))
        self.assertEqual("A <reviewed> preset.", root.findtext("ucx:Description", namespaces=namespace))
        self.assertEqual(["mkv", "mp4"], [node.text for node in root.findall("ucx:InputTypes/ucx:Extension", namespace)])
        self.assertIn(b"Fast &amp; Safe", rendered)
        self.assertIn(b"&lt;reviewed&gt;", rendered)

    def test_success_atomically_replaces_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "preset.pkl"
            source.write_text("name = \"fixture\"", encoding="utf-8")
            output = root / "compiled.preset.xml"
            output.write_bytes(b"old")
            args = argparse.Namespace(input=str(source), output=str(output), overwrite=True)
            rendered = json.dumps(valid_payload()).encode("utf-8")

            with mock.patch.object(pkl_preset, "_find_pkl", return_value="pkl.exe"), \
                    mock.patch.object(pkl_preset, "_version", return_value="Pkl 0.32.0"), \
                    mock.patch.object(pkl_preset, "_bounded_evaluate", return_value=(0, rendered, b"", None)):
                result = pkl_preset.op_compile(args)

            self.assertEqual(0, result)
            self.assertNotEqual(b"old", output.read_bytes())
            ET.parse(output)
            self.assertEqual([], list(root.glob(".compiled.preset.xml.*.tmp")))

    def test_failed_evaluation_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "preset.pkl"
            source.write_text("name = \"fixture\"", encoding="utf-8")
            output = root / "compiled.preset.xml"
            output.write_bytes(b"old")
            args = argparse.Namespace(input=str(source), output=str(output), overwrite=True)

            with mock.patch.object(pkl_preset, "_find_pkl", return_value="pkl.exe"), \
                    mock.patch.object(pkl_preset, "_version", return_value="Pkl 0.32.0"), \
                    mock.patch.object(pkl_preset, "_bounded_evaluate", return_value=(1, b"", b"bad module", None)):
                result = pkl_preset.op_compile(args)

            self.assertEqual(1, result)
            self.assertEqual(b"old", output.read_bytes())

    def test_current_version_floor_and_external_manifest(self) -> None:
        self.assertTrue(pkl_preset._supported_version("Pkl 0.32.0 (Windows 11.0.26100, native)"))
        self.assertTrue(pkl_preset._supported_version("Pkl 1.0.0"))
        self.assertFalse(pkl_preset._supported_version("Pkl 0.31.0"))
        manifest = json.loads((ROOT / "tools" / "pkl-preset" / "ucx.sidecar.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["tools"][0]["managed"])

    def test_shipped_preset_routes_pkl_to_compiler(self) -> None:
        preset = ROOT / "presets" / "pkl-to-ucx-preset.preset.xml"
        root = ET.parse(preset).getroot()
        namespace = {"ucx": pkl_preset.PRESET_NAMESPACE}
        self.assertEqual("pkl-preset", root.findtext("ucx:Engine", namespaces=namespace))
        self.assertEqual("per-file", root.findtext("ucx:InvocationMode", namespaces=namespace))
        self.assertEqual(["compile"], [node.text for node in root.findall("ucx:Args/ucx:Arg", namespace)])

    def test_security_fixture_attempts_environment_resource_read(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "pkl" / "forbidden_environment_resource.pkl"
        self.assertIn('read("env:PATH")', fixture.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

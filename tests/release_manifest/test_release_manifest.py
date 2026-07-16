"""Integration coverage for the release-manifest publishing script."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "installer" / "New-ReleaseManifest.ps1"


class ReleaseManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if cls.pwsh is None:
            raise unittest.SkipTest("PowerShell is unavailable")

    def test_hashes_artifacts_and_inventories_bundled_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"
            artifact = root / "UniversalConverterX_9.8.7.6.msi"
            second_artifact = root / "UniversalConverterX_9.8.7.6.msix"
            output = root / "UniversalConverterX_9.8.7.6.release.json"
            artifact.write_bytes(b"signed-installer-payload")
            second_artifact.write_bytes(b"signed-msix-payload")

            ffmpeg = bundle / "tools" / "ffmpeg" / "ffmpeg.exe"
            ffmpeg.parent.mkdir(parents=True)
            ffmpeg.write_bytes(b"fake-ffmpeg")
            sidecar = bundle / "Sidecars" / "sample" / "sidecar.py"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text("print('sample')\n", encoding="utf-8")
            ignored = bundle / "tools" / "ffmpeg" / "license.txt"
            ignored.write_text("license", encoding="utf-8")
            presets = root / "presets"
            presets.mkdir()
            (presets / "sample.preset.xml").write_text(
                '<Preset xmlns="https://universalconverterx.io/preset/v1">\n'
                "  <Name>Sample</Name><Engine>ffmpeg</Engine>\n"
                "</Preset>\n",
                encoding="utf-8",
            )

            def ps_quote(value: Path) -> str:
                return "'" + str(value).replace("'", "''") + "'"

            command = (
                f"& {ps_quote(SCRIPT)} -Version '9.8.7.6' "
                f"-ArtifactPath @({ps_quote(artifact)},{ps_quote(second_artifact)}) "
                f"-BundleRoot {ps_quote(bundle)} -PresetRoot {ps_quote(presets)} "
                f"-OutputPath {ps_quote(output)}"
            )
            result = subprocess.run(
                [self.pwsh, "-NoProfile", "-Command", command],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, payload["schemaVersion"])
            self.assertEqual("9.8.7.6", payload["version"])
            self.assertEqual("win-x64", payload["runtimeIdentifier"])
            self.assertEqual(
                {
                    "minimumPresetSchemaVersion": 1,
                    "maximumPresetSchemaVersion": 1,
                    "minimumQueueSchemaVersion": 1,
                    "maximumQueueSchemaVersion": 1,
                    "supportedEngines": ["converter", "ffmpeg"],
                },
                payload["compatibility"],
            )
            artifacts = {entry["fileName"]: entry for entry in payload["artifacts"]}
            self.assertEqual({artifact.name, second_artifact.name}, set(artifacts))
            self.assertEqual("msi", artifacts[artifact.name]["type"])
            self.assertEqual(artifact.stat().st_size, artifacts[artifact.name]["sizeBytes"])
            self.assertEqual(
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
                artifacts[artifact.name]["sha256"],
            )
            self.assertEqual("msix", artifacts[second_artifact.name]["type"])

            tools = {entry["path"]: entry for entry in payload["bundledTools"]}
            self.assertEqual({"tools/ffmpeg/ffmpeg.exe", "Sidecars/sample/sidecar.py"}, set(tools))
            self.assertEqual("tool", tools["tools/ffmpeg/ffmpeg.exe"]["kind"])
            self.assertEqual("sidecar", tools["Sidecars/sample/sidecar.py"]["kind"])
            self.assertEqual(
                hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
                tools["tools/ffmpeg/ffmpeg.exe"]["sha256"],
            )

    def test_rejects_empty_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"
            bundle.mkdir()
            artifact = root / "empty.msix"
            artifact.touch()
            output = root / "release.json"

            result = subprocess.run(
                [
                    self.pwsh,
                    "-NoProfile",
                    "-File",
                    str(SCRIPT),
                    "-Version",
                    "1.0.0.0",
                    "-ArtifactPath",
                    str(artifact),
                    "-BundleRoot",
                    str(bundle),
                    "-OutputPath",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

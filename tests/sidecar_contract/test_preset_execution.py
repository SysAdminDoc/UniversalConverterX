"""End-to-end smoke coverage for a real preset and its sidecar."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRESET = ROOT / "presets" / "newline-lf.preset.xml"
NAMESPACE = {"ucx": "https://universalconverterx.io/preset/v1"}


class PresetExecutionSmokeTests(unittest.TestCase):
    def test_newline_preset_executes_real_textencode_sidecar(self) -> None:
        root = ET.parse(PRESET).getroot()
        engine = root.findtext("ucx:Engine", namespaces=NAMESPACE)
        mode = root.findtext("ucx:InvocationMode", namespaces=NAMESPACE)
        args = [element.text or "" for element in root.findall("ucx:Args/ucx:Arg", NAMESPACE)]

        self.assertEqual("textencode", engine)
        self.assertEqual("batch-output-dir", mode)
        sidecar = ROOT / "tools" / engine / "sidecar.py"

        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            source = temp_path / "mixed endings 雪.txt"
            output_dir = temp_path / "converted output"
            source.write_bytes(b"first\r\nsecond\rthird\n")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(sidecar),
                    *args,
                    "--output-dir",
                    str(output_dir),
                    "--input",
                    str(source),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            self.assertEqual(
                b"first\nsecond\nthird\n",
                (output_dir / source.name).read_bytes(),
            )
            events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
            self.assertEqual("complete", events[-1]["event"])


if __name__ == "__main__":
    unittest.main()

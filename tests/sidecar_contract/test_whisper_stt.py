"""Contract tests for governed offline Whisper speaker diarization."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_DIR = ROOT / "tools" / "whisper-stt"
sys.path.insert(0, str(SIDECAR_DIR))
sys.path.insert(0, str(ROOT / "tools" / "_lib"))

import diarization_pack  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "ucx_whisper_stt_contract", SIDECAR_DIR / "sidecar.py")
assert _SPEC and _SPEC.loader
sidecar = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = sidecar
_SPEC.loader.exec_module(sidecar)


class WhisperSidecarTests(unittest.TestCase):
    def test_all_writers_preserve_speaker_labels(self) -> None:
        segments = [{
            "start": 0.0,
            "end": 1.25,
            "text": " Hello world ",
            "speaker": "SPEAKER_00",
        }]

        self.assertIn("[SPEAKER_00] Hello world", sidecar.segments_to_srt(segments))
        self.assertIn("[SPEAKER_00] Hello world", sidecar.segments_to_vtt(segments))
        self.assertEqual("[SPEAKER_00] Hello world", sidecar.segments_to_txt(segments))
        self.assertEqual("SPEAKER_00", json.loads(sidecar.segments_to_json(segments))[0]["speaker"])

    def test_overlap_assignment_always_emits_a_label(self) -> None:
        segments = [
            {"start": 0.0, "end": 2.0, "text": "first"},
            {"start": 4.0, "end": 5.0, "text": "second"},
        ]
        sidecar.assign_speakers(segments, [(0.5, 1.5, "SPEAKER_01")])

        self.assertEqual("SPEAKER_01", segments[0]["speaker"])
        self.assertEqual("SPEAKER_UNKNOWN", segments[1]["speaker"])

    def test_pack_manifest_is_revision_and_hash_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / diarization_pack.PACK_ID
            pack.mkdir()
            for name in diarization_pack.PACK_FILES:
                (pack / name).write_bytes(
                    diarization_pack.LOCAL_CONFIG.encode("utf-8")
                    if name == diarization_pack.CONFIG_FILENAME
                    else (name.encode("ascii") * 32)
                )
            diarization_pack._write_manifest(pack)

            self.assertEqual((True, "ready"), diarization_pack.validate_pack(pack))
            original = (pack / diarization_pack.SEGMENTATION_FILENAME).read_bytes()
            (pack / diarization_pack.SEGMENTATION_FILENAME).write_bytes(
                bytes([original[0] ^ 1]) + original[1:])
            ready, reason = diarization_pack.validate_pack(pack)
            self.assertFalse(ready)
            self.assertIn("SHA-256 mismatch", reason)

    def test_model_status_is_local_and_download_requires_consent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = {**os.environ, "UCX_DIARIZATION_MODEL_DIR": temporary}
            status = subprocess.run(
                [sys.executable, str(SIDECAR_DIR / "sidecar.py"), "model-status"],
                capture_output=True, text=True, env=environment, timeout=20,
            )
            self.assertNotEqual(0, status.returncode)
            self.assertIn("model_not_installed", status.stdout)

            download = subprocess.run(
                [sys.executable, str(SIDECAR_DIR / "sidecar.py"), "download-model"],
                capture_output=True, text=True, env=environment, timeout=20,
            )
            self.assertNotEqual(0, download.returncode)
            self.assertIn("license_acceptance_required", download.stdout)

    def test_inference_source_has_no_hub_token_path(self) -> None:
        source = (SIDECAR_DIR / "sidecar.py").read_text(encoding="utf-8")
        run_source = source.split("def run_diarization", 1)[1].split(
            "# ---------------------------------------------------------------------------", 1)[0]
        self.assertNotIn("HF_TOKEN", run_source)
        self.assertNotIn("from_pretrained(\"pyannote/", run_source)
        self.assertIn('PYANNOTE_METRICS_ENABLED"] = "0"', run_source)


if __name__ == "__main__":
    unittest.main()

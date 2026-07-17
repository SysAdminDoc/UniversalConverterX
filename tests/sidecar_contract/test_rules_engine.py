"""Regression tests for the safe conditional media rules planner."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "rules" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("rules_sidecar", SIDECAR)
assert SPEC and SPEC.loader
rules = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rules
SPEC.loader.exec_module(rules)


def sample_rules() -> dict:
    return {
        "version": 1,
        "rules": [
            {
                "name": "tag-hdr",
                "when": {"hdr": True},
                "action": {"preset": "archive-ffv1", "tags": ["hdr"]},
                "continue": True,
            },
            {
                "name": "compress-4k-hevc",
                "when": {"width_gte": 3840, "video_codec_in": ["hevc", "h265"]},
                "action": {"preset": "av1-quality", "output_suffix": "_av1"},
            },
        ],
        "default": {"skip": True, "note": "No conversion needed"},
    }


class RulesEngineTests(unittest.TestCase):
    def test_valid_document_supports_continue_and_default(self) -> None:
        payload = sample_rules()
        rules.validate_rules(payload)
        names, actions = rules.evaluate(payload, {
            "hdr": True, "width": 3840, "video_codec": "hevc",
            "size_mb": 10, "duration": 2, "height": 2160, "channels": 2,
            "extension": "mkv", "audio_codec": "aac", "has_subtitles": False,
        })
        self.assertEqual(["tag-hdr", "compress-4k-hevc"], names)
        self.assertEqual("archive-ffv1", actions[0]["preset"])
        self.assertEqual("av1-quality", actions[1]["preset"])

        names, actions = rules.evaluate(payload, {
            "hdr": False, "width": 1920, "video_codec": "h264",
            "size_mb": 10, "duration": 2, "height": 1080, "channels": 2,
            "extension": "mp4", "audio_codec": "aac", "has_subtitles": False,
        })
        self.assertEqual(["default"], names)
        self.assertTrue(actions[0]["skip"])

    def test_arbitrary_command_actions_are_rejected(self) -> None:
        payload = sample_rules()
        payload["rules"][0]["action"] = {"command": "format C:"}
        with self.assertRaisesRegex(ValueError, "unsupported action"):
            rules.validate_rules(payload)

    def test_unsafe_preset_and_suffix_are_rejected(self) -> None:
        payload = sample_rules()
        payload["rules"][0]["action"] = {"preset": "../../evil"}
        with self.assertRaisesRegex(ValueError, "safe preset"):
            rules.validate_rules(payload)
        payload = sample_rules()
        payload["rules"][0]["action"] = {"preset": "safe", "output_suffix": "../escape"}
        with self.assertRaisesRegex(ValueError, "safe filename"):
            rules.validate_rules(payload)

    def test_extension_and_numeric_conditions_match(self) -> None:
        facts = {
            "extension": "mkv", "size_mb": 1500, "duration": 90,
            "width": 1920, "height": 1080, "video_codec": "h264",
            "audio_codec": "aac", "channels": 6, "hdr": False,
            "has_subtitles": True,
        }
        self.assertTrue(rules.rule_matches({
            "extension_in": ["mkv", "mp4"], "size_mb_gte": 1000,
            "channels_gte": 6, "has_subtitles": True,
        }, facts))
        self.assertFalse(rules.rule_matches({"extension_not_in": ["mkv"]}, facts))

    def test_atomic_plan_write_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "plan.json"
            output.write_text("stale", encoding="utf-8")
            rules.atomic_json(output, {"version": 1, "results": []})
            payload = json.loads(output.read_text(encoding="utf-8"))
            leftovers = list(output.parent.glob(f".{output.name}.*.tmp"))
        self.assertEqual(1, payload["version"])
        self.assertEqual([], leftovers)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for tools/_lib/ucx_sidecar.py."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "_lib"))
import ucx_sidecar  # noqa: E402


class SharedSidecarUtilsTests(unittest.TestCase):
    def test_emit_writes_one_unicode_ndjson_event(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ucx_sidecar.emit("log", level="info", message="résumé 日本語")

        lines = output.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        self.assertEqual("résumé 日本語", json.loads(lines[0])["message"])

    def test_emit_accepts_prebuilt_event_payload(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ucx_sidecar.emit({"event": "stem", "name": "vocals"})

        self.assertEqual(
            {"event": "stem", "name": "vocals"},
            json.loads(output.getvalue()),
        )

    def test_find_tool_honors_existing_environment_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "ffmpeg.exe"
            executable.write_bytes(b"placeholder")
            with patch.dict(os.environ, {"FFMPEG_PATH": str(executable)}):
                result = ucx_sidecar.find_ffmpeg()

        self.assertEqual(str(executable), result)

    def test_probe_media_rejects_non_json_output(self):
        result = ucx_sidecar.probe_media(sys.executable, "missing.file")

        self.assertIsNone(result)

    def test_run_ffmpeg_maps_progress_and_keeps_bounded_errors(self):
        script = (
            "print('out_time_us=500000');"
            "print('progress=end');"
            "print('diagnostic')"
        )
        events: list[tuple[str, dict]] = []

        result = ucx_sidecar.run_ffmpeg(
            [sys.executable, "-c", script],
            1.0,
            "encode",
            inject_progress_args=False,
            event_emitter=lambda event, **fields: events.append((event, fields)),
        )

        self.assertEqual(0, result)
        progress = [fields for event, fields in events if event == "progress"]
        self.assertEqual(50.0, progress[0]["percent"])
        self.assertEqual(100.0, progress[-1]["percent"])

    def test_sidecars_use_shared_protocol_and_media_helpers(self):
        specialized_emitters = {"videocrush"}
        helper_names = {
            "find_ffmpeg": "shared_find_ffmpeg",
            "_find_ffmpeg": "shared_find_ffmpeg",
            "find_ffprobe": "shared_find_ffprobe",
            "_find_ffprobe": "shared_find_ffprobe",
            "probe": "probe_media",
            "run_ffmpeg": "shared_run_ffmpeg",
        }

        for sidecar in sorted((ROOT / "tools").glob("*/sidecar.py")):
            with self.subTest(sidecar=sidecar.parent.name):
                source = sidecar.read_text(encoding="utf-8-sig")
                tree = ast.parse(source)
                local_functions = {
                    node.name: ast.get_source_segment(source, node) or ""
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                }

                if sidecar.parent.name not in specialized_emitters:
                    self.assertNotIn("emit", local_functions)
                    self.assertIn("from ucx_sidecar import", source)

                for function_name, shared_name in helper_names.items():
                    if function_name in local_functions:
                        self.assertIn(shared_name, local_functions[function_name])

                build_script = sidecar.with_name("build.ps1")
                if "from ucx_sidecar import" in source and build_script.is_file():
                    build_source = build_script.read_text(encoding="utf-8-sig")
                    self.assertIn("--paths", build_source)
                    self.assertIn("../_lib", build_source)


if __name__ == "__main__":
    unittest.main()

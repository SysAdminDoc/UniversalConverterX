import argparse
import importlib.util
import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock


SIDECAR_PATH = Path(__file__).resolve().parents[1] / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ucx_ab_av1_sidecar", SIDECAR_PATH)
sidecar = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sidecar)


class SmartCompressTests(TestCase):
    def test_ndjson_is_safe_for_unicode_input_paths_on_windows(self):
        output = io.StringIO()

        with mock.patch.object(sidecar.sys, "stdout", output):
            sidecar.emit("log", level="info", message="\u2192 \u65e5\u672c\u8a9e \U0001f3ac")

        encoded = output.getvalue().encode("ascii")
        self.assertEqual("\u2192 \u65e5\u672c\u8a9e \U0001f3ac", json.loads(encoded)["message"])

    def test_auto_encode_verifies_final_vmaf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.mkv"
            output_path = root / "output.mkv"
            input_path.write_bytes(b"source")
            commands = []
            events = []

            def fake_stream(command, *_args, **_kwargs):
                commands.append(command)
                if command[1] == "auto-encode":
                    output_path.write_bytes(b"encoded")
                    return 0, "crf 31 VMAF 93.4"
                return 0, "93.18"

            args = argparse.Namespace(
                input=str(input_path),
                output=str(output_path),
                encoder="libsvtav1",
                target_vmaf=93,
                preset="6",
                samples=None,
                min_crf=None,
                max_crf=None,
                xpsnr=False,
                verify_vmaf=True,
            )
            with (
                mock.patch.object(sidecar, "_find_ab_av1", return_value="ab-av1.exe"),
                mock.patch.object(sidecar, "_stream", side_effect=fake_stream),
                mock.patch.object(sidecar, "emit", side_effect=lambda event, **fields: events.append((event, fields))),
            ):
                result = sidecar.op_auto_encode(args)

        self.assertEqual(0, result)
        self.assertEqual("auto-encode", commands[0][1])
        self.assertIn("--min-vmaf", commands[0])
        self.assertEqual(
            ["ab-av1.exe", "vmaf", "--reference", str(input_path), "--distorted", str(output_path)],
            commands[1])
        complete = next(fields for event, fields in events if event == "complete")
        self.assertTrue(complete["vmaf_verified"])
        self.assertEqual(31, complete["final_crf"])
        self.assertEqual(93.18, complete["final_vmaf"])

    def test_search_progress_does_not_regress_with_predicted_size_percentages(self):
        class FakeProcess:
            stdout = iter([
                "crf 37.5 VMAF 91.2 predicted size (10%)\n",
                "crf 18 VMAF 99.1 predicted size (22%)\n",
                "crf 35 VMAF 93.1 predicted size (13%)\n",
            ])
            returncode = 0

            @staticmethod
            def wait():
                return 0

        events = []
        with (
            mock.patch.object(sidecar.subprocess, "Popen", return_value=FakeProcess()),
            mock.patch.object(sidecar, "emit", side_effect=lambda event, **fields: events.append((event, fields))),
        ):
            result, _ = sidecar._stream(["ab-av1.exe"], "search", end_pct=85)

        percents = [fields["percent"] for event, fields in events if event == "progress"]
        self.assertEqual(0, result)
        self.assertEqual(sorted(percents), percents)

    def test_missing_upstream_binary_fails_before_encoding(self):
        args = argparse.Namespace()
        events = []

        with (
            mock.patch.object(sidecar, "_find_ab_av1", return_value=None),
            mock.patch.object(sidecar, "emit", side_effect=lambda event, **fields: events.append((event, fields))),
        ):
            result = sidecar.op_auto_encode(args)

        self.assertEqual(1, result)
        self.assertEqual("missing_ab_av1", events[-1][1]["code"])

    def test_vmaf_parser_accepts_current_numeric_stdout(self):
        self.assertEqual(94.625, sidecar._last_vmaf("progress\n94.625\n"))

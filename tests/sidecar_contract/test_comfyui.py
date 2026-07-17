"""Security and atomic-export tests for the local ComfyUI bridge."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("comfyui_sidecar", ROOT / "tools" / "comfyui" / "sidecar.py")
assert SPEC and SPEC.loader
comfyui = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = comfyui
SPEC.loader.exec_module(comfyui)


def write_workflow(path: Path) -> None:
    path.write_text(json.dumps({
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "local prompt"}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "UCX", "images": ["6", 0]}},
    }), encoding="utf-8")


def run_operation(operation, arguments: list[str]) -> tuple[int, list[dict]]:
    args = comfyui.build_parser().parse_args(arguments)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = operation(args)
    return code, [json.loads(line) for line in stdout.getvalue().splitlines() if line]


class ComfyUiTests(unittest.TestCase):
    def test_endpoint_is_strictly_loopback_http(self) -> None:
        self.assertEqual("http://127.0.0.1:8188", comfyui.validate_endpoint("http://127.0.0.1:8188"))
        for endpoint in (
            "https://127.0.0.1:8188", "http://192.168.1.10:8188",
            "http://example.com:8188", "http://user:pass@localhost:8188",
            "http://localhost:8188/api", "http://localhost:8188?token=x",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(comfyui.SidecarError):
                comfyui.validate_endpoint(endpoint)

    def test_run_requires_explicit_workflow_acceptance_before_network(self) -> None:
        with mock.patch.object(comfyui, "_request_json") as request:
            code, events = run_operation(comfyui.op_run, [
                "run", "--input", "workflow.json", "--output-dir", "out",
            ])
        self.assertEqual(1, code)
        self.assertEqual("workflow_not_accepted", events[-1]["code"])
        request.assert_not_called()

    def test_workflow_rejects_ui_format_remote_urls_credentials_and_network_nodes(self) -> None:
        invalid = (
            {"nodes": []},
            {"1": {"class_type": "LoadImage", "inputs": {"image": "https://example.com/x.png"}}},
            {"1": {"class_type": "LoadImage", "inputs": {"api_key": "secret"}}},
            {"1": {"class_type": "OpenAIImage", "inputs": {"prompt": "hello"}}},
        )
        with tempfile.TemporaryDirectory() as temp:
            for index, payload in enumerate(invalid):
                path = Path(temp) / f"invalid-{index}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(index=index), self.assertRaises(comfyui.SidecarError):
                    comfyui.load_workflow(path)

    def test_overrides_are_bounded_existing_json_values(self) -> None:
        workflow = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old", "seed": 1}}}
        comfyui.apply_overrides(workflow, ['6.text="new"', "6.seed=42"])
        self.assertEqual("new", workflow["6"]["inputs"]["text"])
        self.assertEqual(42, workflow["6"]["inputs"]["seed"])
        for override in ("missing.seed=1", "6.unknown=1", '6.text="https://example.com"'):
            with self.subTest(override=override), self.assertRaises(comfyui.SidecarError):
                comfyui.apply_overrides(workflow, [override])

    def test_output_references_keep_only_safe_final_outputs(self) -> None:
        entry = {"outputs": {"9": {"images": [
            {"filename": "result.png", "subfolder": "", "type": "output"},
            {"filename": "preview.png", "subfolder": "", "type": "temp"},
            {"filename": "../escape.png", "subfolder": "", "type": "output"},
        ]}}}
        references = comfyui.collect_output_references(entry)
        self.assertEqual(["result.png"], [item.filename for item in references])

    def test_run_exports_outputs_and_manifest_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workflow = root / "workflow.json"
            output = root / "result"
            write_workflow(workflow)

            def request(_endpoint, path, **_kwargs):
                if path == "/prompt":
                    return {"prompt_id": "prompt-1"}
                return {"prompt-1": {"status": {"completed": True}, "outputs": {
                    "9": {"images": [{
                        "filename": "generated.png", "subfolder": "", "type": "output",
                    }]},
                }}}

            def download(_endpoint, _reference, destination):
                destination.write_bytes(b"PNGDATA")
                return 7

            with mock.patch.object(comfyui, "_request_json", side_effect=request), \
                    mock.patch.object(comfyui, "_download_output", side_effect=download):
                code, events = run_operation(comfyui.op_run, [
                    "run", "--input", str(workflow), "--output-dir", str(output),
                    "--accept-workflow", "--poll-interval", "0.1",
                ])

            self.assertEqual(0, code, events)
            self.assertEqual(b"PNGDATA", (output / "generated.png").read_bytes())
            manifest = json.loads((output / "workflow-result.json").read_text(encoding="utf-8"))
            self.assertEqual("prompt-1", manifest["promptId"])
            self.assertTrue(manifest["loopbackOnly"])
            self.assertEqual("complete", events[-1]["event"])

    def test_existing_output_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workflow = root / "workflow.json"
            output = root / "result"
            write_workflow(workflow)
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            code, events = run_operation(comfyui.op_run, [
                "run", "--input", str(workflow), "--output-dir", str(output), "--accept-workflow",
            ])
            self.assertEqual(1, code)
            self.assertEqual("output_exists", events[-1]["code"])
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_empty_precreated_output_supports_extract_each_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workflow = root / "workflow.json"
            output = root / "result"
            write_workflow(workflow)
            output.mkdir()

            def request(_endpoint, path, **_kwargs):
                if path == "/prompt":
                    return {"prompt_id": "prompt-empty"}
                return {"prompt-empty": {"status": {"completed": True}, "outputs": {}}}

            with mock.patch.object(comfyui, "_request_json", side_effect=request):
                code, events = run_operation(comfyui.op_run, [
                    "run", "--input", str(workflow), "--output-dir", str(output),
                    "--accept-workflow", "--poll-interval", "0.1",
                ])

            self.assertEqual(0, code, events)
            self.assertTrue((output / "workflow-result.json").is_file())

    def test_precreated_junction_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workflow = root / "workflow.json"
            output = root / "result"
            write_workflow(workflow)
            output.mkdir()
            with mock.patch.object(comfyui.os.path, "isjunction", return_value=True, create=True):
                code, events = run_operation(comfyui.op_run, [
                    "run", "--input", str(workflow), "--output-dir", str(output), "--accept-workflow",
                ])
            self.assertEqual(1, code)
            self.assertEqual("output_exists", events[-1]["code"])

    def test_preset_requires_review_acknowledgement(self) -> None:
        preset = (ROOT / "presets" / "comfyui-run-reviewed-workflow.preset.xml").read_text(encoding="utf-8")
        self.assertIn("<Engine>comfyui</Engine>", preset)
        self.assertIn("<Arg>--accept-workflow</Arg>", preset)
        self.assertIn("<InvocationMode>extract-each</InvocationMode>", preset)


if __name__ == "__main__":
    unittest.main()

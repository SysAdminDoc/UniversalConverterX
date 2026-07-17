"""Explicit-trust bridge to an already running local ComfyUI server.

Only HTTP loopback endpoints are accepted. UCX does not install ComfyUI,
download models/nodes, submit to Comfy Cloud, or enable API nodes. A reviewed
API-format workflow is required for every run because ComfyUI custom nodes are
executable Python inside the user's separately managed server process.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit


DEFAULT_ENDPOINT = "http://127.0.0.1:8188"
MAX_WORKFLOW_BYTES = 4 * 1024 * 1024
MAX_JSON_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
MAX_TOTAL_OUTPUT_BYTES = 8 * 1024 * 1024 * 1024
MAX_OUTPUTS = 1_000
MAX_OVERRIDES = 100
REMOTE_NODE_MARKERS = (
    "anthropic", "api", "cloud", "download", "falapi", "gemini", "http", "ideogram",
    "kling", "lumaapi", "openai", "replicate", "url", "websocket",
)
SECRET_KEYS = {"apikey", "authorization", "password", "secret", "token"}


class SidecarError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


_OPENER = urllib.request.build_opener(NoRedirect)


def _urlopen(request: urllib.request.Request, timeout: float):
    """Open without redirects; named explicitly for the network-path audit."""
    return _OPENER.open(request, timeout=timeout)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def validate_endpoint(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port or 80
    except ValueError as exc:
        raise SidecarError(f"Invalid ComfyUI endpoint: {exc}") from exc
    if parsed.scheme.lower() != "http":
        raise SidecarError("ComfyUI endpoint must use plain HTTP on loopback.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SidecarError("ComfyUI endpoint cannot contain credentials, query, or fragment data.")
    if parsed.path not in ("", "/"):
        raise SidecarError("ComfyUI endpoint must not contain a path.")
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SidecarError("ComfyUI endpoint must be 127.0.0.1, ::1, or localhost.")
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SidecarError(f"ComfyUI loopback endpoint could not be resolved: {exc}") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in addresses):
        raise SidecarError("ComfyUI endpoint did not resolve exclusively to loopback addresses.")
    rendered_host = f"[{host}]" if ":" in host else host
    return f"http://{rendered_host}:{port}"


def _request_json(
    endpoint: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    url = endpoint + path
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json", "User-Agent": "UniversalConverterX-comfyui"},
    )
    try:
        with _urlopen(request, timeout) as response:
            body = response.read(MAX_JSON_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise SidecarError(f"ComfyUI request failed: {exc}") from exc
    if len(body) > MAX_JSON_RESPONSE_BYTES:
        raise SidecarError("ComfyUI JSON response exceeded 16 MiB.")
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SidecarError("ComfyUI returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise SidecarError("ComfyUI JSON response must be an object.")
    return decoded


def _normalized_key(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _validate_local_value(value: object, depth: int = 0) -> None:
    if depth > 64:
        raise SidecarError("Workflow nesting exceeds 64 levels.")
    if isinstance(value, str):
        if len(value) > 100_000:
            raise SidecarError("Workflow string value exceeds 100,000 characters.")
        lowered = value.strip().lower()
        if lowered.startswith(("ftp://", "http://", "https://", "s3://", "ws://", "wss://", "www.")):
            raise SidecarError("Workflow contains a remote URL; UCX ComfyUI workflows are local-only.")
        return
    if isinstance(value, dict):
        if len(value) > 20_000:
            raise SidecarError("Workflow object is too large.")
        for key, child in value.items():
            if _normalized_key(key) in SECRET_KEYS:
                raise SidecarError("Workflow contains a credential field; API/cloud credentials are forbidden.")
            _validate_local_value(child, depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 20_000:
            raise SidecarError("Workflow array is too large.")
        for child in value:
            _validate_local_value(child, depth + 1)


def load_workflow(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.suffix.lower() != ".json":
        raise SidecarError("Input must be an existing ComfyUI API-format .json file.")
    if path.stat().st_size > MAX_WORKFLOW_BYTES:
        raise SidecarError("Workflow exceeds the 4 MiB limit.")
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SidecarError(f"Workflow JSON could not be read: {exc}") from exc
    if not isinstance(workflow, dict) or not workflow or len(workflow) > 5_000:
        raise SidecarError("Workflow must be a non-empty API-format node object with at most 5,000 nodes.")
    for node_id, node in workflow.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            raise SidecarError("Every workflow node must have a string ID and object value.")
        class_type = node.get("class_type")
        inputs = node.get("inputs")
        if not isinstance(class_type, str) or not class_type or not isinstance(inputs, dict):
            raise SidecarError(f"Node {node_id!r} is not an API-format ComfyUI node.")
        lowered = class_type.lower()
        if any(marker in lowered for marker in REMOTE_NODE_MARKERS):
            raise SidecarError(f"Node {node_id!r} ({class_type}) appears network/cloud-capable and is blocked.")
    _validate_local_value(workflow)
    return workflow


def apply_overrides(workflow: dict[str, Any], overrides: list[str]) -> None:
    if len(overrides) > MAX_OVERRIDES:
        raise SidecarError(f"At most {MAX_OVERRIDES} workflow overrides are allowed.")
    for override in overrides:
        if "=" not in override or "." not in override.split("=", 1)[0]:
            raise SidecarError("Each --set value must use NODE.INPUT=JSON_VALUE.")
        target, raw_value = override.split("=", 1)
        node_id, input_name = target.rsplit(".", 1)
        node = workflow.get(node_id)
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict) or input_name not in inputs:
            raise SidecarError(f"Override target does not exist: {target}")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise SidecarError(f"Override value for {target} must be valid JSON.") from exc
        _validate_local_value(value)
        inputs[input_name] = value


@dataclass(frozen=True)
class OutputReference:
    node_id: str
    filename: str
    subfolder: str
    kind: str


def collect_output_references(history_entry: dict[str, Any]) -> list[OutputReference]:
    outputs = history_entry.get("outputs")
    if not isinstance(outputs, dict):
        return []
    found: list[OutputReference] = []
    seen: set[tuple[str, str, str]] = set()
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        for items in node_output.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                kind = item.get("type")
                subfolder = item.get("subfolder", "")
                if not isinstance(filename, str) or kind != "output" or not isinstance(subfolder, str):
                    continue
                if not filename or len(filename) > 255 or len(subfolder) > 1_024:
                    continue
                safe_name = Path(filename).name
                if safe_name != filename or any(character in '<>:"/\\|?*' or ord(character) < 32 for character in filename):
                    continue
                key = (filename, subfolder, kind)
                if key in seen:
                    continue
                seen.add(key)
                found.append(OutputReference(str(node_id), filename, subfolder, kind))
                if len(found) > MAX_OUTPUTS:
                    raise SidecarError(f"Workflow produced more than {MAX_OUTPUTS} output references.")
    return found


def _download_output(endpoint: str, reference: OutputReference, destination: Path) -> int:
    query = urllib.parse.urlencode({
        "filename": reference.filename,
        "subfolder": reference.subfolder,
        "type": reference.kind,
    })
    request = urllib.request.Request(
        f"{endpoint}/view?{query}", headers={"User-Agent": "UniversalConverterX-comfyui"})
    downloaded = 0
    try:
        with _urlopen(request, 120) as response, destination.open("xb") as handle:
            declared = int(response.headers.get("Content-Length", "0") or 0)
            if declared > MAX_OUTPUT_BYTES:
                raise SidecarError(f"ComfyUI output exceeds the 2 GiB per-file limit: {reference.filename}")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_OUTPUT_BYTES:
                    raise SidecarError(f"ComfyUI output exceeds the 2 GiB per-file limit: {reference.filename}")
                handle.write(chunk)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        destination.unlink(missing_ok=True)
        raise SidecarError(f"Could not export {reference.filename}: {exc}") from exc
    if downloaded == 0:
        destination.unlink(missing_ok=True)
        raise SidecarError(f"ComfyUI returned an empty output: {reference.filename}")
    return downloaded


def _poll_history(endpoint: str, prompt_id: str, timeout_seconds: int, interval: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        history = _request_json(endpoint, f"/history/{urllib.parse.quote(prompt_id, safe='')}")
        entry = history.get(prompt_id)
        if isinstance(entry, dict):
            status = entry.get("status")
            status_text = str(status.get("status_str", "")) if isinstance(status, dict) else ""
            messages = status.get("messages", []) if isinstance(status, dict) else []
            if status_text.lower() == "error" or any(
                    isinstance(message, list) and message and message[0] == "execution_error"
                    for message in messages):
                raise SidecarError("ComfyUI reported a workflow execution error.")
            if "outputs" in entry or (isinstance(status, dict) and status.get("completed") is True):
                return entry
        emit("progress", percent=None, stage="comfyui-wait", current=attempt, total=None, eta_seconds=None)
        time.sleep(interval)
    raise SidecarError(f"ComfyUI workflow did not finish within {timeout_seconds} seconds.")


def op_probe(args: argparse.Namespace) -> int:
    try:
        endpoint = validate_endpoint(args.endpoint)
        stats = _request_json(endpoint, "/system_stats", timeout=10)
    except SidecarError as exc:
        return fail("comfyui_unavailable", str(exc))
    system = stats.get("system") if isinstance(stats.get("system"), dict) else {}
    devices = stats.get("devices") if isinstance(stats.get("devices"), list) else []
    emit("backend", available=True, endpoint=endpoint, loopback_only=True,
         comfyui_version=system.get("comfyui_version"), devices=len(devices), cloud_enabled=False)
    emit("complete", output="", size_bytes=0, available=True)
    return 0


def op_run(args: argparse.Namespace) -> int:
    if not args.accept_workflow:
        return fail(
            "workflow_not_accepted",
            "Review the API-format workflow and re-run with --accept-workflow; custom nodes execute inside ComfyUI.",
        )
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    precreated_output = False
    if output.exists():
        try:
            is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(output))
            occupied = output.is_symlink() or is_junction or not output.is_dir() or any(output.iterdir())
        except OSError as exc:
            return fail("output_unavailable", f"Output directory cannot be inspected: {exc}")
        if occupied:
            return fail("output_exists", f"Output directory already exists and is not empty: {output}")
        precreated_output = True
    try:
        endpoint = validate_endpoint(args.endpoint)
        workflow = load_workflow(source)
        apply_overrides(workflow, args.set_values)
        emit("log", level="warning", message=(
            "Submitting a reviewed local workflow to loopback ComfyUI. Start ComfyUI with --disable-api-nodes; "
            "UCX blocks known network nodes and remote URL/credential fields but cannot audit custom-node code."))
        queued = _request_json(endpoint, "/prompt", payload={"prompt": workflow})
        prompt_id = queued.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id or len(prompt_id) > 256:
            raise SidecarError("ComfyUI did not return a valid prompt_id.")
        history_entry = _poll_history(endpoint, prompt_id, args.timeout_seconds, args.poll_interval)
        references = collect_output_references(history_entry)
        output.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=f".{output.name}.ucx-comfyui-", dir=output.parent))
        total = 0
        exported: list[dict[str, Any]] = []
        used_names: set[str] = set()
        try:
            for index, reference in enumerate(references, 1):
                filename = reference.filename
                if filename.lower() in used_names:
                    safe_node = "".join(c for c in reference.node_id if c.isalnum() or c in "-_")[:32] or "node"
                    filename = f"{safe_node}-{filename}"
                used_names.add(filename.lower())
                destination = staged / filename
                size = _download_output(endpoint, reference, destination)
                total += size
                if total > MAX_TOTAL_OUTPUT_BYTES:
                    raise SidecarError("Workflow outputs exceed the 8 GiB aggregate limit.")
                exported.append({"nodeId": reference.node_id, "file": filename, "sizeBytes": size})
                emit("progress", percent=round(index / max(1, len(references)) * 100, 1),
                     stage="comfyui-export", current=index, total=len(references), eta_seconds=None)
            manifest = {
                "schemaVersion": 1,
                "engine": "comfyui",
                "workflow": str(source),
                "promptId": prompt_id,
                "endpoint": endpoint,
                "loopbackOnly": True,
                "outputs": exported,
            }
            (staged / "workflow-result.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if precreated_output:
                try:
                    output.rmdir()
                except OSError as exc:
                    raise SidecarError(f"Pre-created output directory is no longer empty: {exc}") from exc
            try:
                os.replace(staged, output)
            except BaseException:
                if precreated_output:
                    output.mkdir(exist_ok=True)
                raise
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
    except SidecarError as exc:
        return fail("comfyui_failed", str(exc))
    emit("complete", output=str(output), size_bytes=total, count=len(exported), prompt_id=prompt_id)
    return 0


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        result = int(value)
        if not minimum <= result <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return result
    return parse


def _bounded_float(minimum: float, maximum: float):
    def parse(value: str) -> float:
        result = float(value)
        if not minimum <= result <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return result
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    probe = commands.add_parser("probe", help="Probe a loopback ComfyUI server.")
    probe.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    probe.set_defaults(func=op_probe)
    run = commands.add_parser("run", help="Run a reviewed local API-format workflow.")
    run.add_argument("--input", required=True, help="ComfyUI workflow exported with Export (API).")
    run.add_argument("--output-dir", required=True)
    run.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    run.add_argument("--accept-workflow", action="store_true")
    run.add_argument("--set", dest="set_values", action="append", default=[], metavar="NODE.INPUT=JSON")
    run.add_argument("--timeout-seconds", type=_bounded_int(1, 86_400), default=3_600)
    run.add_argument("--poll-interval", type=_bounded_float(0.1, 10.0), default=1.0)
    run.set_defaults(func=op_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

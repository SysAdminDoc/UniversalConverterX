"""Confined offline Pkl-to-UCX-preset compiler."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_tool


MINIMUM_VERSION = (0, 32, 0)
MAX_SOURCE_BYTES = 1024 * 1024
MAX_RENDER_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 256 * 1024
EVALUATION_SECONDS = 15
PRESET_NAMESPACE = "https://universalconverterx.io/preset/v1"
INVOCATION_MODES = {
    "per-file", "batch-input-list", "batch-output-dir",
    "batch-single-output", "extract-each",
}
REQUIRED_KEYS = {
    "schemaVersion", "name", "folder", "inputExtensions",
    "outputFileNameTemplate", "outputExtension", "engine",
    "invocationMode", "args",
}
OPTIONAL_KEYS = {"description"}
_VERSION_RE = re.compile(r"\bPkl\s+(\d+)\.(\d+)\.(\d+)\b", re.IGNORECASE)
_ENGINE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_EXTENSION_RE = re.compile(r"^[a-z0-9][a-z0-9+_-]{0,15}$")
_OUTPUT_EXTENSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./+()-]{0,127}$")


def _here() -> Path:
    return Path(__file__).resolve().parent


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_pkl() -> str | None:
    return find_tool("pkl", env_var="PKL_PATH", anchor=_here())


def _version(pkl: str | None) -> str | None:
    if not pkl:
        return None
    try:
        result = subprocess.run(
            [pkl, "--version"], capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0][:300] if result.returncode == 0 and text else None


def _supported_version(version: str | None) -> bool:
    match = _VERSION_RE.search(version or "")
    return bool(match and tuple(int(part) for part in match.groups()) >= MINIMUM_VERSION)


def op_probe(_: argparse.Namespace) -> int:
    pkl = _find_pkl()
    version = _version(pkl)
    supported = _supported_version(version)
    emit("backend", available=bool(pkl and supported), pkl=pkl, version=version, version_supported=supported)
    emit("complete", output="", size_bytes=0, available=bool(pkl and supported))
    return 0 if pkl and supported else 1


def build_pkl_command(pkl: str, source: Path) -> list[str]:
    root = str(source.parent.resolve())
    return [
        pkl,
        "eval",
        "--format", "json",
        "--allowed-modules", "pkl:,file:",
        # Pkl's standard output renderer reads only this CLI-provided built-in
        # property to select JSON. Keep every file/env/http/custom resource
        # outside the allowlist.
        "--allowed-resources", r"^prop:pkl\.outputFormat$",
        "--root-dir", root,
        "--working-dir", root,
        "--settings", "pkl:settings",
        "--timeout", str(EVALUATION_SECONDS),
        "--no-cache",
        "--no-project",
        "--color", "never",
        source.name,
    ]


def _bounded_evaluate(command: list[str], cwd: Path) -> tuple[int, bytes, bytes, str | None]:
    with tempfile.TemporaryDirectory(prefix="ucx-pkl-") as temp:
        stdout_path = Path(temp) / "stdout.json"
        stderr_path = Path(temp) / "stderr.txt"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command, cwd=str(cwd), stdout=stdout, stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + EVALUATION_SECONDS + 5
            reason: str | None = None
            while process.poll() is None:
                if stdout_path.stat().st_size > MAX_RENDER_BYTES:
                    reason = "output_too_large"
                    process.kill()
                    break
                if stderr_path.stat().st_size > MAX_DIAGNOSTIC_BYTES:
                    reason = "diagnostics_too_large"
                    process.kill()
                    break
                if time.monotonic() > deadline:
                    reason = "timeout"
                    process.kill()
                    break
                time.sleep(0.05)
            rc = process.wait()
        stdout_data = stdout_path.read_bytes()[: MAX_RENDER_BYTES + 1]
        stderr_data = stderr_path.read_bytes()[-MAX_DIAGNOSTIC_BYTES:]
    return rc, stdout_data, stderr_data, reason


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _text(value: object, field: str, *, minimum: int = 1, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or "\x00" in value:
        raise ValueError(f"{field} must be a string between {minimum} and {maximum} characters.")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise ValueError(f"{field} contains a disallowed control character.")
    return value


def validate_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Pkl output must be one JSON object.")
    keys = set(payload)
    missing = REQUIRED_KEYS - keys
    unknown = keys - REQUIRED_KEYS - OPTIONAL_KEYS
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(sorted(missing)))
    if unknown:
        raise ValueError("Unknown fields: " + ", ".join(sorted(unknown)))
    if payload["schemaVersion"] != 1:
        raise ValueError("schemaVersion must be 1.")

    name = _text(payload["name"], "name", maximum=100).strip()
    folder = _text(payload["folder"], "folder", maximum=128).strip()
    if not name:
        raise ValueError("name cannot be blank.")
    if not _FOLDER_RE.fullmatch(folder) or ".." in folder.split("/"):
        raise ValueError("folder must be a safe relative preset folder.")
    description = payload.get("description")
    if description is not None:
        description = _text(description, "description", minimum=0, maximum=500).strip()

    raw_extensions = payload["inputExtensions"]
    if not isinstance(raw_extensions, list) or not 1 <= len(raw_extensions) <= 100:
        raise ValueError("inputExtensions must contain between 1 and 100 entries.")
    extensions: list[str] = []
    seen_extensions: set[str] = set()
    for value in raw_extensions:
        extension = _text(value, "inputExtensions entry", maximum=16).lower().lstrip(".")
        if not _EXTENSION_RE.fullmatch(extension):
            raise ValueError(f"Invalid input extension: {value}")
        if extension in seen_extensions:
            raise ValueError(f"Duplicate input extension: {extension}")
        seen_extensions.add(extension)
        extensions.append(extension)

    output_template = _text(payload["outputFileNameTemplate"], "outputFileNameTemplate", maximum=250).strip()
    if (not output_template.startswith("{dir}/") or "\\" in output_template
            or ".." in output_template.split("/")):
        raise ValueError("outputFileNameTemplate must begin with {dir}/ and not traverse parent directories.")
    output_extension = _text(payload["outputExtension"], "outputExtension", maximum=32).lower().lstrip(".")
    if not _OUTPUT_EXTENSION_RE.fullmatch(output_extension) or ".." in output_extension:
        raise ValueError("outputExtension is invalid.")
    engine = _text(payload["engine"], "engine", maximum=64).lower()
    if not _ENGINE_RE.fullmatch(engine):
        raise ValueError("engine must be a safe lowercase engine identifier.")
    invocation_mode = _text(payload["invocationMode"], "invocationMode", maximum=32)
    if invocation_mode not in INVOCATION_MODES:
        raise ValueError("invocationMode is not supported.")

    raw_args = payload["args"]
    if not isinstance(raw_args, list) or len(raw_args) > 128:
        raise ValueError("args must be an array with at most 128 entries.")
    args = [_text(value, "args entry") for value in raw_args]
    return {
        "name": name,
        "folder": folder,
        "description": description,
        "inputExtensions": extensions,
        "outputFileNameTemplate": output_template,
        "outputExtension": output_extension,
        "engine": engine,
        "invocationMode": invocation_mode,
        "args": args,
    }


def render_preset_xml(payload: dict[str, object]) -> bytes:
    ET.register_namespace("", PRESET_NAMESPACE)
    root = ET.Element(f"{{{PRESET_NAMESPACE}}}Preset")

    def add(name: str, value: object) -> None:
        ET.SubElement(root, f"{{{PRESET_NAMESPACE}}}{name}").text = str(value)

    add("Name", payload["name"])
    add("Folder", payload["folder"])
    if payload["description"]:
        add("Description", payload["description"])
    inputs = ET.SubElement(root, f"{{{PRESET_NAMESPACE}}}InputTypes")
    for extension in payload["inputExtensions"]:
        ET.SubElement(inputs, f"{{{PRESET_NAMESPACE}}}Extension").text = str(extension)
    add("OutputFileNameTemplate", payload["outputFileNameTemplate"])
    add("OutputExtension", payload["outputExtension"])
    add("Engine", payload["engine"])
    add("InvocationMode", payload["invocationMode"])
    args_node = ET.SubElement(root, f"{{{PRESET_NAMESPACE}}}Args")
    for argument in payload["args"]:
        ET.SubElement(args_node, f"{{{PRESET_NAMESPACE}}}Arg").text = str(argument)
    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _atomic_write(output: Path, content: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def op_compile(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if source.suffix.lower() != ".pkl" or not source.is_file():
        return fail("invalid_input", "Input must be an existing local .pkl file.")
    if source.stat().st_size > MAX_SOURCE_BYTES:
        return fail("source_too_large", f"Pkl source exceeds {MAX_SOURCE_BYTES} bytes.")
    output = Path(args.output).resolve()
    if not output.name.lower().endswith(".preset.xml"):
        return fail("invalid_output", "Output must end with .preset.xml.")
    if source.resolve() == output:
        return fail("invalid_output", "Input and output paths must differ.")
    if output.exists() and not args.overwrite:
        return fail("output_exists", f"Output already exists: {output}")

    pkl = _find_pkl()
    version = _version(pkl)
    if not pkl or not version:
        return fail("missing_pkl", "Pkl was not found or did not answer --version.")
    if not _supported_version(version):
        return fail("outdated_pkl", f"Pkl 0.32.0 or newer is required; detected: {version}")

    emit("log", level="info", message="Evaluating Pkl with file/environment/network resources, projects, and cache disabled; file modules are confined to the source directory.")
    emit("progress", percent=0, stage="pkl-evaluate", eta_seconds=None)
    command = build_pkl_command(pkl, source.resolve())
    try:
        rc, stdout, stderr, reason = _bounded_evaluate(command, source.resolve().parent)
    except OSError as ex:
        return fail("pkl_start_failed", str(ex))
    if reason:
        return fail(reason, f"Pkl evaluation stopped: {reason.replace('_', ' ')}.")
    if rc != 0:
        detail = stderr.decode("utf-8", errors="replace")[-4000:]
        return fail("pkl_failed", f"Pkl exited with code {rc}: {detail}")
    if len(stdout) > MAX_RENDER_BYTES:
        return fail("output_too_large", f"Rendered JSON exceeds {MAX_RENDER_BYTES} bytes.")
    emit("progress", percent=55, stage="preset-validate", eta_seconds=None)
    try:
        rendered = json.loads(stdout.decode("utf-8"), object_pairs_hook=_no_duplicate_object)
        normalized = validate_payload(rendered)
        xml = render_preset_xml(normalized)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as ex:
        return fail("invalid_preset", str(ex))
    try:
        _atomic_write(output, xml)
    except OSError as ex:
        return fail("output_failed", str(ex))
    emit("progress", percent=100, stage="preset-compile", eta_seconds=0)
    emit("complete", output=str(output), size_bytes=output.stat().st_size, engine=normalized["engine"], invocation_mode=normalized["invocationMode"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pkl-preset-sidecar",
        description="Compile a confined local Pkl description into validated UCX preset XML.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe", help="Report Pkl 0.32+ readiness.")
    compile_parser = sub.add_parser("compile", help="Compile one .pkl module to .preset.xml.")
    compile_parser.add_argument("--input", required=True)
    compile_parser.add_argument("--output", required=True)
    compile_parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "compile":
            return op_compile(args)
        return fail("unknown_op", f"Unknown operation: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

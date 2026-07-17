"""Offline, read-only c2patool bridge for C2PA Content Credentials."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_tool


MINIMUM_VERSION = (0, 27, 0)
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 256 * 1024
MAX_EXTERNAL_MANIFEST_BYTES = 32 * 1024 * 1024
TIMEOUT_SECONDS = 60
MODES = {"manifest": None, "info": "--info", "tree": "--tree", "certs": "--certs"}
OUTPUT_SUFFIXES = {"manifest": ".json", "info": ".txt", "tree": ".txt", "certs": ".pem"}
OFFLINE_SETTINGS = {
    "version": 1,
    "core": {
        "allowed_network_hosts": [],
        "max_decompressed_manifest_size_in_mb": 32,
    },
    "verify": {
        "verify_after_reading": True,
        "verify_trust": True,
        "verify_timestamp_trust": True,
        "ocsp_fetch": False,
        "remote_manifest_fetch": False,
    },
}
_VERSION_RE = re.compile(r"\bc2patool\s+(\d+)\.(\d+)\.(\d+)\b", re.IGNORECASE)


def _here() -> Path:
    return Path(__file__).resolve().parent


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_c2patool() -> str | None:
    return find_tool("c2patool", env_var="C2PATOOL_PATH", anchor=_here())


def _version(tool: str | None) -> str | None:
    if not tool:
        return None
    try:
        result = subprocess.run(
            [tool, "--version"], capture_output=True, text=True, timeout=15,
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
    tool = _find_c2patool()
    version = _version(tool)
    supported = _supported_version(version)
    available = bool(tool and supported)
    emit("backend", available=available, c2patool=tool, version=version,
         version_supported=supported, network_enabled=False, signing_enabled=False)
    emit("complete", output="", size_bytes=0, available=available)
    return 0 if available else 1


def build_command(tool: str, source: Path, settings: Path, mode: str,
                  external_manifest: Path | None) -> list[str]:
    command = [tool, str(source), "--settings", str(settings)]
    option = MODES[mode]
    if option:
        command.append(option)
    if external_manifest:
        command.extend(["--external-manifest", str(external_manifest)])
    return command


def _bounded_run(command: list[str], cwd: Path,
                 environment: dict[str, str]) -> tuple[int, bytes, bytes, str | None]:
    with tempfile.TemporaryDirectory(prefix="ucx-c2pa-output-") as temp:
        stdout_path = Path(temp) / "stdout"
        stderr_path = Path(temp) / "stderr"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command, cwd=str(cwd), env=environment, stdout=stdout, stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + TIMEOUT_SECONDS
            reason = None
            while process.poll() is None:
                if stdout_path.stat().st_size > MAX_REPORT_BYTES:
                    reason = "report_too_large"
                elif stderr_path.stat().st_size > MAX_DIAGNOSTIC_BYTES:
                    reason = "diagnostics_too_large"
                elif time.monotonic() > deadline:
                    reason = "timeout"
                if reason:
                    process.kill()
                    break
                time.sleep(0.05)
            return_code = process.wait()
        report = stdout_path.read_bytes()[:MAX_REPORT_BYTES + 1]
        diagnostics = stderr_path.read_bytes()[-MAX_DIAGNOSTIC_BYTES:]
    return return_code, report, diagnostics, reason


def _atomic_write(output: Path, content: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent,
    )
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


def _isolated_environment(settings: Path, config_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["C2PATOOL_SETTINGS"] = str(settings)
    environment["XDG_CONFIG_HOME"] = str(config_root)
    for name in (
        "C2PATOOL_TRUST_ANCHORS", "C2PATOOL_ALLOWED_LIST", "C2PATOOL_TRUST_CONFIG",
    ):
        environment.pop(name, None)
    return environment


def op_inspect(args: argparse.Namespace) -> int:
    source = Path(args.input).resolve()
    if not source.is_file():
        return fail("invalid_input", "Input must be an existing local asset file.")
    output = Path(args.output).resolve()
    if output.suffix.lower() != OUTPUT_SUFFIXES[args.mode]:
        return fail("invalid_output", f"{args.mode} output must end with {OUTPUT_SUFFIXES[args.mode]}.")
    if output == source:
        return fail("invalid_output", "Input and output paths must differ.")
    if output.exists() and not args.overwrite:
        return fail("output_exists", f"Output already exists: {output}")

    external = Path(args.external_manifest).resolve() if args.external_manifest else None
    if external and (
        external.suffix.lower() != ".c2pa" or not external.is_file()
        or external.stat().st_size > MAX_EXTERNAL_MANIFEST_BYTES
    ):
        return fail(
            "invalid_external_manifest",
            "External manifest must be an existing local .c2pa file no larger than 32 MiB.",
        )

    tool = _find_c2patool()
    version = _version(tool)
    if not tool or not version:
        return fail("missing_c2patool", "c2patool was not found or did not answer --version.")
    if not _supported_version(version):
        return fail("outdated_c2patool", f"c2patool 0.27.0 or newer is required; detected: {version}")

    with tempfile.TemporaryDirectory(prefix="ucx-c2pa-config-") as temp:
        config_root = Path(temp)
        settings = config_root / "offline-settings.json"
        settings.write_text(json.dumps(OFFLINE_SETTINGS), encoding="utf-8")
        command = build_command(tool, source, settings, args.mode, external)
        emit(
            "log", level="info",
            message="Inspecting Content Credentials offline; remote manifests, OCSP, trust-list downloads, and signing are disabled.",
        )
        emit("progress", percent=0, stage=f"c2pa-{args.mode}", eta_seconds=None)
        try:
            return_code, report, diagnostics, reason = _bounded_run(
                command, source.parent, _isolated_environment(settings, config_root),
            )
        except OSError as ex:
            return fail("c2patool_start_failed", str(ex))

    if reason:
        return fail(reason, f"c2patool stopped: {reason.replace('_', ' ')}.")
    if return_code != 0:
        detail = diagnostics.decode("utf-8", errors="replace")[-4000:]
        return fail("c2patool_failed", f"c2patool exited with code {return_code}: {detail}")
    if not report or len(report) > MAX_REPORT_BYTES:
        return fail("invalid_report", "c2patool returned an empty or oversized report.")
    if args.mode == "manifest":
        try:
            payload = json.loads(report.decode("utf-8"))
            report = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            return fail("invalid_report", f"c2patool returned invalid JSON: {ex}")
    try:
        _atomic_write(output, report)
    except OSError as ex:
        return fail("output_failed", str(ex))
    emit("progress", percent=100, stage=f"c2pa-{args.mode}", eta_seconds=0)
    emit(
        "complete", output=str(output), size_bytes=output.stat().st_size,
        mode=args.mode, external_manifest=bool(external), network_enabled=False,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="c2pa-sidecar", description="Offline read-only C2PA Content Credentials inspection.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe", help="Report c2patool 0.27+ readiness.")
    inspect = sub.add_parser("inspect", help="Write a bounded local C2PA report.")
    inspect.add_argument("--input", required=True)
    inspect.add_argument("--output", required=True)
    inspect.add_argument("--mode", choices=sorted(MODES), default="manifest")
    inspect.add_argument("--external-manifest")
    inspect.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return op_probe(args) if args.op == "probe" else op_inspect(args)
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

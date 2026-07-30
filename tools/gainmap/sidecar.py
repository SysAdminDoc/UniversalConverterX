"""ISO 21496-1 gain-map preservation and AVIF writing sidecar.

The opt-in runtime pins an official libvips 8.18.3 Windows build for UltraHDR
JPEG and a reproducible static libavif 1.4.2 avifgainmaputil build. Runtime
downloads require explicit license acknowledgement and are hash verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit


_HERE = Path(__file__).resolve().parent
_MANIFEST_PATH = _HERE / "runtime.bundle.json"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_GAINMAP_KEYS = (
    "gainmap-max-content-boost", "gainmap-min-content-boost",
    "gainmap-gamma", "gainmap-offset-sdr", "gainmap-offset-hdr",
    "gainmap-hdr-capacity-min", "gainmap-hdr-capacity-max",
    "gainmap-use-base-cg", "gainmap-scale-factor",
)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _runtime_root() -> Path:
    configured = os.environ.get("UCX_GAINMAP_RUNTIME")
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "UniversalConverterX" / "tools" / "gainmap-runtime"


def _manifest(path: Path = _MANIFEST_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1 or len(payload.get("artifacts", [])) != 2:
        raise ValueError("Unsupported gain-map runtime manifest.")
    return payload


def _find_binary(env_var: str, name: str, relative: str) -> str | None:
    root = _runtime_root()
    candidates = (
        os.environ.get(env_var),
        shutil.which(name), shutil.which(f"{name}.exe"),
        str(root / relative), str(_HERE / f"{name}.exe"),
        str(_HERE.parent / "_bin" / f"{name}.exe"),
    )
    return next((str(Path(item)) for item in candidates if item and Path(item).is_file()), None)


def _find_vips() -> str | None:
    return _find_binary("UCX_VIPS_PATH", "vips", "vips/bin/vips.exe")


def _find_avif() -> str | None:
    return _find_binary(
        "UCX_AVIFGAINMAPUTIL_PATH", "avifgainmaputil",
        "avif/avifgainmaputil.exe")


def _run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, creationflags=_CREATE_NO_WINDOW,
    )


def _diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stderr + "\n" + result.stdout).splitlines()
    return "\n".join(lines[-20:]).strip() or f"process exited {result.returncode}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(artifact: dict, destination: Path, start: float, end: float) -> None:
    request = urllib.request.Request(
        artifact["url"], headers={"User-Agent": "UniversalConverterX-GainMap/1"})
    received = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
            digest.update(block)
            received += len(block)
            fraction = min(1.0, received / artifact["bytes"])
            emit("progress", percent=start + (end - start) * fraction,
                 stage=f"downloading {artifact['id']}", eta_seconds=None)
    if received != artifact["bytes"]:
        raise ValueError(
            f"{artifact['id']} size mismatch: expected {artifact['bytes']}, got {received}.")
    if digest.hexdigest() != artifact["sha256"]:
        raise ValueError(f"{artifact['id']} SHA-256 mismatch.")


def _zip_entry_is_link(entry: zipfile.ZipInfo) -> bool:
    mode = (entry.external_attr >> 16) & 0o170000
    return mode in (0o120000, 0o060000)


def _safe_target(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"Unsafe archive path: {relative}")
    target = (root / normalized).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise ValueError(f"Archive path escapes destination: {relative}")
    return target


def _extract_artifact(archive: Path, artifact: dict, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        files = [entry for entry in bundle.infolist() if not entry.is_dir()]
        if artifact["id"] == "libvips":
            prefix = artifact["archivePrefix"]
            selected: list[tuple[zipfile.ZipInfo, str]] = []
            for entry in files:
                if entry.filename == prefix + "LICENSE":
                    selected.append((entry, "LICENSE"))
                elif entry.filename.startswith(prefix + "bin/"):
                    selected.append((entry, entry.filename[len(prefix):]))
            required = {"bin/vips.exe", "bin/vipsheader.exe", "bin/libuhdr.dll", "LICENSE"}
        else:
            selected = [(entry, entry.filename) for entry in files]
            required = {"avifgainmaputil.exe", "licenses/libavif-LICENSE.txt"}
        names = {relative.replace("\\", "/") for _, relative in selected}
        if not required.issubset(names):
            raise ValueError(f"{artifact['id']} archive is missing required runtime files.")
        for entry, relative in selected:
            if _zip_entry_is_link(entry):
                raise ValueError(f"Archive link entries are not allowed: {entry.filename}")
            target = _safe_target(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _install_runtime(manifest: dict, archives: dict[str, Path], destination: Path) -> None:
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    promoted = False
    try:
        for artifact in manifest["artifacts"]:
            folder = "vips" if artifact["id"] == "libvips" else "avif"
            _extract_artifact(archives[artifact["id"]], artifact, staging / folder)
        pack = {
            "runtimeVersion": manifest["runtimeVersion"],
            "artifacts": [
                {key: artifact[key] for key in
                 ("id", "version", "license", "url", "bytes", "sha256")}
                for artifact in manifest["artifacts"]
            ],
        }
        (staging / "pack.json").write_text(
            json.dumps(pack, indent=2) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            os.replace(destination, backup)
        os.replace(staging, destination)
        promoted = True
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if promoted and destination.exists():
            shutil.rmtree(destination)
        if backup.exists():
            os.replace(backup, destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _probe_runtime() -> tuple[bool, dict]:
    vips, avif = _find_vips(), _find_avif()
    status: dict = {"vips": vips, "avifgainmaputil": avif}
    if not vips or not avif:
        return False, status
    version = _run([vips, "--version"], 30)
    uhdrload = _run([vips, "uhdrload"], 30)
    uhdrsave = _run([vips, "uhdrsave"], 30)
    avif_version = _run([avif, "help"], 30)
    status.update({
        "vipsVersion": version.stdout.strip(),
        "uhdrload": uhdrload.returncode == 0 and "load a uhdr image" in uhdrload.stdout.lower(),
        "uhdrsave": uhdrsave.returncode == 0 and "UltraHDR format" in uhdrsave.stdout,
        "avifVersion": next((line.strip() for line in avif_version.stdout.splitlines()
                             if line.startswith("Version:")), ""),
    })
    ready = (
        version.returncode == 0 and re.search(r"8\.(?:1[89]|[2-9]\d)\.", version.stdout) is not None
        and status["uhdrload"] and status["uhdrsave"]
        and avif_version.returncode == 0 and "Version: 1.4.2" in avif_version.stdout
    )
    return ready, status


def _parse_vips_metadata(text: str) -> dict:
    values: dict[str, object] = {}
    first = text.splitlines()[0] if text.splitlines() else ""
    dimension = re.search(r":\s+(\d+)x(\d+)\s", first)
    if dimension:
        values["width"], values["height"] = map(int, dimension.groups())
    for line in text.splitlines()[1:]:
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        if key == "gainmap-data":
            match = re.match(r"(\d+) bytes", value)
            values["gainmapBytes"] = int(match.group(1)) if match else value
        elif key == "vips-loader" or key in _GAINMAP_KEYS:
            values[key] = value.strip()
    values["gainMap"] = values.get("vips-loader") == "uhdrload" and bool(values.get("gainmapBytes"))
    return values


def _parse_avif_metadata(text: str) -> dict:
    def value(label: str) -> float | None:
        match = re.search(rf"\* {re.escape(label)}:\s+(-?[0-9.]+)", text)
        return float(match.group(1)) if match else None
    return {
        "gainMap": "* Gain Map Min:" in text and "* Gain Map Max:" in text,
        "baseHeadroom": value("Base headroom"),
        "alternateHeadroom": value("Alternate headroom"),
        "useBaseColorSpace": "* Use Base Color Space: True" in text,
    }


def _inspect_jpeg(vips: str, source: Path) -> dict:
    header = str(Path(vips).with_name("vipsheader.exe"))
    if not Path(header).is_file():
        header = "vipsheader"
    result = _run([header, "-a", str(source)], 60)
    if result.returncode != 0:
        raise RuntimeError(_diagnostic(result))
    metadata = _parse_vips_metadata(result.stdout)
    if not metadata["gainMap"]:
        raise ValueError("Input is not an ISO 21496-1 UltraHDR JPEG with a gain map.")
    return metadata


def _inspect_avif(avif: str, source: Path) -> dict:
    result = _run([avif, "printmetadata", str(source)], 60)
    if result.returncode != 0:
        raise RuntimeError(_diagnostic(result))
    metadata = _parse_avif_metadata(result.stdout)
    if not metadata["gainMap"]:
        raise ValueError("Input AVIF does not contain a gain map.")
    return metadata


def _paths(source: str, output: str, source_exts: set[str], output_ext: str) -> tuple[Path, Path]:
    src, dst = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if not src.is_file():
        raise ValueError(f"Input file not found: {src}")
    if src.suffix.lower() not in source_exts:
        raise ValueError(f"Input must be one of: {', '.join(sorted(source_exts))}")
    if dst.suffix.lower() != output_ext:
        raise ValueError(f"Output must use the {output_ext} extension.")
    if src == dst:
        raise ValueError("Input and output paths must be different.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    return src, dst


def _temp_output(output: Path) -> Path:
    return output.parent / f".{output.stem}.{uuid.uuid4().hex}.tmp{output.suffix}"


def _promote(temp: Path, output: Path) -> None:
    if not temp.is_file() or temp.stat().st_size == 0:
        raise RuntimeError("Encoder did not create a non-empty output.")
    os.replace(temp, output)


def cmd_download(args: argparse.Namespace) -> int:
    if not args.accept_licenses:
        return fail("license_consent_required",
                    "Re-run with --accept-licenses after reviewing runtime.bundle.json.")
    manifest = _manifest()
    destination = _runtime_root()
    with tempfile.TemporaryDirectory(prefix="ucx-gainmap-download-") as temp:
        root = Path(temp)
        archives: dict[str, Path] = {}
        artifacts = manifest["artifacts"]
        for index, artifact in enumerate(artifacts):
            archive = root / f"{artifact['id']}.zip"
            start = 95.0 * index / len(artifacts)
            end = 95.0 * (index + 1) / len(artifacts)
            _download(artifact, archive, start, end)
            archives[artifact["id"]] = archive
        _install_runtime(manifest, archives, destination)
    emit("complete", output=str(destination), runtimeVersion=manifest["runtimeVersion"])
    return 0


def cmd_probe(_args: argparse.Namespace) -> int:
    ready, status = _probe_runtime()
    if not ready:
        emit("error", code="gainmap_runtime_missing",
             message="Install the pinned runtime with download-runtime --accept-licenses.",
             status=status)
        return 1
    emit("complete", ready=True, status=status)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    ready, _ = _probe_runtime()
    if not ready:
        return fail("gainmap_runtime_missing", "Pinned gain-map runtime is unavailable or outdated.")
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        return fail("input_missing", f"Input file not found: {source}")
    try:
        metadata = (_inspect_avif(_find_avif() or "", source) if source.suffix.lower() == ".avif"
                    else _inspect_jpeg(_find_vips() or "", source))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return fail("gainmap_inspect_failed", str(exc))
    emit("complete", output=str(source), metadata=metadata)
    return 0


def cmd_preserve(args: argparse.Namespace) -> int:
    vips = _find_vips()
    ready, _ = _probe_runtime()
    if not ready or not vips:
        return fail("gainmap_runtime_missing", "Pinned gain-map runtime is unavailable or outdated.")
    temp_output: Path | None = None
    try:
        source, output = _paths(args.input, args.output, {".jpg", ".jpeg"}, ".jpg")
        before = _inspect_jpeg(vips, source)
        temp_output = _temp_output(output)
        with tempfile.TemporaryDirectory(prefix="ucx-ultrahdr-") as temp:
            image = Path(temp) / "decoded.v"
            load = _run([vips, "uhdrload", str(source), str(image)], 300)
            if load.returncode != 0:
                raise RuntimeError(_diagnostic(load))
            emit("progress", percent=50.0, stage="decoded UltraHDR gain map", eta_seconds=None)
            save = _run([vips, "uhdrsave", str(image), str(temp_output),
                         "--Q", str(args.quality), "--keep", "all"], 300)
            if save.returncode != 0:
                raise RuntimeError(_diagnostic(save))
        after = _inspect_jpeg(vips, temp_output)
        for key in _GAINMAP_KEYS:
            if before.get(key) != after.get(key):
                raise RuntimeError(f"Gain-map metadata changed during round-trip: {key}")
        _promote(temp_output, output)
        emit("complete", output=str(output), bytes=output.stat().st_size, metadata=after)
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        if temp_output and temp_output.exists():
            temp_output.unlink()
        return fail("ultrahdr_preserve_failed", str(exc))


def _avif_encode_args(args: argparse.Namespace) -> list[str]:
    command = ["--qcolor", str(args.quality), "--qgain-map", str(args.gainmap_quality),
               "--speed", str(args.speed)]
    if args.depth:
        command.extend(["--depth", str(args.depth)])
    return command


def cmd_convert(args: argparse.Namespace) -> int:
    avif, vips = _find_avif(), _find_vips()
    ready, _ = _probe_runtime()
    if not ready or not avif or not vips:
        return fail("gainmap_runtime_missing", "Pinned gain-map runtime is unavailable or outdated.")
    temp_output: Path | None = None
    try:
        source, output = _paths(args.input, args.output, {".jpg", ".jpeg"}, ".avif")
        _inspect_jpeg(vips, source)
        temp_output = _temp_output(output)
        result = _run([avif, "convert", str(source), str(temp_output), *_avif_encode_args(args)], 600)
        if result.returncode != 0:
            raise RuntimeError(_diagnostic(result))
        metadata = _inspect_avif(avif, temp_output)
        _promote(temp_output, output)
        emit("complete", output=str(output), bytes=output.stat().st_size, metadata=metadata)
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        if temp_output and temp_output.exists():
            temp_output.unlink()
        return fail("gainmap_avif_failed", str(exc))


def cmd_create(args: argparse.Namespace) -> int:
    avif = _find_avif()
    ready, _ = _probe_runtime()
    if not ready or not avif:
        return fail("gainmap_runtime_missing", "Pinned gain-map runtime is unavailable or outdated.")
    temp_output: Path | None = None
    try:
        base, output = _paths(args.base, args.output,
                              {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".avif"}, ".avif")
        alternate = Path(args.alternate).expanduser().resolve()
        if not alternate.is_file() or alternate == base or alternate == output:
            raise ValueError("Alternate image must be a distinct existing file.")
        temp_output = _temp_output(output)
        command = [avif, "combine", str(base), str(alternate), str(temp_output),
                   *_avif_encode_args(args), "--downscaling", str(args.downscaling),
                   "--depth-gain-map", str(args.gainmap_depth),
                   "--max-headroom", str(args.max_headroom),
                   "--cicp-base", args.cicp_base,
                   "--cicp-alternate", args.cicp_alternate]
        result = _run(command, 600)
        if result.returncode != 0:
            raise RuntimeError(_diagnostic(result))
        metadata = _inspect_avif(avif, temp_output)
        _promote(temp_output, output)
        emit("complete", output=str(output), bytes=output.stat().st_size, metadata=metadata)
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        if temp_output and temp_output.exists():
            temp_output.unlink()
        return fail("gainmap_create_failed", str(exc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ISO 21496-1 / UltraHDR gain-map tools")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download-runtime")
    download.add_argument("--accept-licenses", action="store_true")
    download.set_defaults(func=cmd_download)
    sub.add_parser("probe").set_defaults(func=cmd_probe)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--input", required=True)
    inspect.set_defaults(func=cmd_inspect)
    preserve = sub.add_parser("preserve-jpeg")
    preserve.add_argument("--input", required=True)
    preserve.add_argument("--output", required=True)
    preserve.add_argument("--quality", type=int, choices=range(1, 101), default=90)
    preserve.set_defaults(func=cmd_preserve)
    convert = sub.add_parser("to-avif")
    convert.add_argument("--input", required=True)
    convert.add_argument("--output", required=True)
    create = sub.add_parser("create-avif")
    create.add_argument("--base", required=True)
    create.add_argument("--alternate", required=True)
    create.add_argument("--output", required=True)
    create.add_argument("--downscaling", type=int, choices=range(1, 17), default=2)
    create.add_argument("--gainmap-depth", type=int, choices=(8, 10, 12), default=8)
    create.add_argument("--max-headroom", type=float, default=4.0)
    create.add_argument("--cicp-base", default="1/13/6")
    create.add_argument("--cicp-alternate", default="9/16/9")
    for command in (convert, create):
        command.add_argument("--quality", type=int, choices=range(0, 101), default=90)
        command.add_argument("--gainmap-quality", type=int, choices=range(0, 101), default=100)
        command.add_argument("--speed", type=int, choices=range(0, 11), default=8)
        command.add_argument("--depth", type=int, choices=(0, 8, 10, 12), default=0,
                             help="AVIF base image bit depth (0 = automatic)")
    convert.set_defaults(func=cmd_convert)
    create.set_defaults(func=cmd_create)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except (ValueError, OSError, json.JSONDecodeError, zipfile.BadZipFile,
            urllib.error.URLError, subprocess.SubprocessError) as exc:
        return fail("gainmap_error", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())

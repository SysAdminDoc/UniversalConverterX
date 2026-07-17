"""IAMF creation, packaging, and channel-rendering through bundled FFmpeg."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, probe_media, run_ffmpeg


PROFILES = {"stereo", "scalable-5.1"}
RENDER_LAYOUTS = {"stereo", "5.1"}
STEREO_AUDIO_GROUP = "type=iamf_audio_element:id=1:st=0,layer=ch_layout=stereo"
STEREO_MIX_GROUP = (
    "type=iamf_mix_presentation:id=2:stg=0:annotations=en-us=Stereo_Mix,"
    "submix=parameter_id=100:parameter_rate=48000|element=stg=0:parameter_id=100:"
    "annotations=en-us=Stereo_Element|layout=sound_system=stereo"
)
SURROUND_AUDIO_GROUP = (
    "type=iamf_audio_element:id=1:st=0:st=1:st=2:st=3,"
    "demixing=parameter_id=998,recon_gain=parameter_id=101,"
    "layer=ch_layout=stereo,layer=ch_layout=5.1(side)"
)
SURROUND_MIX_GROUP = (
    "type=iamf_mix_presentation:id=2:stg=0:annotations=en-us=Scalable_5_1_Mix,"
    "submix=parameter_id=100:parameter_rate=48000|element=stg=0:parameter_id=100:"
    "annotations=en-us=Scalable_5_1_Element|layout=sound_system=stereo|"
    "layout=sound_system=5.1(side)"
)
SURROUND_SPLIT = (
    "[0:a:0]aresample=48000,aformat=channel_layouts=5.1(side),"
    "channelsplit=channel_layout=5.1(side)[FL][FR][FC][LFE][SL][SR];"
    "[FL][FR]join=inputs=2:channel_layout=stereo[front];"
    "[SL][SR]join=inputs=2:channel_layout=stereo[back];"
    "[FC]aformat=channel_layouts=mono[center];"
    "[LFE]aformat=channel_layouts=mono[lfe]"
)
SURROUND_JOIN = (
    "[0:a:0]channelsplit=channel_layout=stereo[FL][FR];"
    "[0:a:1]channelsplit=channel_layout=stereo[SL][SR];"
    "[0:a:2]aformat=channel_layouts=mono[FC];"
    "[0:a:3]aformat=channel_layouts=mono[LFE];"
    "[FL][FR][FC][LFE][SL][SR]join=inputs=6:channel_layout=5.1(side):"
    "map=0.0-FL|1.0-FR|2.0-FC|3.0-LFE|4.0-SL|5.0-SR[out]"
)


def _here() -> Path:
    return Path(__file__).resolve().parent


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _iamf_probe(ffprobe: str, source: Path) -> dict[str, object] | None:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-show_stream_groups", "-show_format", "-of", "json", str(source)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else None
        return payload if isinstance(payload, dict) else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _duration(payload: dict[str, object] | None) -> float:
    try:
        return float(((payload or {}).get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _iamf_profile(payload: dict[str, object]) -> str | None:
    streams = payload.get("streams")
    groups = payload.get("stream_groups")
    if not isinstance(streams, list) or not isinstance(groups, list) or len(groups) != 2:
        return None
    group_types = {str(group.get("type")) for group in groups if isinstance(group, dict)}
    if group_types != {"IAMF Audio Element", "IAMF Mix Presentation"}:
        return None
    if len(streams) == 1 and streams[0].get("channel_layout") == "stereo":
        return "stereo"
    if len(streams) == 4:
        channels = [int(stream.get("channels") or 0) for stream in streams]
        if channels == [2, 2, 1, 1]:
            return "scalable-5.1"
    return None


def _output_paths(args: argparse.Namespace, suffix: str) -> tuple[Path, Path] | None:
    output = Path(args.output).resolve()
    if output.suffix.lower() != suffix:
        fail("invalid_output", f"Output must end with {suffix}.")
        return None
    if output.exists() and not args.overwrite:
        fail("output_exists", f"Output already exists: {output}")
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(f".{output.stem}.ucx-iamf{suffix}")
    staged.unlink(missing_ok=True)
    return output, staged


def _promote(staged: Path, output: Path) -> bool:
    if not staged.is_file() or staged.stat().st_size == 0:
        return False
    os.replace(staged, output)
    return True


def op_probe(_: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg(_here())
    ffprobe = find_ffprobe(_here())
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe was not found.")
    formats = subprocess.run(
        [ffmpeg, "-hide_banner", "-formats"], capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    encoders = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    text = (formats.stdout or "") + (formats.stderr or "")
    encoder_text = (encoders.stdout or "") + (encoders.stderr or "")
    iamf = "iamf" in text.lower()
    libopus = "libopus" in encoder_text.lower()
    available = iamf and libopus
    emit("backend", available=available, ffmpeg=ffmpeg, ffprobe=ffprobe, iamf=iamf, libopus=libopus)
    emit("complete", output="", size_bytes=0, available=available)
    return 0 if available else 1


def build_encode_command(ffmpeg: str, source: Path, staged: Path,
                         profile: str) -> list[str]:
    base = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source)]
    if profile == "stereo":
        return [
            *base, "-map", "0:a:0", "-ar", "48000", "-ac", "2",
            "-c:a", "libopus", "-b:a", "192k",
            "-stream_group", STEREO_AUDIO_GROUP,
            "-stream_group", STEREO_MIX_GROUP,
            "-streamid", "0:0", str(staged),
        ]
    return [
        *base, "-filter_complex", SURROUND_SPLIT,
        "-map", "[front]", "-map", "[back]", "-map", "[center]", "-map", "[lfe]",
        "-ar", "48000", "-c:a", "libopus",
        "-b:a:0", "160k", "-b:a:1", "128k", "-b:a:2", "64k", "-b:a:3", "32k",
        "-stream_group", SURROUND_AUDIO_GROUP,
        "-stream_group", SURROUND_MIX_GROUP,
        "-streamid", "0:0", "-streamid", "1:1", "-streamid", "2:2", "-streamid", "3:3",
        str(staged),
    ]


def op_encode(args: argparse.Namespace) -> int:
    ffmpeg, ffprobe = find_ffmpeg(_here()), find_ffprobe(_here())
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe was not found.")
    source = Path(args.input).resolve()
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")
    paths = _output_paths(args, ".iamf")
    if not paths:
        return 1
    output, staged = paths
    payload = probe_media(ffprobe, source)
    audio = next((stream for stream in (payload or {}).get("streams", []) if stream.get("codec_type") == "audio"), None)
    channels = int((audio or {}).get("channels") or 0)
    profile = args.profile
    if profile == "auto":
        profile = "stereo" if channels == 2 else "scalable-5.1" if channels == 6 else ""
    if profile == "stereo" and channels < 1:
        return fail("invalid_channels", "Stereo IAMF creation requires an audio stream.")
    if profile == "scalable-5.1" and channels != 6:
        return fail("invalid_channels", "Scalable 5.1 IAMF creation requires a six-channel input.")
    if profile not in PROFILES:
        return fail("invalid_channels", "Auto profile supports only stereo or six-channel inputs.")
    command = build_encode_command(ffmpeg, source, staged, profile)
    emit("log", level="info", message=f"Creating {profile} IAMF master at 48 kHz with Opus.")
    rc = run_ffmpeg(command, _duration(payload), "iamf-encode")
    if rc != 0 or not _promote(staged, output):
        staged.unlink(missing_ok=True)
        return fail("ffmpeg_failed", f"FFmpeg IAMF encode failed with code {rc}.")
    verified = _iamf_probe(ffprobe, output)
    if not verified or _iamf_profile(verified) != profile:
        output.unlink(missing_ok=True)
        return fail("verification_failed", "IAMF stream groups or layers did not match the requested profile.")
    emit("complete", output=str(output), size_bytes=output.stat().st_size, profile=profile, sample_rate=48000)
    return 0


def build_package_command(ffmpeg: str, source: Path, staged: Path,
                          stream_count: int) -> list[str]:
    streams = ":".join(f"st={index}" for index in range(stream_count))
    stream_ids = [value for index in range(stream_count) for value in ("-streamid", f"{index}:{index}")]
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source),
        "-map", "0:a", "-c:a", "copy",
        "-stream_group", f"map=0=0:{streams}", "-stream_group", "map=0=1:stg=0",
        *stream_ids, str(staged),
    ]


def op_package(args: argparse.Namespace) -> int:
    ffmpeg, ffprobe = find_ffmpeg(_here()), find_ffprobe(_here())
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe was not found.")
    source = Path(args.input).resolve()
    if source.suffix.lower() != ".iamf" or not source.is_file():
        return fail("invalid_input", "Packaging input must be an existing .iamf file.")
    payload = _iamf_probe(ffprobe, source)
    profile = _iamf_profile(payload or {})
    if not profile:
        return fail("invalid_iamf", "Input is not a supported stereo or scalable 5.1 IAMF master.")
    paths = _output_paths(args, ".mp4")
    if not paths:
        return 1
    output, staged = paths
    stream_count = len(payload["streams"])
    rc = run_ffmpeg(build_package_command(ffmpeg, source, staged, stream_count), _duration(payload), "iamf-package")
    if rc != 0 or not _promote(staged, output):
        staged.unlink(missing_ok=True)
        return fail("ffmpeg_failed", f"FFmpeg IAMF packaging failed with code {rc}.")
    verified = _iamf_probe(ffprobe, output)
    if not verified or _iamf_profile(verified) != profile:
        output.unlink(missing_ok=True)
        return fail("verification_failed", "MP4 did not preserve the IAMF stream groups.")
    emit("complete", output=str(output), size_bytes=output.stat().st_size, profile=profile, stream_copy=True)
    return 0


def build_render_command(ffmpeg: str, source: Path, staged: Path,
                         profile: str, layout: str) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source)]
    if profile == "scalable-5.1" and layout == "5.1":
        command.extend(["-filter_complex", SURROUND_JOIN, "-map", "[out]"])
    else:
        command.extend(["-map", "0:a:0", "-ac", "2"])
    command.extend(["-ar", "48000"])
    command.extend(["-c:a", "flac"] if staged.suffix.lower() == ".flac" else ["-c:a", "pcm_s24le"])
    command.append(str(staged))
    return command


def op_render(args: argparse.Namespace) -> int:
    ffmpeg, ffprobe = find_ffmpeg(_here()), find_ffprobe(_here())
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe was not found.")
    source = Path(args.input).resolve()
    if source.suffix.lower() not in {".iamf", ".mp4"} or not source.is_file():
        return fail("invalid_input", "Render input must be an existing IAMF or IAMF-in-MP4 file.")
    payload = _iamf_probe(ffprobe, source)
    profile = _iamf_profile(payload or {})
    if not profile:
        return fail("invalid_iamf", "Input is not a supported stereo or scalable 5.1 IAMF master.")
    if args.layout == "5.1" and profile != "scalable-5.1":
        return fail("invalid_layout", "5.1 rendering requires a scalable 5.1 IAMF input.")
    suffix = Path(args.output).suffix.lower()
    if suffix not in {".wav", ".flac"}:
        return fail("invalid_output", "Rendered output must end with .wav or .flac.")
    paths = _output_paths(args, suffix)
    if not paths:
        return 1
    output, staged = paths
    rc = run_ffmpeg(build_render_command(ffmpeg, source, staged, profile, args.layout), _duration(payload), "iamf-render")
    if rc != 0 or not _promote(staged, output):
        staged.unlink(missing_ok=True)
        return fail("ffmpeg_failed", f"FFmpeg IAMF render failed with code {rc}.")
    rendered = probe_media(ffprobe, output)
    audio = next((stream for stream in (rendered or {}).get("streams", []) if stream.get("codec_type") == "audio"), None)
    expected = 2 if args.layout == "stereo" else 6
    if int((audio or {}).get("channels") or 0) != expected:
        output.unlink(missing_ok=True)
        return fail("verification_failed", "Rendered channel count did not match the requested layout.")
    emit("complete", output=str(output), size_bytes=output.stat().st_size, source_profile=profile, layout=args.layout)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iamf-sidecar", description="Create, package, and render IAMF immersive audio.")
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe")
    encode = sub.add_parser("encode")
    encode.add_argument("--input", required=True); encode.add_argument("--output", required=True)
    encode.add_argument("--profile", choices=["auto", *sorted(PROFILES)], default="auto"); encode.add_argument("--overwrite", action="store_true")
    package = sub.add_parser("package")
    package.add_argument("--input", required=True); package.add_argument("--output", required=True); package.add_argument("--overwrite", action="store_true")
    render = sub.add_parser("render")
    render.add_argument("--input", required=True); render.add_argument("--output", required=True)
    render.add_argument("--layout", choices=sorted(RENDER_LAYOUTS), required=True); render.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"probe": op_probe, "encode": op_encode, "package": op_package, "render": op_render}[args.op](args)
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

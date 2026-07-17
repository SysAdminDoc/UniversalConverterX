"""Safe offline conditional media-to-preset planner."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffprobe, probe_media


MAX_RULE_BYTES = 1024 * 1024
MAX_RULES = 1000
NUMERIC_CONDITIONS = {
    "size_mb_gte": ("size_mb", lambda actual, expected: actual >= expected),
    "size_mb_lte": ("size_mb", lambda actual, expected: actual <= expected),
    "duration_gte": ("duration", lambda actual, expected: actual >= expected),
    "duration_lte": ("duration", lambda actual, expected: actual <= expected),
    "width_gte": ("width", lambda actual, expected: actual >= expected),
    "width_lte": ("width", lambda actual, expected: actual <= expected),
    "height_gte": ("height", lambda actual, expected: actual >= expected),
    "height_lte": ("height", lambda actual, expected: actual <= expected),
    "channels_gte": ("channels", lambda actual, expected: actual >= expected),
    "channels_lte": ("channels", lambda actual, expected: actual <= expected),
}
LIST_CONDITIONS = {
    "extension_in": "extension",
    "extension_not_in": "extension",
    "video_codec_in": "video_codec",
    "audio_codec_in": "audio_codec",
}
BOOLEAN_CONDITIONS = {"hdr", "has_subtitles"}
ALLOWED_ACTIONS = {"preset", "skip", "output_suffix", "tags", "note"}
PRESET_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def load_rules(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"Rules file not found: {path}")
    if path.stat().st_size > MAX_RULE_BYTES:
        raise ValueError(f"Rules file exceeds {MAX_RULE_BYTES} bytes.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as ex:
        raise ValueError(f"Invalid rules JSON: {ex}") from ex
    validate_rules(payload)
    return payload


def validate_action(action: object, location: str) -> None:
    if not isinstance(action, dict):
        raise ValueError(f"{location} must be an object.")
    unknown = set(action) - ALLOWED_ACTIONS
    if unknown:
        raise ValueError(f"{location} contains unsupported action fields: {sorted(unknown)}")
    if "preset" not in action and not action.get("skip"):
        raise ValueError(f"{location} must select a preset or set skip=true.")
    if "preset" in action and (
        not isinstance(action["preset"], str) or PRESET_RE.fullmatch(action["preset"]) is None
    ):
        raise ValueError(f"{location}.preset must be a safe preset identifier.")
    if "skip" in action and not isinstance(action["skip"], bool):
        raise ValueError(f"{location}.skip must be boolean.")
    suffix = action.get("output_suffix")
    if suffix is not None and (
        not isinstance(suffix, str) or len(suffix) > 64 or any(char in suffix for char in "/\\:")
    ):
        raise ValueError(f"{location}.output_suffix must be a safe filename suffix.")
    tags = action.get("tags")
    if tags is not None and (
        not isinstance(tags, list)
        or len(tags) > 32
        or any(not isinstance(tag, str) or len(tag) > 64 for tag in tags)
    ):
        raise ValueError(f"{location}.tags must be a short string list.")
    note = action.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > 500):
        raise ValueError(f"{location}.note must be a string up to 500 characters.")


def validate_when(when: object, location: str) -> None:
    if not isinstance(when, dict) or not when:
        raise ValueError(f"{location} must be a non-empty object.")
    supported = set(NUMERIC_CONDITIONS) | set(LIST_CONDITIONS) | BOOLEAN_CONDITIONS
    unknown = set(when) - supported
    if unknown:
        raise ValueError(f"{location} contains unsupported conditions: {sorted(unknown)}")
    for key in set(when) & set(NUMERIC_CONDITIONS):
        if isinstance(when[key], bool) or not isinstance(when[key], (int, float)):
            raise ValueError(f"{location}.{key} must be numeric.")
    for key in set(when) & set(LIST_CONDITIONS):
        values = when[key]
        if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
            raise ValueError(f"{location}.{key} must be a non-empty string list.")
    for key in set(when) & BOOLEAN_CONDITIONS:
        if not isinstance(when[key], bool):
            raise ValueError(f"{location}.{key} must be boolean.")


def validate_rules(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Rules document must be an object.")
    if payload.get("version") != 1:
        raise ValueError("Rules document version must be 1.")
    unknown_root = set(payload) - {"version", "rules", "default"}
    if unknown_root:
        raise ValueError(f"Rules document contains unsupported fields: {sorted(unknown_root)}")
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Rules document must contain a non-empty rules array.")
    if len(rules) > MAX_RULES:
        raise ValueError(f"Rules document exceeds {MAX_RULES} rules.")
    names: set[str] = set()
    for index, rule in enumerate(rules):
        location = f"rules[{index}]"
        if not isinstance(rule, dict):
            raise ValueError(f"{location} must be an object.")
        unknown = set(rule) - {"name", "when", "action", "continue"}
        if unknown:
            raise ValueError(f"{location} contains unsupported fields: {sorted(unknown)}")
        name = rule.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError(f"{location}.name must be a non-empty string.")
        if name in names:
            raise ValueError(f"Duplicate rule name: {name}")
        names.add(name)
        validate_when(rule.get("when"), f"{location}.when")
        validate_action(rule.get("action"), f"{location}.action")
        if "continue" in rule and not isinstance(rule["continue"], bool):
            raise ValueError(f"{location}.continue must be boolean.")
    if "default" in payload:
        validate_action(payload["default"], "default")


def media_facts(path: Path, ffprobe: str | None) -> dict:
    info = probe_media(ffprobe, path) if ffprobe else None
    streams = (info or {}).get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    transfers = {str(stream.get("color_transfer") or "").lower() for stream in streams}
    return {
        "extension": path.suffix.lower().lstrip("."),
        "size_mb": path.stat().st_size / (1024 * 1024),
        "duration": float((info or {}).get("format", {}).get("duration", 0) or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": str(video.get("codec_name") or "").lower(),
        "audio_codec": str(audio.get("codec_name") or "").lower(),
        "channels": int(audio.get("channels") or 0),
        "hdr": bool(transfers & {"smpte2084", "arib-std-b67"}),
        "has_subtitles": any(stream.get("codec_type") == "subtitle" for stream in streams),
    }


def rule_matches(when: dict, facts: dict) -> bool:
    for key, expected in when.items():
        if key in NUMERIC_CONDITIONS:
            field, comparison = NUMERIC_CONDITIONS[key]
            if not comparison(float(facts[field]), float(expected)):
                return False
        elif key in LIST_CONDITIONS:
            field = LIST_CONDITIONS[key]
            values = {str(value).lower().lstrip(".") for value in expected}
            contained = str(facts[field]).lower() in values
            if key.endswith("_not_in") and contained:
                return False
            if not key.endswith("_not_in") and not contained:
                return False
        elif facts[key] is not expected:
            return False
    return True


def evaluate(payload: dict, facts: dict) -> tuple[list[str], list[dict]]:
    names: list[str] = []
    actions: list[dict] = []
    for rule in payload["rules"]:
        if not rule_matches(rule["when"], facts):
            continue
        names.append(rule["name"])
        actions.append(dict(rule["action"]))
        if not rule.get("continue", False):
            break
    if not actions and "default" in payload:
        names.append("default")
        actions.append(dict(payload["default"]))
    return names, actions


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def op_validate(args: argparse.Namespace) -> int:
    try:
        payload = load_rules(Path(args.rules))
    except ValueError as ex:
        return fail("invalid_rules", str(ex))
    emit("complete", output=str(Path(args.rules).resolve()), size_bytes=Path(args.rules).stat().st_size, count=len(payload["rules"]))
    return 0


def op_evaluate(args: argparse.Namespace) -> int:
    try:
        payload = load_rules(Path(args.rules))
    except ValueError as ex:
        return fail("invalid_rules", str(ex))
    inputs = [Path(value) for value in args.input]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        return fail("missing_input", f"Input file(s) not found: {missing}")
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    results: list[dict] = []
    for index, path in enumerate(inputs):
        facts = media_facts(path, ffprobe)
        names, actions = evaluate(payload, facts)
        result = {"input": str(path.resolve()), "facts": facts, "matches": names, "actions": actions}
        results.append(result)
        emit("rule_result", **result)
        emit("progress", percent=round((index + 1) / len(inputs) * 100, 1), stage=f"{index + 1}/{len(inputs)}", eta_seconds=None)
    output = Path(args.output).resolve()
    atomic_json(output, {"version": 1, "rules": str(Path(args.rules).resolve()), "results": results})
    emit("complete", output=str(output), size_bytes=output.stat().st_size, count=len(results))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rules-sidecar",
        description="Safe offline conditional media-to-preset planner.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    validate = sub.add_parser("validate", help="Validate a rules JSON document.")
    validate.add_argument("--rules", required=True)
    evaluate_parser = sub.add_parser("evaluate", help="Evaluate media files and write a deterministic plan.")
    evaluate_parser.add_argument("--rules", required=True)
    evaluate_parser.add_argument("--input", nargs="+", required=True)
    evaluate_parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "validate":
            return op_validate(args)
        if args.op == "evaluate":
            return op_evaluate(args)
        return fail("unknown_op", f"Unknown operation: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

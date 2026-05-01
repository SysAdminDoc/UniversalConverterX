#!/usr/bin/env python3
"""Sidecar NDJSON contract conformance check.

Scans every tools/*/sidecar.py and enforces the rules that bit us in v2.3:

  1. Frozen guard — any sidecar that calls `pip install` via subprocess must
     short-circuit when getattr(sys, 'frozen', False). When PyInstaller-frozen,
     sys.executable IS the sidecar exe; an unguarded pip-install call re-spawns
     the exe and fork-bombs the host. (Found in lipsight/demucs/whisper-stt
     during the 2026-04-30 audit.)

  2. Error-event code field — every emit of {"event": "error", ...} must include
     a "code" key. SidecarRunner.cs keys off `code`; omitting it routes every
     failure as "unknown" in the UI. (Found in lipsight during the same audit.)

  3. Known event names — `event` strings must be one of the documented set:
     progress, log, complete, error, segment, stem, device. New events should
     be added to KNOWN_EVENTS here when intentional, surfacing accidental typos.

Exit code 0 = pass, 1 = violations found. Designed for CI gating.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"

KNOWN_EVENTS = {
    # Standard lifecycle
    "progress", "log", "complete", "error",
    # Domain-specific result events (one per sidecar's output type)
    "segment",  # whisper-stt, lipsight — transcript segments
    "stem",     # demucs — separated audio stems
    "device",   # recordcast — DirectShow device enumeration
    "preset",   # gifstudio — known render presets
    "format",   # heicshift — supported input/output format inventory
    "voice",    # edge-tts — voice catalog enumeration
    "model",    # rnnoise — discoverable .rnnn model files
    "aspect",   # vertigo — target aspect-ratio presets
    "backend",  # whisper-cpp — compiled-in feature probe
    "chapter",  # chaptermark — discovered chapter markers
    "vmaf",          # clipforge.vmaf — per-frame VMAF scores
    "vmaf_summary",  # clipforge.vmaf — pooled mean / harmonic / min / pct<70
    "scene",         # scenedetect — detected scene cut (start/end timecodes)
    "thumb",         # clipforge.timeline — generated thumbnail in the strip
    "track",         # clipforge.track-list — enumerated container stream
    "doc",           # docconvert — produced document file (one per input)
    "archive_entry", # archive — file entry inside an archive
}


class Violation:
    __slots__ = ("path", "line", "rule", "detail")

    def __init__(self, path: Path, line: int, rule: str, detail: str):
        self.path = path
        self.line = line
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        rel = self.path.relative_to(REPO).as_posix()
        return f"{rel}:{self.line}  [{self.rule}]  {self.detail}"


def find_sidecars() -> list[Path]:
    return sorted(p for p in TOOLS.glob("*/sidecar.py") if p.is_file())


def check_frozen_guard(path: Path, src: str, tree: ast.AST) -> list[Violation]:
    """If the file calls pip install via subprocess, it must check sys.frozen first."""
    has_pip_call = False
    pip_lines: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            args_text = ast.dump(node)
            if "'pip'" in args_text and "'install'" in args_text:
                has_pip_call = True
                pip_lines.append(getattr(node, "lineno", 0))

    if not has_pip_call:
        return []

    # If pip install is present, verify sys.frozen is checked SOMEWHERE in
    # the file. We don't try to prove control-flow dominance — the audit-fix
    # pattern just needs the early return to exist.
    if "getattr(sys, 'frozen'" in src or 'getattr(sys, "frozen"' in src:
        return []

    return [Violation(
        path, pip_lines[0] if pip_lines else 1, "frozen-guard",
        f"calls subprocess pip install (line {pip_lines[0]}) without "
        f"`if getattr(sys, 'frozen', False): return` short-circuit — "
        f"will fork-bomb when PyInstaller-frozen",
    )]


def check_error_code_field(path: Path, tree: ast.AST) -> list[Violation]:
    """Every literal emit({event: 'error', ...}) must include a 'code' key.

    Handles three common shapes:
      emit({"event": "error", "code": "...", "message": "..."})
      emit("error", code="...", message="...")
      emit_error(...)  → trust the helper to format correctly
    """
    violations: list[Violation] = []

    def keys_in_dict(d: ast.Dict) -> set[str]:
        out: set[str] = set()
        for k in d.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                out.add(k.value)
        return out

    def value_for_key(d: ast.Dict, key: str) -> str | None:
        for k, v in zip(d.keys, d.values):
            if isinstance(k, ast.Constant) and k.value == key and isinstance(v, ast.Constant):
                return v.value
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Shape A: emit({...})
        if (isinstance(node.func, ast.Name) and node.func.id == "emit"
                and len(node.args) == 1 and isinstance(node.args[0], ast.Dict)):
            d = node.args[0]
            ev = value_for_key(d, "event")
            if ev == "error" and "code" not in keys_in_dict(d):
                violations.append(Violation(
                    path, node.lineno, "error-code-field",
                    "emit({'event':'error', ...}) missing 'code' key — "
                    "SidecarRunner will route as errorCode='unknown'",
                ))

        # Shape B: emit("error", code=..., message=...)
        elif (isinstance(node.func, ast.Name) and node.func.id == "emit"
              and node.args and isinstance(node.args[0], ast.Constant)
              and node.args[0].value == "error"):
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            if "code" not in kw_names:
                violations.append(Violation(
                    path, node.lineno, "error-code-field",
                    "emit('error', ...) missing code= keyword arg",
                ))

    # emit_error helpers: enforce that the helper signature accepts a `code`
    # parameter. Avoids the lipsight-style mistake where every call site loses
    # the field because the helper drops it.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "emit_error":
            arg_names = {a.arg for a in node.args.args}
            if "code" not in arg_names and not node.args.kwonlyargs:
                violations.append(Violation(
                    path, node.lineno, "error-code-field",
                    "emit_error() helper has no 'code' parameter — "
                    "every error from this sidecar will reach the UI as 'unknown'",
                ))

    return violations


def check_known_events(path: Path, tree: ast.AST) -> list[Violation]:
    """Flag {event: '<typo>'} literals that aren't in KNOWN_EVENTS.

    Catches accidental typos like "completed" vs "complete" or "errors" vs "error".
    """
    violations: list[Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"emit", "emit_progress", "emit_log",
                                 "emit_complete", "emit_error"}:
            continue

        # Direct emit("<name>", ...) form
        if node.func.id == "emit" and node.args and isinstance(node.args[0], ast.Constant):
            ev = node.args[0].value
            if isinstance(ev, str) and ev not in KNOWN_EVENTS:
                violations.append(Violation(
                    path, node.lineno, "known-events",
                    f"unknown event name {ev!r} — add to KNOWN_EVENTS in "
                    f"check_contract.py if intentional",
                ))

        # emit({"event": "<name>", ...}) form
        if (node.func.id == "emit" and node.args
                and isinstance(node.args[0], ast.Dict)):
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if (isinstance(k, ast.Constant) and k.value == "event"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)
                        and v.value not in KNOWN_EVENTS):
                    violations.append(Violation(
                        path, node.lineno, "known-events",
                        f"unknown event name {v.value!r}",
                    ))

    return violations


def check_one(path: Path) -> list[Violation]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [Violation(path, e.lineno or 0, "syntax", f"parse failed: {e.msg}")]

    return (
        check_frozen_guard(path, src, tree)
        + check_error_code_field(path, tree)
        + check_known_events(path, tree)
    )


def main(argv: list[str] | None = None) -> int:
    sidecars = find_sidecars()
    if not sidecars:
        print("no sidecars found under tools/*/sidecar.py", file=sys.stderr)
        return 2

    all_violations: list[Violation] = []
    for path in sidecars:
        all_violations.extend(check_one(path))

    if not all_violations:
        print(f"OK — {len(sidecars)} sidecar(s) conform to the NDJSON contract")
        return 0

    print(f"FAIL — {len(all_violations)} violation(s) across "
          f"{len({v.path for v in all_violations})} sidecar(s):", file=sys.stderr)
    print(file=sys.stderr)
    for v in all_violations:
        print(f"  {v}", file=sys.stderr)
    print(file=sys.stderr)
    print("Reference: see ROADMAP.md #49 for the contract.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

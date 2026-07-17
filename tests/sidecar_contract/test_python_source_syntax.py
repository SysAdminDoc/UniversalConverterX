"""Parse every tracked Python source without importing optional runtimes."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_all_tracked_python_sources_parse() -> None:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    sources = [ROOT / relative for relative in result.stdout.splitlines() if relative]
    assert sources
    failures: list[str] = []
    for source in sources:
        try:
            ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        except (SyntaxError, UnicodeError) as exc:
            failures.append(f"{source.relative_to(ROOT)}: {exc}")
    assert not failures, "Tracked Python syntax failures:\n" + "\n".join(failures)

#!/usr/bin/env python3
"""Headless contract for the large catalog pages.

The Windows UI smoke runner can consume the same budgets for telemetry. This
headless gate keeps the source contract honest in environments where a
physical display is unavailable: the three pages must use ItemsRepeater, the
History page must page its SQLite query, and the declared budgets must remain
bounded.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
XAML = REPO / "src" / "UniversalConverterX.UI" / "Views" / "Pages"
SERVICES = REPO / "src" / "UniversalConverterX.UI" / "Services"

# Recorded budgets for a cold page navigation and a typical realized window.
# A UI runner may report these values; this source gate prevents them from
# being removed or changed to unbounded values while UI smoke is unavailable.
COLD_NAVIGATION_BUDGET_MS = 1_000
MAX_REALIZED_CONTAINERS = 64
MAX_WORKING_SET_GROWTH_BYTES = 128 * 1024 * 1024


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    pages = {
        "ToolboxPage": _read(XAML / "ToolboxPage.xaml"),
        "PresetsPage": _read(XAML / "PresetsPage.xaml"),
        "HistoryPage": _read(XAML / "HistoryPage.xaml"),
    }

    for name, source in pages.items():
        _assert(
            "ItemsRepeater" in source,
            f"{name} must use ItemsRepeater for a virtualizing item surface",
            failures,
        )
        _assert(
            "ItemsControl" not in source,
            f"{name} still contains a fully materializing ItemsControl",
            failures,
        )
        _assert(
            "ScrollViewer" in source,
            f"{name} must expose its repeater through a scroll viewer",
            failures,
        )

    _assert(
        "GridView" not in pages["ToolboxPage"],
        "ToolboxPage must not nest GridView instances inside its page ScrollViewer",
        failures,
    )
    _assert(
        "UniformGridLayout" in pages["ToolboxPage"],
        "ToolboxPage must retain a virtualizing uniform grid layout",
        failures,
    )
    _assert(
        "StackLayout" in pages["PresetsPage"] and "StackLayout" in pages["HistoryPage"],
        "PresetsPage and HistoryPage must use virtualizing stack layouts",
        failures,
    )

    history_code = _read(XAML / "HistoryPage.xaml.cs")
    _assert(
        "ViewChanged=\"ListScroll_ViewChanged\"" in pages["HistoryPage"],
        "HistoryPage must load the next page from ScrollViewer.ViewChanged", failures)
    _assert("limit: VirtualizationBudgets.HistoryPageSize" in history_code,
            "HistoryPage must query SQLite in bounded pages", failures)
    _assert("offset: _nextOffset" in history_code,
            "HistoryPage must advance the SQLite offset for incremental loading", failures)
    _assert("VirtualizationBudgets.HistoryMaxRows" in history_code,
            "HistoryPage must enforce its retained-row display cap", failures)

    presets_code = _read(XAML / "PresetsPage.xaml.cs")
    _assert("VirtualizationBudgets.PresetSearchResultLimit" in presets_code,
            "PresetsPage must enforce a bounded semantic-search result set", failures)
    _assert("VirtualizationBudgets.PresetSearchDebounceMilliseconds" in presets_code,
            "PresetsPage must retain a bounded search debounce", failures)

    budgets_code = _read(SERVICES / "VirtualizationBudgets.cs")
    expected_budgets = {
        "ColdNavigationBudgetMilliseconds": r"1_?000",
        "MaxRealizedContainers": r"64",
        "MaxWorkingSetGrowthBytes": r"128L\s*\*\s*1024L\s*\*\s*1024L",
    }
    for name, literal in expected_budgets.items():
        pattern = rf"{name}\s*=\s*{literal}"
        _assert(
            re.search(pattern, budgets_code) is not None,
            f"VirtualizationBudgets.cs must record {name}",
            failures,
        )
    _assert(COLD_NAVIGATION_BUDGET_MS <= 2_000,
            "cold-navigation budget must stay within the release gate ceiling", failures)
    _assert(MAX_REALIZED_CONTAINERS <= 128,
            "realized-container budget must stay bounded", failures)
    _assert(MAX_WORKING_SET_GROWTH_BYTES <= 256 * 1024 * 1024,
            "memory budget must stay within the release gate ceiling", failures)

    if failures:
        print("FAIL — virtualization contract:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(
        "OK — Toolbox, Presets, and History use virtualized repeaters; "
        f"budgets: cold={COLD_NAVIGATION_BUDGET_MS}ms, "
        f"realized<={MAX_REALIZED_CONTAINERS}, "
        f"memory<={MAX_WORKING_SET_GROWTH_BYTES // (1024 * 1024)}MiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

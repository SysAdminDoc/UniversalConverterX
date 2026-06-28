#!/usr/bin/env python3
"""WinUI 3 AutomationId contract check.

Scans every src/UniversalConverterX.UI/Views/**/*.xaml file and enforces:

  Every interactive control (Button, ComboBox, Slider, ToggleSwitch,
  CheckBox, RadioButton, ToggleButton, MenuFlyoutItem, NumberBox, TextBox,
  PasswordBox, AutoSuggestBox) carries an `AutomationProperties.AutomationId`
  attribute so UI automation tests (Playwright / Appium / WinAppDriver) can
  target it deterministically.

ROADMAP Item 10 (a)+(c): the ID gate is the regression-prevention property
the audit asked for; without it, every new <Button> ships without an ID and
the screen-reader / automation surface decays.

To avoid "fix the world" debt blocking the gate from going in, this lint
operates against a baseline file at `tests/uia_contract/baseline.txt`. Each
line in the baseline is a `<relpath>:<element>:<x:Name|UNNAMED#index>`
triple. The lint passes when the *current* set of violations is a subset
of the baseline. Brand-new violations fail; cleanups that shrink the
baseline are allowed (run `--write-baseline` to regenerate).

Line numbers are deliberately omitted from the key so that an unrelated
edit that shifts line offsets doesn't trip the lint. Named controls are
keyed by their `x:Name` (stable across edits); anonymous controls collapse
to per-file `UNNAMED#1`, `UNNAMED#2`, ... in document order — adding a new
anonymous control bumps the index → new key → lint fails until the new
control gets an AutomationId.

Usage:
  python tests/uia_contract/check_uia.py             # gate (CI mode)
  python tests/uia_contract/check_uia.py --report    # dump full violation list
  python tests/uia_contract/check_uia.py --write-baseline  # rebaseline (use sparingly)

Exit codes:
  0  Pass (no new violations beyond baseline)
  1  Fail (new violations introduced)
  2  Fatal (no XAML files found, baseline missing in CI mode, etc.)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
XAML_ROOT = REPO / "src" / "UniversalConverterX.UI" / "Views"
BASELINE = Path(__file__).with_name("baseline.txt")

# Interactive control element names that participate in UIA. Self-closed (<Foo/>)
# and open-tag (<Foo ...>) forms both count.
INTERACTIVE = {
    "Button", "ComboBox", "Slider", "ToggleSwitch", "CheckBox",
    "RadioButton", "ToggleButton", "MenuFlyoutItem", "NumberBox",
    "TextBox", "PasswordBox", "AutoSuggestBox", "DropDownButton",
    "SplitButton", "HyperlinkButton", "RepeatButton", "AppBarButton",
    "AppBarToggleButton", "ColorPicker", "DatePicker", "TimePicker",
    "PivotItem",  # PivotItem isn't strictly clickable but Pivot navigation is keyed by automation tests.
}

# Some elements appear inside DataTemplate / Style / ItemsPanel scopes where an
# AutomationId can't be set declaratively (the template is reused per item). We
# detect the surrounding context and skip those occurrences. Keep the list
# narrow — when in doubt, require the ID.
TEMPLATE_SCOPES = {
    "DataTemplate", "ControlTemplate", "ItemsPanelTemplate", "Style.Setters",
}

# Per-element-tag regex: matches the opening of an interactive control. Using
# non-greedy match up to the matching `>` so we capture only that one tag.
TAG_PATTERN = re.compile(
    r"<(?P<el>[A-Z][A-Za-z]*)(?=[\s>/])(?P<body>[^>]*?)/?>",
    re.DOTALL,
)

AUTOMATION_ID_PATTERN = re.compile(r"AutomationProperties\.AutomationId\s*=", re.MULTILINE)
X_NAME_PATTERN = re.compile(r'\bx:Name\s*=\s*"([^"]+)"')

# Lines starting with comment markers we should ignore when locating tags.
# XAML comments use <!-- ... -->; we strip those entirely before scanning.
COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_comments(src: str) -> str:
    return COMMENT_PATTERN.sub("", src)


def _line_no_for(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def _ancestor_template_scope(src: str, offset: int) -> bool:
    """Return True if *offset* falls inside a DataTemplate / ControlTemplate /
    ItemsPanelTemplate (or close cousin), where setting AutomationId is awkward.

    Heuristic: count opens/closes of each TEMPLATE_SCOPES element before the
    offset. If any has more opens than closes at that point, we're inside it.
    """
    region = src[:offset]
    for scope in TEMPLATE_SCOPES:
        opens = len(re.findall(rf"<{scope}\b", region))
        closes = len(re.findall(rf"</{scope}>", region))
        # Self-closed templates (<Setter/>) don't open a scope.
        if opens > closes:
            return True
    return False


def find_violations(path: Path) -> list[tuple[str, str]]:
    """Return list of (element, name_or_UNNAMED#N) for interactive controls in
    *path* that lack AutomationProperties.AutomationId. UNNAMED controls are
    suffixed with a per-(file,element) document-order index so adding a new
    one bumps the key without renumbering existing ones unrelated."""
    raw = path.read_text(encoding="utf-8")
    src = _strip_comments(raw)
    out: list[tuple[str, str]] = []
    unnamed_counts: dict[str, int] = {}
    for match in TAG_PATTERN.finditer(src):
        el = match.group("el")
        if el not in INTERACTIVE:
            continue
        body = match.group("body") or ""

        # Some tags split AutomationProperties.AutomationId onto multiple
        # lines; the body within `<...>` already covers that since the regex
        # is DOTALL. Check for the property in the body.
        if AUTOMATION_ID_PATTERN.search(body):
            continue

        if _ancestor_template_scope(src, match.start()):
            continue

        # x:Name (when present) helps a reviewer track down the offender; fall
        # back to indexed UNNAMED when the control is anonymous.
        name_match = X_NAME_PATTERN.search(body)
        if name_match:
            name = name_match.group(1)
        else:
            unnamed_counts[el] = unnamed_counts.get(el, 0) + 1
            name = f"UNNAMED#{unnamed_counts[el]}"
        out.append((el, name))
    return out


def collect_all_violations() -> list[str]:
    """Return baseline-format keys for every violation in the tree."""
    if not XAML_ROOT.is_dir():
        return []
    keys: list[str] = []
    for xaml in sorted(XAML_ROOT.rglob("*.xaml")):
        # Skip generated XAML under obj/ if any rglob caught it.
        if "obj" in xaml.parts or "bin" in xaml.parts:
            continue
        rel = xaml.relative_to(REPO).as_posix()
        for el, name in find_violations(xaml):
            keys.append(f"{rel}:{el}:{name}")
    return keys


def load_baseline() -> set[str]:
    if not BASELINE.is_file():
        return set()
    return {ln.strip() for ln in BASELINE.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}


def write_baseline(keys: list[str]) -> None:
    header = (
        "# UIA AutomationId baseline — generated by tests/uia_contract/check_uia.py.\n"
        "# Each line: <relpath>:<element>:<x:Name|UNNAMED#index>\n"
        "# Line numbers are deliberately NOT in the key (unrelated edits would\n"
        "# trip the lint). Named controls keyed by x:Name; anonymous controls\n"
        "# get a per-(file,element) document-order index — adding a new\n"
        "# anonymous control of an existing element type bumps the index.\n"
        "# CI passes when current violations are a subset of this list. New\n"
        "# violations FAIL the build; cleanups that shrink this list are fine.\n"
        "# Regenerate with: python tests/uia_contract/check_uia.py --write-baseline\n"
    )
    BASELINE.write_text(header + "\n".join(sorted(set(keys))) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true",
                        help="Print every current violation (not gated against baseline).")
    parser.add_argument("--write-baseline", action="store_true",
                        help="Overwrite the baseline file with current violations.")
    args = parser.parse_args(argv)

    current = collect_all_violations()
    if not current and not XAML_ROOT.exists():
        print(f"No XAML files found under {XAML_ROOT}", file=sys.stderr)
        return 2

    if args.write_baseline:
        write_baseline(current)
        print(f"Wrote baseline with {len(set(current))} entry(ies) -> "
              f"{BASELINE.relative_to(REPO)}")
        return 0

    if args.report:
        if not current:
            print("OK -- every interactive control has an AutomationId.")
            return 0
        print(f"{len(current)} interactive control(s) without AutomationId:")
        for key in sorted(set(current)):
            print(f"  {key}")
        return 0

    baseline = load_baseline()
    current_set = set(current)
    new_violations = sorted(current_set - baseline)
    if not new_violations:
        suffix = " (baseline unchanged)" if current_set == baseline else \
                 f" ({len(baseline) - len(current_set)} cleanup(s))"
        print(f"OK -- no new UIA AutomationId violations{suffix}.")
        return 0

    print(f"FAIL -- {len(new_violations)} NEW interactive control(s) "
          f"missing AutomationProperties.AutomationId:", file=sys.stderr)
    print(file=sys.stderr)
    for key in new_violations:
        print(f"  {key}", file=sys.stderr)
    print(file=sys.stderr)
    print("Add `AutomationProperties.AutomationId=\"<UniqueIdInPascalCase>\"` "
          "to each control above. The ID should be stable across releases so "
          "automation tests don't break.", file=sys.stderr)
    print("If the addition is genuinely impossible (e.g. inside a templated "
          "ItemsRepeater), add the offender to the template-scope skip-list "
          "in `tests/uia_contract/check_uia.py` (TEMPLATE_SCOPES).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

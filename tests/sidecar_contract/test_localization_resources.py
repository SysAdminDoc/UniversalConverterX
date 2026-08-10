"""Coverage contract for WinUI localization resources."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "localization" / "extract_xaml_resources.py"
SPEC = importlib.util.spec_from_file_location("extract_xaml_resources", SCRIPT)
assert SPEC and SPEC.loader
extractor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = extractor
SPEC.loader.exec_module(extractor)


class LocalizationResourceTests(unittest.TestCase):
    def test_all_literal_xaml_properties_have_uid_and_english_resource(self) -> None:
        english = extractor.load_resw(
            extractor.STRINGS_ROOT / "en-US" / "Resources.resw")
        seen: set[str] = set()
        checked = 0
        missing: list[str] = []
        for path in extractor.xaml_files():
            text = path.read_text(encoding="utf-8-sig")
            for _, _, tag in extractor.iter_start_tags(text):
                attrs = extractor.attributes(tag)
                localizable = [
                    prop for prop, value in attrs.items()
                    if prop in extractor.LOCALIZABLE_PROPERTIES and extractor.is_localizable(value)
                ]
                if not localizable:
                    continue
                uid = attrs.get("x:Uid")
                if not uid:
                    missing.append(f"{path.relative_to(ROOT)}: missing x:Uid")
                    continue
                self.assertNotIn(uid, seen, f"duplicate x:Uid: {uid}")
                seen.add(uid)
                for prop in localizable:
                    key = f"{uid}.{extractor.LOCALIZABLE_PROPERTIES[prop]}"
                    if key not in english:
                        missing.append(f"{path.relative_to(ROOT)}: missing {key}")
                    checked += 1
        self.assertFalse(missing, "\n".join(missing[:30]))
        self.assertGreater(checked, 500)

    def test_priority_locales_have_complete_matching_key_sets(self) -> None:
        english = extractor.load_resw(
            extractor.STRINGS_ROOT / "en-US" / "Resources.resw")
        self.assertTrue(english)
        placeholders = re.compile(r"\{[^{}]+\}")
        for locale in extractor.LOCALES[1:]:
            localized = extractor.load_resw(
                extractor.STRINGS_ROOT / locale / "Resources.resw")
            self.assertEqual(set(english), set(localized), locale)
            for key, value in localized.items():
                self.assertEqual(
                    set(placeholders.findall(english[key])),
                    set(placeholders.findall(value)),
                    f"{locale}: {key}")

    def test_code_localizer_calls_have_stable_resource_entries(self) -> None:
        english = extractor.load_resw(
            extractor.STRINGS_ROOT / "en-US" / "Resources.resw")
        discovered = extractor.discover_code_resources()
        self.assertGreater(len(discovered), 300)
        missing = sorted(key for key in discovered if key not in english)
        self.assertFalse(missing, "Missing code resources: " + ", ".join(missing[:20]))
        for key, value in discovered.items():
            self.assertEqual(value, english[key], key)

    def test_nonempty_imperative_display_assignments_use_localizer(self) -> None:
        """Keep runtime copy on the resource path; empty clears are intentional."""
        # Item-list StatusText/StatusMessage values are a deliberately narrow
        # legacy allowlist: Converter and Compressor persist and compare those
        # stable state tokens during queue recovery. They must be split into a
        # typed state plus a display value before they can be translated safely.
        # This contract therefore targets direct UI/control assignments, while
        # the queue-state migration remains a separate architectural change.
        display_property = re.compile(
            r"\b(?:Text|Content|Header|Title|Message|PlaceholderText|Caption|"
            r"OffContent|OnContent|ToolTip|PrimaryButtonText|SecondaryButtonText|"
            r"CloseButtonText|CancelButtonText|OpenButtonText)\s*=\s*(\$?\"|@\")"
        )
        violations: list[str] = []
        for path in extractor.csharp_files():
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            for line_number, line in enumerate(lines, start=1):
                match = display_property.search(line)
                if not match or "AppLocalizer." in line:
                    continue
                quote = match.group(1)
                start = match.end()
                if quote == '@"':
                    end = line.find('"', start)
                else:
                    end = start
                    escaped = False
                    while end < len(line):
                        character = line[end]
                        if character == '"' and not escaped:
                            break
                        escaped = character == '\\' and not escaped
                        if character != '\\':
                            escaped = False
                        end += 1
                value = line[start:end]
                if value:
                    violations.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
        self.assertFalse(
            violations,
            "Nonempty display literals must use AppLocalizer (empty clears are the only allowlist):\n"
            + "\n".join(violations[:30]),
        )


if __name__ == "__main__":
    unittest.main()

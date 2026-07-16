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


if __name__ == "__main__":
    unittest.main()

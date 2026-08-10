from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "ebookconvert" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ebookconvert_kepub_sidecar", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _write_epub(path: Path) -> None:
    page = b'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Fixture</title></head>
  <body><p>Hello <em>world</em>.</p><p>Second paragraph.</p></body>
</html>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip",
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr("OEBPS/page.xhtml", page)
        archive.writestr("OEBPS/content.opf", b"<package/>")


def _events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


class KepubInterchangeTests(unittest.TestCase):
    def test_epub_to_kepub_and_back_preserves_readable_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "fixture.epub"
            output = root / "out"
            _write_epub(source)

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(SIDECAR.main([
                    "convert", "--format", "kepub", "--output-dir", str(output),
                    "--input", str(source),
                ]), 0)
            kepub = output / "fixture.kepub.epub"
            self.assertTrue(kepub.is_file())
            with zipfile.ZipFile(kepub) as archive:
                self.assertEqual(archive.namelist()[0], "mimetype")
                self.assertEqual(archive.getinfo("mimetype").compress_type,
                                 zipfile.ZIP_STORED)
                page = archive.read("OEBPS/page.xhtml")
            self.assertIn(b"class=\"koboSpan\"", page)
            self.assertIn(b"Hello", page)
            self.assertNotIn(b"<title><span", page)
            self.assertTrue(any(event.get("source") == "kepub"
                                for event in _events(captured.getvalue())))

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(SIDECAR.main([
                    "convert", "--format", "epub", "--output-dir", str(root / "back"),
                    "--input", str(kepub),
                ]), 0)
            restored = root / "back" / "fixture.epub"
            self.assertTrue(restored.is_file())
            with zipfile.ZipFile(restored) as archive:
                restored_page = archive.read("OEBPS/page.xhtml")
            self.assertNotIn(b"koboSpan", restored_page)
            self.assertIn(b"Hello", restored_page)
            self.assertIn(b"world</", restored_page)

    def test_protected_kfx_is_rejected_before_calibre_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "protected.kfx"
            source.write_bytes(b"KFX voucher DRM payload")
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                result = SIDECAR.main([
                    "convert", "--format", "epub", "--output-dir", str(root / "out"),
                    "--input", str(source),
                ])
            self.assertEqual(result, 1)
            events = _events(captured.getvalue())
            self.assertEqual(events[0]["event"], "error")
            self.assertEqual(events[0]["code"], "protected_input")
            self.assertIn("DeDRM", events[0]["message"])


if __name__ == "__main__":
    unittest.main()

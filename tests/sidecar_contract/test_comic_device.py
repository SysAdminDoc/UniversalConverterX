from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "comic" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("comic_device_sidecar", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _write_comic(path: Path, *, cbr_label: bool = False) -> None:
    image = io.BytesIO()
    with Image.new("RGB", (1800, 2400), "white") as page:
        page.save(image, format="PNG")
    archive_path = path.with_suffix(".zip") if cbr_label else path
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("001/page.png", image.getvalue())
        archive.writestr(
            "ComicInfo.xml",
            b"<ComicInfo><Title>Device Fixture</Title><Writer>UCX Test</Writer></ComicInfo>",
        )
    if cbr_label:
        archive_path.replace(path)


def _events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


class ComicDeviceTests(unittest.TestCase):
    def test_cbz_and_zip_compatible_cbr_create_profiled_epub(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cbz = root / "comic.cbz"
            cbr = root / "comic.cbr"
            _write_comic(cbz)
            _write_comic(cbr, cbr_label=True)
            output = root / "out"

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                result = SIDECAR.main([
                    "to-device", "--format", "epub", "--profile", "kobo",
                    "--output-dir", str(output), "--input", str(cbz), str(cbr),
                ])
            self.assertEqual(result, 0)
            for name in ("comic.kobo.epub",):
                self.assertTrue((output / name).is_file())
            events = [event for event in _events(captured.getvalue())
                      if event.get("event") == "comic_book"]
            self.assertEqual(len(events), 2)
            self.assertTrue(all(event["profile"] == "kobo" for event in events))
            with zipfile.ZipFile(output / "comic.kobo.epub") as archive:
                css_name = next(name for name in archive.namelist()
                                if name.endswith("styles/device.css"))
                opf_name = next(name for name in archive.namelist()
                                if name.endswith("content.opf"))
                css = archive.read(css_name)
                self.assertIn(b"kobo", css)
                self.assertIn(b"Device Fixture", archive.read(opf_name))

    def test_mobi_uses_kindled_profile_and_calibre_output_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "comic.cbz"
            _write_comic(source)
            output = root / "out"
            observed: dict[str, object] = {}

            def fake_run(command, **kwargs):
                observed["command"] = command
                Path(command[2]).write_bytes(b"mobi-output")
                return SimpleNamespace(returncode=0, stdout="")

            with (
                mock.patch.object(SIDECAR, "_find_calibre", return_value="fake-calibre"),
                mock.patch.object(SIDECAR.subprocess, "run", side_effect=fake_run),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = SIDECAR.main([
                    "to-device", "--format", "mobi", "--profile", "kindle",
                    "--output-dir", str(output), "--input", str(source),
                ])
            self.assertEqual(result, 0)
            self.assertEqual((output / "comic.kindle.mobi").read_bytes(), b"mobi-output")
            self.assertIn("--output-profile", observed["command"])
            self.assertIn("kindle_pw3", observed["command"])


if __name__ == "__main__":
    unittest.main()

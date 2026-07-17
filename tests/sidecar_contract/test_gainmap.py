"""Focused security, metadata, and command tests for the gain-map sidecar."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "gainmap" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("gainmap_sidecar", SIDECAR)
assert SPEC and SPEC.loader
gainmap = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gainmap
SPEC.loader.exec_module(gainmap)


class GainMapTests(unittest.TestCase):
    def test_runtime_manifest_pins_exact_verified_artifacts(self) -> None:
        manifest = gainmap._manifest()
        artifacts = {item["id"]: item for item in manifest["artifacts"]}

        self.assertEqual("1.4.2+vips8.18.2", manifest["runtimeVersion"])
        self.assertEqual(21145549, artifacts["libvips"]["bytes"])
        self.assertEqual(64, len(artifacts["libvips"]["sha256"]))
        self.assertEqual(4254192, artifacts["avifgainmaputil"]["bytes"])
        self.assertEqual(
            "64fe22b44de6bb8ffd24e00fcfb0984689cc9634c250694099a5b7e6fa09e01c",
            artifacts["avifgainmaputil"]["sha256"])
        self.assertEqual("c5240fc79fe5c2407e10afd35f5505ef6333ea49",
                         artifacts["avifgainmaputil"]["sourceCommit"])

    def test_libvips_extracts_only_runtime_and_license(self) -> None:
        artifact = gainmap._manifest()["artifacts"][0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "vips.zip"
            destination = root / "installed"
            with zipfile.ZipFile(archive, "w") as bundle:
                prefix = artifact["archivePrefix"]
                bundle.writestr(prefix + "bin/vips.exe", "vips")
                bundle.writestr(prefix + "bin/vipsheader.exe", "header")
                bundle.writestr(prefix + "bin/libuhdr.dll", "uhdr")
                bundle.writestr(prefix + "LICENSE", "license")
                bundle.writestr(prefix + "include/not-installed.h", "header")

            gainmap._extract_artifact(archive, artifact, destination)

            self.assertTrue((destination / "bin" / "vips.exe").is_file())
            self.assertTrue((destination / "LICENSE").is_file())
            self.assertFalse((destination / "include").exists())

    def test_extract_rejects_path_traversal(self) -> None:
        artifact = gainmap._manifest()["artifacts"][1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("avifgainmaputil.exe", "binary")
                bundle.writestr("licenses/libavif-LICENSE.txt", "license")
                bundle.writestr("../escape.txt", "blocked")

            with self.assertRaises(ValueError):
                gainmap._extract_artifact(archive, artifact, root / "installed")
            self.assertFalse((root / "escape.txt").exists())

    def test_vips_metadata_parser_requires_uhdr_loader_and_payload(self) -> None:
        metadata = gainmap._parse_vips_metadata(
            "photo.jpg: 3840x2160 uchar, 3 bands, srgb, uhdrload\n"
            "vips-loader: uhdrload\n"
            "gainmap-data: 31738 bytes of binary data\n"
            "gainmap-scale-factor: 4\n"
            "gainmap-hdr-capacity-max: 100\n")

        self.assertTrue(metadata["gainMap"])
        self.assertEqual(3840, metadata["width"])
        self.assertEqual(31738, metadata["gainmapBytes"])
        self.assertEqual("4", metadata["gainmap-scale-factor"])

    def test_avif_metadata_parser_reports_headroom(self) -> None:
        metadata = gainmap._parse_avif_metadata(
            " * Base headroom:      0 (as fraction: 0/1)\n"
            " * Alternate headroom: 4 (as fraction: 4/1)\n"
            " * Gain Map Min: R -2\n * Gain Map Max: R 7\n"
            " * Use Base Color Space: False\n")

        self.assertTrue(metadata["gainMap"])
        self.assertEqual(0.0, metadata["baseHeadroom"])
        self.assertEqual(4.0, metadata["alternateHeadroom"])

    def test_encoder_argument_vector_is_shell_free_and_pinned(self) -> None:
        args = gainmap.build_parser().parse_args([
            "to-avif", "--input", "input.jpg", "--output", "output.avif",
            "--quality", "91", "--gainmap-quality", "99", "--speed", "7",
        ])

        self.assertEqual(
            ["--qcolor", "91", "--qgain-map", "99", "--speed", "7"],
            gainmap._avif_encode_args(args))

    def test_operation_fails_cleanly_when_runtime_is_missing(self) -> None:
        protocol = io.StringIO()
        with mock.patch.object(gainmap, "_probe_runtime", return_value=(False, {})), \
                mock.patch.object(gainmap, "_find_avif", return_value=None), \
                mock.patch.object(gainmap, "_find_vips", return_value=None), \
                redirect_stdout(protocol):
            code = gainmap.main([
                "to-avif", "--input", "missing.jpg", "--output", "out.avif"])

        self.assertEqual(1, code)
        event = json.loads(protocol.getvalue().splitlines()[-1])
        self.assertEqual("gainmap_runtime_missing", event["code"])


if __name__ == "__main__":
    unittest.main()

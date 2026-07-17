"""Repository guardrails for consent-gated, offline sidecar inference."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"


def _call_literals(node: ast.Call) -> set[str]:
    return {
        value.value.lower()
        for value in ast.walk(node)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }


class DownloadIntegrityContractTests(unittest.TestCase):
    def test_direct_sidecar_network_paths_are_explicitly_classified(self) -> None:
        expected = {
            "anime-upscale/sidecar.py": "verified_asset",
            "colorize/sidecar.py": "verified_asset",
            "gainmap/sidecar.py": "verified_asset",
            "seedvr2/sidecar.py": "verified_asset",
            "videotag/sidecar.py": "verified_asset",
            "lipsight/sidecar.py": "user_requested_api",
            "videosummary/sidecar.py": "user_requested_api",
            "alphacut/AlphaCut.py": "update_metadata",
        }
        found: set[str] = set()
        markers = ("urlopen(", "urlretrieve(", "requests.get(", "requests.post(")
        paths = list(TOOLS.rglob("sidecar.py")) + [TOOLS / "alphacut" / "AlphaCut.py"]
        for path in paths:
            source = path.read_text(encoding="utf-8-sig")
            if any(marker in source for marker in markers):
                found.add(path.relative_to(TOOLS).as_posix())
        self.assertEqual(set(expected), found)

        for relative, classification in expected.items():
            if classification != "verified_asset":
                continue
            source = (TOOLS / relative).read_text(encoding="utf-8-sig").lower()
            self.assertIn("accept", source, relative)
            self.assertIn("sha256", source, relative)
            self.assertTrue(
                any(marker in source for marker in (".part", "temporarydirectory", "mkstemp")),
                f"{relative} must stage before promotion",
            )

    def test_high_risk_inference_entrypoints_apply_process_network_guard(self) -> None:
        guarded = (
            "alphacut/sidecar.py",
            "bgremove/sidecar.py",
            "facerestore/sidecar.py",
            "gfpgan/sidecar.py",
            "inpaint/sidecar.py",
            "ocrpro/sidecar.py",
            "premiumtts/sidecar.py",
            "sdkit/sidecar.py",
            "stemkit/sidecar.py",
            "superres/sidecar.py",
            "translatekit/sidecar.py",
            "videotag/sidecar.py",
            "whisper-stt/sidecar.py",
        )
        missing = [
            relative for relative in guarded
            if "enforce_offline()" not in (TOOLS / relative).read_text(encoding="utf-8-sig")
        ]
        self.assertEqual([], missing)

    def test_sidecars_never_install_packages_or_clone_mutable_repositories(self) -> None:
        violations: list[str] = []
        paths = list(TOOLS.rglob("sidecar.py")) + [TOOLS / "alphacut" / "AlphaCut.py"]
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                literals = _call_literals(node)
                if ({"pip", "install"} <= literals or {"git", "clone"} <= literals):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations, "Runtime environment mutation is forbidden")

    def test_model_loaders_are_explicitly_offline(self) -> None:
        paths = list(TOOLS.rglob("sidecar.py")) + [TOOLS / "vertigo" / "core" / "diarize.py"]
        violations: list[str] = []
        for path in paths:
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            offline_module = 'os.environ["HF_HUB_OFFLINE"] = "1"' in source
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name != "from_pretrained":
                    continue
                local_only = any(
                    keyword.arg == "local_files_only"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                )
                if not local_only and not offline_module:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations, "Model inference must not fetch from the network")

    def test_build_downloaders_require_consent_and_exact_pins(self) -> None:
        for relative in ("whisper-cpp/build.ps1", "realesrgan/build.ps1"):
            source = (TOOLS / relative).read_text(encoding="utf-8-sig")
            self.assertIn("[switch] $AcceptLicense", source, relative)
            self.assertIn("$assetSize", source, relative)
            self.assertRegex(source, r"\$assetSha\s*=\s*'[0-9A-F]{64}'", relative)
            self.assertNotRegex(source, r"['\"]0{64}['\"]", relative)
            self.assertIn(".part", source, relative)
            self.assertIn("$LibDir", source, relative)
            self.assertIn("--paths $LibDir", source, relative)

    def test_background_remover_exposes_explicit_consent_flow(self) -> None:
        xaml = (ROOT / "src" / "UniversalConverterX.UI" / "Views" / "Pages" /
                "BackgroundRemoverPage.xaml").read_text(encoding="utf-8-sig")
        code = (ROOT / "src" / "UniversalConverterX.UI" / "Views" / "Pages" /
                "BackgroundRemoverPage.xaml.cs").read_text(encoding="utf-8-sig")
        self.assertIn('Click="DownloadModel_Click"', xaml)
        self.assertIn('PrimaryButtonText = "Accept & download"', code)
        self.assertIn('"--check-model"', code)
        self.assertIn('"--accept-license"', code)

    def test_alphacut_inference_contains_no_download_call(self) -> None:
        path = TOOLS / "alphacut" / "AlphaCut.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        target = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_ensure_model")
        calls = {
            node.func.attr
            for node in ast.walk(target)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse({"urlopen", "urlretrieve"} & calls)

    def test_curated_model_commands_refuse_network_without_consent(self) -> None:
        commands = (
            [sys.executable, str(TOOLS / "superres" / "sidecar.py"),
             "download-model", "--model", "real-esrgan-x4plus"],
            [sys.executable, str(TOOLS / "facerestore" / "sidecar.py"),
             "download-model", "--model", "gfpgan-v1.4"],
            [sys.executable, str(TOOLS / "alphacut" / "sidecar.py"),
             "--download-model", "u2net_human_seg"],
        )
        with tempfile.TemporaryDirectory() as model_dir:
            for command in commands:
                result = subprocess.run(
                    [*command, "--model-dir", model_dir]
                    if command[1].endswith("alphacut\\sidecar.py")
                    else command,
                    capture_output=True, text=True, timeout=20,
                    env={**__import__("os").environ, "UCX_MODEL_DIR": model_dir},
                )
                self.assertNotEqual(0, result.returncode, command)
                self.assertIn("license_not_accepted", result.stdout, command)

    def test_no_placeholder_digest_in_tool_sources(self) -> None:
        placeholder = re.compile(r"(?<![0-9a-f])0{64}(?![0-9a-f])", re.IGNORECASE)
        violations = []
        for path in TOOLS.rglob("*"):
            if path.suffix.lower() not in {".py", ".ps1", ".json"}:
                continue
            if placeholder.search(path.read_text(encoding="utf-8-sig", errors="ignore")):
                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()

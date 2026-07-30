"""Security contract tests for the background-removal model packs."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "bgremove" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("bgremove_sidecar", SIDECAR)
assert SPEC and SPEC.loader
bgremove = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bgremove
SPEC.loader.exec_module(bgremove)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


class BgRemoveModelPackTests(unittest.TestCase):
    def _test_pack(self) -> tuple[dict, dict[str, bytes]]:
        files = {
            "model.py": b"verified model code\n",
            "config.json": b'{"model_type":"test"}\n',
            "model.safetensors": b"safe tensors fixture",
        }
        pack = {
            "backend": "birefnet",
            "modelId": "example/verified-model",
            "revision": "0123456789abcdef0123456789abcdef01234567",
            "license": "MIT",
            "licenseUrl": "https://example.invalid/license",
            "gated": False,
            "files": [
                {
                    "path": "model.py",
                    "bytes": len(files["model.py"]),
                    "sha256": _sha256(files["model.py"]),
                },
                {
                    "path": "config.json",
                    "bytes": len(files["config.json"]),
                    "gitBlobSha1": _git_blob_sha1(files["config.json"]),
                },
                {
                    "path": "model.safetensors",
                    "bytes": len(files["model.safetensors"]),
                    "sha256": _sha256(files["model.safetensors"]),
                },
            ],
        }
        return pack, files

    def test_manifest_pins_full_revisions_and_every_executable_file(self) -> None:
        manifest = bgremove._model_manifest()

        self.assertEqual(1, manifest["schemaVersion"])
        self.assertEqual(bgremove._VERIFIED_BACKENDS,
                         {pack["backend"] for pack in manifest["packs"]})
        portrait = next(
            pack for pack in manifest["packs"]
            if pack["backend"] == "birefnet-portrait")
        self.assertEqual("ZhengPeng7/BiRefNet-portrait", portrait["modelId"])

        for pack in manifest["packs"]:
            with self.subTest(backend=pack["backend"]):
                self.assertRegex(pack["revision"], r"^[0-9a-f]{40}$")
                self.assertNotEqual("main", pack["revision"])
                self.assertTrue(pack["license"])
                self.assertTrue(pack["licenseUrl"].startswith("https://"))
                self.assertGreaterEqual(len(pack["files"]), 4)
                for item in pack["files"]:
                    self.assertGreater(item["bytes"], 0)
                    digest = item.get("sha256") or item.get("gitBlobSha1")
                    self.assertRegex(digest, r"^(?:[0-9a-f]{64}|[0-9a-f]{40})$")

    def test_download_requires_license_before_importing_huggingface(self) -> None:
        args = argparse.Namespace(
            backend="birefnet",
            accept_license=False,
            model_root=None,
        )
        output = io.StringIO()

        with mock.patch.dict(sys.modules, {"huggingface_hub": None}), \
                contextlib.redirect_stdout(output):
            result = bgremove.op_download_model(args)

        self.assertEqual(1, result)
        self.assertEqual("model_license_required",
                         json.loads(output.getvalue())["code"])

    def test_download_uses_full_revision_allowlist_and_atomic_verified_pack(self) -> None:
        pack, files = self._test_pack()
        calls: list[dict] = []

        def snapshot_download(**kwargs):
            calls.append(kwargs)
            destination = Path(kwargs["local_dir"])
            for name, content in files.items():
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            cache = destination / ".cache" / "huggingface"
            cache.mkdir(parents=True)
            (cache / "download.json").write_text("{}", encoding="utf-8")

        hub = types.ModuleType("huggingface_hub")
        hub.snapshot_download = snapshot_download
        args = argparse.Namespace(
            backend="birefnet",
            accept_license=True,
            model_root=None,
        )

        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(
                    bgremove,
                    "_model_manifest",
                    return_value={"schemaVersion": 1, "packs": [pack]},
                ), \
                mock.patch.dict(sys.modules, {"huggingface_hub": hub}), \
                contextlib.redirect_stdout(io.StringIO()):
            args.model_root = temp
            result = bgremove.op_download_model(args)
            installed = bgremove._verify_model_pack("birefnet", temp)
            marker = json.loads(
                (installed / bgremove._PACK_MARKER).read_text(encoding="utf-8"))

            self.assertEqual(0, result)
            self.assertEqual(pack["revision"], marker["revision"])
            self.assertFalse((installed / ".cache").exists())

        self.assertEqual(1, len(calls))
        self.assertEqual(pack["revision"], calls[0]["revision"])
        self.assertCountEqual(
            [item["path"] for item in pack["files"]],
            calls[0]["allow_patterns"])

    def test_pack_verification_rejects_tampering_and_extra_code(self) -> None:
        pack, files = self._test_pack()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "pack"
            directory.mkdir()
            for name, content in files.items():
                (directory / name).write_bytes(content)
            (directory / bgremove._PACK_MARKER).write_text(
                json.dumps({
                    "backend": pack["backend"],
                    "modelId": pack["modelId"],
                    "revision": pack["revision"],
                }),
                encoding="utf-8",
            )

            bgremove._validate_pack_directory(pack, directory)
            (directory / "model.py").write_bytes(b"X" * len(files["model.py"]))
            with self.assertRaisesRegex(bgremove.ModelPackError, "SHA-256 mismatch"):
                bgremove._validate_pack_directory(pack, directory)

            (directory / "model.py").write_bytes(files["model.py"])
            (directory / "poisoned.py").write_text(
                "raise RuntimeError('executed')", encoding="utf-8")
            with self.assertRaisesRegex(bgremove.ModelPackError, "non-allowlisted"):
                bgremove._validate_pack_directory(pack, directory)

    def test_remote_code_loader_uses_only_local_pack_and_private_cache(self) -> None:
        captured: dict[str, object] = {}

        class FakeTensor:
            def unsqueeze(self, _axis):
                return self

            def to(self, *_args, **_kwargs):
                return self

        class FakeArray:
            def __mul__(self, _value):
                return self

            def astype(self, _dtype):
                return self

        class FakePrediction:
            def sigmoid(self):
                return self

            def cpu(self):
                return self

            def __getitem__(self, _index):
                return self

            def squeeze(self):
                return self

            def float(self):
                return self

            def numpy(self):
                return FakeArray()

        class FakeModel:
            def to(self, _device):
                return self

            def eval(self):
                return self

            def __call__(self, _input):
                return [FakePrediction()]

        class FakeAutoModel:
            @staticmethod
            def from_pretrained(path, **kwargs):
                captured["path"] = path
                captured["kwargs"] = kwargs
                captured["cache_env"] = os.environ["HF_MODULES_CACHE"]
                return FakeModel()

        class FakeImage:
            size = (16, 16)

            def convert(self, _mode):
                return self

            def putalpha(self, _mask):
                return None

        image_api = types.SimpleNamespace(
            open=lambda _path: FakeImage(),
            fromarray=lambda _array: types.SimpleNamespace(
                resize=lambda _size: object()),
        )
        pil = types.ModuleType("PIL")
        pil.Image = image_api
        torch = types.ModuleType("torch")
        torch.bfloat16 = "bfloat16"
        torch.float32 = "float32"
        torch.inference_mode = contextlib.nullcontext
        transforms = types.SimpleNamespace(
            Compose=lambda _steps: lambda _image: FakeTensor(),
            Resize=lambda _size: object(),
            ToTensor=lambda: object(),
            Normalize=lambda _mean, _std: object(),
        )
        torchvision = types.ModuleType("torchvision")
        torchvision.transforms = transforms
        transformers = types.ModuleType("transformers")
        transformers.AutoModelForImageSegmentation = FakeAutoModel

        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.dict(
                    sys.modules,
                    {
                        "torch": torch,
                        "PIL": pil,
                        "torchvision": torchvision,
                        "transformers": transformers,
                    },
                ), \
                mock.patch.dict(
                    os.environ,
                    {"HF_MODULES_CACHE": str(Path(temp) / "poisoned-cache")},
                ):
            model_dir = Path(temp) / "verified-pack"
            outputs = list(
                bgremove._segment_birefnet(
                    [Path(temp) / "input.png"],
                    model_dir,
                    "cpu",
                ))

            self.assertEqual(1, len(outputs))
            self.assertEqual(str(model_dir), captured["path"])
            kwargs = captured["kwargs"]
            self.assertTrue(kwargs["local_files_only"])
            self.assertTrue(kwargs["use_safetensors"])
            self.assertTrue(kwargs["trust_remote_code"])
            self.assertNotEqual(
                str(Path(temp) / "poisoned-cache"),
                captured["cache_env"])
            self.assertEqual(captured["cache_env"], kwargs["cache_dir"])
            self.assertFalse(Path(captured["cache_env"]).exists())

    def test_frozen_build_includes_dynamic_model_and_cpu_runtime_dependencies(
            self) -> None:
        build_script = (
            ROOT / "tools" / "bgremove" / "build.ps1"
        ).read_text(encoding="utf-8")
        requirements = (
            ROOT / "tools" / "bgremove" / "requirements.txt"
        ).read_text(encoding="utf-8")

        self.assertIn("rembg[cpu]", requirements)
        for package in ("einops", "kornia", "timm"):
            with self.subTest(package=package):
                self.assertIn(f"--collect-all {package}", build_script)


if __name__ == "__main__":
    unittest.main()

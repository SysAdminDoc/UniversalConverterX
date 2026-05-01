"""Developer build / package-manifest sidecar.

Probe / convert build manifests and lockfiles across language ecosystems:

  * Maven `pom.xml` — Java
  * Gradle `build.gradle` / `build.gradle.kts`
  * npm `package.json` / `package-lock.json`
  * Yarn `yarn.lock` v1 (text) / v2 (YAML)
  * pnpm `pnpm-lock.yaml`
  * Cargo `Cargo.toml` / `Cargo.lock`
  * Composer `composer.json` / `composer.lock` — PHP
  * Bundler `Gemfile` / `Gemfile.lock` — Ruby
  * Go `go.mod` / `go.sum`
  * Pipfile / requirements.txt / pyproject.toml
  * NuGet `*.csproj` / `packages.config`
  * Bazel `BUILD` / `WORKSPACE`

Operations:
  manifest-info        Auto-detect manifest type and emit dependency list -> JSON.
  package-lock-csv     npm package-lock.json -> CSV (one row per dep).
  cargo-lock-csv       Cargo.lock -> CSV.
  composer-lock-csv    composer.lock -> CSV.
  go-sum-csv           go.sum -> CSV.
  pom-deps-csv         Maven pom.xml -> dependency CSV.
  csproj-pkgs-csv      .csproj PackageReferences -> CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str: return _NS_RE.sub("", tag)


# ── npm package-lock.json ─────────────────────────────────────────────

def op_package_lock_csv(args: argparse.Namespace) -> int:
    return _csv_from_json(args, _npm_lock_rows, "npm-package-lock",
                            ["name", "version", "resolved", "integrity",
                             "dev", "optional", "depth"])


def _npm_lock_rows(data: dict) -> list[dict]:
    rows: list[dict] = []
    pkgs = data.get("packages", {})
    if pkgs:
        for path, info in pkgs.items():
            if not path: continue
            depth = path.count("node_modules/")
            rows.append({
                "name": info.get("name", path.split("node_modules/")[-1]),
                "version": info.get("version", ""),
                "resolved": info.get("resolved", ""),
                "integrity": info.get("integrity", ""),
                "dev": info.get("dev", False),
                "optional": info.get("optional", False),
                "depth": depth,
            })
    else:
        # v1 format
        deps = data.get("dependencies", {})
        def _walk(d, depth):
            for name, info in d.items():
                rows.append({
                    "name": name,
                    "version": info.get("version", ""),
                    "resolved": info.get("resolved", ""),
                    "integrity": info.get("integrity", ""),
                    "dev": info.get("dev", False),
                    "optional": info.get("optional", False),
                    "depth": depth,
                })
                if "dependencies" in info: _walk(info["dependencies"],
                                                  depth + 1)
        _walk(deps, 0)
    return rows


# ── Cargo.lock ────────────────────────────────────────────────────────

def op_cargo_lock_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Cargo.lock not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for block in re.split(r"\n\[\[package\]\]\n", text):
            name_m = re.search(r'^name\s*=\s*"([^"]+)"', block, re.MULTILINE)
            ver_m = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
            src_m = re.search(r'^source\s*=\s*"([^"]+)"', block, re.MULTILINE)
            ck_m = re.search(r'^checksum\s*=\s*"([^"]+)"', block, re.MULTILINE)
            if name_m and ver_m:
                rows.append({
                    "name": name_m.group(1),
                    "version": ver_m.group(1),
                    "source": src_m.group(1) if src_m else "",
                    "checksum": ck_m.group(1) if ck_m else "",
                })
        out_path = out_dir / (src.stem + ".cargo.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["name", "version", "source",
                                                 "checksum"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("dev_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="cargo-lock", packages=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── composer.lock ─────────────────────────────────────────────────────

def op_composer_lock_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"composer.lock not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for pkg in data.get("packages", []):
            rows.append({
                "name": pkg.get("name", ""),
                "version": pkg.get("version", ""),
                "type": pkg.get("type", ""),
                "license": ", ".join(pkg.get("license", []) or []),
                "source_url": (pkg.get("source", {}) or {}).get("url", ""),
                "dev": False,
            })
        for pkg in data.get("packages-dev", []):
            rows.append({
                "name": pkg.get("name", ""),
                "version": pkg.get("version", ""),
                "type": pkg.get("type", ""),
                "license": ", ".join(pkg.get("license", []) or []),
                "source_url": (pkg.get("source", {}) or {}).get("url", ""),
                "dev": True,
            })
        out_path = out_dir / (src.stem + ".composer.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["name", "version", "type",
                                                 "license", "source_url",
                                                 "dev"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("dev_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="composer-lock", packages=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── go.sum ────────────────────────────────────────────────────────────

def op_go_sum_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"go.sum not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) < 3: continue
            module, version, hash_ = parts[0], parts[1], parts[2]
            rows.append({
                "module": module,
                "version": version,
                "hash": hash_,
                "is_mod": "/go.mod" in version,
            })
        out_path = out_dir / (src.stem + ".gosum.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["module", "version", "hash",
                                                 "is_mod"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("dev_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="go-sum", entries=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Maven pom.xml deps ────────────────────────────────────────────────

def op_pom_deps_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"pom.xml not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for dep in root.iter():
            if _strip_ns(dep.tag) != "dependency": continue
            d: dict[str, str] = {}
            for c in dep:
                d[_strip_ns(c.tag)] = (c.text or "").strip()
            rows.append({
                "groupId": d.get("groupId", ""),
                "artifactId": d.get("artifactId", ""),
                "version": d.get("version", ""),
                "scope": d.get("scope", "compile"),
                "type": d.get("type", "jar"),
            })
        out_path = out_dir / (src.stem + ".pom.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["groupId", "artifactId",
                                                 "version", "scope", "type"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("dev_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="maven-pom", dependencies=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── .csproj PackageReferences ─────────────────────────────────────────

def op_csproj_pkgs_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".csproj not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[dict] = []
        for pr in root.iter("PackageReference"):
            rows.append({
                "include": pr.get("Include", ""),
                "version": pr.get("Version", ""),
            })
        out_path = out_dir / (src.stem + ".csproj.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["include", "version"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("dev_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="csproj", packages=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Auto-detect manifest -> JSON ──────────────────────────────────────

def op_manifest_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"manifest(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        kind = src.name.lower()
        info: dict = {"file": str(src), "size_bytes": src.stat().st_size,
                       "kind": "unknown"}
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            if kind == "package.json" or kind.endswith(".package.json"):
                info["kind"] = "npm"
                data = json.loads(text)
                info["name"] = data.get("name", "")
                info["version"] = data.get("version", "")
                info["dependencies"] = list(data.get("dependencies", {}))
                info["dev_dependencies"] = list(data.get("devDependencies", {}))
            elif kind == "package-lock.json":
                info["kind"] = "npm-lock"
                data = json.loads(text)
                info["packages"] = len(data.get("packages", {}))
            elif kind == "cargo.toml":
                info["kind"] = "cargo"
                m = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
                v = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
                info["name"] = m.group(1) if m else ""
                info["version"] = v.group(1) if v else ""
            elif kind == "go.mod":
                info["kind"] = "go-mod"
                m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
                go_v = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
                info["module"] = m.group(1) if m else ""
                info["go_version"] = go_v.group(1) if go_v else ""
                info["require_count"] = text.count("\nrequire ") + text.count(
                    "\nrequire (")
            elif kind == "pom.xml":
                info["kind"] = "maven"
                tree = ET.fromstring(text)
                gid = next((c.text for c in tree if _strip_ns(c.tag) == "groupId"),
                            "")
                aid = next((c.text for c in tree if _strip_ns(c.tag) == "artifactId"),
                            "")
                info["groupId"] = gid or ""
                info["artifactId"] = aid or ""
            elif kind == "composer.json":
                info["kind"] = "composer"
                data = json.loads(text)
                info["name"] = data.get("name", "")
                info["require"] = list((data.get("require") or {}).keys())
            elif kind == "gemfile" or kind == "gemfile.lock":
                info["kind"] = "bundler"
                info["gem_lines"] = sum(1 for ln in text.splitlines()
                                          if ln.strip().startswith("gem "))
            elif kind == "pipfile" or kind == "pyproject.toml":
                info["kind"] = "python"
            elif kind == "build.gradle" or kind == "build.gradle.kts":
                info["kind"] = "gradle"
                info["dependency_lines"] = text.count("implementation ") + \
                                            text.count("compile ") + \
                                            text.count("api ")
        except Exception as ex:
            info["error"] = str(ex)
        probes.append(info)
        emit("dev_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source=info["kind"])
    out_path = out_dir / "manifest-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def _csv_from_json(args, row_fn, source: str, keys: list[str]) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"{source} file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            rows = row_fn(data)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + source.split("-")[0] + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("dev_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source=source, packages=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="devbuild-sidecar",
                                description="Developer build / package manifest probes.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("manifest-info",     "Auto-detect manifest -> JSON"),
        ("package-lock-csv",  "npm package-lock.json -> CSV"),
        ("cargo-lock-csv",    "Cargo.lock -> CSV"),
        ("composer-lock-csv", "composer.lock -> CSV"),
        ("go-sum-csv",        "go.sum -> CSV"),
        ("pom-deps-csv",      "Maven pom.xml -> dependency CSV"),
        ("csproj-pkgs-csv",   ".csproj PackageReferences -> CSV"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "manifest-info":     return op_manifest_info(args)
        if args.op == "package-lock-csv":  return op_package_lock_csv(args)
        if args.op == "cargo-lock-csv":    return op_cargo_lock_csv(args)
        if args.op == "composer-lock-csv": return op_composer_lock_csv(args)
        if args.op == "go-sum-csv":        return op_go_sum_csv(args)
        if args.op == "pom-deps-csv":      return op_pom_deps_csv(args)
        if args.op == "csproj-pkgs-csv":   return op_csproj_pkgs_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

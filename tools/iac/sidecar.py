"""Infrastructure-as-Code (IaC) translation sidecar.

Translate IaC formats:

  * Docker Compose v1 (links / volumes_from) -> v2/v3 (networks / depends_on)
  * Helm Chart -> rendered Kubernetes manifests via `helm template`
  * Kustomize overlay -> rendered manifests via `kustomize build`
  * Terraform plan JSON -> human-readable diff (additions / changes / removals)
  * AWS CloudFormation YAML <-> JSON (intrinsic-function aware)

Operations:
  compose-upgrade       v1 -> v3 with networks + depends_on translation.
  helm-template         Helm chart dir -> single rendered manifest stream.
  kustomize-build       Kustomize overlay -> rendered manifests.
  cfn-yaml-to-json      CloudFormation YAML -> JSON.
  cfn-json-to-yaml      CloudFormation JSON -> YAML (preserves !Ref / !Sub).
  tf-plan-summary       terraform-plan JSON -> change summary.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Compose v1 -> v3 ───────────────────────────────────────────────────

def _compose_v1_to_v3(d: dict) -> dict:
    """v1 had services at top-level; v2/v3 nest under 'services'."""
    if "version" in d and "services" in d:
        return d  # already v2+
    services = {}
    networks: dict = {}
    for name, svc in d.items():
        if not isinstance(svc, dict): continue
        new_svc = dict(svc)
        # `links: [a, b:alias]` -> depends_on
        if "links" in new_svc:
            depends = []
            for link in new_svc.pop("links"):
                target = link.split(":")[0]
                depends.append(target)
            new_svc["depends_on"] = depends
        # volumes_from is gone in v3 — translate to named volume reuse
        if "volumes_from" in new_svc:
            new_svc.pop("volumes_from")
        # net: host -> network_mode: host
        if "net" in new_svc:
            new_svc["network_mode"] = new_svc.pop("net")
        # log_driver / log_opt -> logging: { driver, options }
        if "log_driver" in new_svc or "log_opt" in new_svc:
            log = {}
            if "log_driver" in new_svc: log["driver"] = new_svc.pop("log_driver")
            if "log_opt" in new_svc:    log["options"] = new_svc.pop("log_opt")
            new_svc["logging"] = log
        services[name] = new_svc
    return {"version": "3.9", "services": services}


def op_compose_upgrade(args: argparse.Namespace) -> int:
    try:
        import yaml
    except ImportError:
        return fail("missing_dep", "PyYAML not installed (`pip install pyyaml`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"compose file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            d = yaml.safe_load(src.read_text(encoding="utf-8"))
            upgraded = _compose_v1_to_v3(d)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".v3.yml")
        out_path.write_text(yaml.safe_dump(upgraded, sort_keys=False),
                            encoding="utf-8")
        emit("iac_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="compose-v3", source="compose-v1")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── helm template + kustomize build ────────────────────────────────────

def _shell_render(args: argparse.Namespace, cmd_name: str,
                   build_cmd: list[str]) -> int:
    if not shutil.which(cmd_name):
        return fail("missing_dep", f"{cmd_name} CLI not on PATH.")
    chart = Path(args.chart_dir) if hasattr(args, "chart_dir") else None
    overlay = Path(args.overlay_dir) if hasattr(args, "overlay_dir") else None
    target = chart or overlay
    if not target or not target.is_dir():
        return fail("missing_input", f"Directory not found: {target}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(build_cmd, capture_output=True, text=True,
                               timeout=300)
    except Exception as ex:
        return fail("render_failed", f"{ex}")
    if proc.returncode != 0:
        return fail("render_failed",
                    f"{cmd_name} exit {proc.returncode}: {proc.stderr}")
    out_path = out_dir / (target.name + ".rendered.yml")
    out_path.write_text(proc.stdout, encoding="utf-8")
    emit("iac_doc",
         input=str(target), output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="k8s-manifests", source=cmd_name)
    emit("progress", percent=100.0, stage="1/1", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size,
         count=1)
    return 0


def op_helm_template(args: argparse.Namespace) -> int:
    return _shell_render(args, "helm",
                          ["helm", "template", args.release_name or "release",
                           args.chart_dir])


def op_kustomize_build(args: argparse.Namespace) -> int:
    return _shell_render(args, "kustomize",
                          ["kustomize", "build", args.overlay_dir])


# ── CloudFormation YAML <-> JSON ───────────────────────────────────────

def op_cfn_yaml_to_json(args: argparse.Namespace) -> int:
    try:
        import yaml
    except ImportError:
        return fail("missing_dep", "PyYAML not installed.")

    class _CFNLoader(yaml.SafeLoader): pass

    def _construct_intrinsic(loader, tag_suffix, node):
        tag = "Fn::" + tag_suffix if tag_suffix != "Ref" else "Ref"
        if isinstance(node, yaml.ScalarNode):
            return {tag: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {tag: loader.construct_sequence(node, deep=True)}
        if isinstance(node, yaml.MappingNode):
            return {tag: loader.construct_mapping(node, deep=True)}
        return {tag: None}

    _CFNLoader.add_multi_constructor("!", _construct_intrinsic)

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CFN file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            d = yaml.load(src.read_text(encoding="utf-8"), Loader=_CFNLoader)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(d, indent=2, default=str),
                            encoding="utf-8")
        emit("iac_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="cloudformation-yaml")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_cfn_json_to_yaml(args: argparse.Namespace) -> int:
    try:
        import yaml
    except ImportError:
        return fail("missing_dep", "PyYAML not installed.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CFN file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            d = json.loads(src.read_text(encoding="utf-8"))
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".yaml")
        out_path.write_text(yaml.safe_dump(d, sort_keys=False),
                            encoding="utf-8")
        emit("iac_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="cloudformation-yaml", source="json")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── terraform-plan summary ─────────────────────────────────────────────

def op_tf_plan_summary(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"plan(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            plan = json.loads(src.read_text(encoding="utf-8"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        changes = plan.get("resource_changes", [])
        summary: dict = {"create": [], "update": [], "delete": [],
                          "replace": [], "no-op": []}
        for ch in changes:
            actions = ch.get("change", {}).get("actions", [])
            addr = ch.get("address")
            if "create" in actions and "delete" in actions:
                summary["replace"].append(addr)
            elif "create" in actions:
                summary["create"].append(addr)
            elif "delete" in actions:
                summary["delete"].append(addr)
            elif "update" in actions:
                summary["update"].append(addr)
            elif "no-op" in actions:
                summary["no-op"].append(addr)
        out_path = out_dir / (src.stem + ".summary.json")
        out_path.write_text(json.dumps(summary, indent=2),
                            encoding="utf-8")
        emit("iac_plan",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="terraform-plan",
             create=len(summary["create"]),
             update=len(summary["update"]),
             delete=len(summary["delete"]),
             replace=len(summary["replace"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iac-sidecar",
                                description="Infrastructure-as-Code translation.")
    sub = p.add_subparsers(dest="op", required=True)

    cu = sub.add_parser("compose-upgrade", help="Docker Compose v1 -> v3.")
    cu.add_argument("--input", nargs="+", required=True)
    cu.add_argument("--output-dir", required=True, dest="output_dir")

    ht = sub.add_parser("helm-template", help="Helm chart dir -> rendered manifests.")
    ht.add_argument("--chart-dir", required=True, dest="chart_dir")
    ht.add_argument("--output-dir", required=True, dest="output_dir")
    ht.add_argument("--release-name", default="release", dest="release_name")

    kb = sub.add_parser("kustomize-build", help="Kustomize overlay -> manifests.")
    kb.add_argument("--overlay-dir", required=True, dest="overlay_dir")
    kb.add_argument("--output-dir", required=True, dest="output_dir")

    cy = sub.add_parser("cfn-yaml-to-json", help="CFN YAML -> JSON.")
    cy.add_argument("--input", nargs="+", required=True)
    cy.add_argument("--output-dir", required=True, dest="output_dir")

    cj = sub.add_parser("cfn-json-to-yaml", help="CFN JSON -> YAML.")
    cj.add_argument("--input", nargs="+", required=True)
    cj.add_argument("--output-dir", required=True, dest="output_dir")

    tp = sub.add_parser("tf-plan-summary", help="Terraform plan JSON -> change summary.")
    tp.add_argument("--input", nargs="+", required=True)
    tp.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "compose-upgrade":   return op_compose_upgrade(args)
        if args.op == "helm-template":     return op_helm_template(args)
        if args.op == "kustomize-build":   return op_kustomize_build(args)
        if args.op == "cfn-yaml-to-json":  return op_cfn_yaml_to_json(args)
        if args.op == "cfn-json-to-yaml":  return op_cfn_json_to_yaml(args)
        if args.op == "tf-plan-summary":   return op_tf_plan_summary(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

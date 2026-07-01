"""Configuration-file conversion sidecar.

The `datakit` sidecar covers JSON / YAML / TOML / XML / CSV. This one
adds the configuration-file dialects that DevOps engineers juggle:

  * HCL  (HashiCorp / Terraform)              .tf, .hcl
  * HOCON (Typesafe Config)                    .conf
  * Java .properties                           .properties
  * INI                                        .ini, .cfg
  * systemd unit                               .service, .timer
  * Docker Compose                             docker-compose.yml
  * Kubernetes / Helm values                   values.yaml

All round-trip through a normalized JSON middle representation.
"""
from __future__ import annotations

import argparse
import configparser
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import sys
import time
from pathlib import Path


def emit(event: str, **fields_) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields_}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Readers ────────────────────────────────────────────────────────────

def read_hcl(path: Path) -> dict:
    try:
        import hcl2
    except ImportError as ex:
        raise RuntimeError(f"python-hcl2 not installed: {ex}. `pip install python-hcl2`.") from ex
    with path.open("r", encoding="utf-8") as f:
        return hcl2.load(f)


def read_hocon(path: Path) -> dict:
    try:
        from pyhocon import ConfigFactory
    except ImportError as ex:
        raise RuntimeError(f"pyhocon not installed: {ex}. `pip install pyhocon`.") from ex
    return ConfigFactory.parse_file(str(path)).as_plain_ordered_dict()


def read_properties(path: Path) -> dict:
    try:
        from jproperties import Properties
    except ImportError as ex:
        raise RuntimeError(f"jproperties not installed: {ex}.") from ex
    p = Properties()
    with path.open("rb") as f: p.load(f, "utf-8")
    return {k: v.data for k, v in p.items()}


def read_ini(path: Path) -> dict:
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.read(str(path), encoding="utf-8")
    out: dict = {}
    if cfg.defaults():
        out["DEFAULT"] = dict(cfg.defaults())
    for section in cfg.sections():
        out[section] = dict(cfg.items(section))
    return out


def read_systemd(path: Path) -> dict:
    """systemd units are case-sensitive INI; preserve casing."""
    cfg = configparser.RawConfigParser(strict=False)
    cfg.optionxform = str   # don't lowercase keys
    cfg.read(str(path), encoding="utf-8")
    return {section: dict(cfg.items(section)) for section in cfg.sections()}


READERS = {
    ".hcl": read_hcl, ".tf": read_hcl, ".tfvars": read_hcl,
    ".conf": read_hocon, ".hocon": read_hocon,
    ".properties": read_properties,
    ".ini": read_ini, ".cfg": read_ini,
    ".service": read_systemd, ".timer": read_systemd,
    ".socket": read_systemd, ".target": read_systemd,
    ".mount": read_systemd, ".automount": read_systemd,
    ".path": read_systemd, ".swap": read_systemd,
}


# ── Writers ────────────────────────────────────────────────────────────

def write_json(obj: dict, path: Path) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")


def write_yaml(obj: dict, path: Path) -> None:
    import yaml
    path.write_text(yaml.safe_dump(obj, allow_unicode=True), encoding="utf-8")


def write_toml(obj: dict, path: Path) -> None:
    import tomli_w
    path.write_bytes(tomli_w.dumps(obj).encode("utf-8"))


def write_properties(obj: dict, path: Path) -> None:
    """Flat key=value Java properties, with dotted paths for nesting."""
    flat: dict[str, str] = {}
    def walk(prefix: str, node):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        else:
            flat[prefix] = str(node)
    walk("", obj)
    with path.open("w", encoding="utf-8") as f:
        for k, v in flat.items():
            f.write(f"{k}={v}\n")


def write_ini(obj: dict, path: Path) -> None:
    cfg = configparser.ConfigParser(interpolation=None)
    if "DEFAULT" in obj and isinstance(obj["DEFAULT"], dict):
        for k, v in obj["DEFAULT"].items(): cfg.defaults()[k] = str(v)
    for section, items in obj.items():
        if section == "DEFAULT": continue
        if not isinstance(items, dict):
            cfg["__root__"] = {str(section): str(items)}
            continue
        cfg[section] = {k: str(v) for k, v in items.items()}
    with path.open("w", encoding="utf-8") as f:
        cfg.write(f)


def write_systemd(obj: dict, path: Path) -> None:
    cfg = configparser.RawConfigParser(strict=False)
    cfg.optionxform = str
    for section, items in obj.items():
        if not isinstance(items, dict): continue
        cfg[section] = {k: str(v) for k, v in items.items()}
    with path.open("w", encoding="utf-8") as f:
        cfg.write(f)


WRITERS = {
    "json": write_json,
    "yaml": write_yaml, "yml": write_yaml,
    "toml": write_toml,
    "properties": write_properties,
    "ini":  write_ini, "cfg": write_ini,
    "systemd": write_systemd,
}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Config file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in WRITERS:
        return fail("bad_target", f"Choose: {sorted(WRITERS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="config", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        reader = READERS.get(ext)
        if not reader:
            # Fall back to JSON / YAML / TOML if the user passed one of those.
            if ext == ".json":
                obj = json.loads(src.read_text(encoding="utf-8"))
            elif ext in (".yaml", ".yml"):
                import yaml
                obj = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
            elif ext == ".toml":
                import tomllib
                obj = tomllib.loads(src.read_text(encoding="utf-8"))
            else:
                return fail("bad_format", f"Unsupported source ext '{ext}'.")
        else:
            try:
                obj = reader(src)
            except Exception as ex:
                return fail("read_failed", f"{src.name}: {ex}")

        out_path = out_dir / (src.stem + "." + target)
        try:
            WRITERS[target](obj, out_path)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("write_failed", f"{src.name}: {ex}")

        emit("config_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, source_ext=src.suffix.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="config-sidecar",
                                description="DevOps configuration format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert HCL / HOCON / properties / INI / systemd / JSON / YAML / TOML.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="json | yaml | toml | properties | ini | systemd")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())

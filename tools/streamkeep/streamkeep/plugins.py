"""Plugin / Extension SDK — load community plugins from a directory (F77).

Plugins are Python packages or modules in ``%APPDATA%/StreamKeep/plugins/``
(or ``data/plugins/`` in portable mode). Each plugin declares metadata in
a ``plugin.json`` manifest:

    {
        "id": "my-extractor",
        "name": "My Custom Extractor",
        "version": "1.0.0",
        "author": "User",
        "description": "Adds support for example.com",
        "enabled": true
    }

Plugin types (detected by what the module imports/subclasses):
  - Custom extractors: subclass ``streamkeep.extractors.base.Extractor``
  - Post-processing filters: hook into PostProcessor pipeline
  - Upload destinations: subclass ``streamkeep.upload.base.UploadDestination``

Plugins run in the same process — no sandbox. Trust-based, like yt-dlp.
"""

import importlib.util
import json
import os
import sys

from .paths import CONFIG_DIR

PLUGINS_DIR = CONFIG_DIR / "plugins"


def _ensure_dir():
    """Create the plugins directory if it doesn't exist."""
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)


def discover_plugins():
    """Scan the plugins directory and return metadata for each plugin.

    Returns list of dicts: ``[{id, name, version, author, description,
    enabled, path, error}, ...]``
    """
    _ensure_dir()
    plugins = []
    for entry in sorted(os.listdir(str(PLUGINS_DIR))):
        plugin_path = PLUGINS_DIR / entry
        manifest_path = plugin_path / "plugin.json"

        # Must be a directory with plugin.json
        if not plugin_path.is_dir() or not manifest_path.is_file():
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            plugins.append({
                "id": entry, "name": entry, "version": "?",
                "author": "", "description": "",
                "enabled": False, "path": str(plugin_path),
                "error": f"Invalid plugin.json: {e}",
            })
            continue

        plugins.append({
            "id": meta.get("id", entry),
            "name": meta.get("name", entry),
            "version": meta.get("version", "0.0.0"),
            "author": meta.get("author", ""),
            "description": meta.get("description", ""),
            "enabled": bool(meta.get("enabled", True)),
            "path": str(plugin_path),
            "error": "",
        })

    return plugins


def load_plugin(plugin_info, log_fn=None):
    """Load a single plugin by importing its Python module.

    Returns True on success, False on error.
    """
    if not plugin_info.get("enabled", True):
        return False

    plugin_path = plugin_info.get("path", "")
    plugin_id = plugin_info.get("id", "unknown")
    if not plugin_path or not os.path.isdir(plugin_path):
        return False

    # Add the plugin's parent to sys.path at the end so we don't let
    # community plugins shadow app or stdlib modules process-wide.
    parent = os.path.dirname(plugin_path)
    if parent not in sys.path:
        sys.path.append(parent)

    module_name = os.path.basename(plugin_path)
    try:
        # Try loading as a package (has __init__.py)
        init_py = os.path.join(plugin_path, "__init__.py")
        if os.path.isfile(init_py):
            spec = importlib.util.spec_from_file_location(
                f"sk_plugin_{module_name}", init_py,
                submodule_search_locations=[plugin_path],
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                if log_fn:
                    log_fn(f"[PLUGIN] Loaded: {plugin_id} v{plugin_info.get('version', '?')}")
                return True

        # Try loading a single .py file
        for fname in os.listdir(plugin_path):
            if fname.endswith(".py") and fname != "__init__.py":
                fpath = os.path.join(plugin_path, fname)
                spec = importlib.util.spec_from_file_location(
                    f"sk_plugin_{module_name}_{fname[:-3]}", fpath,
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = mod
                    spec.loader.exec_module(mod)
                    if log_fn:
                        log_fn(f"[PLUGIN] Loaded: {plugin_id} ({fname})")
                    return True

    except Exception as e:
        plugin_info["error"] = str(e)
        if log_fn:
            log_fn(f"[PLUGIN] Error loading {plugin_id}: {e}")

    return False


def load_all_plugins(log_fn=None):
    """Discover and load all enabled plugins.

    Returns ``(loaded_count, error_count)``.
    """
    plugins = discover_plugins()
    loaded = 0
    errors = 0
    for p in plugins:
        if not p.get("enabled", True):
            continue
        if load_plugin(p, log_fn):
            loaded += 1
        elif p.get("error"):
            errors += 1
    if log_fn and (loaded or errors):
        log_fn(f"[PLUGIN] {loaded} loaded, {errors} error(s)")
    return loaded, errors


def set_plugin_enabled(plugin_id, enabled):
    """Update a plugin's enabled state in its manifest."""
    _ensure_dir()
    for entry in os.listdir(str(PLUGINS_DIR)):
        plugin_path = PLUGINS_DIR / entry
        manifest_path = plugin_path / "plugin.json"
        if not manifest_path.is_file():
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("id", entry) == plugin_id:
                meta["enabled"] = bool(enabled)
                tmp_path = manifest_path.with_suffix(".json.tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                os.replace(tmp_path, manifest_path)
                return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def plugins_dir_path():
    """Return the plugins directory path (for 'Open folder' button)."""
    _ensure_dir()
    return str(PLUGINS_DIR)

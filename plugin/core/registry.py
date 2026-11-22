"""Centralized storage resolution and module contract registry for Gravity Core."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Optional, Sequence

MODULE_SCHEMA_VERSION = 1
GRAVITY_HOME_ENV = "GRAVITY_HOME"
MODULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

LEGACY_HOME_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("gravity-bridge", "bridge", (".gemini", "gravity-bridge")),
    ("gravity-metrics", "metrics", (".gemini", "gravity-metrics")),
    ("gravity-workflow", "workflow", (".gemini", "gravity-workflow")),
    ("gravity", "workflow", (".gravity",)),
)


def resolve_gravity_home(home: Optional[Path] = None) -> Path:
    """Resolve the Gravity unified home directory (arg > $GRAVITY_HOME > ~/.gemini/gravity)."""
    if home is not None:
        return Path(home).expanduser().resolve()
    env_home = os.environ.get(GRAVITY_HOME_ENV, "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    return (Path.home() / ".gemini" / "gravity").resolve()


def resolve_module_home(
    module_id: str,
    *,
    env_override: Optional[str] = None,
    gravity_home: Optional[Path] = None,
) -> Path:
    """Resolve a module storage directory ($env_override > <gravity_home>/<module_id>)."""
    if not isinstance(module_id, str) or not MODULE_ID_RE.match(module_id):
        raise ValueError(f"Invalid module_id {module_id!r}: must match {MODULE_ID_RE.pattern}")
    if env_override:
        override_val = os.environ.get(env_override, "").strip()
        if override_val:
            return Path(override_val).expanduser().resolve()
    return (resolve_gravity_home(gravity_home) / module_id).resolve()


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_str_list(value: Any, field_name: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"'{field_name}' must be a list of non-empty strings.")
        return
    for idx, item in enumerate(value):
        if not _is_non_empty_str(item):
            errors.append(f"'{field_name}[{idx}]' must be a non-empty string.")


def validate_module_contract(data: Any) -> list[str]:
    """Validate a config/module.json payload against module contract v1."""
    if not isinstance(data, dict):
        return ["module.json must be a JSON object."]

    errors: list[str] = []
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != MODULE_SCHEMA_VERSION:
        errors.append(f"'schema_version' must equal {MODULE_SCHEMA_VERSION}.")

    mod_id = data.get("id")
    if not isinstance(mod_id, str) or not MODULE_ID_RE.match(mod_id):
        errors.append(f"'id' must be a valid slug matching {MODULE_ID_RE.pattern}.")

    for field in ("plugin_name", "role"):
        if not _is_non_empty_str(data.get(field)):
            errors.append(f"'{field}' must be a non-empty string.")

    storage = data.get("storage")
    if not isinstance(storage, dict):
        errors.append("'storage' must be a JSON object.")
    else:
        subdir = storage.get("subdir")
        if not isinstance(subdir, str) or not MODULE_ID_RE.match(subdir):
            errors.append(f"'storage.subdir' must match {MODULE_ID_RE.pattern}.")
        if not _is_non_empty_str(storage.get("env_override")):
            errors.append("'storage.env_override' must be a non-empty string.")

    _validate_str_list(data.get("commands"), "commands", errors)
    _validate_str_list(data.get("capabilities"), "capabilities", errors)

    ui = data.get("ui")
    if not isinstance(ui, dict):
        errors.append("'ui' must be a JSON object.")
    else:
        if not _is_non_empty_str(ui.get("mode")):
            errors.append("'ui.mode' must be a non-empty string.")
        if not _is_non_empty_str(ui.get("target")):
            errors.append("'ui.target' must be a non-empty string.")

    signals = data.get("signals")
    if not isinstance(signals, dict):
        errors.append("'signals' must be a JSON object.")
    else:
        _validate_str_list(signals.get("produces"), "signals.produces", errors)
        _validate_str_list(signals.get("consumes"), "signals.consumes", errors)

    return errors


def default_plugin_roots() -> list[Path]:
    """Return the default Antigravity plugin search roots."""
    return [(Path.home() / ".gemini" / "config" / "plugins").resolve()]


def _read_json_object(path: Path, label: str) -> tuple[Optional[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, [f"Failed to read {label}: {exc}"]

    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append(f"{label} must not contain a UTF-8 BOM.")
        raw = raw[3:]

    try:
        text = raw.decode("utf-8")
        parsed = json.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        errors.append(f"Invalid JSON in {label}: {exc}")
        return None, errors

    if not isinstance(parsed, dict):
        errors.append(f"{label} must contain a JSON object.")
        return None, errors

    return parsed, errors


def _inspect_plugin_module(entry: Path) -> dict[str, Any]:
    module_path = entry / "config" / "module.json"
    manifest_path = entry / "plugin.json"

    mod_data, mod_errors = _read_json_object(module_path, "config/module.json")
    errors = list(mod_errors)
    if mod_data is not None:
        errors.extend(validate_module_contract(mod_data))

    manifest_data: Optional[dict[str, Any]] = None
    if not manifest_path.is_file():
        errors.append("Missing plugin.json.")
    else:
        manifest_data, man_errors = _read_json_object(manifest_path, "plugin.json")
        errors.extend(man_errors)
        if manifest_data is not None and mod_data is not None:
            expected_plugin = mod_data.get("plugin_name")
            actual_plugin = manifest_data.get("name")
            if _is_non_empty_str(expected_plugin) and actual_plugin != expected_plugin:
                errors.append(
                    f"plugin.json name {actual_plugin!r} does not match module.json plugin_name {expected_plugin!r}."
                )

    mod_id = (
        mod_data["id"]
        if mod_data is not None and isinstance(mod_data.get("id"), str) and mod_data["id"].strip()
        else entry.name
    )
    plugin_name = (
        mod_data["plugin_name"]
        if mod_data is not None and _is_non_empty_str(mod_data.get("plugin_name"))
        else (
            manifest_data["name"]
            if manifest_data is not None and _is_non_empty_str(manifest_data.get("name"))
            else entry.name
        )
    )

    return {
        "id": mod_id,
        "plugin_name": plugin_name,
        "display_name": manifest_data.get("displayName") if manifest_data else None,
        "version": manifest_data.get("version") if manifest_data else None,
        "schema_version": mod_data.get("schema_version") if mod_data else None,
        "role": mod_data.get("role") if mod_data and isinstance(mod_data.get("role"), str) else "",
        "storage": mod_data.get("storage") if mod_data and isinstance(mod_data.get("storage"), dict) else {},
        "commands": mod_data.get("commands") if mod_data and isinstance(mod_data.get("commands"), list) else [],
        "capabilities": (
            mod_data.get("capabilities")
            if mod_data and isinstance(mod_data.get("capabilities"), list)
            else []
        ),
        "ui": mod_data.get("ui") if mod_data and isinstance(mod_data.get("ui"), dict) else {},
        "signals": mod_data.get("signals") if mod_data and isinstance(mod_data.get("signals"), dict) else {},
        "plugin_dir": str(entry),
        "module_path": str(module_path),
        "manifest_path": str(manifest_path) if manifest_path.is_file() else None,
        "valid": len(errors) == 0,
        "errors": errors,
    }


def discover_modules(plugin_roots: Optional[Sequence[Path]] = None) -> list[dict[str, Any]]:
    """Scan plugin directories for config/module.json + plugin.json, sorted by id."""
    if plugin_roots is None:
        roots = default_plugin_roots()
    elif isinstance(plugin_roots, (str, Path)):
        roots = [Path(plugin_roots)]
    else:
        roots = [Path(p) for p in plugin_roots]

    seen_dirs: set[Path] = set()
    modules: list[dict[str, Any]] = []

    for root in roots:
        resolved_root = root.expanduser().resolve()
        if not resolved_root.is_dir():
            continue
        try:
            children = sorted(resolved_root.iterdir(), key=lambda p: p.name)
        except OSError:
            continue

        for entry in children:
            if not entry.is_dir():
                continue
            resolved_entry = entry.resolve()
            if resolved_entry in seen_dirs:
                continue
            module_path = resolved_entry / "config" / "module.json"
            if not module_path.exists() and not module_path.is_symlink():
                continue
            seen_dirs.add(resolved_entry)
            modules.append(_inspect_plugin_module(resolved_entry))

    modules.sort(key=lambda item: (str(item["id"]), str(item["plugin_name"]), str(item["plugin_dir"])))
    return modules


def detect_legacy_homes(home_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    """Detect legacy Gravity home directories read-only without modifying or deleting anything."""
    base_home = (
        Path.home().expanduser().resolve()
        if home_dir is None
        else Path(home_dir).expanduser().resolve()
    )
    detected: list[dict[str, Any]] = []
    for name, target_module, rel_parts in LEGACY_HOME_SPECS:
        candidate = base_home.joinpath(*rel_parts)
        if candidate.exists() or candidate.is_symlink():
            detected.append(
                {
                    "name": name,
                    "target_module": target_module,
                    "path": str(candidate),
                    "is_dir": candidate.is_dir(),
                }
            )
    detected.sort(key=lambda item: item["path"])
    return detected


def write_modules_registry(gravity_home: Path, modules: Sequence[dict[str, Any]]) -> Path:
    """Atomically write <gravity_home>/core/modules.json as UTF-8 without BOM and LF endings."""
    base = Path(gravity_home).expanduser().resolve()
    core_dir = base / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    registry_path = core_dir / "modules.json"

    payload = {
        "schema_version": MODULE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gravity_home": str(base),
        "module_count": len(modules),
        "modules": list(modules),
    }
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(core_dir),
            prefix=".modules-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(registry_path))
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    return registry_path

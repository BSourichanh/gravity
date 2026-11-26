"""Centralized storage resolution and module contract registry for Gravity Core."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Optional, Sequence

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.atomic_io import write_json_atomic  # noqa: E402
from _shared.path_safety import ensure_safe_dir, is_symlink_or_junction, safe_home_dir  # noqa: E402
from _shared.validator_core import Report, validate_module_contract as _vc_validate_module_contract  # noqa: E402

MODULE_SCHEMA_VERSION = 1
GRAVITY_HOME_ENV = "GRAVITY_HOME"
MODULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

LEGACY_HOME_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
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
    return (safe_home_dir() / ".gemini" / "gravity").resolve()


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


def validate_module_contract(data: Any) -> list[str]:
    """Validate a config/module.json payload against module contract v1 (including SPI-1..3)."""
    if not isinstance(data, dict):
        return ["module.json must be a JSON object."]
    report = Report()
    _vc_validate_module_contract(data, report)
    return list(report.errors)


def default_plugin_roots() -> list[Path]:
    """Return the default Antigravity plugin search roots."""
    return [(safe_home_dir() / ".gemini" / "config" / "plugins").resolve()]


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

    record: dict[str, Any] = {
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
    if mod_data is not None:
        if isinstance(mod_data.get("dashboard"), dict):
            record["dashboard"] = mod_data["dashboard"]
        if isinstance(mod_data.get("capture_policy"), dict):
            record["capture_policy"] = mod_data["capture_policy"]
    return record


def enrich_module_homes(
    modules: Sequence[dict[str, Any]],
    gravity_home: Path,
) -> list[dict[str, Any]]:
    """Attach resolved_home to each valid module record without writing to disk."""
    enriched: list[dict[str, Any]] = []
    for mod in modules:
        item = dict(mod)
        storage = mod.get("storage") or {}
        subdir = storage.get("subdir")
        env_override = storage.get("env_override")
        if mod.get("valid") and isinstance(subdir, str) and subdir:
            try:
                resolved = resolve_module_home(
                    subdir,
                    env_override=env_override if isinstance(env_override, str) else None,
                    gravity_home=gravity_home,
                )
                item["resolved_home"] = str(resolved)
            except ValueError as exc:
                item["valid"] = False
                item["errors"] = [*item.get("errors", []), str(exc)]
                item["resolved_home"] = None
        else:
            item["resolved_home"] = None
        enriched.append(item)
    return enriched


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
        safe_home_dir().expanduser().resolve()
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
    raw_base = Path(gravity_home).expanduser()
    if is_symlink_or_junction(raw_base):
        raise ValueError(f"Refusing symlink or junction gravity_home: {raw_base}")
    base = raw_base.resolve()
    core_dir = base / "core"
    if is_symlink_or_junction(core_dir):
        raise ValueError(f"Refusing symlink or junction core directory: {core_dir}")
    ensure_safe_dir(core_dir)
    registry_path = core_dir / "modules.json"
    if is_symlink_or_junction(registry_path):
        raise ValueError(f"Refusing symlink or junction registry file: {registry_path}")

    payload = {
        "schema_version": MODULE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gravity_home": str(base),
        "module_count": len(modules),
        "modules": list(modules),
    }
    return write_json_atomic(registry_path, payload, indent=2, ensure_ascii=False)

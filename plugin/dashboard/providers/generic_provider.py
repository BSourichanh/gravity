"""Read-only generic OCP module provider for the Gravity dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Sequence

from _shared.path_safety import is_symlink_or_junction
from core.registry import MODULE_ID_RE, discover_modules, resolve_gravity_home, resolve_module_home
from dashboard.providers import load_modules_snapshot_ro, normalize_plugin_roots, resolve_provider_kind
from dashboard.providers.spi import extract_module_spi_metadata, invoke_dashboard_provider

MAX_TOP_ENTRIES = 25


def _list_top_entries_ro(storage_dir: Optional[Path]) -> tuple[list[dict[str, Any]], bool]:
    """Return up to 25 shallow entries in `storage_dir` without following symlinks or reading contents."""
    if storage_dir is None or not storage_dir.is_dir():
        return [], False

    try:
        with os.scandir(storage_dir) as handle:
            dir_entries = sorted(handle, key=lambda e: e.name.lower())
    except OSError:
        return [], False

    truncated = len(dir_entries) > MAX_TOP_ENTRIES
    entries_out: list[dict[str, Any]] = []
    for entry in dir_entries[:MAX_TOP_ENTRIES]:
        try:
            if is_symlink_or_junction(entry.path):
                entries_out.append({"name": entry.name, "kind": "symlink", "size_bytes": None})
            elif entry.is_dir(follow_symlinks=False):
                entries_out.append({"name": entry.name, "kind": "dir", "size_bytes": None})
            elif entry.is_file(follow_symlinks=False):
                st = entry.stat(follow_symlinks=False)
                entries_out.append({"name": entry.name, "kind": "file", "size_bytes": int(st.st_size)})
            else:
                entries_out.append({"name": entry.name, "kind": "other", "size_bytes": None})
        except OSError:
            entries_out.append({"name": entry.name, "kind": "error", "size_bytes": None})

    return entries_out, truncated


def get_module_info(
    module_id: str,
    *,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Return read-only contract metadata and shallow storage listing for any discovered module."""
    if not isinstance(module_id, str) or not MODULE_ID_RE.match(module_id):
        return {
            "found": False,
            "module_id": module_id if isinstance(module_id, str) else "",
            "error": f"Invalid module_id {module_id!r}: must match {MODULE_ID_RE.pattern}",
        }

    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    resolved_gravity = resolve_gravity_home(gravity_home, home_dir=home_dir)
    modules, registry_source, _, _, warnings = load_modules_snapshot_ro(
        resolved_gravity,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    target_mod = next((m for m in modules if m.get("id") == module_id), None)

    if target_mod is None and registry_source == "modules.json" and eff_roots is not None:
        discovered = discover_modules(eff_roots, home_dir=home_dir)
        target_mod = next((dict(m) for m in discovered if m.get("id") == module_id), None)

    if target_mod is None:
        return {
            "found": False,
            "module_id": module_id,
            "error": f"Module {module_id!r} not found.",
            "warnings": warnings,
        }

    storage_raw = target_mod.get("storage") if isinstance(target_mod.get("storage"), dict) else {}
    subdir = storage_raw.get("subdir")
    env_override = storage_raw.get("env_override")
    eff_subdir = subdir if isinstance(subdir, str) and subdir else module_id
    eff_env = env_override if isinstance(env_override, str) else ""

    resolved_home: Optional[Path] = None
    if MODULE_ID_RE.match(eff_subdir):
        try:
            resolved_home = resolve_module_home(
                eff_subdir,
                env_override=eff_env or None,
                gravity_home=resolved_gravity,
            )
        except ValueError:
            resolved_home = None

    exists = bool(resolved_home is not None and resolved_home.is_dir())
    top_entries, truncated = _list_top_entries_ro(resolved_home if exists else None)

    return {
        "found": True,
        "module_id": module_id,
        "plugin_name": target_mod.get("plugin_name"),
        "display_name": target_mod.get("display_name"),
        "version": target_mod.get("version"),
        "role": target_mod.get("role") or "",
        "valid": bool(target_mod.get("valid", False)),
        "errors": list(target_mod.get("errors") or []),
        "commands": list(target_mod.get("commands") or []),
        "capabilities": list(target_mod.get("capabilities") or []),
        "ui": dict(target_mod.get("ui") or {}),
        "signals": dict(target_mod.get("signals") or {}),
        "storage": {
            "subdir": eff_subdir,
            "env_override": eff_env,
            "resolved_home": str(resolved_home) if resolved_home is not None else None,
            "exists": exists,
        },
        "dedicated_provider": resolve_provider_kind(module_id) != "generic",
        "spi": extract_module_spi_metadata(target_mod),
        "top_entries": top_entries,
        "top_entries_truncated": truncated,
        "warnings": warnings,
    }


def get_generic_view(
    module_id: str,
    *,
    view: str = "",
    since_signature: str = "",
    params: Optional[dict[str, Any]] = None,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Dispatch a generic OCP module view via SPI-1 when configured, else fall back to `get_module_info`."""
    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    info = get_module_info(
        module_id,
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    if not info.get("found"):
        return info

    spi_meta = info.get("spi") if isinstance(info.get("spi"), dict) else {}
    if not spi_meta.get("enabled"):
        return info

    views = list(spi_meta.get("views") or [])
    target_view = (view or "").strip()
    if not target_view:
        target_view = "overview" if "overview" in views else (views[0] if views else "")

    if not target_view or (views and target_view not in views):
        return info

    res = invoke_dashboard_provider(
        module_id,
        view=target_view,
        since_signature=since_signature,
        params=params,
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    if not res.get("spi_fallback"):
        return res

    fallback = dict(info)
    fallback["spi_fallback"] = True
    fallback["warnings"] = list(
        dict.fromkeys([*(info.get("warnings") or []), *(res.get("warnings") or [])])
    )
    return fallback


__all__ = ["MAX_TOP_ENTRIES", "get_generic_view", "get_module_info"]

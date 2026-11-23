"""Read-only Core / Doctor overview provider for the Gravity dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from core.registry import (
    detect_legacy_homes,
    discover_modules,  # noqa: F401 - exposed as part of core.registry contract reuse
    resolve_gravity_home,
    resolve_module_home,
)
from dashboard.providers import (
    build_dashboard_tabs,
    load_modules_snapshot_ro,
    short_digest,
    stat_token,
    unchanged_response,
)


def _find_duplicate_ids(modules: Sequence[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for mod in modules:
        mod_id = str(mod.get("id") or "").strip()
        if mod_id:
            counts[mod_id] = counts.get(mod_id, 0) + 1
    return sorted(mod_id for mod_id, count in counts.items() if count > 1)


def _enrich_modules_ro(
    modules: Sequence[dict[str, Any]],
    gravity_home: Path,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for mod in modules:
        item = dict(mod)
        storage = item.get("storage") if isinstance(item.get("storage"), dict) else {}
        subdir = storage.get("subdir")
        env_override = storage.get("env_override")
        resolved_home: Optional[Path] = None
        if item.get("valid") and isinstance(subdir, str) and subdir:
            try:
                resolved_home = resolve_module_home(
                    subdir,
                    env_override=env_override if isinstance(env_override, str) else None,
                    gravity_home=gravity_home,
                )
            except ValueError as exc:
                item["valid"] = False
                item["errors"] = [*list(item.get("errors") or []), str(exc)]
                resolved_home = None
        item["resolved_home"] = str(resolved_home) if resolved_home is not None else None
        item["home_exists"] = bool(resolved_home is not None and resolved_home.is_dir())
        enriched.append(item)
    return enriched


def get_overview(
    since_signature: str = "",
    *,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Return read-only Gravity Core health, modules, tabs, and legacy notice."""
    resolved_gravity = resolve_gravity_home(gravity_home)
    core_dir = resolved_gravity / "core"
    registry_path = core_dir / "modules.json"

    raw_modules, registry_source, registry_exists, generated_at, warnings = load_modules_snapshot_ro(
        resolved_gravity,
        plugin_roots=plugin_roots,
    )
    modules = _enrich_modules_ro(raw_modules, resolved_gravity)
    legacy_homes = detect_legacy_homes(home_dir)

    duplicate_ids = _find_duplicate_ids(modules)
    invalid_count = sum(1 for mod in modules if not mod.get("valid"))
    valid_count = len(modules) - invalid_count
    initialized = core_dir.is_dir() and registry_path.is_file() and registry_source == "modules.json"

    doctor_warnings = list(warnings)
    if not registry_exists:
        doctor_warnings.append("core/modules.json is not initialized; using read-only discovery.")
    if legacy_homes:
        doctor_warnings.append(
            f"{len(legacy_homes)} legacy Gravity directory(ies) detected (read-only notice)."
        )

    if invalid_count > 0 or duplicate_ids:
        status = "error"
    elif not initialized or legacy_homes or doctor_warnings or len(modules) == 0:
        status = "warn"
    else:
        status = "ok"

    doctor = {
        "initialized": initialized,
        "module_count": len(modules),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "duplicate_ids": duplicate_ids,
        "legacy_count": len(legacy_homes),
        "status": status,
        "warnings": doctor_warnings,
    }
    tabs = build_dashboard_tabs(modules)

    sig_parts: list[Any] = [
        str(resolved_gravity),
        stat_token(registry_path),
        registry_source,
        status,
        len(modules),
        *[
            (
                m.get("id"),
                m.get("version"),
                bool(m.get("valid")),
                m.get("resolved_home"),
                bool(m.get("home_exists")),
                stat_token(Path(m["module_path"])) if m.get("module_path") else "none",
            )
            for m in modules
        ],
        *[lh.get("path") for lh in legacy_homes],
    ]
    sig = short_digest(sig_parts)
    if since_signature and since_signature == sig:
        return unchanged_response(sig)

    return {
        "changed": True,
        "unchanged": False,
        "signature": sig,
        "gravity_home": str(resolved_gravity),
        "registry_path": str(registry_path),
        "registry_exists": registry_exists,
        "registry_source": registry_source,
        "registry_generated_at": generated_at,
        "modules": modules,
        "tabs": tabs,
        "doctor": doctor,
        "legacy_homes": legacy_homes,
        "warnings": doctor_warnings,
    }

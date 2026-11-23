"""Shared helpers and provider registry for the read-only Gravity dashboard."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Sequence

DEDICATED_PROVIDERS: tuple[str, ...] = ("core", "workflow", "metrics")

_DEFAULT_LABELS: dict[str, str] = {
    "core": "Overview",
    "workflow": "Workflow Live",
    "metrics": "Metrics",
}


def stat_token(path: Optional[Path]) -> str:
    """Return a lightweight read-only `<mtime_ns>:<size>` token for a filesystem path."""
    if path is None:
        return "missing"
    try:
        st = Path(path).stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "error"


def short_digest(parts: Sequence[Any], length: int = 12) -> str:
    """Return a deterministic truncated SHA-256 hex digest over stringified parts."""
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def unchanged_response(sig: str) -> dict[str, Any]:
    """Return the canonical fast-path payload when source signatures are unchanged."""
    return {"changed": False, "unchanged": True, "signature": sig}


def resolve_provider_kind(module_id: str) -> str:
    """Return the provider kind (`core`, `workflow`, `metrics`, or `generic`)."""
    if module_id in DEDICATED_PROVIDERS:
        return module_id
    return "generic"


def build_dashboard_tabs(modules: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ordered dashboard tabs: `overview`, detected dedicated tabs, then generic OCP modules."""
    by_id: dict[str, dict[str, Any]] = {}
    ordered_others: list[dict[str, Any]] = []

    for raw in modules:
        if not isinstance(raw, dict):
            continue
        mod_id = str(raw.get("id") or "").strip()
        if not mod_id:
            continue
        if mod_id in by_id:
            if raw.get("valid") and not by_id[mod_id].get("valid"):
                by_id[mod_id] = raw
            continue
        by_id[mod_id] = raw
        if mod_id not in DEDICATED_PROVIDERS:
            ordered_others.append(raw)

    core_mod = by_id.get("core") or {}
    tabs: list[dict[str, Any]] = [
        {
            "id": "overview",
            "kind": "core",
            "module_id": "core",
            "label": _DEFAULT_LABELS["core"],
            "display_name": core_mod.get("display_name") or "Gravity Core",
            "plugin_name": core_mod.get("plugin_name") or "gravity",
            "version": core_mod.get("version"),
            "valid": bool(core_mod.get("valid", True)) if core_mod else True,
            "dedicated": True,
            "commands": list(core_mod.get("commands") or ["/gravity"]),
            "ui": dict(core_mod.get("ui") or {"mode": "core", "target": "gravity"}),
        }
    ]

    for mod_id in ("workflow", "metrics"):
        mod = by_id.get(mod_id)
        if mod is None:
            continue
        tabs.append(
            {
                "id": mod_id,
                "kind": mod_id,
                "module_id": mod_id,
                "label": _DEFAULT_LABELS[mod_id],
                "display_name": mod.get("display_name") or mod.get("plugin_name") or mod_id.title(),
                "plugin_name": mod.get("plugin_name") or f"gravity-{mod_id}",
                "version": mod.get("version"),
                "valid": bool(mod.get("valid", False)),
                "dedicated": True,
                "commands": list(mod.get("commands") or []),
                "ui": dict(mod.get("ui") or {}),
            }
        )

    for mod in ordered_others:
        mod_id = str(mod["id"])
        label = str(mod.get("display_name") or mod.get("plugin_name") or mod_id.title())
        tabs.append(
            {
                "id": mod_id,
                "kind": "generic",
                "module_id": mod_id,
                "label": label,
                "display_name": label,
                "plugin_name": mod.get("plugin_name") or mod_id,
                "version": mod.get("version"),
                "role": mod.get("role") or "",
                "valid": bool(mod.get("valid", False)),
                "dedicated": False,
                "commands": list(mod.get("commands") or []),
                "ui": dict(mod.get("ui") or {}),
            }
        )

    return tabs


def read_json_ro(path: Path) -> tuple[Any, Optional[str]]:
    """Read and decode a JSON file read-only without raising exceptions."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"Failed to read {path.name}: {exc}"

    warning: Optional[str] = None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        warning = f"UTF-8 BOM detected in {path.name}."

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"Invalid JSON in {path.name}: {exc}"

    return data, warning


def file_uri_if_exists(path: Path) -> str:
    """Return a `file://` URI if `path` exists as a regular file, else empty string."""
    try:
        if path.is_file():
            return path.resolve().as_uri()
    except OSError:
        pass
    return ""


def load_modules_snapshot_ro(
    gravity_home: Path,
    plugin_roots: Optional[Sequence[Path]] = None,
) -> tuple[list[dict[str, Any]], str, bool, Optional[str], list[str]]:
    """Load modules from `<gravity_home>/core/modules.json` or fallback read-only to `discover_modules`."""
    from core.registry import discover_modules

    registry_path = gravity_home / "core" / "modules.json"
    warnings: list[str] = []
    registry_exists = registry_path.is_file()

    if registry_exists:
        data, read_warn = read_json_ro(registry_path)
        if read_warn:
            warnings.append(read_warn)
        if isinstance(data, dict) and isinstance(data.get("modules"), list):
            raw_modules = [dict(m) for m in data["modules"] if isinstance(m, dict)]
            generated_at = data.get("generated_at")
            gen_str = str(generated_at) if isinstance(generated_at, str) else None
            return raw_modules, "modules.json", True, gen_str, warnings
        if data is not None:
            warnings.append("Invalid structure in core/modules.json; falling back to live module discovery.")

    discovered = [dict(m) for m in discover_modules(plugin_roots)]
    return discovered, "discovered", registry_exists, None, warnings


__all__ = [
    "DEDICATED_PROVIDERS",
    "build_dashboard_tabs",
    "file_uri_if_exists",
    "load_modules_snapshot_ro",
    "read_json_ro",
    "resolve_provider_kind",
    "short_digest",
    "stat_token",
    "unchanged_response",
]

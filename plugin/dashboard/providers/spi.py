"""SPI-1 subprocess dispatcher for decoupled Gravity companion dashboard providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence as AbcSequence
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Optional, Sequence

from _shared.path_safety import (
    ensure_no_symlink_or_junction_under,
    is_symlink_or_junction,
    is_within_root,
    validate_rel_member_path,
)
from core.registry import MODULE_ID_RE, resolve_gravity_home
from dashboard.providers import enforce_payload_budget, load_modules_snapshot_ro, read_json_ro

SPI_TIMEOUT_S: float = 15.0
MAX_PAYLOAD_BYTES: int = 450_000
_SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DEFAULT_LIST_KEYS: tuple[str, ...] = (
    "records",
    "audits",
    "pending_sessions",
    "ignored_sessions",
    "events",
    "projects",
    "specs",
    "tasks",
    "handoffs",
    "workspaces",
    "items",
    "entries",
)


def _serialize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _serialize_json_value(v) for k, v in value.items()}
    if isinstance(value, AbcSequence) and not isinstance(value, (bytes, bytearray)):
        return [_serialize_json_value(item) for item in value]
    return str(value)


def _clean_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            val = item.strip()
            if val and _SAFE_SLUG_RE.match(val):
                out.append(val)
    return out


def _read_dashboard_block(
    mod: Mapping[str, Any],
    plugin_dir: Path,
    warnings: list[str],
) -> Optional[dict[str, Any]]:
    raw_dash = mod.get("dashboard")
    if isinstance(raw_dash, dict):
        return dict(raw_dash)
    if raw_dash is not None:
        warnings.append("Invalid 'dashboard' block in module registry entry.")
        return None

    mod_json_raw = plugin_dir / "config" / "module.json"
    try:
        ensure_no_symlink_or_junction_under(plugin_dir, mod_json_raw)
    except ValueError as exc:
        warnings.append(str(exc))
        return None

    if not mod_json_raw.is_file():
        return None
    data, read_warn = read_json_ro(mod_json_raw)
    if read_warn:
        warnings.append(read_warn)
    if isinstance(data, dict) and isinstance(data.get("dashboard"), dict):
        return dict(data["dashboard"])
    return None


def extract_module_spi_metadata(mod: Mapping[str, Any]) -> dict[str, Any]:
    """Return read-only SPI-1 capability metadata (`enabled`, `provider_script`, `views`, `actions`)."""
    empty: dict[str, Any] = {"enabled": False, "provider_script": "", "views": [], "actions": []}
    raw_dir = mod.get("plugin_dir")
    if not isinstance(raw_dir, str) or not raw_dir.strip():
        raw_dash = mod.get("dashboard")
        if not isinstance(raw_dash, dict):
            return empty
        dash = dict(raw_dash)
    else:
        raw_path = Path(raw_dir.strip()).expanduser()
        if is_symlink_or_junction(raw_path):
            return empty
        try:
            plugin_dir = raw_path.resolve()
        except OSError:
            return empty
        if not plugin_dir.is_dir():
            return empty
        dash = _read_dashboard_block(mod, plugin_dir, []) or {}

    raw_ps = dash.get("provider_script")
    if not isinstance(raw_ps, str) or not raw_ps.strip():
        return empty
    try:
        rel_ps = validate_rel_member_path(raw_ps.strip(), label="dashboard.provider_script")
    except ValueError:
        return empty

    return {
        "enabled": True,
        "provider_script": rel_ps,
        "views": _clean_str_list(dash.get("views")),
        "actions": _clean_str_list(dash.get("actions")),
    }


def _resolve_error(module_id: str, reason: str, warnings: Sequence[str] = ()) -> dict[str, Any]:
    all_warnings = list(dict.fromkeys([*warnings, reason]))
    return {
        "ok": False,
        "module_id": module_id,
        "error": reason,
        "warnings": all_warnings,
    }


def resolve_dashboard_provider(
    module_id: str,
    *,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Resolve and validate a companion module's SPI-1 `dashboard.provider_script` read-only."""
    clean_id = module_id.strip() if isinstance(module_id, str) else ""
    if not clean_id or not MODULE_ID_RE.match(clean_id):
        return _resolve_error(clean_id, f"Invalid module_id {module_id!r}.")

    resolved_gravity = resolve_gravity_home(gravity_home, home_dir=home_dir)
    modules, _, _, _, warnings = load_modules_snapshot_ro(
        resolved_gravity,
        plugin_roots=plugin_roots,
        home_dir=home_dir,
    )
    target_mod = next((m for m in modules if isinstance(m, dict) and m.get("id") == clean_id), None)
    if target_mod is None:
        return _resolve_error(clean_id, f"Module {clean_id!r} is not installed or registered.", warnings)

    raw_dir = target_mod.get("plugin_dir")
    if not isinstance(raw_dir, str) or not raw_dir.strip():
        return _resolve_error(clean_id, f"Module {clean_id!r} has no plugin_dir configured.", warnings)

    raw_plugin_path = Path(raw_dir.strip()).expanduser()
    if is_symlink_or_junction(raw_plugin_path):
        return _resolve_error(clean_id, f"Refusing symlink or junction plugin_dir: {raw_plugin_path}", warnings)

    try:
        plugin_dir = raw_plugin_path.resolve()
    except OSError as exc:
        return _resolve_error(clean_id, f"Failed to resolve plugin_dir for {clean_id!r}: {exc}", warnings)
    if not plugin_dir.is_dir():
        return _resolve_error(clean_id, f"Plugin directory does not exist for {clean_id!r}: {plugin_dir}", warnings)

    dash = _read_dashboard_block(target_mod, plugin_dir, warnings)
    if dash is None:
        return _resolve_error(clean_id, f"Module {clean_id!r} does not declare a dashboard SPI-1 provider.", warnings)

    raw_ps = dash.get("provider_script")
    if not isinstance(raw_ps, str) or not raw_ps.strip():
        return _resolve_error(clean_id, f"Module {clean_id!r} dashboard.provider_script is missing.", warnings)
    try:
        rel_script = validate_rel_member_path(raw_ps.strip(), label="dashboard.provider_script")
    except ValueError as exc:
        return _resolve_error(clean_id, str(exc), warnings)

    raw_script = plugin_dir.joinpath(*rel_script.split("/"))
    try:
        ensure_no_symlink_or_junction_under(plugin_dir, raw_script)
        script_path = raw_script.resolve()
    except (OSError, ValueError) as exc:
        return _resolve_error(clean_id, f"Unsafe provider_script path for {clean_id!r}: {exc}", warnings)

    if not is_within_root(plugin_dir, script_path) or not script_path.is_file():
        return _resolve_error(
            clean_id,
            f"Dashboard provider script not found under plugin_dir for {clean_id!r}: {rel_script}",
            warnings,
        )

    return {
        "ok": True,
        "module_id": clean_id,
        "plugin_dir": plugin_dir,
        "script_path": script_path,
        "provider_script": rel_script,
        "views": _clean_str_list(dash.get("views")),
        "actions": _clean_str_list(dash.get("actions")),
        "dashboard": dash,
        "warnings": warnings,
    }


def _fallback_response(
    module_id: str,
    *,
    view: str = "",
    action: str = "",
    reason: str,
    warnings: Sequence[str] = (),
    returncode: Optional[int] = None,
) -> dict[str, Any]:
    merged_warnings = list(dict.fromkeys([w for w in warnings if w] + ([reason] if reason else [])))
    if action:
        out: dict[str, Any] = {
            "ok": False,
            "spi_fallback": True,
            "module_id": module_id,
            "action": action,
            "message": reason,
            "error": reason,
            "warnings": merged_warnings,
        }
        if returncode is not None:
            out["returncode"] = returncode
        return out
    out = {
        "available": False,
        "changed": True,
        "unchanged": False,
        "spi_fallback": True,
        "module_id": module_id,
        "view": view,
        "error": reason,
        "warnings": merged_warnings,
    }
    if returncode is not None:
        out["returncode"] = returncode
    return out


def invoke_dashboard_provider(
    module_id: str,
    *,
    view: str = "",
    action: str = "",
    since_signature: str = "",
    params: Optional[Mapping[str, Any]] = None,
    ctx: Optional[Mapping[str, Any]] = None,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
    timeout_s: float = SPI_TIMEOUT_S,
    list_keys: Sequence[str] = _DEFAULT_LIST_KEYS,
) -> dict[str, Any]:
    """Invoke a companion module's SPI-1 `dashboard_provider.py` via `subprocess.run(shell=False)`."""
    clean_mod = module_id.strip() if isinstance(module_id, str) else ""
    clean_view = view.strip() if isinstance(view, str) else ""
    clean_action = action.strip() if isinstance(action, str) else ""

    if bool(clean_view) == bool(clean_action):
        return _fallback_response(
            clean_mod,
            view=clean_view,
            action=clean_action,
            reason="Specify exactly one of 'view' or 'action'.",
        )
    if clean_view and not _SAFE_SLUG_RE.match(clean_view):
        return _fallback_response(clean_mod, view=clean_view, reason=f"Invalid SPI view {view!r}.")
    if clean_action and not _SAFE_SLUG_RE.match(clean_action):
        return _fallback_response(clean_mod, action=clean_action, reason=f"Invalid SPI action {action!r}.")

    resolved = resolve_dashboard_provider(
        clean_mod,
        gravity_home=gravity_home,
        plugin_roots=plugin_roots,
        home_dir=home_dir,
    )
    if not resolved.get("ok"):
        return _fallback_response(
            clean_mod,
            view=clean_view,
            action=clean_action,
            reason=str(resolved.get("error") or "SPI provider resolution failed."),
            warnings=resolved.get("warnings") or (),
        )

    views = resolved.get("views") or []
    actions = resolved.get("actions") or []
    if clean_view and views and clean_view not in views:
        return _fallback_response(
            clean_mod,
            view=clean_view,
            reason=f"View {clean_view!r} is not declared by module {clean_mod!r}.",
            warnings=resolved.get("warnings") or (),
        )
    if clean_action and (not isinstance(actions, list) or clean_action not in actions):
        return _fallback_response(
            clean_mod,
            action=clean_action,
            reason=f"Action {clean_action!r} is not declared by module {clean_mod!r}.",
            warnings=resolved.get("warnings") or (),
        )

    cmd: list[str] = [sys.executable, "-B", str(resolved["script_path"])]
    if clean_view:
        cmd.extend(["--view", clean_view])
        if since_signature:
            cmd.extend(["--since-signature", str(since_signature)])
    else:
        cmd.extend(["--action", clean_action])
    cmd.append("--json")

    stdin_payload = json.dumps(
        {
            "params": _serialize_json_value(params or {}),
            "context": _serialize_json_value(ctx or {}),
        },
        ensure_ascii=False,
    )
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if home_dir is not None:
        resolved_user = str(Path(home_dir).expanduser().resolve())
        env["HOME"] = resolved_user
        env["USERPROFILE"] = resolved_user
        if gravity_home is None and not os.environ.get("GRAVITY_HOME", "").strip():
            env["GRAVITY_HOME"] = str(resolve_gravity_home(None, home_dir=home_dir))
    if gravity_home is not None:
        env["GRAVITY_HOME"] = str(Path(gravity_home).expanduser().resolve())

    eff_timeout = SPI_TIMEOUT_S if timeout_s is None else max(0.01, min(float(timeout_s), SPI_TIMEOUT_S))
    base_warnings: list[str] = list(resolved.get("warnings") or [])

    try:
        proc = subprocess.run(
            cmd,
            input=stdin_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=eff_timeout,
            env=env,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _fallback_response(
            clean_mod,
            view=clean_view,
            action=clean_action,
            reason=f"SPI provider for {clean_mod!r} timed out after {eff_timeout:.1f}s.",
            warnings=base_warnings,
        )
    except (OSError, ValueError) as exc:
        return _fallback_response(
            clean_mod,
            view=clean_view,
            action=clean_action,
            reason=f"SPI subprocess execution failed for {clean_mod!r}: {exc}",
            warnings=base_warnings,
        )

    if proc.returncode != 0:
        err_tail = (proc.stderr or proc.stdout or "").strip()[:240]
        detail = f" ({err_tail})" if err_tail else ""
        return _fallback_response(
            clean_mod,
            view=clean_view,
            action=clean_action,
            reason=f"SPI provider for {clean_mod!r} exited with code {proc.returncode}{detail}.",
            warnings=base_warnings,
            returncode=proc.returncode,
        )

    raw_out = (proc.stdout or "").strip()
    try:
        parsed = json.loads(raw_out)
    except ValueError as exc:
        return _fallback_response(
            clean_mod,
            view=clean_view,
            action=clean_action,
            reason=f"SPI provider for {clean_mod!r} returned invalid JSON: {exc}",
            warnings=base_warnings,
        )

    if not isinstance(parsed, dict):
        return _fallback_response(
            clean_mod,
            view=clean_view,
            action=clean_action,
            reason=f"SPI provider for {clean_mod!r} returned non-object JSON.",
            warnings=base_warnings,
        )

    all_list_keys = tuple(
        dict.fromkeys([*list_keys, *[k for k, v in parsed.items() if isinstance(v, list)]])
    )
    return enforce_payload_budget(parsed, all_list_keys, max_bytes=MAX_PAYLOAD_BYTES)


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "SPI_TIMEOUT_S",
    "extract_module_spi_metadata",
    "invoke_dashboard_provider",
    "resolve_dashboard_provider",
]

"""Read-only Gravity Workflow live state provider for the Gravity dashboard."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any, Optional

from core.registry import resolve_module_home
from dashboard.providers import (
    read_json_ro,
    short_digest,
    stat_token,
    unchanged_response,
)

MAX_EVENTS = 50
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _default_workflow_fields() -> dict[str, Any]:
    return {
        "stage": "idle",
        "progress": "0/8",
        "mode": "evo",
        "level": "standard",
        "preset_profile": "standard",
        "suggested_profile": "standard",
        "suggested_reason": "",
        "role_models": {"plan": "flash", "build": "flash", "review": "pro"},
        "caveman": "lite",
        "caveman_locked": False,
        "guard_status": "ON",
        "nodes": {"planner": "", "builder": "", "reviewer": ""},
        "events": [],
    }


def _workspace_slug_hash(workspace_root: Path) -> str:
    resolved = workspace_root.resolve()
    norm = os.path.normcase(str(resolved))
    slug = _SLUG_RE.sub("-", resolved.name.lower()).strip("-")[:32] or "workspace"
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _is_valid_state_path(raw_path: Any) -> Optional[Path]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    candidate = Path(raw_path.strip()).expanduser()
    if candidate.name != "live_state.json":
        return None
    return candidate


def _load_registered_workspaces_ro(
    reg_file: Path,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not reg_file.is_file():
        return []
    data, read_warn = read_json_ro(reg_file)
    if read_warn:
        warnings.append(read_warn)
    if not isinstance(data, dict):
        if data is not None:
            warnings.append("Invalid structure in live_workspaces.json: expected JSON object.")
        return []
    entries = data.get("workspaces")
    if not isinstance(entries, list):
        warnings.append("Invalid 'workspaces' field in live_workspaces.json.")
        return []

    valid_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_sp = entry.get("state_path")
        sp = _is_valid_state_path(raw_sp)
        if sp is None:
            warnings.append(
                f"Ignored unsafe or non-live_state.json registry entry: {raw_sp!r}."
            )
            continue
        if sp.is_symlink():
            warnings.append(f"Ignored symlinked live_state.json entry: {sp}.")
            continue
        ws_path = str(entry.get("workspace_path") or entry.get("workspace") or "").strip()
        valid_entries.append(
            {
                "workspace_path": ws_path or str(sp.parent),
                "workspace": ws_path or str(sp.parent),
                "state_path": str(sp),
                "updated_at": str(entry.get("updated_at") or ""),
                "exists": sp.is_file(),
                "source": "registry",
            }
        )

    valid_entries.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return valid_entries


def _scan_workspaces_dir_ro(wf_home: Path) -> list[dict[str, Any]]:
    workspaces_dir = wf_home / "workspaces"
    if not workspaces_dir.is_dir():
        return []

    found: list[dict[str, Any]] = []
    try:
        children = sorted(workspaces_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return []

    for sub in children:
        if sub.is_symlink() or not sub.is_dir():
            continue
        state_file = sub / "live_state.json"
        if state_file.is_symlink() or not state_file.is_file():
            continue
        try:
            mtime_ns = state_file.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        found.append(
            {
                "workspace_path": sub.name,
                "workspace": sub.name,
                "state_path": str(state_file.resolve()),
                "updated_at": "",
                "exists": True,
                "source": "scan",
                "_mtime_ns": mtime_ns,
            }
        )

    found.sort(key=lambda item: (-int(item.get("_mtime_ns") or 0), str(item["workspace_path"])))
    for item in found:
        item.pop("_mtime_ns", None)
    return found


def _norm_ws_key(raw: str) -> str:
    try:
        return os.path.normcase(str(Path(raw).expanduser().resolve()))
    except OSError:
        return os.path.normcase(raw)


def _select_workspace(
    ws: str,
    workspaces: list[dict[str, Any]],
    wf_home: Path,
) -> tuple[Optional[dict[str, Any]], Optional[Path]]:
    query = ws.strip()
    if not query:
        if not workspaces:
            return None, None
        first = workspaces[0]
        return first, Path(first["state_path"])

    if query.isdigit():
        idx = int(query)
        if 0 <= idx < len(workspaces):
            chosen = workspaces[idx]
            return chosen, Path(chosen["state_path"])

    norm_query = _norm_ws_key(query)
    for item in workspaces:
        ws_val = str(item.get("workspace_path") or "")
        st_val = str(item.get("state_path") or "")
        if query in (ws_val, st_val) or (ws_val and _norm_ws_key(ws_val) == norm_query):
            return item, Path(st_val)
    for item in workspaces:
        ws_val = str(item.get("workspace_path") or "")
        if ws_val and Path(ws_val).name.casefold() == query.casefold():
            return item, Path(item["state_path"])

    ws_dir = Path(query).expanduser()
    if ws_dir.is_dir():
        resolved_ws = ws_dir.resolve()
        central = (wf_home / "workspaces" / _workspace_slug_hash(resolved_ws) / "live_state.json").resolve()
        local = (resolved_ws / ".agents" / "gravity-workflow" / "observability" / "live_state.json").resolve()
        if central.is_file() and not central.is_symlink():
            entry = {
                "workspace_path": str(resolved_ws),
                "workspace": str(resolved_ws),
                "state_path": str(central),
                "updated_at": "",
                "exists": True,
                "source": "central_fallback",
            }
            return entry, central
        if local.is_file() and not local.is_symlink():
            entry = {
                "workspace_path": str(resolved_ws),
                "workspace": str(resolved_ws),
                "state_path": str(local),
                "updated_at": "",
                "exists": True,
                "source": "local_fallback",
            }
            return entry, local
        return {
            "workspace_path": str(resolved_ws),
            "workspace": str(resolved_ws),
            "state_path": str(central),
            "updated_at": "",
            "exists": False,
            "source": "unresolved",
        }, None

    return None, None


def _coerce_workflow_payload(raw: dict[str, Any]) -> dict[str, Any]:
    out = _default_workflow_fields()
    for str_key in (
        "stage",
        "progress",
        "mode",
        "level",
        "preset_profile",
        "suggested_profile",
        "suggested_reason",
        "caveman",
        "guard_status",
    ):
        val = raw.get(str_key)
        if isinstance(val, str) and val != "":
            out[str_key] = val
        elif str_key == "suggested_reason" and isinstance(val, str):
            out[str_key] = val

    if "caveman_locked" in raw:
        out["caveman_locked"] = bool(raw.get("caveman_locked"))

    raw_rm = raw.get("role_models")
    if isinstance(raw_rm, dict):
        merged_rm = dict(out["role_models"])
        for k, v in raw_rm.items():
            if isinstance(k, str) and isinstance(v, str):
                merged_rm[k] = v
        out["role_models"] = merged_rm

    raw_nodes = raw.get("nodes")
    if isinstance(raw_nodes, dict):
        merged_nodes = dict(out["nodes"])
        for k, v in raw_nodes.items():
            if isinstance(k, str) and isinstance(v, str):
                merged_nodes[k] = v
        out["nodes"] = merged_nodes

    raw_events = raw.get("events")
    if isinstance(raw_events, list):
        out["events"] = [e for e in raw_events[-MAX_EVENTS:] if isinstance(e, dict)]

    return out


def get_workflow_state(
    ws: str = "",
    since_signature: str = "",
    *,
    gravity_home: Optional[Path] = None,
    workflow_home: Optional[Path] = None,
    registry_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return read-only Gravity Workflow v0.3.0 live state for the selected workspace."""
    wf_home = (
        Path(workflow_home).expanduser().resolve()
        if workflow_home is not None
        else resolve_module_home("workflow", env_override="GRAVITY_WORKFLOW_HOME", gravity_home=gravity_home)
    )
    reg_file = (
        Path(registry_path).expanduser().resolve()
        if registry_path is not None
        else (wf_home / "live_workspaces.json").resolve()
    )

    warnings: list[str] = []
    workspaces = _load_registered_workspaces_ro(reg_file, warnings)
    if not workspaces:
        workspaces = _scan_workspaces_dir_ro(wf_home)

    selected_workspace, selected_state_file = _select_workspace(ws, workspaces, wf_home)

    if selected_state_file is not None and selected_state_file.name != "live_state.json":
        warnings.append(f"Refused non-live_state.json state path: {selected_state_file}.")
        selected_state_file = None

    sig = short_digest(
        [
            ws.strip(),
            str(wf_home),
            stat_token(reg_file),
            stat_token(selected_state_file),
            len(workspaces),
        ]
    )
    if since_signature and since_signature == sig:
        return unchanged_response(sig)

    fields = _default_workflow_fields()
    available = False

    if selected_state_file is not None and selected_state_file.is_file() and not selected_state_file.is_symlink():
        raw_state, read_warn = read_json_ro(selected_state_file)
        if read_warn:
            warnings.append(read_warn)
        if isinstance(raw_state, dict):
            fields = _coerce_workflow_payload(raw_state)
            available = True
        elif raw_state is not None:
            warnings.append(f"Invalid structure in {selected_state_file.name}: expected JSON object.")

    return {
        "changed": True,
        "unchanged": False,
        "signature": sig,
        "available": available,
        "workflow_home": str(wf_home),
        "registry_path": str(reg_file),
        "workspaces": workspaces,
        "selected_workspace": selected_workspace,
        **fields,
        "warnings": warnings,
    }

"""Unified read-only facade for the Gravity Dashboard (MCP App & tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from dashboard.providers.architect_provider import get_architect_state
from dashboard.providers.bridge_provider import get_bridge_state
from dashboard.providers.core_provider import get_overview
from dashboard.providers.generic_provider import get_module_info
from dashboard.providers.metrics_provider import get_metrics_state, get_session_detail
from dashboard.providers.workflow_provider import get_workflow_state


def build_initial_summary(
    *,
    view: str = "overview",
    project: str = "",
    ws: str = "",
    module_id: str = "",
    overview: Optional[dict[str, Any]] = None,
    workflow: Optional[dict[str, Any]] = None,
    metrics: Optional[dict[str, Any]] = None,
    bridge: Optional[dict[str, Any]] = None,
    architect: Optional[dict[str, Any]] = None,
    module_info: Optional[dict[str, Any]] = None,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
    workflow_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    audits_dirs: Optional[Sequence[Path]] = None,
    bridge_home: Optional[Path] = None,
    db_path: Optional[Path] = None,
    architect_home: Optional[Path] = None,
    architect_workspace: Optional[Path] = None,
) -> str:
    """Build a concise plain-text summary for `open_gravity_dashboard` responses."""
    req_view = (view or "overview").strip().lower() or "overview"
    ov = overview if overview is not None else get_overview(
        gravity_home=gravity_home,
        plugin_roots=plugin_roots,
        home_dir=home_dir,
    )
    doctor = ov.get("doctor") or {}
    tab_ids = {str(t.get("id") or "") for t in (ov.get("tabs") or []) if isinstance(t, dict)}

    parts: list[str] = [
        (
            f"Gravity Dashboard (view={req_view}) : "
            f"{doctor.get('module_count', 0)} module(s) "
            f"[{doctor.get('valid_count', 0)} ok, doctor={doctor.get('status', 'unknown')}]"
        )
    ]

    if req_view == "module" and module_id.strip():
        minfo = module_info if module_info is not None else get_module_info(
            module_id.strip(),
            gravity_home=gravity_home,
            plugin_roots=plugin_roots,
        )
        if minfo.get("found"):
            parts.append(
                f"Module {minfo.get('module_id')} ({minfo.get('plugin_name')} "
                f"v{minfo.get('version') or '?'})"
            )
        else:
            parts.append(f"Module {module_id.strip()}: introuvable")

    if workflow is not None or req_view == "workflow" or "workflow" in tab_ids:
        wf = workflow if workflow is not None else get_workflow_state(
            ws=ws,
            gravity_home=gravity_home,
            workflow_home=workflow_home,
        )
        if wf.get("available"):
            parts.append(
                f"Workflow: {wf.get('stage', 'idle')} ({wf.get('progress', '0/8')}, "
                f"{wf.get('preset_profile', 'standard')})"
            )
        else:
            parts.append("Workflow: idle")

    if metrics is not None or req_view == "metrics" or project.strip() or "metrics" in tab_ids:
        met = metrics if metrics is not None else get_metrics_state(
            project=project,
            gravity_home=gravity_home,
            metrics_home=metrics_home,
            audits_dirs=audits_dirs,
        )
        kpis = met.get("kpis") or {}
        scope_lbl = f"projet '{project.strip()}'" if project.strip() else "global"
        parts.append(
            f"Metrics ({scope_lbl}): {kpis.get('sessions_count', 0)} session(s), "
            f"${float(kpis.get('cost_usd') or 0.0):.4f}, "
            f"{len(met.get('pending_sessions') or [])} en attente"
        )

    if bridge is not None or req_view == "bridge" or "bridge" in tab_ids:
        br = bridge if bridge is not None else get_bridge_state(
            gravity_home=gravity_home,
            bridge_home=bridge_home,
            db_path=db_path,
        )
        if br.get("available"):
            bk = br.get("kpis") or {}
            parts.append(
                f"Bridge: {bk.get('online_count', 0)}/{bk.get('workspaces_count', 0)} sidecar(s), "
                f"{bk.get('threads_open', 0)} ouvert(s)"
            )
        else:
            parts.append("Bridge: inactif")

    if architect is not None or req_view == "architect" or "architect" in tab_ids:
        arch = architect if architect is not None else get_architect_state(
            gravity_home=gravity_home,
            bridge_home=bridge_home,
            architect_home=architect_home,
            architect_workspace=architect_workspace,
        )
        if arch.get("available"):
            parts.append(
                f"Architect: {len(arch.get('projects') or [])} projet(s), "
                f"{len(arch.get('specs') or [])} spec(s), "
                f"{len(arch.get('handoffs') or [])} handoff(s), "
                f"{len(arch.get('audits') or [])} audit(s) code"
            )
        else:
            parts.append("Architect: atelier non détecté")

    return " | ".join(parts)


__all__ = [
    "build_initial_summary",
    "get_architect_state",
    "get_bridge_state",
    "get_metrics_state",
    "get_module_info",
    "get_overview",
    "get_session_detail",
    "get_workflow_state",
]

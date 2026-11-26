"""Unified read-only SPI-1 facade for the Gravity Dashboard (MCP App & tests)."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Optional, Sequence

from _shared.path_safety import validate_rel_member_path
from dashboard.providers import normalize_plugin_roots
from dashboard.providers.core_provider import get_overview
from dashboard.providers.generic_provider import get_module_info
from dashboard.providers.spi import invoke_dashboard_provider

ALLOWED_METRICS_ACTIONS: tuple[str, ...] = (
    "record",
    "update",
    "update-meta",
    "ignore",
    "unignore",
    "remove",
)
_SAFE_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def get_workflow_state(
    ws: str = "",
    since_signature: str = "",
    *,
    gravity_home: Optional[Path] = None,
    workflow_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    """Return read-only Gravity Workflow state via companion SPI-1 provider."""
    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    res = invoke_dashboard_provider(
        "workflow",
        view="workflow",
        since_signature=since_signature,
        params={"ws": ws},
        ctx={"workflow_home": workflow_home},
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    if res.get("spi_fallback"):
        res.setdefault("stage", "idle")
        res.setdefault("progress", "0/0")
        res.setdefault("preset_profile", "standard")
        res.setdefault("events", [])
        res.setdefault("workspaces", [])
    return res


def get_metrics_state(
    project: str = "",
    limit: int = 100,
    q: str = "",
    since_signature: str = "",
    *,
    gravity_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    audits_dirs: Optional[Sequence[Path]] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    """Return read-only Gravity Metrics state via companion SPI-1 provider."""
    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    res = invoke_dashboard_provider(
        "metrics",
        view="metrics",
        since_signature=since_signature,
        params={"project": project, "limit": limit, "q": q},
        ctx={"metrics_home": metrics_home, "audits_dirs": audits_dirs},
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    if res.get("spi_fallback"):
        res.setdefault("kpis", {"sessions_count": 0, "useful_tokens": 0, "cost_usd": 0.0})
        res.setdefault("pending_sessions", [])
        res.setdefault("ignored_sessions", [])
        res.setdefault("records", [])
        res.setdefault("audits", [])
    return res


def get_session_detail(
    target: str,
    *,
    gravity_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    """Return read-only session detail via Gravity Metrics SPI-1 provider."""
    clean_target = str(target or "").strip()
    if (
        not clean_target
        or "\x00" in clean_target
        or "/" in clean_target
        or "\\" in clean_target
        or ".." in clean_target
    ):
        return {
            "found": False,
            "target": clean_target,
            "error": "Invalid session target identifier.",
            "spi_fallback": True,
        }
    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    res = invoke_dashboard_provider(
        "metrics",
        view="session-detail",
        params={"target": clean_target},
        ctx={"metrics_home": metrics_home},
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    if res.get("spi_fallback"):
        res.setdefault("found", False)
        res.setdefault("target", clean_target)
    return res


def run_metrics_cli_action(
    action: str,
    *,
    conversation_id: str = "",
    slug: str = "",
    target: str = "",
    label: str = "",
    project: str = "",
    note: str = "",
    reason: str = "",
    workspace: str = "",
    full: bool = False,
    purge_reports: bool = False,
    gravity_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    brain_dir: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    """Dispatch a validated Gravity Metrics lifecycle action via SPI-1."""
    clean_action = str(action or "").strip()
    if clean_action not in ALLOWED_METRICS_ACTIONS:
        msg = f"Unsupported metrics action: {action!r}."
        return {"ok": False, "action": clean_action, "error": msg, "message": msg}

    clean_target = ""
    for cand in (target, conversation_id, slug):
        s = str(cand or "").strip()
        if s:
            clean_target = s
            break
    if not clean_target or not _SAFE_TARGET_RE.match(clean_target):
        msg = f"Invalid metrics target identifier: {clean_target!r}."
        return {"ok": False, "action": clean_action, "error": msg, "message": msg}

    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    return invoke_dashboard_provider(
        "metrics",
        action=clean_action,
        params={
            "target": clean_target,
            "conversation_id": str(conversation_id or "").strip(),
            "slug": str(slug or "").strip(),
            "label": str(label or ""),
            "project": str(project or ""),
            "note": str(note or ""),
            "reason": str(reason or ""),
            "workspace": str(workspace or ""),
            "full": bool(full),
            "purge_reports": bool(purge_reports),
        },
        ctx={"metrics_home": metrics_home, "brain_dir": brain_dir},
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )


def read_metrics_audit(
    target: str,
    *,
    gravity_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    audits_dirs: Optional[Sequence[Path]] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    """Read an agent audit report via Gravity Metrics SPI-1 (rejects traversal and audits/code)."""
    clean_target = str(target or "").strip()
    try:
        rel_path = validate_rel_member_path(clean_target, label="audit target")
    except ValueError as exc:
        return {"found": False, "path": clean_target, "error": str(exc), "spi_fallback": True}

    low = rel_path.lower()
    if low == "code" or low.startswith("code/") or "/code/" in low or low.startswith("audits/code/"):
        return {
            "found": False,
            "path": rel_path,
            "error": "Access to audits/code/ is forbidden.",
            "spi_fallback": True,
        }

    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    res = invoke_dashboard_provider(
        "metrics",
        view="audit-detail",
        params={"path": rel_path},
        ctx={"metrics_home": metrics_home, "audits_dirs": audits_dirs},
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    if res.get("spi_fallback"):
        res.setdefault("found", False)
        res.setdefault("path", rel_path)
    return res


def get_architect_state(
    since_signature: str = "",
    atelier: str = "",
    ws: str = "",
    *,
    gravity_home: Optional[Path] = None,
    architect_home: Optional[Path] = None,
    architect_workspace: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    """Return read-only Gravity Architect state via companion SPI-1 provider."""
    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    res = invoke_dashboard_provider(
        "architect",
        view="architect",
        since_signature=since_signature,
        params={"atelier": atelier, "ws": ws},
        ctx={"architect_home": architect_home, "architect_workspace": architect_workspace},
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
        home_dir=home_dir,
    )
    if res.get("spi_fallback"):
        res.setdefault("projects", [])
        res.setdefault("specs", [])
        res.setdefault("tasks", [])
        res.setdefault("handoffs", [])
        res.setdefault("audits", [])
    return res


def get_live_session_state(
    session_id: str = "",
    since_signature: str = "",
    include_events: bool = True,
    *,
    ws: str = "",
    gravity_home: Optional[Path] = None,
    brain_dir: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    workflow_home: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    home_dir: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    **_: Any,
) -> dict[str, Any]:
    """Return live session state via lazy import of `dashboard.providers.live_provider`."""
    try:
        from dashboard.providers.live_provider import get_live_session_state as _impl
    except ImportError:
        return {
            "available": False,
            "changed": True,
            "unchanged": False,
            "agents": [],
            "sessions": [],
            "recent_events": [],
            "summary": {"total_agents": 0, "active_agents": 0},
            "warnings": ["live_provider is not available."],
        }
    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    return _impl(
        session_id=session_id,
        since_signature=since_signature,
        include_events=include_events,
        ws=ws,
        gravity_home=gravity_home,
        brain_dir=brain_dir,
        metrics_home=metrics_home,
        workflow_home=workflow_home,
        registry_path=registry_path,
        home_dir=home_dir,
        plugin_roots=eff_roots,
    )


def build_initial_summary(
    *,
    view: str = "overview",
    project: str = "",
    ws: str = "",
    atelier: str = "",
    module_id: str = "",
    session_id: str = "",
    overview: Optional[dict[str, Any]] = None,
    live: Optional[dict[str, Any]] = None,
    workflow: Optional[dict[str, Any]] = None,
    metrics: Optional[dict[str, Any]] = None,
    architect: Optional[dict[str, Any]] = None,
    module_info: Optional[dict[str, Any]] = None,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    plugins_dir: Optional[Any] = None,
    home_dir: Optional[Path] = None,
    brain_dir: Optional[Path] = None,
    workflow_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    audits_dirs: Optional[Sequence[Path]] = None,
    architect_home: Optional[Path] = None,
    architect_workspace: Optional[Path] = None,
) -> str:
    """Build a concise plain-text summary for `open_gravity_dashboard` responses."""
    eff_roots = normalize_plugin_roots(plugin_roots, plugins_dir)
    req_view = (view or "overview").strip().lower() or "overview"
    ov = overview if overview is not None else get_overview(
        gravity_home=gravity_home,
        plugin_roots=eff_roots,
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
            plugin_roots=eff_roots,
            home_dir=home_dir,
        )
        if minfo.get("found"):
            parts.append(
                f"Module {minfo.get('module_id')} ({minfo.get('plugin_name')} "
                f"v{minfo.get('version') or '?'})"
            )
        else:
            parts.append(f"Module {module_id.strip()}: introuvable")

    if live is not None or req_view == "live" or "live" in tab_ids:
        lv = live if live is not None else get_live_session_state(
            session_id=session_id,
            ws=ws,
            gravity_home=gravity_home,
            brain_dir=brain_dir,
            metrics_home=metrics_home,
            workflow_home=workflow_home,
            home_dir=home_dir,
            plugin_roots=eff_roots,
        )
        lv_sum = lv.get("summary") or {}
        if lv.get("available"):
            parts.append(
                f"Live: {len(lv.get('sessions') or [])} session(s), "
                f"{lv_sum.get('active_agents', 0)}/{lv_sum.get('total_agents', 0)} agent(s) actif(s)"
            )
        else:
            parts.append("Live: aucune session active")

    if workflow is not None or req_view == "workflow" or "workflow" in tab_ids:
        wf = workflow if workflow is not None else get_workflow_state(
            ws=ws,
            gravity_home=gravity_home,
            workflow_home=workflow_home,
            plugin_roots=eff_roots,
            home_dir=home_dir,
        )
        if wf.get("available"):
            parts.append(
                f"Workflow: {wf.get('stage', 'idle')} ({wf.get('progress', '0/0')}, "
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
            plugin_roots=eff_roots,
            home_dir=home_dir,
        )
        kpis = met.get("kpis") or {}
        scope_lbl = f"projet '{project.strip()}'" if project.strip() else "global"
        parts.append(
            f"Metrics ({scope_lbl}): {kpis.get('sessions_count', 0)} session(s), "
            f"{int(kpis.get('useful_tokens') or 0)} tok. utiles, "
            f"{len(met.get('pending_sessions') or [])} en attente"
        )

    if architect is not None or req_view == "architect" or "architect" in tab_ids:
        arch = architect if architect is not None else get_architect_state(
            atelier=atelier,
            ws=ws,
            gravity_home=gravity_home,
            architect_home=architect_home,
            architect_workspace=architect_workspace,
            plugin_roots=eff_roots,
            home_dir=home_dir,
        )
        if arch.get("available"):
            parts.append(
                f"Architect: {len(arch.get('projects') or [])} projet(s), "
                f"{len(arch.get('specs') or [])} spec(s), "
                f"{len(arch.get('tasks') or [])} task(s), "
                f"{len(arch.get('audits') or [])} audit(s) code"
            )
        else:
            parts.append("Architect: atelier non détecté")

    return " | ".join(parts)


__all__ = [
    "ALLOWED_METRICS_ACTIONS",
    "build_initial_summary",
    "get_architect_state",
    "get_live_session_state",
    "get_metrics_state",
    "get_module_info",
    "get_overview",
    "get_session_detail",
    "get_workflow_state",
    "invoke_dashboard_provider",
    "read_metrics_audit",
    "run_metrics_cli_action",
]

#!/usr/bin/env python3
"""Stdio JSON-RPC 2.0 MCP App server for Gravity Core (100% stdlib Python 3.10+)."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Optional

MCP_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = MCP_DIR.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from dashboard import api  # noqa: E402
from mcp.tools_schema import build_tool_definitions  # noqa: E402
from mcp.widget_html import render_dashboard_html  # noqa: E402

SERVER_NAME = "gravity"
APP_URI = "ui://gravity/dashboard.html"
APP_MIME = "text/html;profile=mcp-app"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
MAX_TRAJECTORY_BYTES = 450_000
VALID_VIEWS = ("live", "metrics", "architect", "overview", "workflow")
VALID_METRICS_SUBS = ("overview", "sessions", "pending", "audits", "compare")
MIN_ANTIGRAVITY_MCP_APP_VERSION = (2, 34, 0)

_BUDGET_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("live", ("recent_events", "agents", "sessions")),
    ("metrics", ("records", "audits", "pending_sessions", "ignored_sessions")),
    ("workflow", ("events",)),
    ("architect", ("audits", "tasks", "specs", "projects")),
)
_CTX_PATH_KEYS = (
    "gravity_home",
    "home_dir",
    "brain_dir",
    "workflow_home",
    "metrics_home",
    "architect_home",
    "architect_workspace",
)
_HOST_CLIENT_STATE: dict[str, Any] = {"initialized": False, "ui_supported": None, "client_desc": ""}


def _reset_host_client_state() -> None:
    """Reset cached MCP host capabilities for isolated unit tests."""
    _HOST_CLIENT_STATE["initialized"] = False
    _HOST_CLIENT_STATE["ui_supported"] = None
    _HOST_CLIENT_STATE["client_desc"] = ""


def _parse_semver(raw: Any) -> Optional[tuple[int, int, int]]:
    if not isinstance(raw, str):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", raw)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _inspect_client_ui_support(params: Mapping[str, Any]) -> tuple[Optional[bool], str]:
    """Determine whether the initialized MCP client supports MCP Apps UI."""
    client_info = params.get("clientInfo")
    c_name = str(client_info.get("name") or "").strip() if isinstance(client_info, Mapping) and isinstance(client_info.get("name"), str) else ""
    c_ver = str(client_info.get("version") or "").strip() if isinstance(client_info, Mapping) and isinstance(client_info.get("version"), str) else ""
    client_desc = f"{c_name} {c_ver}".strip() if (c_name or c_ver) else "client inconnu"

    capabilities = params.get("capabilities")
    if isinstance(capabilities, Mapping):
        ext = capabilities.get("extensions")
        exp = capabilities.get("experimental")
        ui_candidates = (
            ext.get("io.modelcontextprotocol/ui") if isinstance(ext, Mapping) else None,
            exp.get("io.modelcontextprotocol/ui") if isinstance(exp, Mapping) else None,
            ext.get("com.google.antigravity/ui") if isinstance(ext, Mapping) else None,
            exp.get("com.google.antigravity/ui") if isinstance(exp, Mapping) else None,
            capabilities.get("ui"),
        )
        if any(bool(candidate) for candidate in ui_candidates):
            return True, client_desc

    low = c_name.lower()
    if "antigravity" in low and "cli" not in low:
        parsed_ver = _parse_semver(c_ver)
        if parsed_ver is not None and parsed_ver < MIN_ANTIGRAVITY_MCP_APP_VERSION:
            return False, client_desc

    if not isinstance(capabilities, Mapping) or (len(capabilities) == 0 and not c_name):
        return None, client_desc
    return False, client_desc


def _read_plugin_version() -> str:
    try:
        raw = (PLUGIN_ROOT / "plugin.json").read_bytes()
        data = json.loads((raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).decode("utf-8"))
        if isinstance(data, dict) and isinstance(data.get("version"), str) and data["version"].strip():
            return data["version"].strip()
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return "0.4.0"


SERVER_VERSION = _read_plugin_version()


def _normalize_ctx(ctx: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not ctx:
        return {}
    out: dict[str, Any] = {k: Path(ctx[k]) for k in _CTX_PATH_KEYS if ctx.get(k) is not None}
    for seq_key in ("plugin_roots", "audits_dirs"):
        if ctx.get(seq_key) is not None:
            out[seq_key] = [Path(p) for p in ctx[seq_key]]
    return out


def _tool_ok(text: str, structured: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "structuredContent": structured, "isError": False}


def _tool_err(message: str, *, structured: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"content": [{"type": "text", "text": message}], "isError": True}
    if structured is not None:
        payload["structuredContent"] = structured
    return payload


def _encoded_bytes(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _enforce_trajectory_budget(result: dict[str, Any], initial_view: str) -> dict[str, Any]:
    if _encoded_bytes(result) <= MAX_TRAJECTORY_BYTES:
        return result
    sc = result.get("structuredContent")
    if not isinstance(sc, dict):
        return result

    for sec_key, list_keys in _BUDGET_SECTIONS:
        sec = sc.get(sec_key)
        if not isinstance(sec, dict):
            continue
        for list_key in list_keys:
            items = sec.get(list_key)
            while _encoded_bytes(result) > MAX_TRAJECTORY_BYTES and isinstance(items, list) and items:
                if sec_key == "workflow":
                    items = items[len(items) // 2 + 1 :] if len(items) > 1 else []
                else:
                    sec["truncated"] = True
                    items = items[: max(0, len(items) // 2)]
                sec[list_key] = items

    for section in ("workflow", "metrics", "architect", "live"):
        if _encoded_bytes(result) > MAX_TRAJECTORY_BYTES and initial_view != section:
            sc.pop(section, None)
    return result


def _tool_definitions() -> list[dict[str, Any]]:
    return build_tool_definitions(VALID_VIEWS, APP_URI)


def _handle_open_gravity_dashboard(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raw_view = str(args.get("view") or "live").strip().lower()
    initial_view = "live" if raw_view == "workflow" else (raw_view if raw_view in VALID_VIEWS else "live")
    initial_project = str(args.get("project") or "").strip()
    initial_ws = str(args.get("ws") or "").strip()
    initial_atelier = str(args.get("atelier") or "").strip()
    initial_target = str(args.get("target") or "").strip()
    raw_sub = str(args.get("metrics_sub") or "").strip().lower()
    initial_metrics_sub = raw_sub if raw_sub in VALID_METRICS_SUBS else ""
    initial_module_id = str(args.get("module_id") or "").strip()

    overview = api.get_overview(
        gravity_home=ctx.get("gravity_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    tab_ids = {str(t.get("id") or "") for t in (overview.get("tabs") or []) if isinstance(t, dict)}
    mod_ids = {str(m.get("id") or "") for m in (overview.get("modules") or []) if isinstance(m, dict)}

    live: Optional[dict[str, Any]] = None
    if initial_view == "live" or "live" in tab_ids:
        live = api.get_live_session_state(
            session_id=initial_target if initial_view == "live" else "",
            ws=initial_ws,
            gravity_home=ctx.get("gravity_home"),
            brain_dir=ctx.get("brain_dir"),
            metrics_home=ctx.get("metrics_home"),
            workflow_home=ctx.get("workflow_home"),
            home_dir=ctx.get("home_dir"),
            plugin_roots=ctx.get("plugin_roots"),
        )

    workflow: Optional[dict[str, Any]] = None
    if raw_view == "workflow" or initial_ws or "workflow" in mod_ids:
        workflow = api.get_workflow_state(
            ws=initial_ws,
            gravity_home=ctx.get("gravity_home"),
            workflow_home=ctx.get("workflow_home"),
            plugin_roots=ctx.get("plugin_roots"),
            home_dir=ctx.get("home_dir"),
        )

    metrics: Optional[dict[str, Any]] = None
    if initial_view == "metrics" or initial_project or initial_metrics_sub or "metrics" in tab_ids:
        metrics = api.get_metrics_state(
            project=initial_project,
            gravity_home=ctx.get("gravity_home"),
            brain_dir=ctx.get("brain_dir"),
            metrics_home=ctx.get("metrics_home"),
            audits_dirs=ctx.get("audits_dirs"),
            plugin_roots=ctx.get("plugin_roots"),
            home_dir=ctx.get("home_dir"),
        )

    architect: Optional[dict[str, Any]] = None
    if initial_view == "architect" or initial_atelier or "architect" in tab_ids:
        architect = api.get_architect_state(
            atelier=initial_atelier,
            ws=initial_ws,
            gravity_home=ctx.get("gravity_home"),
            architect_home=ctx.get("architect_home"),
            architect_workspace=ctx.get("architect_workspace"),
            plugin_roots=ctx.get("plugin_roots"),
            home_dir=ctx.get("home_dir"),
        )

    module_info: Optional[dict[str, Any]] = None
    if initial_module_id:
        module_info = api.get_module_info(
            initial_module_id,
            gravity_home=ctx.get("gravity_home"),
            plugin_roots=ctx.get("plugin_roots"),
            home_dir=ctx.get("home_dir"),
        )

    summary = api.build_initial_summary(
        view=initial_view, project=initial_project, ws=initial_ws, atelier=initial_atelier,
        module_id=initial_module_id, session_id=initial_target if initial_view == "live" else "",
        overview=overview, live=live, workflow=workflow, metrics=metrics, architect=architect,
        module_info=module_info, gravity_home=ctx.get("gravity_home"), plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"), brain_dir=ctx.get("brain_dir"), workflow_home=ctx.get("workflow_home"),
        metrics_home=ctx.get("metrics_home"), audits_dirs=ctx.get("audits_dirs"),
        architect_home=ctx.get("architect_home"), architect_workspace=ctx.get("architect_workspace"),
    )

    if _HOST_CLIENT_STATE.get("initialized") and _HOST_CLIENT_STATE.get("ui_supported") is False:
        client_desc = str(_HOST_CLIENT_STATE.get("client_desc") or "client inconnu").strip() or "client inconnu"
        summary = (
            f"{summary}\n"
            f"[WARN UI] Client MCP sans support MCP Apps détecté ({client_desc}) : "
            "affichage texte uniquement ; Antigravity App v2.34.0+ requis pour l'interface graphique."
        )

    structured: dict[str, Any] = {
        "initial_view": initial_view,
        "initial_project": initial_project,
        "initial_ws": initial_ws,
        "initial_atelier": initial_atelier,
        "initial_target": initial_target,
        "initial_metrics_sub": initial_metrics_sub,
        "initial_module_id": initial_module_id,
        "overview": overview,
    }
    for key, val in (("live", live), ("workflow", workflow), ("metrics", metrics), ("architect", architect), ("module_info", module_info)):
        if val is not None:
            structured[key] = val

    return _enforce_trajectory_budget(_tool_ok(summary, structured), initial_view)


def _handle_get_overview(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    data = api.get_overview(
        since_signature=str(args.get("since_signature") or "").strip(),
        gravity_home=ctx.get("gravity_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    doctor = data.get("doctor") or {}
    return _tool_ok(f"Overview: {doctor.get('module_count', 0)} module(s), doctor={doctor.get('status', 'unknown')}.", data)


def _handle_get_workflow_state(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    data = api.get_workflow_state(
        ws=str(args.get("ws") or "").strip(),
        since_signature=str(args.get("since_signature") or "").strip(),
        gravity_home=ctx.get("gravity_home"),
        workflow_home=ctx.get("workflow_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    txt = f"Workflow: {data.get('stage', 'idle')} ({data.get('progress', '0/0')})." if data.get("available") else "Workflow: idle."
    return _tool_ok(txt, data)


def _handle_get_metrics_state(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raw_limit = args.get("limit", 100)
    try:
        limit = int(raw_limit) if raw_limit is not None else 100
    except (TypeError, ValueError):
        limit = 100
    data = api.get_metrics_state(
        project=str(args.get("project") or "").strip(),
        limit=limit,
        q=str(args.get("q") or "").strip(),
        since_signature=str(args.get("since_signature") or "").strip(),
        gravity_home=ctx.get("gravity_home"),
        brain_dir=ctx.get("brain_dir"),
        metrics_home=ctx.get("metrics_home"),
        audits_dirs=ctx.get("audits_dirs"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    res = _tool_ok(
        f"Metrics: {data.get('total_matching', 0)} session(s), "
        f"{len(data.get('pending_sessions') or [])} en attente, {len(data.get('audits') or [])} audit(s).",
        data,
    )
    return _enforce_trajectory_budget(res, "metrics")


def _handle_get_session_detail(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    target = str(args.get("target") or "").strip()
    if not target:
        return _tool_err("Le paramètre 'target' est requis.")
    data = api.get_session_detail(
        target,
        gravity_home=ctx.get("gravity_home"),
        metrics_home=ctx.get("metrics_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    if not data.get("found"):
        return _tool_err(str(data.get("error") or f"Session introuvable : {target!r}."), structured=data)
    return _enforce_trajectory_budget(_tool_ok(f"Détail session '{data.get('label') or target}' chargé.", data), "metrics")


def _handle_get_architect_state(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    data = api.get_architect_state(
        since_signature=str(args.get("since_signature") or "").strip(),
        atelier=str(args.get("atelier") or "").strip(),
        ws=str(args.get("ws") or "").strip(),
        gravity_home=ctx.get("gravity_home"),
        architect_home=ctx.get("architect_home"),
        architect_workspace=ctx.get("architect_workspace"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    txt = (
        f"Architect: {len(data.get('projects') or [])} projet(s), {len(data.get('specs') or [])} spec(s), "
        f"{len(data.get('tasks') or [])} task(s), {len(data.get('audits') or [])} audit(s) code."
        if data.get("available")
        else "Architect: atelier non détecté."
    )
    return _enforce_trajectory_budget(_tool_ok(txt, data), "architect")


def _handle_get_module_info(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    module_id = str(args.get("module_id") or "").strip()
    if not module_id:
        return _tool_err("Le paramètre 'module_id' est requis.")
    data = api.get_module_info(module_id, gravity_home=ctx.get("gravity_home"), plugin_roots=ctx.get("plugin_roots"), home_dir=ctx.get("home_dir"))
    if not data.get("found"):
        return _tool_err(str(data.get("error") or f"Module introuvable : {module_id!r}."), structured=data)
    return _tool_ok(f"Module '{data.get('module_id')}' ({data.get('plugin_name')}) chargé.", data)


def _handle_get_live_session(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    data = api.get_live_session_state(
        session_id=str(args.get("session_id") or "").strip(),
        since_signature=str(args.get("since_signature") or "").strip(),
        include_events=bool(args.get("include_events", True)),
        ws=str(args.get("ws") or "").strip(),
        gravity_home=ctx.get("gravity_home"),
        brain_dir=ctx.get("brain_dir"),
        metrics_home=ctx.get("metrics_home"),
        workflow_home=ctx.get("workflow_home"),
        home_dir=ctx.get("home_dir"),
        plugin_roots=ctx.get("plugin_roots"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    lv_sum = data.get("summary") or {}
    txt = (
        f"Live: {len(data.get('sessions') or [])} session(s), "
        f"{lv_sum.get('active_agents', 0)}/{lv_sum.get('total_agents', 0)} agent(s) actif(s)."
        if data.get("available")
        else "Live: aucune session active."
    )
    return _tool_ok(txt, data)


def _handle_metrics_action(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    data = api.run_metrics_cli_action(
        action,
        conversation_id=str(args.get("conversation_id") or ""),
        slug=str(args.get("slug") or ""),
        target=str(args.get("target") or ""),
        label=str(args.get("label") or ""),
        project=str(args.get("project") or ""),
        note=str(args.get("note") or ""),
        reason=str(args.get("reason") or ""),
        workspace=str(args.get("workspace") or ""),
        full=bool(args.get("full", False)),
        purge_reports=bool(args.get("purge_reports", True)),
        gravity_home=ctx.get("gravity_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
        metrics_home=ctx.get("metrics_home"),
        brain_dir=ctx.get("brain_dir"),
    )
    if not data.get("ok"):
        return _tool_err(str(data.get("message") or data.get("error") or "Action Metrics échouée."), structured=data)
    return _tool_ok(str(data.get("message") or f"Action {action} exécutée."), data)


def _handle_read_audit(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    target = str(args.get("path") or args.get("audit_id") or args.get("target") or "").strip()
    if not target:
        return _tool_err("Le paramètre 'path' est requis.")
    data = api.read_metrics_audit(
        target,
        gravity_home=ctx.get("gravity_home"),
        metrics_home=ctx.get("metrics_home"),
        audits_dirs=ctx.get("audits_dirs"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    if not data.get("found"):
        return _tool_err(str(data.get("error") or f"Audit introuvable : {target!r}."), structured=data)
    return _tool_ok(f"Audit '{data.get('title') or target}' chargé.", data)


_TOOL_DISPATCH = {
    "open_gravity_dashboard": _handle_open_gravity_dashboard,
    "gravity_get_live_session": _handle_get_live_session,
    "gravity_get_overview": _handle_get_overview,
    "gravity_get_workflow_state": _handle_get_workflow_state,
    "gravity_get_metrics_state": _handle_get_metrics_state,
    "gravity_get_session_detail": _handle_get_session_detail,
    "gravity_metrics_action": _handle_metrics_action,
    "gravity_read_audit": _handle_read_audit,
    "gravity_get_architect_state": _handle_get_architect_state,
    "gravity_get_module_info": _handle_get_module_info,
}


def _rpc_err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_jsonrpc_message(
    msg: Any, *, ctx: Optional[Mapping[str, Any]] = None
) -> Optional[dict[str, Any]]:
    """Process one MCP JSON-RPC 2.0 request or notification (None returned for notifications)."""
    if not isinstance(msg, dict):
        return _rpc_err(None, -32600, "Invalid Request")
    req_id = msg.get("id")
    if "id" not in msg or req_id is None:
        return None
    method = msg.get("method")
    if not isinstance(method, str):
        return _rpc_err(req_id, -32600, "Invalid Request")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    norm_ctx = _normalize_ctx(ctx)

    try:
        if method == "initialize":
            ui_supported, client_desc = _inspect_client_ui_support(params)
            _HOST_CLIENT_STATE.update({"initialized": True, "ui_supported": ui_supported, "client_desc": client_desc})
            result: dict[str, Any] = {
                "protocolVersion": str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": _tool_definitions()}
        elif method == "tools/call":
            tool_name = str(params.get("name") or "")
            tool_args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            handler = _TOOL_DISPATCH.get(tool_name)
            if handler is None:
                return _rpc_err(req_id, -32602, f"Unknown tool: {tool_name}")
            try:
                result = handler(tool_args, norm_ctx)
            except Exception as exc:
                result = _tool_err(str(exc))
        elif method == "resources/list":
            result = {
                "resources": [{
                    "uri": APP_URI, "name": "gravity_dashboard", "title": "Gravity",
                    "description": "Tableau de bord unifié Gravity (Core, Workflow Live, Metrics, modules OCP).",
                    "mimeType": APP_MIME, "_meta": {"ui": {"prefersBorder": False}},
                }]
            }
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "resources/read":
            uri = str(params.get("uri") or "")
            if uri != APP_URI:
                return _rpc_err(req_id, -32002, f"Resource not found: {uri}")
            result = {"contents": [{"uri": APP_URI, "mimeType": APP_MIME, "text": render_dashboard_html(), "_meta": {"ui": {"prefersBorder": False}}}]}
        elif method == "prompts/list":
            result = {"prompts": []}
        else:
            return _rpc_err(req_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        return _rpc_err(req_id, -32603, str(exc))

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _write_jsonrpc(payload: dict[str, Any]) -> None:
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def main() -> int:
    while True:
        raw_line = sys.stdin.buffer.readline()
        if not raw_line:
            break
        text = raw_line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            msg = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            _write_jsonrpc(_rpc_err(None, -32700, "Parse error"))
            continue
        response = handle_jsonrpc_message(msg)
        if response is not None:
            _write_jsonrpc(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stdio JSON-RPC 2.0 MCP App server for Gravity Core (100% stdlib Python 3.10+)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional

MCP_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = MCP_DIR.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from dashboard import api  # noqa: E402
from mcp.widget_html import render_dashboard_html  # noqa: E402

SERVER_NAME = "gravity"
APP_URI = "ui://gravity/dashboard.html"
APP_MIME = "text/html;profile=mcp-app"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
MAX_TRAJECTORY_BYTES = 450_000
VALID_VIEWS = ("overview", "workflow", "metrics", "bridge", "architect", "module")


def _read_plugin_version() -> str:
    manifest_path = PLUGIN_ROOT / "plugin.json"
    try:
        raw = manifest_path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            ver = data.get("version")
            if isinstance(ver, str) and ver.strip():
                return ver.strip()
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return "0.3.0"


SERVER_VERSION = _read_plugin_version()


def _normalize_ctx(ctx: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not ctx:
        return {}
    out: dict[str, Any] = {}
    for key in (
        "gravity_home",
        "home_dir",
        "workflow_home",
        "metrics_home",
        "bridge_home",
        "db_path",
        "architect_home",
        "architect_workspace",
    ):
        val = ctx.get(key)
        if val is not None:
            out[key] = Path(val)
    for seq_key in ("plugin_roots", "audits_dirs"):
        val = ctx.get(seq_key)
        if val is not None:
            out[seq_key] = [Path(p) for p in val]
    return out


def _tool_ok(text: str, structured: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": False,
    }


def _tool_err(
    message: str,
    *,
    structured: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }
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

    met = sc.get("metrics")
    if isinstance(met, dict):
        for list_key in ("records", "audits", "pending_sessions", "ignored_sessions"):
            items = met.get(list_key)
            while _encoded_bytes(result) > MAX_TRAJECTORY_BYTES and isinstance(items, list) and items:
                met["truncated"] = True
                items = items[: max(0, len(items) // 2)]
                met[list_key] = items

    wf = sc.get("workflow")
    if isinstance(wf, dict):
        events = wf.get("events")
        while _encoded_bytes(result) > MAX_TRAJECTORY_BYTES and isinstance(events, list) and events:
            events = events[len(events) // 2 + 1 :] if len(events) > 1 else []
            wf["events"] = events

    br = sc.get("bridge")
    if isinstance(br, dict):
        for list_key in ("threads", "jobs", "workspaces"):
            items = br.get(list_key)
            while _encoded_bytes(result) > MAX_TRAJECTORY_BYTES and isinstance(items, list) and items:
                br["truncated"] = True
                items = items[: max(0, len(items) // 2)]
                br[list_key] = items

    arch = sc.get("architect")
    if isinstance(arch, dict):
        for list_key in ("audits", "handoffs", "specs", "projects"):
            items = arch.get(list_key)
            while _encoded_bytes(result) > MAX_TRAJECTORY_BYTES and isinstance(items, list) and items:
                arch["truncated"] = True
                items = items[: max(0, len(items) // 2)]
                arch[list_key] = items

    for section in ("metrics", "workflow", "bridge", "architect"):
        if _encoded_bytes(result) > MAX_TRAJECTORY_BYTES and initial_view != section:
            sc.pop(section, None)

    return result


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "open_gravity_dashboard",
            "title": "Ouvrir Gravity Dashboard",
            "description": (
                "Ouvre le tableau de bord unifié Gravity (Overview/Doctor, Workflow Live, "
                "Metrics, Bridge RO, Architect RO et modules OCP) dans Antigravity."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": list(VALID_VIEWS),
                        "description": "Vue initiale : overview, workflow, metrics, bridge, architect ou module.",
                    },
                    "project": {
                        "type": "string",
                        "description": "Filtre projet initial pour la vue Metrics.",
                    },
                    "ws": {
                        "type": "string",
                        "description": "Workspace initial pour la vue Workflow Live et repli Architect (ws_hint).",
                    },
                    "atelier": {
                        "type": "string",
                        "description": "Chemin d'atelier Architect cible (optionnel).",
                    },
                    "module_id": {
                        "type": "string",
                        "description": "Identifiant module cible si view=module.",
                    },
                },
            },
            "_meta": {
                "ui": {
                    "resourceUri": APP_URI,
                    "visibility": ["model", "app"],
                },
                "com.google.antigravity/ui": {
                    "entrypoints": [
                        {"type": "aux_pane", "title": "Gravity"},
                        {"type": "global", "title": "Gravity"},
                    ]
                },
            },
        },
        {
            "name": "gravity_get_overview",
            "title": "État Overview Gravity",
            "description": "Retourne l'état Core/Doctor, les onglets et les dossiers legacy en lecture seule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour fast-path inchangé.",
                    }
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_workflow_state",
            "title": "État Workflow Live",
            "description": "Retourne l'état temps réel lecture seule de Gravity Workflow pour un workspace.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ws": {
                        "type": "string",
                        "description": "Chemin ou nom du workspace cible.",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour polling incrémental.",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_metrics_state",
            "title": "État Metrics & Audits Agents",
            "description": "Retourne KPIs, sessions filtrées, file pending et audits agents en lecture seule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Filtre projet optionnel.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximal de sessions récentes retournées.",
                    },
                    "q": {
                        "type": "string",
                        "description": "Recherche texte sur label, modèle, projet ou ID.",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour fast-path inchangé.",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_session_detail",
            "title": "Détail d'une session Metrics",
            "description": "Charge en lecture seule le rapport JSON confiné d'une session sans trajectoire brute.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Slug, label ou conversation_id de la session.",
                    }
                },
                "required": ["target"],
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_bridge_state",
            "title": "État Gravity Bridge (RO)",
            "description": "Retourne workspaces, sidecars, threads et jobs Bridge en lecture seule (?mode=ro).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filtre statut des threads : '', 'open' ou 'done'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximal de threads/jobs retournés (1..200).",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour fast-path inchangé.",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_architect_state",
            "title": "État Gravity Architect (RO)",
            "description": "Retourne ECOSYSTEM.md, delta.md, projets, specs, handoffs et audits/code/ en lecture seule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "atelier": {
                        "type": "string",
                        "description": "Chemin d'atelier Architect cible (optionnel).",
                    },
                    "ws": {
                        "type": "string",
                        "description": "Indice workspace courant pour repli Architect (ws_hint).",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour fast-path inchangé.",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_module_info",
            "title": "Inspection d'un module OCP",
            "description": "Retourne le contrat et le listing superficiel du stockage d'un module Gravity.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "module_id": {
                        "type": "string",
                        "description": "Identifiant du module Gravity (ex. bridge, architect).",
                    }
                },
                "required": ["module_id"],
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
    ]


def _handle_open_gravity_dashboard(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raw_view = str(args.get("view") or "overview").strip().lower()
    initial_view = raw_view if raw_view in VALID_VIEWS else "overview"
    initial_project = str(args.get("project") or "").strip()
    initial_ws = str(args.get("ws") or "").strip()
    initial_atelier = str(args.get("atelier") or "").strip()
    initial_module_id = str(args.get("module_id") or "").strip()

    overview = api.get_overview(
        gravity_home=ctx.get("gravity_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    tab_ids = {str(t.get("id") or "") for t in (overview.get("tabs") or []) if isinstance(t, dict)}

    workflow: Optional[dict[str, Any]] = None
    if initial_view == "workflow" or initial_ws or "workflow" in tab_ids:
        workflow = api.get_workflow_state(
            ws=initial_ws,
            gravity_home=ctx.get("gravity_home"),
            workflow_home=ctx.get("workflow_home"),
        )

    metrics: Optional[dict[str, Any]] = None
    if initial_view == "metrics" or initial_project or "metrics" in tab_ids:
        metrics = api.get_metrics_state(
            project=initial_project,
            gravity_home=ctx.get("gravity_home"),
            metrics_home=ctx.get("metrics_home"),
            audits_dirs=ctx.get("audits_dirs"),
        )

    bridge: Optional[dict[str, Any]] = None
    if initial_view == "bridge" or "bridge" in tab_ids:
        bridge = api.get_bridge_state(
            gravity_home=ctx.get("gravity_home"),
            bridge_home=ctx.get("bridge_home"),
            db_path=ctx.get("db_path"),
        )

    architect: Optional[dict[str, Any]] = None
    if initial_view == "architect" or initial_atelier or "architect" in tab_ids:
        architect = api.get_architect_state(
            atelier=initial_atelier,
            ws=initial_ws,
            gravity_home=ctx.get("gravity_home"),
            bridge_home=ctx.get("bridge_home"),
            architect_home=ctx.get("architect_home"),
            architect_workspace=ctx.get("architect_workspace"),
        )

    module_info: Optional[dict[str, Any]] = None
    if initial_view == "module" and initial_module_id:
        module_info = api.get_module_info(
            initial_module_id,
            gravity_home=ctx.get("gravity_home"),
            plugin_roots=ctx.get("plugin_roots"),
        )

    summary = api.build_initial_summary(
        view=initial_view,
        project=initial_project,
        ws=initial_ws,
        atelier=initial_atelier,
        module_id=initial_module_id,
        overview=overview,
        workflow=workflow,
        metrics=metrics,
        bridge=bridge,
        architect=architect,
        module_info=module_info,
        gravity_home=ctx.get("gravity_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
        workflow_home=ctx.get("workflow_home"),
        metrics_home=ctx.get("metrics_home"),
        audits_dirs=ctx.get("audits_dirs"),
        bridge_home=ctx.get("bridge_home"),
        db_path=ctx.get("db_path"),
        architect_home=ctx.get("architect_home"),
        architect_workspace=ctx.get("architect_workspace"),
    )

    structured: dict[str, Any] = {
        "initial_view": initial_view,
        "initial_project": initial_project,
        "initial_ws": initial_ws,
        "initial_atelier": initial_atelier,
        "initial_module_id": initial_module_id,
        "overview": overview,
    }
    if workflow is not None:
        structured["workflow"] = workflow
    if metrics is not None:
        structured["metrics"] = metrics
    if bridge is not None:
        structured["bridge"] = bridge
    if architect is not None:
        structured["architect"] = architect
    if module_info is not None:
        structured["module_info"] = module_info

    return _enforce_trajectory_budget(_tool_ok(summary, structured), initial_view)


def _handle_get_overview(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    since_sig = str(args.get("since_signature") or "").strip()
    data = api.get_overview(
        since_signature=since_sig,
        gravity_home=ctx.get("gravity_home"),
        plugin_roots=ctx.get("plugin_roots"),
        home_dir=ctx.get("home_dir"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    doctor = data.get("doctor") or {}
    return _tool_ok(
        f"Overview: {doctor.get('module_count', 0)} module(s), doctor={doctor.get('status', 'unknown')}.",
        data,
    )


def _handle_get_workflow_state(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    ws = str(args.get("ws") or "").strip()
    since_sig = str(args.get("since_signature") or "").strip()
    data = api.get_workflow_state(
        ws=ws,
        since_signature=since_sig,
        gravity_home=ctx.get("gravity_home"),
        workflow_home=ctx.get("workflow_home"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    if data.get("available"):
        txt = f"Workflow: {data.get('stage', 'idle')} ({data.get('progress', '0/8')})."
    else:
        txt = "Workflow: idle."
    return _tool_ok(txt, data)


def _handle_get_metrics_state(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    project = str(args.get("project") or "").strip()
    q = str(args.get("q") or "").strip()
    since_sig = str(args.get("since_signature") or "").strip()
    raw_limit = args.get("limit", 100)
    try:
        limit = int(raw_limit) if raw_limit is not None else 100
    except (TypeError, ValueError):
        limit = 100

    data = api.get_metrics_state(
        project=project,
        limit=limit,
        q=q,
        since_signature=since_sig,
        gravity_home=ctx.get("gravity_home"),
        metrics_home=ctx.get("metrics_home"),
        audits_dirs=ctx.get("audits_dirs"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    res = _tool_ok(
        (
            f"Metrics: {data.get('total_matching', 0)} session(s), "
            f"{len(data.get('pending_sessions') or [])} en attente, "
            f"{len(data.get('audits') or [])} audit(s)."
        ),
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
    )
    if not data.get("found"):
        return _tool_err(str(data.get("error") or f"Session introuvable : {target!r}."), structured=data)
    res = _tool_ok(f"Détail session '{data.get('label') or target}' chargé.", data)
    return _enforce_trajectory_budget(res, "metrics")


def _handle_get_bridge_state(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "").strip().lower()
    since_sig = str(args.get("since_signature") or "").strip()
    raw_limit = args.get("limit", 50)
    try:
        limit = int(raw_limit) if raw_limit is not None else 50
    except (TypeError, ValueError):
        limit = 50

    data = api.get_bridge_state(
        since_signature=since_sig,
        status=status,
        limit=limit,
        gravity_home=ctx.get("gravity_home"),
        bridge_home=ctx.get("bridge_home"),
        db_path=ctx.get("db_path"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    kpis = data.get("kpis") or {}
    txt = (
        f"Bridge: {kpis.get('online_count', 0)}/{kpis.get('workspaces_count', 0)} sidecar(s), "
        f"{kpis.get('threads_open', 0)} ouvert(s)."
        if data.get("available")
        else "Bridge: inactif."
    )
    return _enforce_trajectory_budget(_tool_ok(txt, data), "bridge")


def _handle_get_architect_state(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    atelier = str(args.get("atelier") or "").strip()
    ws = str(args.get("ws") or "").strip()
    since_sig = str(args.get("since_signature") or "").strip()
    data = api.get_architect_state(
        since_signature=since_sig,
        atelier=atelier,
        ws=ws,
        gravity_home=ctx.get("gravity_home"),
        bridge_home=ctx.get("bridge_home"),
        architect_home=ctx.get("architect_home"),
        architect_workspace=ctx.get("architect_workspace"),
    )
    if data.get("unchanged"):
        return _tool_ok("Inchangé.", data)
    txt = (
        f"Architect: {len(data.get('projects') or [])} projet(s), "
        f"{len(data.get('specs') or [])} spec(s), "
        f"{len(data.get('handoffs') or [])} handoff(s), "
        f"{len(data.get('audits') or [])} audit(s) code."
        if data.get("available")
        else "Architect: atelier non détecté."
    )
    return _enforce_trajectory_budget(_tool_ok(txt, data), "architect")


def _handle_get_module_info(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    module_id = str(args.get("module_id") or "").strip()
    if not module_id:
        return _tool_err("Le paramètre 'module_id' est requis.")
    data = api.get_module_info(
        module_id,
        gravity_home=ctx.get("gravity_home"),
        plugin_roots=ctx.get("plugin_roots"),
    )
    if not data.get("found"):
        return _tool_err(str(data.get("error") or f"Module introuvable : {module_id!r}."), structured=data)
    return _tool_ok(
        f"Module '{data.get('module_id')}' ({data.get('plugin_name')}) chargé.",
        data,
    )


_TOOL_DISPATCH = {
    "open_gravity_dashboard": _handle_open_gravity_dashboard,
    "gravity_get_overview": _handle_get_overview,
    "gravity_get_workflow_state": _handle_get_workflow_state,
    "gravity_get_metrics_state": _handle_get_metrics_state,
    "gravity_get_session_detail": _handle_get_session_detail,
    "gravity_get_bridge_state": _handle_get_bridge_state,
    "gravity_get_architect_state": _handle_get_architect_state,
    "gravity_get_module_info": _handle_get_module_info,
}


def handle_jsonrpc_message(
    msg: Any,
    *,
    ctx: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Process one MCP JSON-RPC 2.0 request or notification (None returned for notifications)."""
    if not isinstance(msg, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    req_id = msg.get("id")
    has_id = "id" in msg and req_id is not None
    method = msg.get("method")
    params = msg.get("params")
    if not isinstance(params, dict):
        params = {}

    if not has_id:
        return None

    if not isinstance(method, str):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    norm_ctx = _normalize_ctx(ctx)

    try:
        if method == "initialize":
            client_proto = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
            result: dict[str, Any] = {
                "protocolVersion": client_proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": _tool_definitions()}
        elif method == "tools/call":
            tool_name = str(params.get("name") or "")
            tool_args = params.get("arguments")
            if not isinstance(tool_args, dict):
                tool_args = {}
            handler = _TOOL_DISPATCH.get(tool_name)
            if handler is None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
                }
            try:
                result = handler(tool_args, norm_ctx)
            except Exception as exc:
                result = _tool_err(str(exc))
        elif method == "resources/list":
            result = {
                "resources": [
                    {
                        "uri": APP_URI,
                        "name": "gravity_dashboard",
                        "title": "Gravity",
                        "description": "Tableau de bord unifié Gravity (Core, Workflow Live, Metrics, modules OCP).",
                        "mimeType": APP_MIME,
                        "_meta": {"ui": {"prefersBorder": False}},
                    }
                ]
            }
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "resources/read":
            uri = str(params.get("uri") or "")
            if uri != APP_URI:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": f"Resource not found: {uri}"},
                }
            result = {
                "contents": [
                    {
                        "uri": APP_URI,
                        "mimeType": APP_MIME,
                        "text": render_dashboard_html(),
                        "_meta": {"ui": {"prefersBorder": False}},
                    }
                ]
            }
        elif method == "prompts/list":
            result = {"prompts": []}
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": str(exc)},
        }

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _write_jsonrpc(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8"))
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
            _write_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
            )
            continue
        response = handle_jsonrpc_message(msg)
        if response is not None:
            _write_jsonrpc(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

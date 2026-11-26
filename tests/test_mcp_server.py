"""Isolated unit and stdio tests for plugin/mcp/server.py & widget_html.py (TemporaryDirectory only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.registry import write_modules_registry  # noqa: E402
from mcp import server as mcp_server  # noqa: E402
from mcp.widget_html import render_dashboard_html  # noqa: E402


def _write_fake_plugin(
    plugins_root: Path,
    *,
    mod_id: str,
    plugin_name: str,
    version: str = "0.2.0",
    ui_mode: str = "none",
) -> Path:
    mod_dir = plugins_root / plugin_name
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": plugin_name,
        "displayName": plugin_name.replace("-", " ").title(),
        "version": version,
        "description": f"Fake plugin {plugin_name}",
        "logo": "assets/logo.svg",
        "suggestedPrompts": ["One", "Two", "Three"],
        "author": {"name": "Gravity Contributors"},
        "homepage": f"https://github.com/BSourichanh/{plugin_name}",
        "repository": f"https://github.com/BSourichanh/{plugin_name}.git",
    }
    contract = {
        "schema_version": 1,
        "id": mod_id,
        "plugin_name": plugin_name,
        "role": f"Role {mod_id}",
        "storage": {
            "subdir": mod_id,
            "env_override": f"GRAVITY_{mod_id.upper()}_HOME",
        },
        "commands": [f"/{plugin_name}"],
        "capabilities": ["read-only-test"],
        "ui": {"mode": ui_mode, "target": "gravity"},
        "signals": {"produces": [], "consumes": []},
    }
    (mod_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (mod_dir / "config" / "module.json").write_text(json.dumps(contract), encoding="utf-8")
    return mod_dir


class TestMcpServer(unittest.TestCase):
    def setUp(self) -> None:
        mcp_server._reset_host_client_state()

    def tearDown(self) -> None:
        mcp_server._reset_host_client_state()

    def test_protocol_lifecycle_tools_and_resources(self) -> None:
        self.assertEqual(mcp_server.SERVER_NAME, "gravity")
        self.assertEqual(mcp_server.APP_URI, "ui://gravity/dashboard.html")
        self.assertEqual(mcp_server.APP_MIME, "text/html;profile=mcp-app")
        self.assertEqual(mcp_server.MAX_TRAJECTORY_BYTES, 450_000)

        init_resp = mcp_server.handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
        )
        self.assertIsNotNone(init_resp)
        assert init_resp is not None
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "gravity")
        self.assertEqual(init_resp["result"]["protocolVersion"], "2025-06-18")

        notif_resp = mcp_server.handle_jsonrpc_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        self.assertIsNone(notif_resp)

        ping_resp = mcp_server.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        self.assertEqual(ping_resp["result"], {})  # type: ignore[index]

        tools_resp = mcp_server.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        tools = tools_resp["result"]["tools"]  # type: ignore[index]
        names = [t["name"] for t in tools]
        self.assertEqual(
            names,
            [
                "open_gravity_dashboard",
                "gravity_get_live_session",
                "gravity_get_overview",
                "gravity_get_workflow_state",
                "gravity_get_metrics_state",
                "gravity_get_session_detail",
                "gravity_metrics_action",
                "gravity_read_audit",
                "gravity_get_architect_state",
                "gravity_get_module_info",
            ],
        )
        self.assertNotIn("gravity_get_bridge_state", names)
        self.assertEqual(mcp_server.VALID_VIEWS, ("live", "metrics", "architect", "overview", "workflow"))

        open_tool = tools[0]
        self.assertIn("atelier", open_tool["inputSchema"]["properties"])
        self.assertIn("target", open_tool["inputSchema"]["properties"])
        self.assertIn("metrics_sub", open_tool["inputSchema"]["properties"])
        self.assertEqual(open_tool["_meta"]["ui"]["resourceUri"], mcp_server.APP_URI)
        self.assertEqual(open_tool["_meta"]["ui"]["visibility"], ["model", "app"])
        eps = open_tool["_meta"]["com.google.antigravity/ui"]["entrypoints"]
        self.assertEqual([e["type"] for e in eps], ["aux_pane", "global"])

        arch_tool = next(t for t in tools if t["name"] == "gravity_get_architect_state")
        self.assertIn("atelier", arch_tool["inputSchema"]["properties"])

        for app_tool in tools[1:]:
            self.assertEqual(app_tool["_meta"]["ui"]["visibility"], ["app"])

        res_list = mcp_server.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
        res_items = res_list["result"]["resources"]  # type: ignore[index]
        self.assertEqual(len(res_items), 1)
        self.assertEqual(res_items[0]["uri"], mcp_server.APP_URI)
        self.assertFalse(res_items[0]["_meta"]["ui"]["prefersBorder"])

        res_read = mcp_server.handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": mcp_server.APP_URI}}
        )
        c0 = res_read["result"]["contents"][0]  # type: ignore[index]
        self.assertEqual(c0["mimeType"], mcp_server.APP_MIME)
        html_txt = c0["text"]
        self.assertEqual(html_txt, render_dashboard_html())
        self.assertLess(len(html_txt.encode("utf-8")), 150 * 1024)
        for forbidden in ("innerHTML", "http://", "https://", "window.confirm", "window.alert", "window.prompt"):
            self.assertNotIn(forbidden, html_txt)
        for required in (
            "ui/initialize",
            "2026-01-26",
            "ui/notifications/initialized",
            "ui/notifications/host-context-changed",
            "com.google.antigravity/toggle-aux-pane",
            'addEventListener("message"',
            "renderArchitectView",
            "renderLiveView",
            "renderMetricsUnifiedView",
            "gravity_get_live_session",
            "gravity_metrics_action",
            "gravity_read_audit",
            "since_signature",
            "captureFocusAndScroll",
            "g-arch-ws",
            "g-slideover",
            "g-metrics-project",
            "proj-grid",
            "wave-group",
            "nav-history",
        ):
            self.assertIn(required, html_txt)
        for absent in (
            "renderBridgeView",
            "renderBridgeSvgChart",
            "renderWorkflowView",
            "renderArchitectSvgChart",
            "gravity_get_bridge_state",
            "loadBridgeState",
            "Tarif 2026",
            "Tarif 2027",
            "metricsTariff",
            "set-tariff",
        ):
            self.assertNotIn(absent, html_txt)

        bad_read = mcp_server.handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 6, "method": "resources/read", "params": {"uri": "ui://gravity/nope.html"}}
        )
        self.assertEqual(bad_read["error"]["code"], -32002)  # type: ignore[index]

        bad_tool = mcp_server.handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "unknown", "arguments": {}}}
        )
        self.assertEqual(bad_tool["error"]["code"], -32602)  # type: ignore[index]

        bad_method = mcp_server.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 8, "method": "nope/method"})
        self.assertEqual(bad_method["error"]["code"], -32601)  # type: ignore[index]

    def test_all_seven_tools_with_isolated_ctx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            wf_home = g_home / "workflow"
            met_home = g_home / "metrics"
            atelier_dir = tmp_path / "gravity-studio"
            (g_home / "core").mkdir(parents=True)
            (wf_home / "workspaces" / "proj-1").mkdir(parents=True)
            (met_home / "data").mkdir(parents=True)
            (met_home / "reports").mkdir(parents=True)
            (atelier_dir / "tracking" / "snapshots").mkdir(parents=True)
            (atelier_dir / "audits" / "code").mkdir(parents=True)
            (atelier_dir / "audits" / "agents").mkdir(parents=True)

            (atelier_dir / "ECOSYSTEM.md").write_text("# Atelier\n", encoding="utf-8")
            (atelier_dir / "projects.json").write_text(
                json.dumps({"schema_version": 5, "projects": [{"id": "gravity", "name": "Gravity", "path": "../gravity"}]}),
                encoding="utf-8",
            )
            (g_home / "architect").mkdir(parents=True)
            (g_home / "architect" / "ateliers.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ateliers": [
                            {
                                "workspace_path": str(atelier_dir.resolve()),
                                "workspace_name": "Studio",
                                "updated_at": "2026-11-23T22:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (atelier_dir / "tracking" / "snapshots" / "delta.md").write_text(
                "- **Date :** `2026-11-23T22:00:00Z`\n- **Statut éditorial :** `NO_EDITORIAL_CHANGES`\n",
                encoding="utf-8",
            )
            (atelier_dir / "audits" / "code" / "README.md").write_text("# Code Index\n", encoding="utf-8")
            (atelier_dir / "audits" / "code" / "2026-11-23-audit-code-gravity.md").write_text(
                "# Audit Code\n\n- **Verdict :** `PASS`\n",
                encoding="utf-8",
            )
            (atelier_dir / "audits" / "agents" / "2026-11-23-agent.md").write_text(
                "# Secret Agent Audit\n\nVerdict: BLOQUANT\n",
                encoding="utf-8",
            )

            _write_fake_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_fake_plugin(plugins_root, mod_id="workflow", plugin_name="gravity-workflow", ui_mode="none")
            met_plugin = _write_fake_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="none")
            (met_plugin / "scripts").mkdir(parents=True)
            (met_plugin / "scripts" / "cli.py").write_text(
                "import json, sys\nprint(json.dumps({'ok': True, 'argv': sys.argv[1:]}))\n",
                encoding="utf-8",
            )
            _write_fake_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect", ui_mode="none")

            mods = []
            for mod_id, pname, ui_mode in (
                ("core", "gravity", "core"),
                ("workflow", "gravity-workflow", "none"),
                ("metrics", "gravity-metrics", "none"),
                ("architect", "gravity-architect", "none"),
            ):
                mods.append(
                    {
                        "id": mod_id,
                        "plugin_name": pname,
                        "plugin_dir": str(plugins_root / pname),
                        "display_name": pname.title(),
                        "version": "0.2.0",
                        "valid": True,
                        "errors": [],
                        "storage": {"subdir": mod_id, "env_override": f"GRAVITY_{mod_id.upper()}_HOME"},
                        "commands": [f"/{pname}"],
                        "capabilities": ["test"],
                        "ui": {"mode": ui_mode, "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                    }
                )
            write_modules_registry(g_home, mods)

            brain_dir = tmp_path / "brain"
            live_cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            live_tpath = brain_dir / live_cid / ".system_generated" / "logs" / "transcript.jsonl"
            live_tpath.parent.mkdir(parents=True)
            live_tpath.write_text(
                json.dumps(
                    {
                        "step_index": 0,
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": "2026-11-25T12:00:00Z",
                        "model": "gemini-4-neon-high",
                        "input_tokens": 500,
                        "cache_read_tokens": 1000,
                        "output_tokens": 120,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            ws_dir = tmp_path / "demo-ws"
            ws_dir.mkdir()
            state_file = wf_home / "workspaces" / "proj-1" / "live_state.json"
            state_file.write_text(
                json.dumps(
                    {
                        "stage": "build",
                        "progress": "3/8",
                        "mode": "evo",
                        "preset_profile": "standard",
                        "guard_status": "ON",
                        "nodes": {"planner": "done", "builder": "running", "reviewer": ""},
                        "events": [{"type": "step", "summary": "Building MCP server"}],
                    }
                ),
                encoding="utf-8",
            )
            (wf_home / "live_workspaces.json").write_text(
                json.dumps({"workspaces": [{"workspace_path": str(ws_dir), "state_path": str(state_file), "updated_at": "2026-11-23T20:00:00Z"}]}),
                encoding="utf-8",
            )

            hist_rec = {
                "conversation_id": "11111111-2222-3333-4444-555555555555",
                "label": "demo-session",
                "detail_slug": "demo-session",
                "project": "gravity",
                "status": "archived",
                "cost_usd": 0.42,
                "cost_2027_usd": 0.55,
                "cache_hit_rate_pct": 85.0,
                "total_tokens": 12000,
                "llm_calls": 4,
            }
            (met_home / "data" / "history.jsonl").write_text(json.dumps(hist_rec) + "\n", encoding="utf-8")
            (met_home / "reports" / "demo-session.json").write_text(
                json.dumps({"label": "demo-session", "summary": {"cost_usd": {"total": 0.42}}, "trajectory": ["secret"]}),
                encoding="utf-8",
            )
            (met_home / "reports" / "demo-session.md").write_text("# Demo Report\n", encoding="utf-8")

            ctx = {
                "gravity_home": g_home,
                "plugin_roots": [plugins_root],
                "home_dir": fake_user,
                "brain_dir": brain_dir,
                "workflow_home": wf_home,
                "metrics_home": met_home,
                "audits_dirs": [atelier_dir / "audits" / "agents"],
            }

            open_res = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "open_gravity_dashboard", "arguments": {}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(open_res["isError"])
            self.assertLessEqual(len(json.dumps(open_res, ensure_ascii=False).encode("utf-8")), mcp_server.MAX_TRAJECTORY_BYTES)
            sc = open_res["structuredContent"]
            self.assertEqual(sc["initial_view"], "live")
            self.assertEqual([t["id"] for t in sc["overview"]["tabs"]], ["live", "architect", "metrics", "overview"])
            self.assertTrue(sc["live"]["available"])
            self.assertEqual(sc["workflow"]["stage"], "build")
            self.assertEqual(sc["metrics"]["kpis"]["sessions_count"], 1)
            self.assertNotIn("bridge", sc)
            self.assertTrue(sc["architect"]["available"])

            open_wf = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 110, "method": "tools/call", "params": {"name": "open_gravity_dashboard", "arguments": {"view": "workflow"}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertEqual(open_wf["initial_view"], "live")

            open_met = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 111,
                    "method": "tools/call",
                    "params": {"name": "open_gravity_dashboard", "arguments": {"view": "metrics", "metrics_sub": "audits", "target": "demo-session"}},
                },
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertEqual(open_met["initial_view"], "metrics")
            self.assertEqual(open_met["initial_metrics_sub"], "audits")
            self.assertEqual(open_met["initial_target"], "demo-session")

            lv1 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 112, "method": "tools/call", "params": {"name": "gravity_get_live_session", "arguments": {}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(lv1["available"])
            self.assertEqual(lv1["selected_session"]["conversation_id"], live_cid)
            lv2 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 113, "method": "tools/call", "params": {"name": "gravity_get_live_session", "arguments": {"since_signature": lv1["signature"]}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(lv2["unchanged"])

            act_ok = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 114,
                    "method": "tools/call",
                    "params": {"name": "gravity_metrics_action", "arguments": {"action": "update-meta", "slug": "demo-session", "label": "Demo V2", "project": "gravity"}},
                },
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(act_ok["isError"])
            self.assertEqual(act_ok["structuredContent"]["result"]["argv"][0], "update-meta")

            act_bad = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 115,
                    "method": "tools/call",
                    "params": {"name": "gravity_metrics_action", "arguments": {"action": "ignore", "target": "../etc/passwd"}},
                },
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertTrue(act_bad["isError"])

            audit_id = sc["metrics"]["audits"][0]["audit_id"]
            aud_ok = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 116, "method": "tools/call", "params": {"name": "gravity_read_audit", "arguments": {"path": audit_id}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(aud_ok["isError"])
            self.assertIn("Secret Agent Audit", aud_ok["structuredContent"]["content"])

            aud_bad = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 117, "method": "tools/call", "params": {"name": "gravity_read_audit", "arguments": {"path": "../audits/code/2026-11-23-audit-code-gravity.md"}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertTrue(aud_bad["isError"])

            ov1 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "gravity_get_overview", "arguments": {}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            ov2 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "gravity_get_overview", "arguments": {"since_signature": ov1["signature"]}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(ov2["unchanged"])

            wf1 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 13, "method": "tools/call", "params": {"name": "gravity_get_workflow_state", "arguments": {"ws": "demo-ws"}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(wf1["available"])
            wf2 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 14, "method": "tools/call", "params": {"name": "gravity_get_workflow_state", "arguments": {"ws": "demo-ws", "since_signature": wf1["signature"]}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(wf2["unchanged"])

            met1 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 15, "method": "tools/call", "params": {"name": "gravity_get_metrics_state", "arguments": {"project": "gravity"}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertEqual(met1["total_matching"], 1)

            det = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 16, "method": "tools/call", "params": {"name": "gravity_get_session_detail", "arguments": {"target": "demo-session"}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(det["isError"])
            self.assertNotIn("trajectory", det["structuredContent"]["detail"])
            self.assertTrue(det["structuredContent"]["report_md_uri"].startswith("file://"))

            det_err = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 17, "method": "tools/call", "params": {"name": "gravity_get_session_detail", "arguments": {"target": ""}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertTrue(det_err["isError"])

            mod_ok = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 18, "method": "tools/call", "params": {"name": "gravity_get_module_info", "arguments": {"module_id": "workflow"}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(mod_ok["isError"])
            self.assertEqual(mod_ok["structuredContent"]["top_entries"][0]["name"], "live_workspaces.json")

            mod_err = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 19, "method": "tools/call", "params": {"name": "gravity_get_module_info", "arguments": {"module_id": "nonexistent"}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertTrue(mod_err["isError"])

            removed_br = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 20, "method": "tools/call", "params": {"name": "gravity_get_bridge_state", "arguments": {"status": "open"}}},
                ctx=ctx,
            )
            self.assertEqual(removed_br["error"]["code"], -32602)  # type: ignore[index]
            open_fallback = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 21, "method": "tools/call", "params": {"name": "open_gravity_dashboard", "arguments": {"view": "bridge"}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertEqual(open_fallback["initial_view"], "live")
            self.assertNotIn("bridge", open_fallback)

            arch1 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 22, "method": "tools/call", "params": {"name": "gravity_get_architect_state", "arguments": {}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(arch1["available"])
            self.assertEqual(arch1["discovery_source"], "architect_registry")
            self.assertEqual(len(arch1["audits"]), 1)
            self.assertEqual(arch1["audits"][0]["verdict"], "PASS")
            arch2 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 23, "method": "tools/call", "params": {"name": "gravity_get_architect_state", "arguments": {"since_signature": arch1["signature"]}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(arch2["unchanged"])

    def test_architect_mcp_ws_hint_and_atelier_selector_without_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            arch_home = g_home / "architect"
            (g_home / "core").mkdir(parents=True)
            arch_home.mkdir(parents=True)

            atelier_one = tmp_path / "atelier-one"
            atelier_two = tmp_path / "atelier-two"
            for idx, adir in enumerate((atelier_one, atelier_two), start=1):
                (adir / "tracking" / "snapshots").mkdir(parents=True)
                (adir / "ECOSYSTEM.md").write_text(f"# Atelier {idx}\n", encoding="utf-8")
                (adir / "projects.json").write_text(
                    json.dumps({"schema_version": 5, "workspace_name": f"Atelier {idx}", "projects": []}),
                    encoding="utf-8",
                )

            (arch_home / "ateliers.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ateliers": [
                            {"workspace_path": str(atelier_one), "workspace_name": "Atelier 1", "updated_at": "2026-11-24T09:00:00Z"},
                            {"workspace_path": str(atelier_two), "workspace_name": "Atelier 2", "updated_at": "2026-11-24T08:00:00Z"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            _write_fake_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_fake_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect", ui_mode="none")
            write_modules_registry(
                g_home,
                [
                    {
                        "id": "core",
                        "plugin_name": "gravity",
                        "display_name": "Gravity",
                        "version": "0.3.0",
                        "valid": True,
                        "errors": [],
                        "storage": {"subdir": "core", "env_override": "GRAVITY_CORE_HOME"},
                        "commands": ["/gravity"],
                        "capabilities": ["test"],
                        "ui": {"mode": "core", "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                    },
                    {
                        "id": "architect",
                        "plugin_name": "gravity-architect",
                        "display_name": "Gravity Architect",
                        "version": "0.5.0",
                        "valid": True,
                        "errors": [],
                        "storage": {"subdir": "architect", "env_override": "GRAVITY_ARCHITECT_HOME"},
                        "commands": ["/gravity-architect"],
                        "capabilities": ["test"],
                        "ui": {"mode": "none", "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                    },
                ],
            )

            ctx = {
                "gravity_home": g_home,
                "plugin_roots": [plugins_root],
                "home_dir": fake_user,
                "architect_home": arch_home,
            }

            open_ws = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 30,
                    "method": "tools/call",
                    "params": {"name": "open_gravity_dashboard", "arguments": {"view": "architect", "ws": str(atelier_two)}},
                },
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(open_ws["isError"])
            sc = open_ws["structuredContent"]
            self.assertEqual(sc["initial_atelier"], "")
            self.assertTrue(sc["architect"]["available"])
            self.assertEqual(sc["architect"]["discovery_source"], "ws_hint")
            self.assertEqual(Path(sc["architect"]["atelier_root"]), atelier_two.resolve())
            self.assertEqual(len(sc["architect"]["ateliers"]), 2)

            switch_res = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 31,
                    "method": "tools/call",
                    "params": {"name": "gravity_get_architect_state", "arguments": {"atelier": str(atelier_one)}},
                },
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(switch_res["available"])
            self.assertEqual(switch_res["discovery_source"], "selected_atelier")
            self.assertEqual(Path(switch_res["atelier_root"]), atelier_one.resolve())

            bad_res = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 32,
                    "method": "tools/call",
                    "params": {"name": "gravity_get_architect_state", "arguments": {"atelier": str(tmp_path / "missing")}},
                },
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertFalse(bad_res["available"])
            self.assertEqual(bad_res["discovery_source"], "selected_atelier")
            self.assertTrue(bad_res["warnings"])

    def test_architect_ws_hint_preserved_on_refresh_without_registry_or_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            arch_home = g_home / "architect"
            (g_home / "core").mkdir(parents=True)
            arch_home.mkdir(parents=True)

            atelier_dir = tmp_path / "atelier-direct"
            (atelier_dir / "tracking" / "snapshots").mkdir(parents=True)
            (atelier_dir / "ECOSYSTEM.md").write_text("# Atelier Direct\n", encoding="utf-8")
            (atelier_dir / "projects.json").write_text(
                json.dumps({"schema_version": 5, "workspace_name": "Atelier Direct", "projects": []}),
                encoding="utf-8",
            )

            _write_fake_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_fake_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect", ui_mode="none")
            write_modules_registry(
                g_home,
                [
                    {
                        "id": "core",
                        "plugin_name": "gravity",
                        "display_name": "Gravity",
                        "version": "0.3.0",
                        "valid": True,
                        "errors": [],
                        "storage": {"subdir": "core", "env_override": "GRAVITY_CORE_HOME"},
                        "commands": ["/gravity"],
                        "capabilities": ["test"],
                        "ui": {"mode": "core", "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                    },
                    {
                        "id": "architect",
                        "plugin_name": "gravity-architect",
                        "display_name": "Gravity Architect",
                        "version": "0.5.0",
                        "valid": True,
                        "errors": [],
                        "storage": {"subdir": "architect", "env_override": "GRAVITY_ARCHITECT_HOME"},
                        "commands": ["/gravity-architect"],
                        "capabilities": ["test"],
                        "ui": {"mode": "none", "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                    },
                ],
            )

            ctx = {
                "gravity_home": g_home,
                "plugin_roots": [plugins_root],
                "home_dir": fake_user,
                "architect_home": arch_home,
            }

            tools_resp = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 40, "method": "tools/list", "params": {}},
                ctx=ctx,
            )["result"]["tools"]  # type: ignore[index]
            arch_tool = next(t for t in tools_resp if t["name"] == "gravity_get_architect_state")
            self.assertIn("ws", arch_tool["inputSchema"]["properties"])

            open_res = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 41,
                    "method": "tools/call",
                    "params": {"name": "open_gravity_dashboard", "arguments": {"ws": str(atelier_dir)}},
                },
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertEqual(open_res["initial_ws"], str(atelier_dir))
            self.assertTrue(open_res["architect"]["available"])
            self.assertEqual(open_res["architect"]["discovery_source"], "ws_hint")

            refresh_res = mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "tools/call",
                    "params": {
                        "name": "gravity_get_architect_state",
                        "arguments": {"ws": str(atelier_dir), "atelier": ""},
                    },
                },
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(refresh_res["available"])
            self.assertEqual(refresh_res["discovery_source"], "ws_hint")
            self.assertEqual(Path(refresh_res["atelier_root"]), atelier_dir.resolve())

    def test_stdio_subprocess_roundtrip_and_parse_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            g_home = tmp_path / "gravity-home"
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["HOME"] = str(fake_home)
            env["USERPROFILE"] = str(fake_home)
            env["GRAVITY_HOME"] = str(g_home)
            for k in (
                "GRAVITY_CORE_HOME",
                "GRAVITY_WORKFLOW_HOME",
                "GRAVITY_METRICS_HOME",
                "GRAVITY_BRIDGE_HOME",
                "GRAVITY_ARCHITECT_HOME",
                "GRAVITY_ARCHITECT_WORKSPACE",
            ):
                env.pop(k, None)

            stdin_lines = [
                "{not-valid-json",
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "prompts/list", "params": {}}),
            ]
            proc = subprocess.run(
                [sys.executable, "-B", str(PLUGIN_ROOT / "mcp" / "server.py")],
                input="\n".join(stdin_lines) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            out_objs = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
            self.assertEqual(len(out_objs), 3)
            self.assertEqual(out_objs[0]["error"]["code"], -32700)
            self.assertEqual(out_objs[1]["id"], 1)
            self.assertEqual(out_objs[2]["result"], {"prompts": []})

    def test_initialize_ui_capability_detection_and_open_dashboard_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            (g_home / "core").mkdir(parents=True)
            _write_fake_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            write_modules_registry(
                g_home,
                [
                    {
                        "id": "core",
                        "plugin_name": "gravity",
                        "display_name": "Gravity",
                        "version": "0.3.0",
                        "valid": True,
                        "errors": [],
                        "storage": {"subdir": "core", "env_override": "GRAVITY_CORE_HOME"},
                        "commands": ["/gravity"],
                        "capabilities": ["test"],
                        "ui": {"mode": "core", "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                    }
                ],
            )
            ctx = {
                "gravity_home": g_home,
                "plugin_roots": [plugins_root],
                "home_dir": fake_user,
            }

            def _call_open(req_id: int) -> dict[str, object]:
                resp = mcp_server.handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "method": "tools/call",
                        "params": {"name": "open_gravity_dashboard", "arguments": {}},
                    },
                    ctx=ctx,
                )
                assert resp is not None
                return resp["result"]  # type: ignore[return-value]

            # 1) Without initialize -> no [WARN UI]
            res_uninit = _call_open(100)
            self.assertFalse(res_uninit["isError"])
            self.assertNotIn("[WARN UI]", res_uninit["content"][0]["text"])  # type: ignore[index]

            # 2) initialize without capabilities or with empty capabilities & no clientInfo -> ui_supported=None, no [WARN UI]
            for idx, params in enumerate(
                ({}, {"protocolVersion": "2025-06-18"}, {"capabilities": {}}),
                start=101,
            ):
                mcp_server._reset_host_client_state()
                mcp_server.handle_jsonrpc_message(
                    {"jsonrpc": "2.0", "id": idx, "method": "initialize", "params": params}
                )
                self.assertIsNone(mcp_server._HOST_CLIENT_STATE["ui_supported"])
                res_unknown = _call_open(idx + 10)
                self.assertFalse(res_unknown["isError"])
                self.assertNotIn("[WARN UI]", res_unknown["content"][0]["text"])  # type: ignore[index]

            # 3) initialize with MCP Apps capabilities -> ui_supported=True, no [WARN UI]
            for idx, cap_payload in enumerate(
                (
                    {"extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}},
                    {"experimental": {"io.modelcontextprotocol/ui": True}},
                    {"extensions": {"com.google.antigravity/ui": {"entrypoints": True}}},
                    {"experimental": {"com.google.antigravity/ui": True}},
                    {"ui": {"enabled": True}},
                ),
                start=120,
            ):
                mcp_server._reset_host_client_state()
                mcp_server.handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": idx,
                        "method": "initialize",
                        "params": {
                            "capabilities": cap_payload,
                            "clientInfo": {"name": "antigravity", "version": "2.35.0"},
                        },
                    }
                )
                self.assertTrue(mcp_server._HOST_CLIENT_STATE["ui_supported"])
                res_ok = _call_open(idx + 20)
                self.assertFalse(res_ok["isError"])
                self.assertNotIn("[WARN UI]", res_ok["content"][0]["text"])  # type: ignore[index]

            # 4) initialize with Antigravity < 2.34.0 -> ui_supported=False, [WARN UI] appended, isError=False
            mcp_server._reset_host_client_state()
            mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 150,
                    "method": "initialize",
                    "params": {
                        "capabilities": {},
                        "clientInfo": {"name": "antigravity", "version": "2.33.0"},
                    },
                }
            )
            self.assertIs(mcp_server._HOST_CLIENT_STATE["ui_supported"], False)
            res_old = _call_open(151)
            self.assertFalse(res_old["isError"])
            txt_old = res_old["content"][0]["text"]  # type: ignore[index]
            self.assertIn("[WARN UI]", txt_old)
            self.assertIn("antigravity 2.33.0", txt_old)
            self.assertIn("v2.34.0+", txt_old)

            # 5) initialize with non-UI client (e.g. agy CLI) -> ui_supported=False, [WARN UI] appended
            mcp_server._reset_host_client_state()
            mcp_server.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 160,
                    "method": "initialize",
                    "params": {
                        "capabilities": {"roots": {"listChanged": True}},
                        "clientInfo": {"name": "agy", "version": "1.0.0"},
                    },
                }
            )
            self.assertIs(mcp_server._HOST_CLIENT_STATE["ui_supported"], False)
            res_cli = _call_open(161)
            self.assertFalse(res_cli["isError"])
            txt_cli = res_cli["content"][0]["text"]  # type: ignore[index]
            self.assertIn("[WARN UI]", txt_cli)
            self.assertIn("agy 1.0.0", txt_cli)

    def test_metrics_ui_bundle_dom_renderers_and_actions(self) -> None:
        import re
        import shutil
        from mcp.ui.charts_js import CHARTS_JS
        from mcp.ui.live_views_js import LIVE_VIEWS_JS
        from mcp.ui.metrics_views_js import METRICS_VIEWS_JS
        from mcp.ui.views_js import VIEWS_JS

        html = render_dashboard_html()
        self.assertLess(len(html.encode("utf-8")), 150 * 1024)
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node binary not available")

        match = re.search(r"<script>\n(.*)\n</script>", html, flags=re.DOTALL)
        self.assertIsNotNone(match)
        assert match is not None

        harness = r"""
function makeNode(tag) {
  return {
    tagName: String(tag).toUpperCase(), className: "", textContent: "", attrs: {}, style: {},
    children: [], listeners: {}, value: "", selected: false, disabled: false, open: false,
    get firstChild() { return this.children[0] || null; },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = String(v); if (k === "value") this.value = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    addEventListener(ev, fn) { this.listeners[ev] = this.listeners[ev] || []; this.listeners[ev].push(fn); }
  };
}
function collectText(n) {
  if (!n) return "";
  const out = n.textContent ? [n.textContent] : [];
  for (const ch of (n.children || [])) out.push(collectText(ch));
  return out.join(" ");
}
function findAll(node, pred, acc) {
  acc = acc || [];
  if (!node) return acc;
  if (pred(node)) acc.push(node);
  for (const ch of (node.children || [])) findAll(ch, pred, acc);
  return acc;
}
const document = { createElement: (t) => makeNode(t), createElementNS: (_ns, t) => makeNode(t), getElementById: () => null };
const state = {
  overview: { tabs: [{ id: "live", kind: "live" }, { id: "architect", kind: "architect" }, { id: "metrics", kind: "metrics" }, { id: "overview", kind: "core" }] },
  live: { selected_session: { conversation_id: "cid-1" }, summary: { llm_calls: 15 } },
  metricsProject: "", metricsQ: "", metricsSub: "overview", metricsFilter: "recorded", metricsSort: "date",
  metricsActionInFlight: false, compareOpen: false, compareA: "s-1", compareB: "s-2",
  sessionTarget: "", sessionDetail: null, sessionDetailLoading: false, sessionDetailSub: "summary",
  sessionAgentId: "", sessionCollapsed: {},
  sessionEditOpen: false, sessionDeleteConfirm: false, pendingDeleteTarget: "",
  auditTarget: "", auditData: null, auditLoading: false, architectSub: "projects",
  metrics: {
    projects: ["gravity", "gravity-studio"],
    workspaces: ["gravity", "gravity-metrics", "gravity-studio"],
    metrics_md_uri: "file:///tmp/METRICS.md",
    total_matching: 2,
    kpis: {
      sessions_count: 2, archived_count: 2, active_count: 0, useful_tokens: 45000, cache_read_tokens: 120000,
      total_tokens: 165000, avg_cache_hit_rate_pct: 72.7, total_llm_calls: 20, max_context_tokens: 145000,
      context_alerts_count: 1, context_critical_count: 0, wall_clock_s: 320, latency_p95_ms: 1850,
      latency_avg_ms: 920, thinking_est_tokens: 4200, compaction_count: 1, error_steps: 1, avg_error_rate_pct: 5.0,
      duplicate_spawns: 0, rewind_calls: 1, interrupted_agents: 0
    },
    by_workspace: [
      { workspace: "gravity-studio", kind: "atelier", useful_tokens: 15000, sessions: 1 },
      { workspace: "gravity", kind: "code", useful_tokens: 30000, sessions: 2 }
    ],
    records: [
      {
        conversation_id: "cid-1", label: "Session One", detail_slug: "s-1", project: "gravity", status: "archived",
        primary_model: "gemini-4-neon-high", models: { "gemini-4-neon-high": { calls: 12 } },
        category_share_pct: { builder: 75, reviewer: 25 }, input_tokens: 20000, output_tokens: 5000,
        cache_read_tokens: 80000, total_tokens: 105000, cache_hit_rate_pct: 80, max_context_tokens: 145000,
        llm_calls: 12, tool_calls: 24, latency_p95_ms: 1850, error_steps: 1, error_rate_pct: 8.3,
        compaction_count: 1, wall_clock_s: 200, cost_usd: 0.25, cache_savings_usd: 0.40,
        agents: 4, max_depth: 2, current_phase: "build",
        workspace_share_pct: { gravity: 75, "gravity-studio": 25 },
        workspace_kinds: { gravity: "code", "gravity-studio": "atelier" },
        started_at: "2026-11-25T10:00:00Z", ended_at: "2026-11-25T10:03:20Z"
      },
      {
        conversation_id: "cid-2", label: "Session Two", detail_slug: "s-2", project: "gravity-studio", status: "archived",
        primary_model: "gemini-4-hydrogen-high", input_tokens: 16000, output_tokens: 4000,
        cache_read_tokens: 40000, total_tokens: 60000, cache_hit_rate_pct: 66.7, max_context_tokens: 90000,
        llm_calls: 8, tool_calls: 10, latency_p95_ms: 1100, error_steps: 0, error_rate_pct: 0,
        compaction_count: 0, wall_clock_s: 120, cost_usd: 0.15, cache_savings_usd: 0.20,
        started_at: "2026-11-25T09:00:00Z", ended_at: "2026-11-25T09:02:00Z"
      }
    ],
    pending_sessions: [{ conversation_id: "cid-pend", label: "Pending Run", project: "gravity", cwd: "/tmp/gravity", updated_at: "2026-11-25T11:00:00Z" }],
    ignored_sessions: [{ conversation_id: "cid-ign", label: "Noise Run", project: "gravity", ignored_reason: "test", ignored_at: "2026-11-25T08:00:00Z" }],
    audits: [{ audit_id: "studio:2026-11-25.md", title: "Audit W4", workspace: "gravity-studio", verdict: "PASS", verdict_tone: "ok", date: "2026-11-25", size_bytes: 512, uri: "file:///tmp/a.md" }]
  }
};
"""
        assertions = r"""
function assert(c, m) { if (!c) throw new Error("ASSERT: " + m); }
const box1 = makeNode("div");
renderMetricsUnifiedView(box1);
const t1 = collectText(box1);
assert(t1.includes("Tokens utiles") && t1.includes("Pression contexte") && t1.includes("Atelier") && t1.includes("Code"), "overview technical KPIs & workspaces");
assert(t1.includes("Répartition par Modèle") && t1.includes("Répartition par Rôle") && t1.includes("Audits Agents (1)"), "model, role breakdown & unified audits");
assert(t1.includes("gravity-metrics") && !t1.includes("Tarif 2026") && !t1.includes("Tarif 2027"), "workspaces filter & no tariff toggle");

state.metricsSub = "sessions";
state.compareOpen = true;
state.sessionTarget = "s-1";
state.sessionEditOpen = true;
state.sessionDeleteConfirm = true;
state.pendingDeleteTarget = "s-1";
state.sessionDetail = {
  found: true, source: "report_json", slug: "s-1", conversation_id: "cid-1", label: "Session One",
  report_md_uri: "file:///tmp/s1.md", record: state.metrics.records[0],
  detail: {
    summary: { input_tokens: 20000, output_tokens: 5000, cache_read_tokens: 80000, cache_hit_rate_pct: 80, total_llm_calls: 12, total_tool_calls: 24, wall_clock_s: 200, cost_usd: { total_usd: 0.25, cache_savings_usd: 0.40 } },
    agents: [
      { role: "Builder", conversation_id: "cid-root", workspace: "gravity", workspace_kind: "code", model: "gemini-4-neon-high", max_context_tokens: 145000, input_tokens: 20000, output_tokens: 5000, cache_read_tokens: 80000, llm_calls: 12, tool_calls: 24, clean_termination: true },
      { role: "Verifier", conversation_id: "cid-wf", parent_id: "cid-root", depth: 1, source: "workflow", category: "verification", workspace: "gravity", workspace_kind: "code", by_model: { "gemini-4-hydrogen-high": { calls: 15 } }, max_context_tokens: 60000, input_tokens: 8000, output_tokens: 2000, cache_read_tokens: 30000, llm_calls: 15, tool_calls_total: 37, active_s: 95, clean_termination: false, error_steps: 1, total_anomalies: 2, cost_usd: { total_usd: 0.12 } }
    ],
    tool_usage: { by_tool: { edit_file: 10 } }
  }
};
const box2 = makeNode("div");
renderMetricsUnifiedView(box2);
const t2 = collectText(box2);
assert(t2.includes("4 ag.") && t2.includes("prof. N2") && t2.includes("Phase : build") && t2.includes("gravity 75%"), "enriched session cards");
assert(t2.includes("Mettre à jour (+3 appels)") && t2.includes("Comparateur A/B") && t2.includes("Delta (B - A)"), "freshness badge & A/B comparator");
assert(t2.includes("Supprimer cette session") && t2.includes("Repère secondaire ($)") && findAll(box2, (n) => n.className === "slide-over").length === 1, "slide-over inline delete confirm & discrete $ footnote");

state.sessionDetailSub = "agents";
const box2b = makeNode("div");
renderMetricsUnifiedView(box2b);
const t2b = collectText(box2b);
assert(findAll(box2b, (n) => n.className && n.className.includes("tree-row")).length === 2, "agent tree renders 2 rows");
assert(t2b.includes("Outils les plus utilisés") && t2b.includes("edit_file"), "agents & tools subtab");
assert(t2b.includes("gemini-4-neon-high") && t2b.includes("Outils : 24"), "legacy agent model & tool_calls fallback");

state.sessionAgentId = "cid-wf";
const box2b2 = makeNode("div");
renderMetricsUnifiedView(box2b2);
const t2b2 = collectText(box2b2);
assert(t2b2.includes("gemini-4-hydrogen-high") && t2b2.includes("Outils : 37") && t2b2.includes("Workflow") && t2b2.includes("Vérification") && t2b2.includes("Erreur") && t2b2.includes("↳ Builder · N1") && t2b2.includes("Anomalies : 2") && t2b2.includes("$0.1200"), "inspector selected agent details");

state.sessionDetailSub = "diagnostic";
const box2c = makeNode("div");
renderMetricsUnifiedView(box2c);
assert(collectText(box2c).includes("Doublons de rôles") && collectText(box2c).includes("Compactions contexte"), "diagnostic subtab");

state.sessionTarget = "";
state.metricsSub = "audits";
state.auditTarget = "studio:2026-11-25.md";
state.auditData = { found: true, title: "Audit W4", verdict: "PASS", workspace: "gravity-studio", date: "2026-11-25", content: "# Audit Body", uri: "file:///tmp/a.md" };
const box3 = makeNode("div");
renderMetricsUnifiedView(box3);
assert(findAll(box3, (n) => n.className === "slide-over").length === 1 && collectText(box3).includes("# Audit Body") && collectText(box3).includes("Ouvrir .md"), "audits slide-over reader");

state.architectSub = "projects";
state.architect = {
  available: true, atelier_root: "/tmp/gravity-studio", discovery_source: "architect_registry",
  ecosystem: { exists: true, size_bytes: 2048, budget_bytes: 6000, over_budget: false, alerts: [], uri: "file:///tmp/ECO.md" },
  delta: { exists: true, editorial_status: "NO_EDITORIAL_CHANGES", date: "2026-11-26", hygiene_alerts: [], uri: "file:///tmp/delta.md" },
  watches_count: 1, archived_specs_count: 1, archived_tasks_count: 2,
  projects: [{ id: "gravity", name: "Gravity", path: "../gravity", role: "core", main_branch: "main", default_dev_branch: "dev", release_main: "0.3.0", dev_status: "ahead 1", installed_version: "0.3.0", wip_status: "clean", specs_count: 1, tasks_count: 2, audits_count: 1, card_bytes: 1200, card_uri: "file:///tmp/gravity.md" }],
  specs: [{ filename: "s1.md", title: "Spec v2", target_project: "gravity", status: "validated", status_code: "validated", date: "2026-11-26", size_bytes: 1024, uri: "file:///tmp/s1.md" }],
  tasks: [{ filename: "t1.md", title: "Task 1", target_project: "gravity", wave: 1, status: "done", status_code: "done", workflow_profile: "quick", expected_branch: "dev", dependencies: ["w0"], spec_source: "specs/s1.md", date: "2026-11-26", uri: "file:///tmp/t1.md" }],
  waves_summary: { total_tasks: 1, waves_count: 1, waves: [{ wave: 1, tasks_count: 1, projects: ["gravity"], status_counts: { done: 1 } }] },
  audits: [{ audit_id: "code:a.md", title: "Audit Code", target: "gravity", verdict: "PASS", verdict_tone: "ok", date: "2026-11-26", size_bytes: 512, uri: "file:///tmp/ac.md" }]
};
const archP = makeNode("div");
renderArchitectView(archP);
const archPTxt = collectText(archP);
assert(archPTxt.includes("Voir sessions") && archPTxt.includes("Ouvrir fiche") && archPTxt.includes("1 spec(s)") && archPTxt.includes("2 task(s)"), "architect projects cards");
state.architectSub = "waves";
const archW = makeNode("div");
renderArchitectView(archW);
const archWTxt = collectText(archW);
assert(archWTxt.includes("Vague 1") && archWTxt.includes("profil: quick") && archWTxt.includes("déps: w0"), "architect waves & tasks");
console.log(JSON.stringify({ ok: true }));
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bundle = tmp_path / "bundle.js"
            bundle.write_text(match.group(1), encoding="utf-8")
            chk = subprocess.run([node_bin, "--check", str(bundle)], capture_output=True, text=True, check=False)
            self.assertEqual(chk.returncode, 0, msg=chk.stderr or chk.stdout)

            dom = tmp_path / "metrics_dom.js"
            dom.write_text("\n".join([harness, VIEWS_JS, CHARTS_JS, LIVE_VIEWS_JS, METRICS_VIEWS_JS, assertions]), encoding="utf-8")
            run = subprocess.run([node_bin, str(dom)], capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, msg=run.stderr or run.stdout)
            self.assertTrue(json.loads(run.stdout.strip()).get("ok"))


if __name__ == "__main__":
    unittest.main()

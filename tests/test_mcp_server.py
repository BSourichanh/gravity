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
                "gravity_get_overview",
                "gravity_get_workflow_state",
                "gravity_get_metrics_state",
                "gravity_get_session_detail",
                "gravity_get_architect_state",
                "gravity_get_module_info",
            ],
        )
        self.assertNotIn("gravity_get_bridge_state", names)
        self.assertEqual(mcp_server.VALID_VIEWS, ("overview", "workflow", "metrics", "architect", "module"))

        open_tool = tools[0]
        self.assertIn("atelier", open_tool["inputSchema"]["properties"])
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
        self.assertLess(len(html_txt.encode("utf-8")), 200 * 1024)
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
            "g-arch-ws",
        ):
            self.assertIn(required, html_txt)
        for absent in ("renderBridgeView", "renderBridgeSvgChart", "gravity_get_bridge_state", "loadBridgeState"):
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
            _write_fake_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="transition-mcp")
            _write_fake_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect", ui_mode="none")

            mods = []
            for mod_id, pname, ui_mode in (
                ("core", "gravity", "core"),
                ("workflow", "gravity-workflow", "none"),
                ("metrics", "gravity-metrics", "transition-mcp"),
                ("architect", "gravity-architect", "none"),
            ):
                mods.append(
                    {
                        "id": mod_id,
                        "plugin_name": pname,
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
                "workflow_home": wf_home,
                "metrics_home": met_home,
                "audits_dirs": [],
            }

            open_res = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "open_gravity_dashboard", "arguments": {}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(open_res["isError"])
            self.assertLessEqual(len(json.dumps(open_res, ensure_ascii=False).encode("utf-8")), mcp_server.MAX_TRAJECTORY_BYTES)
            sc = open_res["structuredContent"]
            self.assertEqual(sc["initial_view"], "overview")
            self.assertEqual([t["id"] for t in sc["overview"]["tabs"]], ["overview", "workflow", "metrics", "architect"])
            self.assertEqual(sc["workflow"]["stage"], "build")
            self.assertEqual(sc["metrics"]["kpis"]["sessions_count"], 1)
            self.assertNotIn("bridge", sc)
            self.assertTrue(sc["architect"]["available"])

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
            self.assertEqual(open_fallback["initial_view"], "overview")
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


if __name__ == "__main__":
    unittest.main()

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
                "gravity_get_module_info",
            ],
        )

        open_tool = tools[0]
        self.assertEqual(open_tool["_meta"]["ui"]["resourceUri"], mcp_server.APP_URI)
        self.assertEqual(open_tool["_meta"]["ui"]["visibility"], ["model", "app"])
        eps = open_tool["_meta"]["com.google.antigravity/ui"]["entrypoints"]
        self.assertEqual([e["type"] for e in eps], ["aux_pane", "global"])

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
        ):
            self.assertIn(required, html_txt)

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

    def test_all_six_tools_with_isolated_ctx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            wf_home = g_home / "workflow"
            met_home = g_home / "metrics"
            bridge_home = g_home / "bridge"
            (g_home / "core").mkdir(parents=True)
            (wf_home / "workspaces" / "proj-1").mkdir(parents=True)
            (met_home / "data").mkdir(parents=True)
            (met_home / "reports").mkdir(parents=True)
            bridge_home.mkdir(parents=True)
            (bridge_home / "bridge.db").write_text("sqlite-stub", encoding="utf-8")

            _write_fake_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_fake_plugin(plugins_root, mod_id="workflow", plugin_name="gravity-workflow", ui_mode="transition-sidecar")
            _write_fake_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="transition-mcp")
            _write_fake_plugin(plugins_root, mod_id="bridge", plugin_name="gravity-bridge", ui_mode="none")

            mods = []
            for mod_id, pname, ui_mode in (
                ("core", "gravity", "core"),
                ("workflow", "gravity-workflow", "transition-sidecar"),
                ("metrics", "gravity-metrics", "transition-mcp"),
                ("bridge", "gravity-bridge", "none"),
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
            self.assertEqual([t["id"] for t in sc["overview"]["tabs"]], ["overview", "workflow", "metrics", "bridge"])
            self.assertEqual(sc["workflow"]["stage"], "build")
            self.assertEqual(sc["metrics"]["kpis"]["sessions_count"], 1)

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
                {"jsonrpc": "2.0", "id": 18, "method": "tools/call", "params": {"name": "gravity_get_module_info", "arguments": {"module_id": "bridge"}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertFalse(mod_ok["isError"])
            self.assertEqual(mod_ok["structuredContent"]["top_entries"][0]["name"], "bridge.db")

            mod_err = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 19, "method": "tools/call", "params": {"name": "gravity_get_module_info", "arguments": {"module_id": "nonexistent"}}},
                ctx=ctx,
            )["result"]  # type: ignore[index]
            self.assertTrue(mod_err["isError"])

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
            for k in ("GRAVITY_CORE_HOME", "GRAVITY_WORKFLOW_HOME", "GRAVITY_METRICS_HOME"):
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


if __name__ == "__main__":
    unittest.main()

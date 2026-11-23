"""Isolated unit and stdio tests for plugin/mcp/server.py & widget_html.py (TemporaryDirectory only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
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
                "gravity_get_bridge_state",
                "gravity_get_architect_state",
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
            "renderBridgeView",
            "renderArchitectView",
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

    def test_all_eight_tools_with_isolated_ctx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            wf_home = g_home / "workflow"
            met_home = g_home / "metrics"
            bridge_home = g_home / "bridge"
            atelier_dir = tmp_path / "gravity-studio"
            (g_home / "core").mkdir(parents=True)
            (wf_home / "workspaces" / "proj-1").mkdir(parents=True)
            (met_home / "data").mkdir(parents=True)
            (met_home / "reports").mkdir(parents=True)
            bridge_home.mkdir(parents=True)
            (atelier_dir / "tracking" / "snapshots").mkdir(parents=True)
            (atelier_dir / "audits" / "code").mkdir(parents=True)
            (atelier_dir / "audits" / "agents").mkdir(parents=True)

            conn = sqlite3.connect(str(bridge_home / "bridge.db"))
            try:
                conn.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    CREATE TABLE workspaces (
                        slug TEXT PRIMARY KEY, canonical_path TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
                        sidecar_id TEXT, sidecar_pid INTEGER, sidecar_last_seen_at TEXT,
                        project_id TEXT, created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
                    );
                    CREATE TABLE threads (
                        id TEXT PRIMARY KEY, from_workspace TEXT NOT NULL, to_workspace TEXT NOT NULL,
                        msg_type TEXT NOT NULL, subject TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                        approved INTEGER NOT NULL DEFAULT 0, target_conversation_id TEXT,
                        caller_conversation_id TEXT, notify_caller INTEGER NOT NULL DEFAULT 0,
                        callback_dispatched_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
                        sender_workspace TEXT NOT NULL, msg_type TEXT NOT NULL, body TEXT NOT NULL,
                        file_refs_json TEXT NOT NULL DEFAULT '[]', is_read INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, message_id INTEGER NOT NULL,
                        target_workspace TEXT NOT NULL, action TEXT NOT NULL, direction TEXT NOT NULL DEFAULT 'outbound',
                        model TEXT, sidecar_id TEXT, target_conversation_id TEXT, status TEXT NOT NULL,
                        exit_code INTEGER, error_summary TEXT, claimed_at TEXT, dispatched_at TEXT,
                        finished_at TEXT, created_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("gravity-studio", str(atelier_dir.resolve()), "Studio", "sc-1", 10, "2026-11-23T22:00:00Z", "studio", "2026-11-23T20:00:00Z", "2026-11-23T22:00:00Z"),
                )
                conn.execute(
                    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("thr-1", "gravity-studio", "gravity", "handoff", "Lot 2", "open", 1, "c1", "c2", 1, None, "2026-11-23T21:00:00Z", "2026-11-23T22:00:00Z"),
                )
                conn.execute(
                    "INSERT INTO messages (thread_id, sender_workspace, msg_type, body, is_read, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    ("thr-1", "gravity-studio", "handoff", "Bridge message preview", 0, "2026-11-23T22:00:00Z"),
                )
                conn.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("job-1", "thr-1", 1, "gravity", "new_conversation", "outbound", "pro", "sc-1", "c1", "completed", 0, None, "2026-11-23T22:00:00Z", "2026-11-23T22:00:01Z", "2026-11-23T22:00:05Z", "2026-11-23T22:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()

            (atelier_dir / "ECOSYSTEM.md").write_text("# Atelier\n", encoding="utf-8")
            (atelier_dir / "projects.json").write_text(
                json.dumps({"schema_version": 5, "projects": [{"id": "gravity", "name": "Gravity", "path": "../gravity"}]}),
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
            _write_fake_plugin(plugins_root, mod_id="workflow", plugin_name="gravity-workflow", ui_mode="transition-sidecar")
            _write_fake_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="transition-mcp")
            _write_fake_plugin(plugins_root, mod_id="bridge", plugin_name="gravity-bridge", ui_mode="none")
            _write_fake_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect", ui_mode="none")

            mods = []
            for mod_id, pname, ui_mode in (
                ("core", "gravity", "core"),
                ("workflow", "gravity-workflow", "transition-sidecar"),
                ("metrics", "gravity-metrics", "transition-mcp"),
                ("bridge", "gravity-bridge", "none"),
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
                "bridge_home": bridge_home,
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
            self.assertEqual([t["id"] for t in sc["overview"]["tabs"]], ["overview", "workflow", "metrics", "bridge", "architect"])
            self.assertEqual(sc["workflow"]["stage"], "build")
            self.assertEqual(sc["metrics"]["kpis"]["sessions_count"], 1)
            self.assertTrue(sc["bridge"]["available"])
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

            br1 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 20, "method": "tools/call", "params": {"name": "gravity_get_bridge_state", "arguments": {"status": "open"}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(br1["available"])
            self.assertEqual(br1["kpis"]["threads_open"], 1)
            br2 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 21, "method": "tools/call", "params": {"name": "gravity_get_bridge_state", "arguments": {"status": "open", "since_signature": br1["signature"]}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(br2["unchanged"])

            arch1 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 22, "method": "tools/call", "params": {"name": "gravity_get_architect_state", "arguments": {}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(arch1["available"])
            self.assertEqual(arch1["discovery_source"], "bridge_discovery")
            self.assertEqual(len(arch1["audits"]), 1)
            self.assertEqual(arch1["audits"][0]["verdict"], "PASS")
            arch2 = mcp_server.handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 23, "method": "tools/call", "params": {"name": "gravity_get_architect_state", "arguments": {"since_signature": arch1["signature"]}}},
                ctx=ctx,
            )["result"]["structuredContent"]  # type: ignore[index]
            self.assertTrue(arch2["unchanged"])

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


if __name__ == "__main__":
    unittest.main()

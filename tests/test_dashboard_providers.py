"""Isolated unit tests for plugin/dashboard/ (100% stdlib, TemporaryDirectory only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.registry import write_modules_registry  # noqa: E402
import dashboard  # noqa: E402
from dashboard import api  # noqa: E402
from dashboard import providers as dashboard_providers  # noqa: E402
from dashboard.providers import (  # noqa: E402
    DEDICATED_PROVIDERS,
    build_dashboard_tabs,
    resolve_provider_kind,
    short_digest,
    stat_token,
    unchanged_response,
)


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "GRAVITY_HOME",
        "GRAVITY_CORE_HOME",
        "GRAVITY_WORKFLOW_HOME",
        "GRAVITY_METRICS_HOME",
        "GRAVITY_ARCHITECT_HOME",
        "GRAVITY_ARCHITECT_WORKSPACE",
        "GRAVITY_AUDITS_DIR",
    ):
        env.pop(key, None)
    return env


def _write_module_plugin(
    plugins_root: Path,
    *,
    mod_id: str,
    plugin_name: str,
    version: str = "0.2.0",
    ui_mode: str = "none",
    dashboard_cfg: dict | None = None,
    provider_script_body: str = "",
) -> Path:
    mod_dir = plugins_root / plugin_name
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": plugin_name,
        "displayName": plugin_name.replace("-", " ").title(),
        "version": version,
        "description": f"Test plugin {plugin_name}",
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
        "role": f"Role for {mod_id}",
        "storage": {
            "subdir": mod_id,
            "env_override": f"GRAVITY_{mod_id.upper().replace('-', '_')}_HOME",
        },
        "commands": [f"/{plugin_name}"],
        "capabilities": ["cap-test"],
        "ui": {"mode": ui_mode, "target": "gravity"},
        "signals": {"produces": [f"{mod_id}-state"], "consumes": []},
    }
    if dashboard_cfg is not None:
        contract["dashboard"] = dashboard_cfg
    (mod_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    (mod_dir / "config" / "module.json").write_text(json.dumps(contract), encoding="utf-8", newline="\n")
    if provider_script_body:
        (mod_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (mod_dir / "scripts" / "dashboard_provider.py").write_text(
            provider_script_body,
            encoding="utf-8",
            newline="\n",
        )
    return mod_dir


class TestDashboardHelpers(unittest.TestCase):
    def test_provider_helpers_and_tab_ordering(self) -> None:
        self.assertEqual(DEDICATED_PROVIDERS, ("core", "workflow", "metrics", "architect"))
        self.assertEqual(resolve_provider_kind("core"), "core")
        self.assertEqual(resolve_provider_kind("workflow"), "workflow")
        self.assertEqual(resolve_provider_kind("metrics"), "metrics")
        self.assertEqual(resolve_provider_kind("bridge"), "generic")
        self.assertEqual(resolve_provider_kind("architect"), "architect")
        self.assertEqual(resolve_provider_kind("custom"), "generic")
        self.assertEqual(unchanged_response("abc"), {"changed": False, "unchanged": True, "signature": "abc"})
        self.assertEqual(len(short_digest(["a", 1])), 12)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sample.txt"
            self.assertEqual(stat_token(p), "missing")
            p.write_text("hello", encoding="utf-8")
            self.assertRegex(stat_token(p), r"^\d+:5$")

        modules = [
            {"id": "custom", "plugin_name": "gravity-custom", "valid": True},
            {"id": "bridge", "plugin_name": "gravity-bridge", "valid": True},
            {"id": "metrics", "plugin_name": "gravity-metrics", "valid": True},
            {"id": "architect", "plugin_name": "gravity-architect", "valid": True},
            {"id": "workflow", "plugin_name": "gravity-workflow", "valid": True},
            {"id": "core", "plugin_name": "gravity", "valid": True},
        ]
        tabs = build_dashboard_tabs(modules)
        self.assertEqual(
            [t["id"] for t in tabs],
            ["live", "architect", "metrics", "overview", "custom", "bridge"],
        )
        self.assertTrue(tabs[0]["dedicated"])
        self.assertTrue(tabs[1]["dedicated"])
        self.assertTrue(tabs[2]["dedicated"])
        self.assertTrue(tabs[3]["dedicated"])
        self.assertFalse(tabs[4]["dedicated"])
        self.assertFalse(tabs[5]["dedicated"])
        self.assertEqual(tabs[4]["kind"], "generic")
        self.assertEqual(tabs[5]["kind"], "generic")


class TestCoreAndGenericProviders(unittest.TestCase):
    def test_core_overview_uses_modules_json_shared_status_and_spi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            metrics_dir = _write_module_plugin(
                plugins_root,
                mod_id="metrics",
                plugin_name="gravity-metrics",
                ui_mode="transition-mcp",
                dashboard_cfg={
                    "provider_script": "scripts/dashboard_provider.py",
                    "views": ["metrics", "session-detail"],
                    "actions": ["record"],
                },
                provider_script_body="print('{}')\n",
            )
            _write_module_plugin(plugins_root, mod_id="bridge", plugin_name="gravity-bridge")

            (g_home / "core").mkdir(parents=True)
            (g_home / "metrics").mkdir(parents=True)
            sample_mods = [
                {
                    "id": "core",
                    "plugin_name": "gravity",
                    "display_name": "Gravity",
                    "version": "0.2.0",
                    "valid": True,
                    "errors": [],
                    "storage": {"subdir": "core", "env_override": "GRAVITY_CORE_HOME"},
                    "commands": ["/gravity"],
                    "capabilities": ["env-init"],
                    "ui": {"mode": "core", "target": "gravity"},
                    "signals": {"produces": [], "consumes": ["*"]},
                },
                {
                    "id": "metrics",
                    "plugin_name": "gravity-metrics",
                    "display_name": "Gravity Metrics",
                    "version": "0.5.0",
                    "valid": True,
                    "errors": [],
                    "storage": {"subdir": "metrics", "env_override": "GRAVITY_METRICS_HOME"},
                    "commands": ["/gravity-metrics"],
                    "capabilities": ["metrics"],
                    "ui": {"mode": "transition-mcp", "target": "gravity"},
                    "signals": {"produces": ["session-metrics"], "consumes": []},
                    "plugin_dir": str(metrics_dir),
                },
                {
                    "id": "bridge",
                    "plugin_name": "gravity-bridge",
                    "display_name": "Gravity Bridge",
                    "version": "0.3.0",
                    "valid": True,
                    "errors": [],
                    "storage": {"subdir": "bridge", "env_override": "GRAVITY_BRIDGE_HOME"},
                    "commands": ["/gravity-bridge"],
                    "capabilities": ["bridge"],
                    "ui": {"mode": "none", "target": "gravity"},
                    "signals": {"produces": ["bridge-threads"], "consumes": []},
                },
            ]
            write_modules_registry(g_home, sample_mods)

            ov = api.get_overview(gravity_home=g_home, plugin_roots=[plugins_root], home_dir=fake_user)
            self.assertEqual(ov["registry_source"], "modules.json")
            self.assertEqual(ov["doctor"]["status"], "ok")
            self.assertTrue(ov["doctor"]["initialized"])
            self.assertEqual([t["id"] for t in ov["tabs"]], ["live", "metrics", "overview", "bridge"])

            shared_status = ov.get("shared_status") or {}
            self.assertEqual(shared_status.get("status"), "ok")
            self.assertTrue(shared_status.get("manifest_exists"))
            self.assertTrue(shared_status.get("shared_dir_exists"))
            self.assertGreaterEqual(shared_status.get("actual_file_count", 0), 9)

            by_id = {m["id"]: m for m in ov["modules"]}
            self.assertTrue(by_id["core"]["home_exists"])
            self.assertFalse(by_id["core"]["spi"]["enabled"])
            self.assertTrue(by_id["metrics"]["home_exists"])
            self.assertTrue(by_id["metrics"]["spi"]["enabled"])
            self.assertEqual(by_id["metrics"]["spi"]["provider_script"], "scripts/dashboard_provider.py")
            self.assertEqual(by_id["metrics"]["spi"]["views"], ["metrics", "session-detail"])
            self.assertEqual(by_id["metrics"]["spi"]["actions"], ["record"])
            self.assertFalse(by_id["bridge"]["home_exists"])

            unchanged = api.get_overview(
                ov["signature"],
                gravity_home=g_home,
                plugin_roots=[plugins_root],
                home_dir=fake_user,
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": ov["signature"]})

    def test_core_overview_corrupt_registry_fallback_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            (fake_user / ".gemini" / "gravity-metrics").mkdir(parents=True)
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")

            ov_missing = api.get_overview(gravity_home=g_home, plugin_roots=[plugins_root], home_dir=fake_user)
            self.assertEqual(ov_missing["registry_source"], "discovered")
            self.assertFalse(g_home.exists())
            self.assertEqual(ov_missing["doctor"]["status"], "warn")
            self.assertEqual(ov_missing["doctor"]["legacy_count"], 1)

            (g_home / "core").mkdir(parents=True)
            reg_file = g_home / "core" / "modules.json"
            reg_file.write_text("{corrupt", encoding="utf-8")
            ov_corrupt = api.get_overview(gravity_home=g_home, plugin_roots=[plugins_root], home_dir=fake_user)
            self.assertEqual(ov_corrupt["registry_source"], "discovered")
            self.assertTrue(ov_corrupt["warnings"])
            self.assertEqual(reg_file.read_text(encoding="utf-8"), "{corrupt")

    def test_generic_module_info_validation_and_bounded_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="custom", plugin_name="gravity-custom")
            _write_module_plugin(plugins_root, mod_id="bridge", plugin_name="gravity-bridge")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics")

            custom_home = g_home / "custom"
            custom_home.mkdir(parents=True)
            for idx in range(30):
                (custom_home / f"item_{idx:02d}.txt").write_text(f"data-{idx}", encoding="utf-8")

            for bad_id in ("", "../escape", "a/b", "BadUpper"):
                res_bad = api.get_module_info(bad_id, gravity_home=g_home, plugin_roots=[plugins_root])
                self.assertFalse(res_bad["found"])
                self.assertIn("Invalid module_id", res_bad["error"])

            missing = api.get_module_info("unknown", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertFalse(missing["found"])

            info = api.get_module_info("custom", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(info["found"])
            self.assertEqual(info["plugin_name"], "gravity-custom")
            self.assertFalse(info["dedicated_provider"])
            self.assertTrue(info["storage"]["exists"])
            self.assertEqual(len(info["top_entries"]), 25)
            self.assertTrue(info["top_entries_truncated"])
            self.assertNotIn("content", info["top_entries"][0])

            bridge_info = api.get_module_info("bridge", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(bridge_info["found"])
            self.assertFalse(bridge_info["dedicated_provider"])

            metrics_info = api.get_module_info("metrics", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(metrics_info["found"])
            self.assertTrue(metrics_info["dedicated_provider"])


class TestBridgeNotInCoreApi(unittest.TestCase):
    def test_bridge_symbols_and_sqlite_removed_from_core_api(self) -> None:
        self.assertFalse(hasattr(api, "get_bridge_state"))
        self.assertFalse(hasattr(dashboard, "get_bridge_state"))
        self.assertNotIn("get_bridge_state", dashboard.__all__)
        self.assertNotIn("get_bridge_state", api.__all__)
        self.assertFalse(hasattr(dashboard_providers, "open_sqlite_ro"))
        self.assertNotIn("open_sqlite_ro", dashboard_providers.__all__)


class TestWorkflowProvider(unittest.TestCase):
    def test_workflow_absent_returns_clean_spi_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            g_home = Path(tmp) / "gravity-home"
            wf_home = Path(tmp) / "workflow"
            res = api.get_workflow_state(gravity_home=g_home, workflow_home=wf_home, plugin_roots=[])
            self.assertFalse(res["available"])
            self.assertTrue(res["spi_fallback"])
            self.assertEqual(res["stage"], "idle")
            self.assertEqual(res["progress"], "0/0")
            self.assertFalse(wf_home.exists())

    def test_workflow_routes_via_spi_companion(self) -> None:
        wf_script = """\
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
if a.since_signature == "wf-sig":
    print(json.dumps({"changed": False, "unchanged": True, "signature": "wf-sig"}))
else:
    print(json.dumps({
        "available": True,
        "changed": True,
        "unchanged": False,
        "signature": "wf-sig",
        "stage": "review",
        "progress": "2/3",
        "preset_profile": "deep",
        "ws_echo": req["params"].get("ws", ""),
        "events": [{"ts": "10:00:00", "decision": "allow"}],
    }))
"""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(
                plugins_root,
                mod_id="workflow",
                plugin_name="gravity-workflow",
                dashboard_cfg={"provider_script": "scripts/dashboard_provider.py", "views": ["workflow"], "actions": []},
                provider_script_body=wf_script,
            )
            res = api.get_workflow_state(ws="/tmp/ws1", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(res["available"])
            self.assertEqual(res["stage"], "review")
            self.assertEqual(res["progress"], "2/3")
            self.assertEqual(res["ws_echo"], "/tmp/ws1")

            unchanged = api.get_workflow_state(
                since_signature="wf-sig",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": "wf-sig"})


class TestMetricsProvider(unittest.TestCase):
    def test_metrics_absent_returns_clean_spi_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            g_home = Path(tmp) / "gravity-home"
            res = api.get_metrics_state(gravity_home=g_home, plugin_roots=[])
            self.assertFalse(res["available"])
            self.assertTrue(res["spi_fallback"])
            self.assertEqual(res["kpis"]["sessions_count"], 0)
            self.assertEqual(res["records"], [])

    def test_metrics_views_and_actions_route_via_spi(self) -> None:
        met_script = """\
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--action", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
if a.view == "metrics":
    if a.since_signature == "met-sig":
        print(json.dumps({"changed": False, "unchanged": True, "signature": "met-sig"}))
    else:
        print(json.dumps({
            "available": True,
            "changed": True,
            "unchanged": False,
            "signature": "met-sig",
            "kpis": {"sessions_count": 3, "useful_tokens": 12000, "cost_usd": 2.1},
            "pending_sessions": [{"conversation_id": "99999999-0000-1111-2222-333333333333"}],
            "records": [{"label": "lot-1a"}],
            "audits": [{"rel_path": "2026-11-23-review.md", "verdict": "NON BLOQUANT"}],
        }))
elif a.view == "session-detail":
    print(json.dumps({"found": True, "source": "report_json", "target": req["params"]["target"]}))
elif a.view == "audit-detail":
    print(json.dumps({"found": True, "path": req["params"]["path"], "content": "# Audit"}))
elif a.action:
    print(json.dumps({"ok": True, "action": a.action, "target": req["params"]["target"]}))
"""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(
                plugins_root,
                mod_id="metrics",
                plugin_name="gravity-metrics",
                dashboard_cfg={
                    "provider_script": "scripts/dashboard_provider.py",
                    "views": ["metrics", "session-detail", "audit-detail"],
                    "actions": ["record", "ignore"],
                },
                provider_script_body=met_script,
            )

            state = api.get_metrics_state(project="gravity", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(state["available"])
            self.assertEqual(state["kpis"]["sessions_count"], 3)
            self.assertEqual(state["kpis"]["useful_tokens"], 12000)

            unchanged = api.get_metrics_state(
                since_signature="met-sig",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": "met-sig"})

            det = api.get_session_detail("run-alpha", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(det["found"])
            self.assertEqual(det["target"], "run-alpha")

            aud = api.read_metrics_audit("2026-11-23-review.md", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(aud["found"])
            self.assertEqual(aud["path"], "2026-11-23-review.md")

            act = api.run_metrics_cli_action("record", target="abcdef12", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(act["ok"])
            self.assertEqual(act["target"], "abcdef12")


class TestArchitectProvider(unittest.TestCase):
    def test_architect_absent_returns_clean_spi_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            g_home = Path(tmp) / "gravity-home"
            res = api.get_architect_state(gravity_home=g_home, plugin_roots=[])
            self.assertFalse(res["available"])
            self.assertTrue(res["spi_fallback"])
            self.assertEqual(res["projects"], [])
            self.assertFalse(g_home.exists())

    def test_architect_routes_via_spi_companion(self) -> None:
        arch_script = """\
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
if a.since_signature == "arch-sig":
    print(json.dumps({"changed": False, "unchanged": True, "signature": "arch-sig"}))
else:
    print(json.dumps({
        "available": True,
        "changed": True,
        "unchanged": False,
        "signature": "arch-sig",
        "workspace_name": "gravity-workshop",
        "projects": [{"id": "gravity"}],
        "specs": [{"filename": "2026-11-26-spec-core-01.md"}],
        "tasks": [{"id": "TASK-CORE-01a"}],
        "handoffs": [],
        "audits": [{"rel_path": "2026-11-26-audit-code.md", "verdict": "PASS"}],
        "ctx_echo": req["context"].get("architect_workspace"),
    }))
"""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            atelier = tmp_path / "gravity-workshop"
            atelier.mkdir()
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(
                plugins_root,
                mod_id="architect",
                plugin_name="gravity-architect",
                dashboard_cfg={"provider_script": "scripts/dashboard_provider.py", "views": ["architect"], "actions": []},
                provider_script_body=arch_script,
            )

            res = api.get_architect_state(
                gravity_home=g_home,
                architect_workspace=atelier,
                plugin_roots=[plugins_root],
            )
            self.assertTrue(res["available"])
            self.assertEqual(res["workspace_name"], "gravity-workshop")
            self.assertEqual(res["ctx_echo"], str(atelier))

            unchanged = api.get_architect_state(
                since_signature="arch-sig",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": "arch-sig"})


class TestDashboardFacade(unittest.TestCase):
    def test_build_initial_summary_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_module_plugin(plugins_root, mod_id="workflow", plugin_name="gravity-workflow", ui_mode="mcp-app")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="mcp-app")
            _write_module_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect")

            summary = api.build_initial_summary(
                view="workflow",
                gravity_home=g_home,
                plugin_roots=[plugins_root],
                home_dir=fake_user,
            )
            self.assertIn("Gravity Dashboard", summary)
            self.assertIn("Live:", summary)
            self.assertIn("Workflow:", summary)
            self.assertIn("Metrics", summary)
            self.assertIn("Architect:", summary)
            self.assertNotIn("Bridge:", summary)
            self.assertNotIn("0/8", summary)


if __name__ == "__main__":
    unittest.main()

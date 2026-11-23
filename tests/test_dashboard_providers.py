"""Isolated unit tests for plugin/dashboard/ (100% stdlib, TemporaryDirectory only)."""

from __future__ import annotations

import hashlib
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
from dashboard import api  # noqa: E402
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
        "GRAVITY_BRIDGE_HOME",
        "GRAVITY_ARCHITECT_HOME",
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
    (mod_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (mod_dir / "config" / "module.json").write_text(json.dumps(contract), encoding="utf-8")
    return mod_dir


class TestDashboardHelpers(unittest.TestCase):
    def test_provider_helpers_and_tab_ordering(self) -> None:
        self.assertEqual(DEDICATED_PROVIDERS, ("core", "workflow", "metrics"))
        self.assertEqual(resolve_provider_kind("core"), "core")
        self.assertEqual(resolve_provider_kind("workflow"), "workflow")
        self.assertEqual(resolve_provider_kind("metrics"), "metrics")
        self.assertEqual(resolve_provider_kind("bridge"), "generic")
        self.assertEqual(unchanged_response("abc"), {"changed": False, "unchanged": True, "signature": "abc"})
        self.assertEqual(len(short_digest(["a", 1])), 12)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sample.txt"
            self.assertEqual(stat_token(p), "missing")
            p.write_text("hello", encoding="utf-8")
            self.assertRegex(stat_token(p), r"^\d+:5$")

        modules = [
            {"id": "bridge", "plugin_name": "gravity-bridge", "valid": True},
            {"id": "metrics", "plugin_name": "gravity-metrics", "valid": True},
            {"id": "architect", "plugin_name": "gravity-architect", "valid": True},
            {"id": "workflow", "plugin_name": "gravity-workflow", "valid": True},
            {"id": "core", "plugin_name": "gravity", "valid": True},
        ]
        tabs = build_dashboard_tabs(modules)
        self.assertEqual([t["id"] for t in tabs], ["overview", "workflow", "metrics", "bridge", "architect"])
        self.assertTrue(tabs[0]["dedicated"])
        self.assertTrue(tabs[1]["dedicated"])
        self.assertTrue(tabs[2]["dedicated"])
        self.assertFalse(tabs[3]["dedicated"])
        self.assertEqual(tabs[3]["kind"], "generic")


class TestCoreAndGenericProviders(unittest.TestCase):
    def test_core_overview_uses_modules_json_and_since_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="transition-mcp")
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
            self.assertEqual([t["id"] for t in ov["tabs"]], ["overview", "metrics", "bridge"])

            by_id = {m["id"]: m for m in ov["modules"]}
            self.assertTrue(by_id["core"]["home_exists"])
            self.assertTrue(by_id["metrics"]["home_exists"])
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
            (fake_user / ".gemini" / "gravity-bridge").mkdir(parents=True)
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")

            # Missing modules.json -> read-only discovery, never creates modules.json
            ov_missing = api.get_overview(gravity_home=g_home, plugin_roots=[plugins_root], home_dir=fake_user)
            self.assertEqual(ov_missing["registry_source"], "discovered")
            self.assertFalse(g_home.exists())
            self.assertEqual(ov_missing["doctor"]["status"], "warn")
            self.assertEqual(ov_missing["doctor"]["legacy_count"], 1)

            # Corrupt modules.json -> warning + fallback discovery, file untouched
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
            _write_module_plugin(plugins_root, mod_id="bridge", plugin_name="gravity-bridge")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics")

            bridge_home = g_home / "bridge"
            bridge_home.mkdir(parents=True)
            for idx in range(30):
                (bridge_home / f"item_{idx:02d}.txt").write_text(f"data-{idx}", encoding="utf-8")

            for bad_id in ("", "../escape", "a/b", "BadUpper"):
                res_bad = api.get_module_info(bad_id, gravity_home=g_home, plugin_roots=[plugins_root])
                self.assertFalse(res_bad["found"])
                self.assertIn("Invalid module_id", res_bad["error"])

            missing = api.get_module_info("unknown", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertFalse(missing["found"])

            info = api.get_module_info("bridge", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(info["found"])
            self.assertEqual(info["plugin_name"], "gravity-bridge")
            self.assertFalse(info["dedicated_provider"])
            self.assertTrue(info["storage"]["exists"])
            self.assertEqual(len(info["top_entries"]), 25)
            self.assertTrue(info["top_entries_truncated"])
            self.assertNotIn("content", info["top_entries"][0])

            metrics_info = api.get_module_info("metrics", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(metrics_info["found"])
            self.assertTrue(metrics_info["dedicated_provider"])


class TestWorkflowProvider(unittest.TestCase):
    def test_workflow_absent_and_corrupt_returns_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            wf_home = Path(tmp) / "workflow"
            res = api.get_workflow_state(workflow_home=wf_home)
            self.assertFalse(res["available"])
            self.assertEqual(res["stage"], "idle")
            self.assertFalse(wf_home.exists())

            wf_home.mkdir(parents=True)
            (wf_home / "live_workspaces.json").write_text("{broken", encoding="utf-8")
            res_corrupt = api.get_workflow_state(workflow_home=wf_home)
            self.assertFalse(res_corrupt["available"])
            self.assertEqual(res_corrupt["stage"], "idle")
            self.assertTrue(res_corrupt["warnings"])

    def test_workflow_registry_guardrail_events_cap_and_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            wf_home = tmp_path / "workflow"
            ws1 = tmp_path / "proj-one"
            ws2 = tmp_path / "proj-two"
            ws3 = tmp_path / "proj-three"
            ws1.mkdir()
            ws2.mkdir()
            ws3.mkdir()

            state1 = wf_home / "workspaces" / "proj-one-11111111" / "live_state.json"
            state1.parent.mkdir(parents=True)
            events = [{"ts": f"10:00:{i:02d}", "decision": "allow", "tool": "read_file"} for i in range(60)]
            state1.write_text(
                json.dumps(
                    {
                        "stage": "review",
                        "progress": "6/8",
                        "mode": "evo",
                        "level": "deep",
                        "preset_profile": "deep",
                        "suggested_profile": "standard",
                        "suggested_reason": "low complexity",
                        "role_models": {"plan": "pro", "build": "flash", "review": "pro"},
                        "caveman": "ultra",
                        "caveman_locked": True,
                        "guard_status": "ON",
                        "nodes": {"planner": "done", "builder": "done", "reviewer": "active"},
                        "events": events,
                    }
                ),
                encoding="utf-8",
            )
            bad_secret = tmp_path / "secrets.json"
            bad_secret.write_text('{"secret": "do-not-read"}', encoding="utf-8")

            reg = wf_home / "live_workspaces.json"
            reg.write_text(
                json.dumps(
                    {
                        "workspaces": [
                            {
                                "workspace_path": str(ws1),
                                "state_path": str(state1),
                                "updated_at": "2026-11-23T12:00:00Z",
                            },
                            {
                                "workspace_path": str(ws1),
                                "state_path": str(bad_secret),
                                "updated_at": "2026-11-23T12:05:00Z",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            res = api.get_workflow_state(workflow_home=wf_home)
            self.assertTrue(res["available"])
            self.assertEqual(res["stage"], "review")
            self.assertEqual(res["preset_profile"], "deep")
            self.assertEqual(res["suggested_profile"], "standard")
            self.assertTrue(res["caveman_locked"])
            self.assertEqual(len(res["events"]), 50)
            self.assertEqual(len(res["workspaces"]), 1)
            self.assertTrue(any("secrets.json" in w for w in res["warnings"]))

            unchanged = api.get_workflow_state(since_signature=res["signature"], workflow_home=wf_home)
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": res["signature"]})

            # Fallback central hash for ws2 absent from registry
            resolved_ws2 = ws2.resolve()
            norm2 = os.path.normcase(str(resolved_ws2))
            digest2 = hashlib.sha256(norm2.encode("utf-8")).hexdigest()[:8]
            state2 = wf_home / "workspaces" / f"proj-two-{digest2}" / "live_state.json"
            state2.parent.mkdir(parents=True)
            state2.write_text(json.dumps({"stage": "build", "progress": "4/8"}), encoding="utf-8")

            res_ws2 = api.get_workflow_state(ws=str(ws2), workflow_home=wf_home)
            self.assertTrue(res_ws2["available"])
            self.assertEqual(res_ws2["stage"], "build")
            self.assertEqual(res_ws2["selected_workspace"]["source"], "central_fallback")

            # Fallback local .agents/gravity-workflow/observability/live_state.json for ws3
            state3 = ws3 / ".agents" / "gravity-workflow" / "observability" / "live_state.json"
            state3.parent.mkdir(parents=True)
            state3.write_text(json.dumps({"stage": "plan", "progress": "2/8"}), encoding="utf-8")

            res_ws3 = api.get_workflow_state(ws=str(ws3), workflow_home=wf_home)
            self.assertTrue(res_ws3["available"])
            self.assertEqual(res_ws3["stage"], "plan")
            self.assertEqual(res_ws3["selected_workspace"]["source"], "local_fallback")


class TestMetricsProvider(unittest.TestCase):
    def test_metrics_history_filters_pending_audits_and_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            m_home = tmp_path / "metrics"
            (m_home / "data").mkdir(parents=True)
            (m_home / "METRICS.md").write_text("# Metrics\n", encoding="utf-8")

            ws_dir = tmp_path / "repo-alpha"
            agents_dir = ws_dir / "audits" / "agents"
            code_dir = ws_dir / "audits" / "code"
            agents_dir.mkdir(parents=True)
            code_dir.mkdir(parents=True)
            (agents_dir / "README.md").write_text("# Index Audits\n\nSummary index.\n", encoding="utf-8")
            (agents_dir / "_TEMPLATE.md").write_text("# Template\n", encoding="utf-8")
            (agents_dir / "2026-11-23-review.md").write_text(
                "# Audit Lot 1A\n\nVerdict: NON BLOQUANT\n\nEverything looks clean and modular.\n",
                encoding="utf-8",
            )
            (code_dir / "2026-11-23-secret-code-audit.md").write_text(
                "# Code Audit\n\nVerdict: BLOQUANT\n", encoding="utf-8"
            )

            rec_v05 = {
                "schema_version": 2,
                "status": "archived",
                "label": "lot-1a",
                "detail_slug": "lot-1a",
                "conversation_id": "11111111-2222-3333-4444-555555555555",
                "project": "Gravity",
                "primary_model": "gemini-2.5-pro",
                "execution_mode": "swarm",
                "current_phase": "Clôture",
                "cost_usd": 1.25,
                "cost_2027_usd": 1.50,
                "cache_savings_usd": 0.40,
                "cache_hit_rate_pct": 80.0,
                "total_tokens": 10_000,
                "llm_calls": 10,
                "bridge_children_count": 2,
            }
            rec_v043 = {
                "label": "legacy-run",
                "conversation_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "project": "gravity",
                "primary_model": "gemini-2.5-flash",
                "cost_usd": 0.75,
                "cache_savings_usd": 0.10,
                "cache_hit_rate_pct": 60.0,
                "total_tokens": 5_000,
                "llm_calls": 4,
            }
            rec_active = {
                "status": "active",
                "label": "live-run",
                "conversation_id": "99999999-0000-1111-2222-333333333333",
                "project": "Other",
                "cost_usd": 0.10,
                "cache_hit_rate_pct": 50.0,
                "total_tokens": 1_000,
                "llm_calls": 2,
            }
            (m_home / "data" / "history.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(rec_v05),
                        "{broken-jsonl-line",
                        json.dumps(rec_v043),
                        json.dumps(rec_active),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (m_home / "active_captures.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "captures": {
                            "99999999-0000-1111-2222-333333333333": {
                                "start_step": 3,
                                "label": "live-run",
                                "project": "Other",
                                "updated_at": "2026-11-23T10:00:00Z",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (m_home / "ignored.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ignored": {
                            "77777777-0000-1111-2222-333333333333": {
                                "ignored_at": "2026-11-23T09:00:00Z",
                                "reason": "noise",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (m_home / "session_meta.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sessions": {
                            "99999999-0000-1111-2222-333333333333": {
                                "cwd": str(ws_dir),
                                "project": "Other",
                                "updated_at": "2026-11-23T10:00:00Z",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            state = api.get_metrics_state(metrics_home=m_home)
            self.assertEqual(state["total_records"], 3)
            self.assertEqual(state["kpis"]["sessions_count"], 3)
            self.assertEqual(state["kpis"]["archived_count"], 2)
            self.assertEqual(state["kpis"]["active_count"], 1)
            self.assertAlmostEqual(state["kpis"]["cost_usd"], 2.1)
            self.assertAlmostEqual(state["kpis"]["cost_2027_usd"], 2.35)
            self.assertEqual(state["kpis"]["bridge_sessions_count"], 1)
            self.assertEqual(state["kpis"]["bridge_children_total"], 2)
            self.assertTrue(state["metrics_md_uri"].startswith("file://"))
            self.assertTrue(any("corrupted" in w for w in state["warnings"]))
            self.assertEqual(len(state["pending_sessions"]), 1)
            self.assertEqual(len(state["ignored_sessions"]), 1)

            # Audits checks: README separated into index_audit, _TEMPLATE and code/ excluded
            self.assertEqual(len(state["audits"]), 1)
            self.assertEqual(state["audits"][0]["verdict"], "NON BLOQUANT")
            self.assertEqual(state["audits"][0]["verdict_tone"], "ok")
            self.assertNotIn("content", state["audits"][0])
            self.assertIsNotNone(state["index_audit"])
            self.assertEqual(state["index_audit"]["rel_path"], "README.md")

            # Filter by project & query
            filtered = api.get_metrics_state(project="GRAVITY", q="legacy", metrics_home=m_home)
            self.assertEqual(filtered["total_matching"], 1)
            self.assertEqual(filtered["records"][0]["label"], "legacy-run")

            # Fast-path since_signature
            unchanged = api.get_metrics_state(since_signature=state["signature"], metrics_home=m_home)
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": state["signature"]})

            # Explicit audits_dir pointing to audits/code must yield 0 audits
            no_code = api.get_metrics_state(metrics_home=m_home, audits_dirs=[code_dir])
            self.assertEqual(no_code["audits"], [])

    def test_metrics_payload_cap_under_450kb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            m_home = Path(tmp) / "metrics"
            (m_home / "data").mkdir(parents=True)
            big_note = "x" * 3000
            lines = [
                json.dumps(
                    {
                        "conversation_id": f"{i:08x}-0000-0000-0000-000000000000",
                        "label": f"run-{i:03d}",
                        "project": "Big",
                        "note": big_note,
                        "cost_usd": 1.0,
                    }
                )
                for i in range(250)
            ]
            (m_home / "data" / "history.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

            res = api.get_metrics_state(limit=999, metrics_home=m_home, audits_dirs=[])
            self.assertEqual(res["filters"]["limit"], 500)
            self.assertEqual(res["total_matching"], 250)
            self.assertEqual(res["kpis"]["sessions_count"], 250)
            self.assertTrue(res["truncated"])
            encoded_len = len(json.dumps(res, ensure_ascii=False).encode("utf-8"))
            self.assertLess(encoded_len, 450_000)

    def test_session_detail_resolution_stripping_and_confinement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            m_home = Path(tmp) / "metrics"
            (m_home / "data").mkdir(parents=True)
            (m_home / "reports").mkdir(parents=True)
            (m_home / "secret.json").write_text('{"leaked": true}', encoding="utf-8")

            cid1 = "abcdef12-3456-7890-abcd-ef1234567890"
            cid2 = "12345678-0000-0000-0000-000000000001"
            records = [
                {"conversation_id": cid1, "label": "Run Alpha", "detail_slug": "run-alpha", "cost_usd": 0.5},
                {"conversation_id": cid2, "label": "Traversal", "detail_slug": "../secret", "cost_usd": 0.1},
            ]
            (m_home / "data" / "history.jsonl").write_text(
                "\n".join(json.dumps(r) for r in records) + "\n",
                encoding="utf-8",
            )
            (m_home / "reports" / "run-alpha.json").write_text(
                json.dumps(
                    {
                        "label": "Run Alpha",
                        "summary": {"total_tokens": 1200},
                        "trajectory": [{"step": 1, "raw": "secret"}],
                        "agents": [{"role": "planner", "steps": [{"raw": "hidden"}]}],
                    }
                ),
                encoding="utf-8",
            )
            (m_home / "reports" / "run-alpha.md").write_text("# Run Alpha\n", encoding="utf-8")

            for key in ("run-alpha", "run alpha", cid1, "abcdef12"):
                det = api.get_session_detail(key, metrics_home=m_home)
                self.assertTrue(det["found"])
                self.assertEqual(det["source"], "report_json")
                self.assertNotIn("trajectory", det["detail"])
                self.assertNotIn("steps", det["detail"]["agents"][0])
                self.assertTrue(det["report_md_uri"].startswith("file://"))

            trav = api.get_session_detail("Traversal", metrics_home=m_home)
            self.assertTrue(trav["found"])
            self.assertEqual(trav["source"], "history_fallback")
            self.assertNotIn("leaked", trav["detail"])
            self.assertTrue(trav["warnings"])

            short_pref = api.get_session_detail("abcdef", metrics_home=m_home)
            self.assertFalse(short_pref["found"])


class TestDashboardFacade(unittest.TestCase):
    def test_build_initial_summary_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_module_plugin(plugins_root, mod_id="workflow", plugin_name="gravity-workflow", ui_mode="transition-sidecar")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="transition-mcp")

            summary = api.build_initial_summary(
                gravity_home=g_home,
                plugin_roots=[plugins_root],
                home_dir=fake_user,
            )
            self.assertIn("Gravity Dashboard", summary)
            self.assertIn("Workflow:", summary)
            self.assertIn("Metrics", summary)


if __name__ == "__main__":
    unittest.main()

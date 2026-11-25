"""Isolated unit tests for plugin/dashboard/ (100% stdlib, TemporaryDirectory only)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
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
        self.assertEqual(DEDICATED_PROVIDERS, ("core", "workflow", "metrics", "architect"))
        self.assertEqual(resolve_provider_kind("core"), "core")
        self.assertEqual(resolve_provider_kind("workflow"), "workflow")
        self.assertEqual(resolve_provider_kind("metrics"), "metrics")
        self.assertEqual(resolve_provider_kind("architect"), "architect")
        self.assertEqual(resolve_provider_kind("bridge"), "generic")
        self.assertEqual(resolve_provider_kind("custom"), "generic")
        self.assertEqual(unchanged_response("abc"), {"changed": False, "unchanged": True, "signature": "abc"})
        self.assertEqual(len(short_digest(["a", 1])), 12)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sample.txt"
            self.assertEqual(stat_token(p), "missing")
            p.write_text("hello", encoding="utf-8")
            self.assertRegex(stat_token(p), r"^\d+:5$")

        modules_4 = [
            {"id": "metrics", "plugin_name": "gravity-metrics", "valid": True},
            {"id": "architect", "plugin_name": "gravity-architect", "valid": True},
            {"id": "workflow", "plugin_name": "gravity-workflow", "valid": True},
            {"id": "core", "plugin_name": "gravity", "valid": True},
        ]
        tabs_4 = build_dashboard_tabs(modules_4)
        self.assertEqual([t["id"] for t in tabs_4], ["live", "architect", "metrics", "overview"])
        self.assertEqual([t["label"] for t in tabs_4], ["Session", "Projets", "Historique", "Système"])
        self.assertTrue(all(t["dedicated"] for t in tabs_4))

        modules = [
            {"id": "custom", "plugin_name": "gravity-custom", "valid": True},
            {"id": "bridge", "plugin_name": "gravity-bridge", "valid": True},
            *modules_4,
        ]
        tabs = build_dashboard_tabs(modules)
        self.assertEqual([t["id"] for t in tabs], ["live", "architect", "metrics", "overview", "custom", "bridge"])
        self.assertTrue(all(t["dedicated"] for t in tabs[:4]))
        self.assertFalse(tabs[4]["dedicated"])
        self.assertEqual(tabs[4]["kind"], "generic")
        self.assertFalse(tabs[5]["dedicated"])
        self.assertEqual(tabs[5]["kind"], "generic")


class TestCoreAndGenericProviders(unittest.TestCase):
    def test_core_overview_uses_modules_json_and_since_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="none")
            _write_module_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect")

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
                    "ui": {"mode": "none", "target": "gravity"},
                    "signals": {"produces": ["session-metrics"], "consumes": []},
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
                    "capabilities": ["architect"],
                    "ui": {"mode": "none", "target": "gravity"},
                    "signals": {"produces": ["specs"], "consumes": []},
                },
            ]
            write_modules_registry(g_home, sample_mods)

            ov = api.get_overview(gravity_home=g_home, plugin_roots=[plugins_root], home_dir=fake_user)
            self.assertEqual(ov["registry_source"], "modules.json")
            self.assertEqual(ov["doctor"]["status"], "ok")
            self.assertTrue(ov["doctor"]["initialized"])
            self.assertEqual([t["id"] for t in ov["tabs"]], ["live", "architect", "metrics", "overview"])

            by_id = {m["id"]: m for m in ov["modules"]}
            self.assertTrue(by_id["core"]["home_exists"])
            self.assertTrue(by_id["metrics"]["home_exists"])
            self.assertFalse(by_id["architect"]["home_exists"])

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
            _write_module_plugin(plugins_root, mod_id="custom", plugin_name="gravity-custom")
            _write_module_plugin(plugins_root, mod_id="bridge", plugin_name="gravity-bridge")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics")
            _write_module_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect")

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

            architect_info = api.get_module_info("architect", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(architect_info["found"])
            self.assertTrue(architect_info["dedicated_provider"])


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

            state = api.get_metrics_state(gravity_home=tmp_path, metrics_home=m_home)
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
            filtered = api.get_metrics_state(project="GRAVITY", q="legacy", gravity_home=tmp_path, metrics_home=m_home)
            self.assertEqual(filtered["total_matching"], 1)
            self.assertEqual(filtered["records"][0]["label"], "legacy-run")

            # Fast-path since_signature
            unchanged = api.get_metrics_state(
                since_signature=state["signature"],
                gravity_home=tmp_path,
                metrics_home=m_home,
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": state["signature"]})

            # Explicit audits_dir pointing to audits/code must yield 0 audits
            no_code = api.get_metrics_state(gravity_home=tmp_path, metrics_home=m_home, audits_dirs=[code_dir])
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

            res = api.get_metrics_state(limit=999, gravity_home=Path(tmp), metrics_home=m_home, audits_dirs=[])
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


_BRIDGE_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
CREATE TABLE workspaces (
    slug TEXT PRIMARY KEY,
    canonical_path TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    sidecar_id TEXT,
    sidecar_pid INTEGER,
    sidecar_last_seen_at TEXT,
    project_id TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    from_workspace TEXT NOT NULL,
    to_workspace TEXT NOT NULL,
    msg_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    approved INTEGER NOT NULL DEFAULT 0,
    target_conversation_id TEXT,
    caller_conversation_id TEXT,
    notify_caller INTEGER NOT NULL DEFAULT 0,
    callback_dispatched_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    sender_workspace TEXT NOT NULL,
    msg_type TEXT NOT NULL,
    body TEXT NOT NULL,
    file_refs_json TEXT NOT NULL DEFAULT '[]',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    target_workspace TEXT NOT NULL,
    action TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'outbound',
    model TEXT,
    sidecar_id TEXT,
    target_conversation_id TEXT,
    status TEXT NOT NULL,
    exit_code INTEGER,
    error_summary TEXT,
    claimed_at TEXT,
    dispatched_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL
);
"""


def _create_sample_bridge_db(db_path: Path, *, studio_path: Optional[Path] = None) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    recent_iso = (now - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_iso = (now - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ws_studio = str(studio_path.resolve()) if studio_path else "/tmp/studio"

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_BRIDGE_SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO workspaces (
                slug, canonical_path, display_name, sidecar_id, sidecar_pid,
                sidecar_last_seen_at, project_id, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("gravity", "/tmp/gravity", "Gravity", "sc-gravity", 1234, recent_iso, "gravity", recent_iso, recent_iso),
                ("gravity-studio", ws_studio, "Gravity Studio", "sc-studio", 5678, stale_iso, "studio", stale_iso, stale_iso),
                ("metrics", "/tmp/metrics", "Metrics", None, None, None, None, stale_iso, stale_iso),
            ],
        )
        conn.executemany(
            """
            INSERT INTO threads (
                id, from_workspace, to_workspace, msg_type, subject, status,
                approved, target_conversation_id, caller_conversation_id,
                notify_caller, callback_dispatched_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("thr-open-1", "gravity-studio", "gravity", "handoff", "Lot 2", "open", 1, "conv-t1", "conv-c1", 1, None, stale_iso, recent_iso),
                ("thr-done-1", "gravity", "metrics", "info", "Sync OK", "done", 1, None, None, 0, None, stale_iso, stale_iso),
            ],
        )
        long_body = "Header " + ("detail-" * 45)
        conn.executemany(
            """
            INSERT INTO messages (
                thread_id, sender_workspace, msg_type, body, file_refs_json, is_read, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("thr-open-1", "gravity-studio", "handoff", "Initial body", "[]", 1, stale_iso),
                ("thr-open-1", "gravity-studio", "reply", long_body, "[]", 0, recent_iso),
                ("thr-done-1", "gravity", "info", "Completed clean", "[]", 1, stale_iso),
            ],
        )
        conn.executemany(
            """
            INSERT INTO jobs (
                id, thread_id, message_id, target_workspace, action, direction, model,
                sidecar_id, target_conversation_id, status, exit_code, error_summary,
                claimed_at, dispatched_at, finished_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("job-1", "thr-open-1", 1, "gravity", "new_conversation", "outbound", "pro", "sc-gravity", "conv-t1", "completed", 0, None, stale_iso, stale_iso, recent_iso, stale_iso),
                ("job-2", "thr-open-1", 2, "gravity-studio", "send_message", "callback", "flash", "sc-studio", "conv-c1", "queued", None, None, None, None, None, recent_iso),
            ],
        )
        conn.commit()
    finally:
        conn.close()


class TestBridgeRetirement(unittest.TestCase):
    def test_bridge_provider_and_w2_shims_removed(self) -> None:
        self.assertFalse((PLUGIN_ROOT / "dashboard" / "providers" / "bridge_provider.py").exists())
        self.assertFalse(hasattr(api, "get_bridge_state"))
        self.assertFalse(hasattr(dashboard, "get_bridge_state"))
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("dashboard.providers.bridge_provider")
        with self.assertRaises(TypeError):
            api.get_architect_state(bridge_home=Path("."))  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            api.build_initial_summary(bridge={}, bridge_home=Path("."), db_path=Path("x"))  # type: ignore[call-arg]


class TestArchitectProvider(unittest.TestCase):
    def _write_mini_atelier(self, root: Path) -> None:
        (root / "tracking" / "snapshots").mkdir(parents=True)
        (root / "tracking" / "projects").mkdir(parents=True)
        (root / "specs" / "archive").mkdir(parents=True)
        (root / "tasks" / "archive").mkdir(parents=True)
        (root / "audits" / "code").mkdir(parents=True)
        (root / "audits" / "agents").mkdir(parents=True)

        (root / "ECOSYSTEM.md").write_text(
            "# Tableau de bord\n\n"
            "<!-- AUTO:START:ecosystem-projects -->\n"
            "| Projet | Release (`main`) | Branche `dev` | Installé local | WIP | Fiche |\n"
            "|---|---|---|---|---|---|\n"
            "| **Gravity Core** (`../gravity`) | `v0.3.0` (`abc123`) | `0.3.0` (+2 vs `main`) | `0.3.0` *(aligné)* | **Propre** | [`gravity.md`](tracking/projects/gravity.md) |\n"
            "| **Gravity Metrics** (`../gravity-metrics`) | `v0.5.1` | `0.5.1` | `0.5.1` | **Propre** |\n"
            "<!-- AUTO:END:ecosystem-projects -->\n\n"
            "<!-- AUTO:START:ecosystem-hygiene -->\n"
            "- `gravity` : WIP local détecté.\n"
            "<!-- AUTO:END:ecosystem-hygiene -->\n",
            encoding="utf-8",
        )
        (root / "tracking" / "snapshots" / "delta.md").write_text(
            "# Delta\n\n"
            "- **Date :** `2026-11-23T22:00:00Z`\n"
            "- **Statut éditorial :** `EDITORIAL_UPDATE_REQUIRED`\n"
            "- **Veilles :** `ok`\n",
            encoding="utf-8",
        )
        (root / "projects.json").write_text(
            json.dumps(
                {
                    "schema_version": 5,
                    "workspace_name": "Atelier Test",
                    "hot_budgets": {"ECOSYSTEM.md": 6000, "project_card_max_bytes": 3500},
                    "watches": [{"id": "antigravity"}],
                    "projects": [
                        {
                            "id": "gravity",
                            "name": "Gravity",
                            "path": "../gravity",
                            "default_dev_branch": "dev-next",
                            "role": "Core plugin",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "tracking" / "projects" / "gravity.md").write_text("# Gravity\n", encoding="utf-8")
        (root / "specs" / "_TEMPLATE.md").write_text("# Template Spec\n", encoding="utf-8")
        (root / "specs" / "2026-11-23-dashboard.md").write_text(
            "# Dashboard Spec\n\n- **Date / Statut :** `validated`\n- **Projets impactés :** `gravity`\n",
            encoding="utf-8",
        )
        (root / "specs" / "archive" / "2026-11-01-old.md").write_text("# Old Spec\n", encoding="utf-8")
        (root / "tasks" / "_TEMPLATE.md").write_text("# Template Task\n", encoding="utf-8")
        (root / "tasks" / "2026-11-23-lot2.md").write_text(
            "# Lot 2\n\n"
            "- **Vague :** `2`\n"
            "- **Dépôt cible :** `gravity` (`../gravity`)\n"
            "- **Branche attendue :** `dev`\n"
            "- **Dépendances :** `2026-11-23-lot1`\n"
            "- **Profil workflow :** `standard`\n"
            "- **Spec source :** `specs/2026-11-23-dashboard.md`\n"
            "- **Date / Statut :** `2026-11-23` — `ready`\n",
            encoding="utf-8",
        )
        (root / "tasks" / "archive" / "2026-11-01-old-task.md").write_text("# Old Task\n", encoding="utf-8")
        (root / "audits" / "code" / "README.md").write_text("# Index Audits Code\n", encoding="utf-8")
        (root / "audits" / "code" / "_TEMPLATE.md").write_text("# Template Audit\n", encoding="utf-8")
        (root / "audits" / "code" / "2026-11-23-audit-code-gravity.md").write_text(
            "# Audit Code Gravity\n\n- **Cible :** `gravity`\n- **Verdict :** `PASS`\n\nClean architecture.\n",
            encoding="utf-8",
        )
        (root / "audits" / "code" / "2026-11-24-audit-code-ecosystem.md").write_text(
            "# Audit Code Ecosystem\n\n- **Cible :** `ecosystem (gravity, gravity-architect)`\n- **Verdict :** `PASS`\n\nEcosystem audit.\n",
            encoding="utf-8",
        )
        (root / "audits" / "agents" / "2026-11-23-secret-agent.md").write_text(
            "# Agent Audit\n\nVerdict: BLOQUANT\n",
            encoding="utf-8",
        )

    def test_architect_absent_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            g_home = Path(tmp) / "gravity-home"
            res = api.get_architect_state(gravity_home=g_home)
            self.assertFalse(res["available"])
            self.assertEqual(res["discovery_source"], "module_home")
            self.assertFalse(g_home.exists())

    def test_architect_discovery_precedence_and_code_audit_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            arch_home = g_home / "architect"
            arch_home.mkdir(parents=True)
            atelier = tmp_path / "gravity-studio"
            self._write_mini_atelier(atelier)
            (arch_home / "ateliers.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ateliers": [{"workspace_path": str(atelier), "updated_at": "2026-11-24T10:00:00Z"}],
                    }
                ),
                encoding="utf-8",
            )
            # Residual bridge.db pointing to another atelier must be ignored completely
            b_home = g_home / "bridge"
            other_bridge = tmp_path / "ignored-bridge-atelier"
            self._write_mini_atelier(other_bridge)
            _create_sample_bridge_db(b_home / "bridge.db", studio_path=other_bridge)

            via_registry = api.get_architect_state(gravity_home=g_home)
            self.assertTrue(via_registry["available"])
            self.assertEqual(via_registry["discovery_source"], "architect_registry")
            self.assertEqual(Path(via_registry["atelier_root"]), atelier.resolve())
            self.assertEqual(via_registry["workspace_name"], "Atelier Test")
            self.assertTrue(via_registry["ecosystem"]["exists"])
            self.assertEqual(via_registry["ecosystem"]["alerts"], ["gravity : WIP local détecté."])
            self.assertEqual(via_registry["delta"]["editorial_status"], "EDITORIAL_UPDATE_REQUIRED")
            self.assertEqual(len(via_registry["projects"]), 1)
            proj0 = via_registry["projects"][0]
            self.assertEqual(proj0["default_dev_branch"], "dev-next")
            self.assertEqual(proj0["dev_branch"], "dev-next")
            self.assertEqual(proj0["role"], "Core plugin")
            self.assertEqual(proj0["release_main"], "v0.3.0 (abc123)")
            self.assertEqual(proj0["dev_status"], "0.3.0 (+2 vs main)")
            self.assertEqual(proj0["installed_version"], "0.3.0 (aligné)")
            self.assertEqual(proj0["wip_status"], "Propre")
            self.assertEqual(proj0["specs_count"], 1)
            self.assertEqual(proj0["tasks_count"], 1)
            self.assertEqual(proj0["audits_count"], 2)
            self.assertIn("gravity-metrics", via_registry["ecosystem"]["projects_status"])
            self.assertEqual(via_registry["ecosystem"]["projects_status"]["gravity-metrics"]["release_main"], "v0.5.1")
            self.assertEqual([s["filename"] for s in via_registry["specs"]], ["2026-11-23-dashboard.md"])
            self.assertEqual(via_registry["specs"][0]["status_code"], "validated")
            self.assertEqual(via_registry["archived_specs_count"], 1)
            self.assertEqual([t["filename"] for t in via_registry["tasks"]], ["2026-11-23-lot2.md"])
            task0 = via_registry["tasks"][0]
            self.assertEqual(task0["wave"], 2)
            self.assertEqual(task0["dependencies"], ["2026-11-23-lot1"])
            self.assertEqual(task0["workflow_profile"], "standard")
            self.assertEqual(task0["spec_source"], "specs/2026-11-23-dashboard.md")
            self.assertEqual(task0["expected_branch"], "dev")
            self.assertEqual(task0["status_code"], "ready")
            self.assertEqual(via_registry["waves_summary"]["waves_count"], 1)
            self.assertEqual(via_registry["waves_summary"]["waves"][0]["wave"], 2)
            self.assertEqual(via_registry["waves_summary"]["waves"][0]["tasks_count"], 1)
            self.assertEqual(via_registry["archived_tasks_count"], 1)
            self.assertNotIn("handoffs", via_registry)
            self.assertNotIn("archived_handoffs_count", via_registry)
            self.assertEqual(len(via_registry["audits"]), 2)
            self.assertEqual(via_registry["audits"][0]["verdict"], "PASS")
            self.assertEqual(via_registry["audits"][0]["verdict_tone"], "ok")
            self.assertIsNotNone(via_registry["index_audit"])
            self.assertEqual(via_registry["index_audit"]["rel_path"], "README.md")
            self.assertTrue(all("agent" not in a["rel_path"].lower() for a in via_registry["audits"]))

            # Fast-path since_signature
            unchanged = api.get_architect_state(
                since_signature=via_registry["signature"], gravity_home=g_home
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": via_registry["signature"]})

            # Explicit architect_workspace overrides architect_registry
            other = tmp_path / "other-atelier"
            other.mkdir()
            explicit = api.get_architect_state(
                gravity_home=g_home, architect_workspace=other
            )
            self.assertEqual(explicit["discovery_source"], "arg_workspace")
            self.assertFalse(explicit["available"])

    def test_architect_registry_mru_dedup_ignores_bridge_and_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            arch_home = g_home / "architect"
            arch_home.mkdir(parents=True)
            b_home = g_home / "bridge"

            a_old = tmp_path / "atelier-old"
            a_new = tmp_path / "atelier-new"
            a_bridge = tmp_path / "atelier-bridge"
            a_invalid = tmp_path / "not-an-atelier"
            for d in (a_old, a_new, a_bridge):
                self._write_mini_atelier(d)
            a_invalid.mkdir()
            (a_new / "projects.json").write_text(
                json.dumps({"schema_version": 5, "workspace_name": "Atelier Nouveau", "projects": []}),
                encoding="utf-8",
            )
            (a_bridge / "projects.json").write_text(
                json.dumps({"schema_version": 5, "workspace_name": "Atelier Bridge", "projects": []}),
                encoding="utf-8",
            )

            _create_sample_bridge_db(b_home / "bridge.db", studio_path=a_bridge)
            reg_path = arch_home / "ateliers.json"
            reg_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ateliers": [
                            {"workspace_path": str(a_old), "workspace_name": "Old", "updated_at": "2026-11-20T10:00:00Z"},
                            {"workspace_path": str(a_new), "workspace_name": "New", "updated_at": "2026-11-24T09:00:00Z"},
                            {"workspace_path": str(a_new), "workspace_name": "New Dup", "updated_at": "2026-11-24T08:00:00Z"},
                            {"workspace_path": str(a_invalid), "workspace_name": "Invalid", "updated_at": "2026-11-24T12:00:00Z"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            res = api.get_architect_state(gravity_home=g_home)
            self.assertTrue(res["available"])
            self.assertEqual(res["discovery_source"], "architect_registry")
            self.assertEqual(Path(res["atelier_root"]), a_new.resolve())
            self.assertEqual(res["workspace_name"], "Atelier Nouveau")
            self.assertEqual(
                [Path(item["workspace_path"]) for item in res["ateliers"]],
                [a_new.resolve(), a_old.resolve()],
            )
            self.assertEqual([item["source"] for item in res["ateliers"]], ["architect_registry", "architect_registry"])

            unchanged = api.get_architect_state(since_signature=res["signature"], gravity_home=g_home)
            self.assertTrue(unchanged["unchanged"])

            # Mutating ateliers.json must invalidate since_signature
            reg_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "ateliers": [
                            {"workspace_path": str(a_old), "workspace_name": "Old Updated", "updated_at": "2026-11-24T11:00:00Z"},
                            {"workspace_path": str(a_new), "workspace_name": "New", "updated_at": "2026-11-24T09:00:00Z"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            updated = api.get_architect_state(since_signature=res["signature"], gravity_home=g_home)
            self.assertTrue(updated["changed"])
            self.assertEqual(Path(updated["atelier_root"]), a_old.resolve())

    def test_architect_full_precedence_ws_hint_and_fail_closed_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            arch_home = g_home / "architect"
            arch_home.mkdir(parents=True)
            b_home = g_home / "bridge"

            a_arg = tmp_path / "atelier-arg"
            a_sel = tmp_path / "atelier-sel"
            a_env = tmp_path / "atelier-env"
            a_hint = tmp_path / "atelier-hint"
            a_reg = tmp_path / "atelier-reg"
            a_bridge = tmp_path / "atelier-bridge"
            product_ws = tmp_path / "product-repo"
            product_ws.mkdir()
            (product_ws / "README.md").write_text("# Product\n", encoding="utf-8")

            for d in (a_arg, a_sel, a_env, a_hint, a_reg, a_bridge):
                self._write_mini_atelier(d)

            _create_sample_bridge_db(b_home / "bridge.db", studio_path=a_bridge)
            (arch_home / "ateliers.json").write_text(
                json.dumps({"ateliers": [{"workspace_path": str(a_reg), "updated_at": "2026-11-24T10:00:00Z"}]}),
                encoding="utf-8",
            )

            # 1. arg_workspace > selected_atelier
            r1 = api.get_architect_state(
                atelier=str(a_sel),
                ws=str(a_hint),
                gravity_home=g_home,
                architect_workspace=a_arg,
            )
            self.assertEqual(r1["discovery_source"], "arg_workspace")
            self.assertEqual(Path(r1["atelier_root"]), a_arg.resolve())

            # 2. selected_atelier > env_workspace
            with mock.patch.dict(os.environ, {"GRAVITY_ARCHITECT_WORKSPACE": str(a_env)}):
                r2 = api.get_architect_state(atelier=str(a_sel), ws=str(a_hint), gravity_home=g_home)
                self.assertEqual(r2["discovery_source"], "selected_atelier")
                self.assertEqual(Path(r2["atelier_root"]), a_sel.resolve())

                # 3. env_workspace > ws_hint
                r3 = api.get_architect_state(ws=str(a_hint), gravity_home=g_home)
                self.assertEqual(r3["discovery_source"], "env_workspace")
                self.assertEqual(Path(r3["atelier_root"]), a_env.resolve())

            # 4. ws_hint > architect_registry when ws is a valid atelier
            r4 = api.get_architect_state(ws=str(a_hint), gravity_home=g_home)
            self.assertEqual(r4["discovery_source"], "ws_hint")
            self.assertEqual(Path(r4["atelier_root"]), a_hint.resolve())

            # 5. ws ignored silently when product repo -> falls back to architect_registry
            r5 = api.get_architect_state(ws=str(product_ws), gravity_home=g_home)
            self.assertEqual(r5["discovery_source"], "architect_registry")
            self.assertEqual(Path(r5["atelier_root"]), a_reg.resolve())
            self.assertEqual(r5["warnings"], [])

            # 6. architect_registry default
            r6 = api.get_architect_state(gravity_home=g_home)
            self.assertEqual(r6["discovery_source"], "architect_registry")

            # 7. Remove ateliers.json -> module_home unavailable (no bridge.db fallback)
            (arch_home / "ateliers.json").unlink()
            r7 = api.get_architect_state(gravity_home=g_home)
            self.assertEqual(r7["discovery_source"], "module_home")
            self.assertFalse(r7["available"])
            self.assertEqual(r7["warnings"], [])

            # Fail-closed selected_atelier: nonexistent, non-atelier, symlink
            bad_missing = api.get_architect_state(atelier=str(tmp_path / "nope"), gravity_home=g_home)
            self.assertFalse(bad_missing["available"])
            self.assertEqual(bad_missing["discovery_source"], "selected_atelier")
            self.assertTrue(bad_missing["warnings"])

            bad_product = api.get_architect_state(atelier=str(product_ws), gravity_home=g_home)
            self.assertFalse(bad_product["available"])
            self.assertEqual(bad_product["discovery_source"], "selected_atelier")
            self.assertTrue(bad_product["warnings"])

            sym_atelier = tmp_path / "sym-atelier"
            try:
                sym_atelier.symlink_to(a_sel, target_is_directory=True)
            except (OSError, NotImplementedError):
                sym_atelier = None
            if sym_atelier is not None:
                bad_sym = api.get_architect_state(atelier=str(sym_atelier), gravity_home=g_home)
                self.assertFalse(bad_sym["available"])
                self.assertEqual(bad_sym["discovery_source"], "selected_atelier")
                self.assertTrue(bad_sym["warnings"])

    def test_architect_corrupt_or_symlink_registry_resilience(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            arch_home = g_home / "architect"
            arch_home.mkdir(parents=True)
            b_home = g_home / "bridge"
            a_bridge = tmp_path / "atelier-bridge"
            a_ws = tmp_path / "atelier-ws"
            self._write_mini_atelier(a_bridge)
            self._write_mini_atelier(a_ws)
            _create_sample_bridge_db(b_home / "bridge.db", studio_path=a_bridge)

            reg_path = arch_home / "ateliers.json"
            reg_path.write_text("{broken-json", encoding="utf-8")
            res_corrupt = api.get_architect_state(ws=str(a_ws), gravity_home=g_home)
            self.assertTrue(res_corrupt["available"])
            self.assertEqual(res_corrupt["discovery_source"], "ws_hint")
            self.assertTrue(any("ateliers.json" in w for w in res_corrupt["warnings"]))
            res_corrupt_no_ws = api.get_architect_state(gravity_home=g_home)
            self.assertFalse(res_corrupt_no_ws["available"])
            self.assertEqual(res_corrupt_no_ws["discovery_source"], "module_home")

            reg_path.write_text(json.dumps({"ateliers": "not-a-list"}), encoding="utf-8")
            res_bad_field = api.get_architect_state(ws=str(a_ws), gravity_home=g_home)
            self.assertTrue(res_bad_field["available"])
            self.assertEqual(res_bad_field["discovery_source"], "ws_hint")
            self.assertTrue(any("ateliers" in w for w in res_bad_field["warnings"]))

            reg_path.unlink()
            real_target = tmp_path / "real-reg.json"
            real_target.write_text(json.dumps({"ateliers": [{"workspace_path": str(a_bridge)}]}), encoding="utf-8")
            try:
                reg_path.symlink_to(real_target)
            except (OSError, NotImplementedError):
                return
            res_sym = api.get_architect_state(ws=str(a_ws), gravity_home=g_home)
            self.assertTrue(res_sym["available"])
            self.assertEqual(res_sym["discovery_source"], "ws_hint")
            self.assertTrue(any("symlink" in w.lower() for w in res_sym["warnings"]))

    def test_architect_legacy_handoffs_ro_fallback_and_tasks_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            legacy_atelier = tmp_path / "legacy-atelier"
            (legacy_atelier / "handoffs" / "archive").mkdir(parents=True)
            (legacy_atelier / "ECOSYSTEM.md").write_text("# Legacy Atelier\n", encoding="utf-8")
            (legacy_atelier / "projects.json").write_text(
                json.dumps({"schema_version": 5, "workspace_name": "Legacy Atelier", "projects": []}),
                encoding="utf-8",
            )
            (legacy_atelier / "handoffs" / "_TEMPLATE.md").write_text("# Template Handoff\n", encoding="utf-8")
            legacy_file = legacy_atelier / "handoffs" / "2026-11-20-legacy.md"
            legacy_file.write_text(
                "# Legacy Handoff\n\n- **Date / Statut :** `ready`\n- **Dépôt cible :** `gravity`\n",
                encoding="utf-8",
            )
            (legacy_atelier / "handoffs" / "archive" / "2026-11-01-old.md").write_text("# Old\n", encoding="utf-8")

            legacy_state = api.get_architect_state(ws=str(legacy_atelier), gravity_home=g_home)
            self.assertTrue(legacy_state["available"])
            self.assertEqual(legacy_state["discovery_source"], "ws_hint")
            self.assertEqual([t["filename"] for t in legacy_state["tasks"]], ["2026-11-20-legacy.md"])
            self.assertEqual(legacy_state["archived_tasks_count"], 1)
            self.assertNotIn("handoffs", legacy_state)
            self.assertNotIn("archived_handoffs_count", legacy_state)
            self.assertFalse((legacy_atelier / "tasks").exists())

            # Creating tasks/ (even empty) disables legacy handoffs/ fallback
            (legacy_atelier / "tasks").mkdir()
            empty_tasks_state = api.get_architect_state(ws=str(legacy_atelier), gravity_home=g_home)
            self.assertEqual(empty_tasks_state["tasks"], [])
            self.assertEqual(empty_tasks_state["archived_tasks_count"], 0)
            self.assertNotEqual(empty_tasks_state["signature"], legacy_state["signature"])

            # Populating tasks/ shows tasks/ only and ignores handoffs/
            (legacy_atelier / "tasks" / "2026-11-25-current.md").write_text(
                "# Current Task\n\n- **Date / Statut :** `ready`\n- **Dépôt cible :** `gravity`\n",
                encoding="utf-8",
            )
            current_state = api.get_architect_state(ws=str(legacy_atelier), gravity_home=g_home)
            self.assertEqual([t["filename"] for t in current_state["tasks"]], ["2026-11-25-current.md"])
            self.assertTrue(legacy_file.exists())


class TestDashboardFacade(unittest.TestCase):
    def test_build_initial_summary_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            fake_user = tmp_path / "user-home"
            fake_user.mkdir()
            plugins_root = tmp_path / "plugins"
            _write_module_plugin(plugins_root, mod_id="core", plugin_name="gravity", ui_mode="core")
            _write_module_plugin(plugins_root, mod_id="workflow", plugin_name="gravity-workflow", ui_mode="none")
            _write_module_plugin(plugins_root, mod_id="metrics", plugin_name="gravity-metrics", ui_mode="none")
            _write_module_plugin(plugins_root, mod_id="architect", plugin_name="gravity-architect")

            summary = api.build_initial_summary(
                gravity_home=g_home,
                plugin_roots=[plugins_root],
                home_dir=fake_user,
            )
            self.assertIn("Gravity Dashboard", summary)
            self.assertIn("Live:", summary)
            self.assertIn("Metrics", summary)
            self.assertNotIn("Bridge:", summary)
            self.assertIn("Architect:", summary)


if __name__ == "__main__":
    unittest.main()

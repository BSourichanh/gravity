"""Isolated unit tests for metrics_provider retirement, SPI-1 metrics routing, and _shared worktree helpers."""

from __future__ import annotations

import importlib
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

from _shared.transcript_reader import is_worktree_path  # noqa: E402
from core.registry import write_modules_registry  # noqa: E402
from dashboard import api  # noqa: E402


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


_FAKE_METRICS_PROVIDER = """\
import argparse, json, sys

p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--action", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
params = req.get("params") or {}

if a.action:
    print(json.dumps({
        "ok": True,
        "action": a.action,
        "message": f"Action {a.action} ok",
        "target": params.get("target", ""),
    }))
elif a.view == "session-detail":
    print(json.dumps({
        "found": True,
        "target": params.get("target", ""),
        "label": "demo-session",
        "detail": {"summary": {"input_tokens": 100}},
    }))
elif a.view == "audit-detail":
    print(json.dumps({
        "found": True,
        "path": params.get("path", ""),
        "title": "Agent Audit",
        "content": "# Agent Audit\\nVerdict: PASS\\n",
    }))
else:
    sig = f"met:{params.get('project', '')}:{params.get('q', '')}"
    if a.since_signature == sig:
        print(json.dumps({"changed": False, "unchanged": True, "signature": sig}))
    else:
        print(json.dumps({
            "available": True,
            "changed": True,
            "unchanged": False,
            "signature": sig,
            "kpis": {"sessions_count": 2, "useful_tokens": 4200, "cost_usd": 0.05},
            "records": [],
            "pending_sessions": [],
            "ignored_sessions": [],
            "audits": [],
        }))
"""


class TestMetricsRetirementAndWorktreeHelpers(unittest.TestCase):
    def test_metrics_provider_retired(self) -> None:
        self.assertFalse((PLUGIN_ROOT / "dashboard" / "providers" / "metrics_provider.py").exists())
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("dashboard.providers.metrics_provider")
        api_text = (PLUGIN_ROOT / "dashboard" / "api.py").read_text(encoding="utf-8")
        self.assertNotIn("metrics_provider", api_text)

    def test_metrics_spi_routing_and_fail_closed_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            m_home = g_home / "metrics"
            plugins_root = tmp_path / "plugins"
            mod_dir = plugins_root / "gravity-metrics"
            (g_home / "core").mkdir(parents=True)
            m_home.mkdir(parents=True)
            (mod_dir / "config").mkdir(parents=True)
            (mod_dir / "scripts").mkdir(parents=True)
            (mod_dir / "scripts" / "dashboard_provider.py").write_text(
                _FAKE_METRICS_PROVIDER,
                encoding="utf-8",
                newline="\n",
            )
            (mod_dir / "plugin.json").write_text(
                json.dumps({"name": "gravity-metrics", "version": "0.5.0"}),
                encoding="utf-8",
                newline="\n",
            )
            (mod_dir / "config" / "module.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "id": "metrics",
                        "plugin_name": "gravity-metrics",
                        "role": "Metrics",
                        "storage": {"subdir": "metrics", "env_override": "GRAVITY_METRICS_HOME"},
                        "commands": ["/gravity-metrics"],
                        "capabilities": ["metrics"],
                        "ui": {"mode": "metrics", "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                        "dashboard": {
                            "provider_script": "scripts/dashboard_provider.py",
                            "views": ["metrics", "session-detail", "audit-detail"],
                            "actions": ["record", "update", "update-meta", "ignore", "unignore", "remove"],
                        },
                    }
                ),
                encoding="utf-8",
                newline="\n",
            )

            # Without registered module -> clean SPI fallback
            empty_plugins = tmp_path / "empty-plugins"
            empty_plugins.mkdir()
            empty_res = api.get_metrics_state(gravity_home=g_home, plugin_roots=[empty_plugins])
            self.assertTrue(empty_res["spi_fallback"])
            self.assertFalse(empty_res["available"])
            self.assertEqual(empty_res["pending_sessions"], [])

            write_modules_registry(
                g_home,
                [
                    {
                        "id": "metrics",
                        "plugin_name": "gravity-metrics",
                        "display_name": "Gravity Metrics",
                        "version": "0.5.0",
                        "valid": True,
                        "errors": [],
                        "plugin_dir": str(mod_dir.resolve()),
                        "storage": {"subdir": "metrics", "env_override": "GRAVITY_METRICS_HOME"},
                        "commands": ["/gravity-metrics"],
                        "capabilities": ["metrics"],
                        "ui": {"mode": "metrics", "target": "gravity"},
                        "signals": {"produces": [], "consumes": []},
                    }
                ],
            )

            state1 = api.get_metrics_state(
                project="gravity",
                q="demo",
                gravity_home=g_home,
                metrics_home=m_home,
                plugin_roots=[plugins_root],
            )
            self.assertTrue(state1["available"])
            self.assertEqual(state1["kpis"]["sessions_count"], 2)
            unchanged = api.get_metrics_state(
                project="gravity",
                q="demo",
                since_signature=state1["signature"],
                gravity_home=g_home,
                metrics_home=m_home,
                plugin_roots=[plugins_root],
            )
            self.assertTrue(unchanged["unchanged"])

            detail = api.get_session_detail("demo-session", gravity_home=g_home, metrics_home=m_home, plugin_roots=[plugins_root])
            self.assertTrue(detail["found"])
            self.assertEqual(detail["target"], "demo-session")

            act = api.run_metrics_cli_action("record", conversation_id="cid-123", gravity_home=g_home, metrics_home=m_home, plugin_roots=[plugins_root])
            self.assertTrue(act["ok"])
            self.assertEqual(act["action"], "record")

            aud = api.read_metrics_audit("2026-11-26-audit.md", gravity_home=g_home, metrics_home=m_home, plugin_roots=[plugins_root])
            self.assertTrue(aud["found"])

            # Fail-closed validation checks
            for bad_target in ("", "../secret", "a/b", r"a\b", "bad\x00id"):
                bad_det = api.get_session_detail(bad_target, gravity_home=g_home, plugin_roots=[plugins_root])
                self.assertFalse(bad_det["found"])
                self.assertTrue(bad_det["spi_fallback"])

            bad_act = api.run_metrics_cli_action("drop-db", conversation_id="cid-123", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertFalse(bad_act["ok"])
            bad_cid = api.run_metrics_cli_action("record", target="../escape", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertFalse(bad_cid["ok"])

            for bad_audit in ("", "../escape.md", "/abs/audit.md", "audits/code/secret.md", "code/secret.md"):
                bad_aud = api.read_metrics_audit(bad_audit, gravity_home=g_home, plugin_roots=[plugins_root])
                self.assertFalse(bad_aud["found"])
                self.assertTrue(bad_aud["spi_fallback"])

    def test_shared_is_worktree_path_posix_and_windows(self) -> None:
        self.assertTrue(is_worktree_path("/home/user/.gemini/antigravity/worktrees/gravity/feat-x"))
        self.assertTrue(is_worktree_path(r"C:\Users\dev\.gemini\antigravity\worktrees\gravity\feat-y"))
        self.assertTrue(is_worktree_path(r"D:\repos\worktrees\sub-1"))
        self.assertTrue(is_worktree_path("/tmp/gravity-worktrees/gravity-w1"))
        self.assertTrue(is_worktree_path("/home/user/repo/.worktrees/w1"))
        self.assertTrue(is_worktree_path("/home/user/repo/worktrees/w1"))
        self.assertTrue(is_worktree_path("file:///home/user/.gemini/antigravity/worktrees/gravity/feat-uri"))
        self.assertFalse(is_worktree_path("/home/user/Documents/Github/gravity"))
        self.assertFalse(is_worktree_path(r"C:\Users\dev\Documents\Github\gravity"))
        self.assertFalse(is_worktree_path(""))
        self.assertFalse(is_worktree_path(None))


if __name__ == "__main__":
    unittest.main()

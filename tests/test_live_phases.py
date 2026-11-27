"""Unit tests for 4-phase Live tracking (`build_live_phases`, agent phase assignment, and live payload)."""

from __future__ import annotations

from datetime import datetime, timezone
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

from _shared.signal_bus import publish_signal  # noqa: E402
from dashboard import api  # noqa: E402
from dashboard.providers import live_progress, live_provider  # noqa: E402


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
        "GRAVITY_BRAIN_DIR",
    ):
        env.pop(key, None)
    return env


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(it) + "\n" for it in items), encoding="utf-8", newline="\n")


def _write_wf_spi_plugin(plugins_root: Path) -> Path:
    mod_dir = plugins_root / "gravity-workflow"
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "scripts").mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "gravity-workflow",
        "displayName": "Gravity Workflow",
        "version": "0.3.0",
        "description": "Workflow stub for live phases tests",
        "logo": "assets/logo.svg",
        "suggestedPrompts": ["One", "Two", "Three"],
        "author": {"name": "Gravity Contributors"},
        "homepage": "https://github.com/BSourichanh/gravity-workflow",
        "repository": "https://github.com/BSourichanh/gravity-workflow.git",
    }
    contract = {
        "schema_version": 1,
        "id": "workflow",
        "plugin_name": "gravity-workflow",
        "role": "Workflow engine",
        "storage": {"subdir": "workflow", "env_override": "GRAVITY_WORKFLOW_HOME"},
        "commands": ["/gravity-workflow"],
        "capabilities": ["spi-1"],
        "ui": {"mode": "none", "target": "gravity"},
        "signals": {"produces": [], "consumes": []},
        "dashboard": {"provider_script": "scripts/dashboard_provider.py", "views": ["workflow"], "actions": []},
    }
    script = """\
import argparse, json, os, pathlib, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--json", action="store_true")
p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
ctx = req.get("context") or {}
wf_home = pathlib.Path(ctx.get("workflow_home") or os.environ.get("GRAVITY_WORKFLOW_HOME") or ".")
state_f = wf_home / "stub_wf.json"
if state_f.is_file():
    st = json.loads(state_f.read_text(encoding="utf-8"))
    print(json.dumps({"available": True, "changed": True, "unchanged": False, "signature": f"wf:{st.get('stage')}", **st}))
else:
    print(json.dumps({"available": False, "changed": True, "unchanged": False, "signature": "wf-idle", "stage": "idle", "progress": "0/0", "tasks": [], "events": []}))
"""
    (mod_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    (mod_dir / "config" / "module.json").write_text(json.dumps(contract), encoding="utf-8", newline="\n")
    (mod_dir / "scripts" / "dashboard_provider.py").write_text(script, encoding="utf-8", newline="\n")
    return mod_dir


class TestLivePhases(unittest.TestCase):
    def setUp(self) -> None:
        live_provider.reset_live_cache()

    def test_build_live_progress_default_preserved(self) -> None:
        self.assertEqual(
            live_progress.build_live_progress(None),
            {"label": "0/0", "done": 0, "total": 0, "pct": 0, "waves": [], "tasks": []},
        )
        self.assertEqual(live_progress.build_live_progress({})["label"], "0/0")
        self.assertEqual(live_progress.build_live_progress({"stage": "idle"})["label"], "0/0")

    def test_build_live_phases_ordered_defaults_and_workflow_stages(self) -> None:
        idle = live_progress.build_live_phases(None)
        self.assertEqual(idle["current_phase"], "conception")
        self.assertEqual([p["id"] for p in idle["phases"]], ["conception", "planification", "production", "validation"])
        self.assertEqual([p["status"] for p in idle["phases"]], ["pending", "pending", "pending", "pending"])
        for ph in idle["phases"]:
            self.assertEqual((ph["tokens"], ph["useful_tokens"], ph["agents"], ph["duration_s"]), (0, 0, 0, 0.0))

        plan_res = live_progress.build_live_phases({"available": True, "stage": "workflow:planning", "nodes": {"planner": "running"}})
        self.assertEqual(plan_res["current_phase"], "planification")
        self.assertEqual([p["status"] for p in plan_res["phases"]], ["done", "active", "pending", "pending"])

        prod_res = live_progress.build_live_phases(
            {"available": True, "stage": "workflow:building", "nodes": {"planner": "done", "builder": "running"}},
            agents=[
                {"id": "coord", "depth": 0, "source": "root", "status": "waiting", "useful_tokens": 1000, "cache_read_tokens": 2000, "duration_s": 12.4},
                {"id": "scout", "depth": 1, "source": "subagent", "type_name": "explore", "status": "done", "useful_tokens": 500, "cache_read_tokens": 500, "duration_s": 4.2},
                {"id": "w1", "depth": 1, "source": "swarm", "role": "worker", "phase": "production", "status": "active", "useful_tokens": 3000, "cache_read_tokens": 4000, "duration_s": 18.1},
            ],
        )
        self.assertEqual(prod_res["current_phase"], "production")
        by_id = {p["id"]: p for p in prod_res["phases"]}
        self.assertEqual([prod_res["phases"][i]["status"] for i in range(4)], ["done", "done", "active", "pending"])
        self.assertEqual((by_id["conception"]["agents"], by_id["conception"]["useful_tokens"], by_id["conception"]["tokens"], by_id["conception"]["duration_s"]), (1, 500, 1000, 4.2))
        self.assertEqual((by_id["planification"]["agents"], by_id["planification"]["tokens"]), (0, 0))
        self.assertEqual((by_id["production"]["agents"], by_id["production"]["useful_tokens"], by_id["production"]["tokens"], by_id["production"]["duration_s"]), (2, 4000, 10000, 30.5))

        val_err = live_progress.build_live_phases({"available": True, "stage": "workflow:refused"})
        self.assertEqual(val_err["current_phase"], "validation")
        self.assertEqual([p["status"] for p in val_err["phases"]], ["done", "done", "done", "error"])

        arch_done = live_progress.build_live_phases(
            architect_state={
                "available": True,
                "current_phase": "validation",
                "cycle_phases": [
                    {"id": "conception", "status": "done"},
                    {"id": "planification", "status": "done"},
                    {"id": "production", "status": "done"},
                    {"id": "validation", "status": "active"},
                ],
            },
            is_archived=True,
        )
        self.assertEqual(arch_done["current_phase"], "validation")
        self.assertEqual([p["status"] for p in arch_done["phases"]], ["done", "done", "done", "done"])

    def test_classify_agent_phase_and_build_agent_entry(self) -> None:
        self.assertEqual(live_progress.classify_agent_phase({"type_name": "explore", "role": "Reader"}), "conception")
        self.assertEqual(live_progress.classify_agent_phase({"type_name": "planner", "role": "Wave Planner"}), "planification")
        self.assertEqual(live_progress.classify_agent_phase({"id": "verifier-w1", "role": "worker"}), "validation")
        self.assertEqual(live_progress.classify_agent_phase({"type_name": "code_review", "role": "Review"}), "validation")
        self.assertEqual(
            live_progress.classify_agent_phase({
                "id": "w2", "type_name": "worker", "role": "worker",
                "phase_signals": {"production": True, "validation": True, "last_phase": "validation"},
            }),
            "production",
        )

        acc = live_provider._new_transcript_acc()
        live_provider._apply_transcript_obj(acc, {
            "step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE",
            "created_at": "2026-11-27T10:00:00Z", "input_tokens": 200, "cache_read_tokens": 800, "output_tokens": 50,
            "tool_calls": [{"name": "edit_file", "args": {"Path": "/tmp/repo/plugin/app.py"}}],
        }, "w-prod")
        entry = live_provider._build_agent_entry(
            agent_id="w-prod", cid="11111111-1111-1111-1111-111111111111", role="worker", type_name="worker",
            status="done", acc=acc, model_hint="gemini-pro", workspace="gravity", workspace_kind="code",
            task_title="Implémenter tests et validation", depth=1, source="swarm",
        )
        self.assertEqual(entry["phase"], "production")

    def test_get_live_session_state_phases_signature_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            plugins_root = tmp_path / "plugins"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)
            _write_wf_spi_plugin(plugins_root)

            # 0. No session -> phases pending, current_phase=conception
            st_empty = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertFalse(st_empty["available"])
            self.assertEqual(st_empty["current_phase"], "conception")
            self.assertEqual([p["status"] for p in st_empty["phases"]], ["pending", "pending", "pending", "pending"])

            root_cid = "aaaaaaaa-1111-2222-3333-444444444444"
            explore_cid = "bbbbbbbb-1111-2222-3333-444444444444"
            worker_cid = "cccccccc-1111-2222-3333-444444444444"
            verifier_cid = "dddddddd-1111-2222-3333-444444444444"

            t_root = brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl"
            _write_jsonl(t_root, [
                {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-27T12:00:00Z", "content": "<USER_REQUEST>/gravity-architect \"feature\"</USER_REQUEST>"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-27T12:00:05Z", "model": "gemini-4-neon-high", "input_tokens": 500, "cache_read_tokens": 1000, "output_tokens": 100, "tool_calls": [{"name": "edit_file", "args": {"Path": "/tmp/ws/specs/spec.md"}}]},
                {"step_index": 2, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-27T12:00:10Z", "model": "gemini-4-neon-high", "input_tokens": 400, "cache_read_tokens": 1000, "output_tokens": 100, "tool_calls": [{"name": "edit_file", "args": {"Path": "/tmp/ws/tasks/task.md"}}]},
            ])
            _write_jsonl(brain / explore_cid / ".system_generated" / "logs" / "transcript.jsonl", [
                {"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-27T12:00:02Z", "input_tokens": 300, "cache_read_tokens": 700, "output_tokens": 50},
            ])
            _write_jsonl(brain / worker_cid / ".system_generated" / "logs" / "transcript.jsonl", [
                {"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-27T12:00:15Z", "input_tokens": 800, "cache_read_tokens": 1200, "output_tokens": 200, "tool_calls": [{"name": "edit_file", "args": {"Path": "/tmp/gravity/plugin/mod.py"}}]},
            ])
            _write_jsonl(brain / verifier_cid / ".system_generated" / "logs" / "transcript.jsonl", [
                {"step_index": 0, "type": "PLANNER_RESPONSE", "status": "RUNNING", "created_at": "2026-11-27T12:00:25Z", "input_tokens": 250, "cache_read_tokens": 500, "output_tokens": 50, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "python3 plugin/scripts/validate.py --strict"}}]},
            ])

            sg_root = brain / root_cid / ".system_generated"
            (sg_root / "subagents").mkdir(parents=True)
            (sg_root / "swarm").mkdir(parents=True)
            (sg_root / "subagents" / f"{explore_cid}.json").write_text(
                json.dumps({"conversationId": explore_cid, "state": "SUBAGENT_STATE_COMPLETED", "subagentDescriptor": {"typeName": "explore", "role": "Spec Explorer"}}),
                encoding="utf-8",
            )
            (sg_root / "swarm" / "members.json").write_text(
                json.dumps({
                    "title": "Wave 2",
                    "members": {
                        "coordinator": {"conversation_id": root_cid, "role": "coordinator", "phase": "RUNNING", "wake_mode": "mentions"},
                        "w1-builder": {"conversation_id": worker_cid, "role": "worker", "phase": "STOPPED", "desired_state": "STOPPED", "killed": True},
                        "verifier-w2": {"conversation_id": verifier_cid, "role": "worker", "phase": "RUNNING", "wake_mode": "working"},
                    },
                }),
                encoding="utf-8",
            )
            (wf_home / "stub_wf.json").write_text(json.dumps({"stage": "workflow:building", "progress": "1/2"}), encoding="utf-8")

            st1 = api.get_live_session_state(
                session_id=root_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertEqual(st1["current_phase"], "validation")
            self.assertEqual(st1["selected_session"]["current_phase"], "validation")
            self.assertEqual(st1["phases"], st1["selected_session"]["phases"])
            self.assertEqual([p["id"] for p in st1["phases"]], ["conception", "planification", "production", "validation"])
            self.assertEqual([p["status"] for p in st1["phases"]], ["done", "done", "done", "active"])

            by_id = {a["id"]: a for a in st1["agents"]}
            self.assertEqual(by_id[f"sub-{explore_cid[:8]}"]["phase"], "conception")
            self.assertEqual(by_id["w1-builder"]["phase"], "production")
            self.assertEqual(by_id["verifier-w2"]["phase"], "validation")
            self.assertEqual(by_id["coordinator"]["phase"], "validation")

            p_map = {p["id"]: p for p in st1["phases"]}
            self.assertEqual(p_map["conception"]["agents"], 1)
            self.assertEqual(p_map["production"]["agents"], 1)
            self.assertEqual(p_map["validation"]["agents"], 2)
            self.assertEqual(sum(p["agents"] for p in st1["phases"]), len(st1["agents"]))
            self.assertEqual(sum(p["useful_tokens"] for p in st1["phases"]), st1["summary"]["useful_tokens"])

            bytes_first = live_provider.get_live_cache_stats()["bytes_read"]
            st_unchanged = api.get_live_session_state(
                session_id=root_cid, since_signature=st1["signature"], gravity_home=g_home, brain_dir=brain,
                metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root],
            )
            self.assertTrue(st_unchanged["unchanged"])
            self.assertEqual(live_provider.get_live_cache_stats()["bytes_read"], bytes_first)

            # Workflow stage change invalidates signature (validation stays active while verifier-w2 is still running)
            (wf_home / "stub_wf.json").write_text(json.dumps({"stage": "workflow:done", "progress": "2/2"}), encoding="utf-8")
            st2 = api.get_live_session_state(
                session_id=root_cid, since_signature=st1["signature"], gravity_home=g_home, brain_dir=brain,
                metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root],
            )
            self.assertTrue(st2["changed"])
            self.assertEqual([p["status"] for p in st2["phases"]], ["done", "done", "done", "active"])

            # Finish verifier-w2 -> workflow:done completes all 4 phases
            with (brain / verifier_cid / ".system_generated" / "logs" / "transcript.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-27T12:00:30Z"}) + "\n")
            st2b = api.get_live_session_state(
                session_id=root_cid, since_signature=st2["signature"], gravity_home=g_home, brain_dir=brain,
                metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root],
            )
            self.assertTrue(st2b["changed"])
            self.assertEqual([p["status"] for p in st2b["phases"]], ["done", "done", "done", "done"])

            # Archived via signal_bus (even if workflow returns to idle) -> all 4 phases done
            (wf_home / "stub_wf.json").unlink()
            ended_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            publish_signal(
                "session-metrics", "archive-index", "gravity-metrics",
                {"archived_cids": {root_cid: {"status": "archived", "ended_at": ended_iso}}},
                sample_count=1, window_size=1, gravity_home=g_home,
            )
            st3 = api.get_live_session_state(
                session_id=root_cid, since_signature=st2b["signature"], gravity_home=g_home, brain_dir=brain,
                metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root],
            )
            self.assertTrue(st3["changed"])
            self.assertEqual([p["status"] for p in st3["phases"]], ["done", "done", "done", "done"])

            # Payload budget <= MAX_PAYLOAD_BYTES even under heavy agents/events
            big_cid = "eeeeeeee-1111-2222-3333-444444444444"
            heavy_steps = [
                {
                    "step_index": i,
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "created_at": "2026-11-27T12:10:00Z",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "tool_calls": [{"name": "edit_file", "args": {"Path": f"/tmp/repo/f{i}.py", "Blob": "x" * 200}}],
                }
                for i in range(60)
            ]
            _write_jsonl(brain / big_cid / ".system_generated" / "logs" / "transcript.jsonl", heavy_steps)
            st_big = api.get_live_session_state(
                session_id=big_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            encoded_len = len(json.dumps(st_big, ensure_ascii=False).encode("utf-8"))
            self.assertLess(encoded_len, live_provider.MAX_PAYLOAD_BYTES)
            self.assertEqual(len(st_big["phases"]), 4)
            self.assertEqual(st_big["current_phase"], "production")


if __name__ == "__main__":
    unittest.main()

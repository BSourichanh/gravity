"""Isolated unit tests for live_provider, live_progress, generic_provider SPI-1, and metrics SPI-1 actions/audits."""

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
from core.registry import write_modules_registry  # noqa: E402
from dashboard import api  # noqa: E402
from dashboard.providers import generic_provider, live_progress, live_provider  # noqa: E402


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
    path.write_text("".join(json.dumps(it) + "\n" for it in items), encoding="utf-8")


def _write_spi_plugin(
    plugins_root: Path,
    *,
    mod_id: str,
    plugin_name: str,
    script_body: str,
    views: list[str],
    actions: list[str],
) -> Path:
    mod_dir = plugins_root / plugin_name
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "scripts").mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": plugin_name,
        "displayName": plugin_name.replace("-", " ").title(),
        "version": "0.3.0",
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
        "role": f"Role {mod_id}",
        "storage": {"subdir": mod_id, "env_override": f"GRAVITY_{mod_id.upper()}_HOME"},
        "commands": [f"/{plugin_name}"],
        "capabilities": ["spi-1"],
        "ui": {"mode": "mcp-app", "target": "gravity"},
        "signals": {"produces": [], "consumes": []},
        "dashboard": {
            "provider_script": "scripts/dashboard_provider.py",
            "views": views,
            "actions": actions,
        },
    }
    (mod_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    (mod_dir / "config" / "module.json").write_text(json.dumps(contract), encoding="utf-8", newline="\n")
    (mod_dir / "scripts" / "dashboard_provider.py").write_text(script_body, encoding="utf-8", newline="\n")
    return mod_dir


_LIVE_META_SPI_SCRIPT = """\
import argparse, hashlib, json, os, pathlib, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
ctx = req.get("context") or {}
if a.view == "live-meta":
    m_raw = ctx.get("metrics_home") or os.environ.get("GRAVITY_METRICS_HOME") or ""
    if not m_raw:
        g_raw = os.environ.get("GRAVITY_HOME") or ""
        m_raw = str(pathlib.Path(g_raw) / "metrics") if g_raw else "."
    m_home = pathlib.Path(m_raw)
    cap_f, meta_f = m_home / "active_captures.json", m_home / "session_meta.json"
    caps = json.loads(cap_f.read_text(encoding="utf-8")).get("captures", {}) if cap_f.is_file() else {}
    meta = json.loads(meta_f.read_text(encoding="utf-8")).get("sessions", {}) if meta_f.is_file() else {}
    sig = hashlib.sha256(json.dumps({"c": caps, "m": meta}, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    print(json.dumps({"ok": True, "active_captures": caps, "session_meta": meta, "signature": sig}))
else:
    print(json.dumps({"available": True, "changed": True, "unchanged": False, "signature": "met-stub", "records": []}))
"""

_WF_LIVE_SPI_SCRIPT = """\
import argparse, json, os, pathlib, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
ctx = req.get("context") or {}
ws = str((req.get("params") or {}).get("ws") or "").strip()
wf_raw = ctx.get("workflow_home") or os.environ.get("GRAVITY_WORKFLOW_HOME") or ""
if not wf_raw:
    g_raw = os.environ.get("GRAVITY_HOME") or ""
    wf_raw = str(pathlib.Path(g_raw) / "workflow") if g_raw else "."
wf_home = pathlib.Path(wf_raw)
reg_f = wf_home / "live_workspaces.json"
if reg_f.is_file():
    entries = json.loads(reg_f.read_text(encoding="utf-8")).get("workspaces") or []
    for entry in entries:
        wp = str(entry.get("workspace_path") or "")
        sp = pathlib.Path(str(entry.get("state_path") or ""))
        if sp.is_file() and (not ws or wp == ws or pathlib.Path(wp).name == ws):
            st = json.loads(sp.read_text(encoding="utf-8"))
            print(json.dumps({"available": True, "changed": True, "unchanged": False, "signature": f"wf:{st.get('stage')}:{st.get('progress')}", **st}))
            sys.exit(0)
print(json.dumps({"available": False, "changed": True, "unchanged": False, "signature": "wf-idle", "stage": "idle", "progress": "0/0", "tasks": [], "events": []}))
"""


class TestLiveProvider(unittest.TestCase):
    def setUp(self) -> None:
        live_provider.reset_live_cache()

    def test_incremental_offset_read_and_since_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "11111111-2222-3333-4444-555555555555"
            tpath = brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl"
            initial_steps = [
                {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-25T10:00:00Z", "content": "go"},
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "status": "DONE",
                    "created_at": "2026-11-25T10:00:02Z",
                    "model": "gemini-4-neon-high",
                    "input_tokens": 1000,
                    "cache_read_tokens": 3000,
                    "output_tokens": 200,
                    "thinking": "x" * 80,
                    "tool_calls": [{"name": "read_file", "args": {"Path": "README.md"}}],
                },
            ]
            _write_jsonl(tpath, initial_steps)

            st1 = api.get_live_session_state(gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home)
            self.assertTrue(st1["available"])
            self.assertTrue(st1["changed"])
            self.assertEqual(st1["summary"]["llm_calls"], 1)
            self.assertEqual(st1["summary"]["thinking_est_tokens"], 20)
            self.assertEqual(st1["workflow"]["progress"], "0/0")
            bytes_first = live_provider.get_live_cache_stats()["bytes_read"]
            self.assertGreater(bytes_first, 0)

            unchanged = api.get_live_session_state(
                since_signature=st1["signature"], gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual(unchanged, {"changed": False, "unchanged": True, "signature": st1["signature"]})
            self.assertEqual(live_provider.get_live_cache_stats()["bytes_read"], bytes_first)

            extra_line = (
                json.dumps(
                    {
                        "step_index": 2,
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:05Z",
                        "model": "gemini-4-neon-high",
                        "input_tokens": 500,
                        "cache_read_tokens": 4000,
                        "output_tokens": 100,
                        "thinking": "y" * 40,
                        "tool_calls": [{"name": "edit_file", "args": {"Path": "/tmp/a.py"}}],
                    }
                )
                + "\n"
            )
            with tpath.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(extra_line)

            st2 = api.get_live_session_state(
                since_signature=st1["signature"], gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertTrue(st2["changed"])
            self.assertEqual(st2["summary"]["llm_calls"], 2)
            self.assertEqual(st2["summary"]["thinking_est_tokens"], 30)
            bytes_second = live_provider.get_live_cache_stats()["bytes_read"]
            self.assertEqual(bytes_second - bytes_first, len(extra_line.encode("utf-8")))

    def test_swarm_subagents_workspace_normalization_and_workflow_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            atelier = tmp_path / "gravity-workshop"
            (atelier / "specs").mkdir(parents=True)
            (atelier / "projects.json").write_text("{}", encoding="utf-8")

            root_cid = "aaaaaaaa-1111-2222-3333-444444444444"
            worker_cid = "bbbbbbbb-1111-2222-3333-444444444444"
            rev_cid = "cccccccc-1111-2222-3333-444444444444"

            m_home.mkdir(parents=True)
            (m_home / "session_meta.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sessions": {
                            root_cid: {"cwd": str(atelier), "project": "gravity-workshop"},
                            worker_cid: {"cwd": str(atelier), "project": "gravity-workshop"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (m_home / "active_captures.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "captures": {root_cid: {"label": "live-cap", "project": "gravity-workshop", "start_step": 0}},
                    }
                ),
                encoding="utf-8",
            )

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T11:00:00Z", "model": "gemini-4-hydrogen-high", "input_tokens": 1000, "cache_read_tokens": 2000, "output_tokens": 100}],
            )
            _write_jsonl(
                brain / worker_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{
                    "step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T11:00:10Z",
                    "model": "gemini-4-hydrogen-high", "input_tokens": 800, "cache_read_tokens": 1200, "output_tokens": 300,
                    "tool_calls": [{"name": "edit_file", "args": {"Path": "/tmp/gravity-worktrees/gravity-w1/plugin/dashboard/api.py"}}],
                }],
            )
            _write_jsonl(
                brain / rev_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{
                    "step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T11:00:20Z",
                    "model": "gemini-4-neon-high", "input_tokens": 400, "cache_read_tokens": 600, "output_tokens": 50,
                    "tool_calls": [{"name": "read_file", "args": {"Path": "/tmp/gravity-metrics/plugin/scripts/cli.py"}}],
                }],
            )

            sg_root = brain / root_cid / ".system_generated"
            (sg_root / "swarm").mkdir(parents=True)
            (sg_root / "subagents").mkdir(parents=True)
            (sg_root / "swarm" / "members.json").write_text(
                json.dumps(
                    {
                        "title": "Wave 1",
                        "members": {
                            "coordinator": {"conversation_id": root_cid, "role": "coordinator", "phase": "RUNNING", "wake_mode": "mentions", "model": "gemini-4-hydrogen-high"},
                            "core-w1": {"conversation_id": worker_cid, "role": "worker", "phase": "RUNNING", "wake_mode": "working", "model": "gemini-4-hydrogen-high"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (sg_root / "swarm" / "plan.json").write_text(
                json.dumps({"goal": {"title": "Unified Dashboard"}, "tasks": {"core-w1": "Implement live provider"}}),
                encoding="utf-8",
            )
            _write_jsonl(
                sg_root / "swarm" / "board.jsonl",
                [{"seq": 1, "agent": "core-w1", "text": "Working on live_provider", "time": "2026-11-25 11:00:15", "kind": "update"}],
            )
            (sg_root / "subagents" / f"{worker_cid}.json").write_text(
                json.dumps({"conversationId": worker_cid, "subagentDescriptor": {"typeName": "worker", "role": "Swarm Worker (core-w1)"}, "state": "SUBAGENT_STATE_ALIVE", "workspaceUris": [atelier.as_uri()]}),
                encoding="utf-8",
            )
            (sg_root / "subagents" / f"{rev_cid}.json").write_text(
                json.dumps({"conversationId": rev_cid, "subagentDescriptor": {"typeName": "explore", "role": "CLI Reader"}, "state": "SUBAGENT_STATE_COMPLETED", "workspaceUris": [atelier.as_uri()]}),
                encoding="utf-8",
            )

            wf_home.mkdir(parents=True)
            ws_state_file = wf_home / "workspaces" / "gravity-workshop" / "live_state.json"
            ws_state_file.parent.mkdir(parents=True)
            ws_state_file.write_text(
                json.dumps({"stage": "build", "progress": "4/8", "preset_profile": "standard"}),
                encoding="utf-8",
            )
            (wf_home / "live_workspaces.json").write_text(
                json.dumps({"workspaces": [{"workspace_path": str(atelier), "state_path": str(ws_state_file), "updated_at": "2026-11-25T11:00:25Z"}]}),
                encoding="utf-8",
            )
            plugins_root = tmp_path / "plugins"
            _write_spi_plugin(
                plugins_root, mod_id="metrics", plugin_name="gravity-metrics",
                script_body=_LIVE_META_SPI_SCRIPT, views=["metrics", "live-meta"], actions=[],
            )
            _write_spi_plugin(
                plugins_root, mod_id="workflow", plugin_name="gravity-workflow",
                script_body=_WF_LIVE_SPI_SCRIPT, views=["workflow"], actions=[],
            )

            state = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertEqual([s["conversation_id"] for s in state["sessions"]], [root_cid])
            self.assertEqual(state["workflow"]["stage"], "build")
            self.assertEqual(state["workflow"]["progress"], "4/8")
            self.assertTrue(state["workflow"]["is_active"])
            self.assertEqual(state["selected_session"]["session_started_at"], "2026-11-25T11:00:00Z")
            self.assertEqual(state["selected_session"]["session_last_ts"], "2026-11-25T11:00:20Z")

            by_id = {a["id"]: a for a in state["agents"]}
            self.assertEqual(set(by_id.keys()), {"coordinator", "core-w1", f"sub-{rev_cid[:8]}"})
            self.assertEqual(by_id["coordinator"]["started_at"], "2026-11-25T11:00:00Z")
            self.assertEqual(by_id["coordinator"]["workspace"], "gravity-workshop")
            self.assertEqual(by_id["coordinator"]["workspace_kind"], "atelier")
            self.assertEqual(by_id["core-w1"]["status"], "active")
            self.assertEqual(by_id["core-w1"]["workspace"], "gravity")
            self.assertEqual(by_id["core-w1"]["workspace_kind"], "code")
            self.assertEqual(by_id["core-w1"]["task_title"], "Implement live provider")
            self.assertEqual(by_id[f"sub-{rev_cid[:8]}"]["status"], "done")
            self.assertEqual(by_id[f"sub-{rev_cid[:8]}"]["workspace"], "gravity-metrics")
            self.assertTrue(any(ev["kind"] == "board" for ev in state["recent_events"]))

    def test_excludes_run_workflow_children_without_bytes_read_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "11111111-aaaa-bbbb-cccc-111111111111"
            wf_task_cid = "33333333-aaaa-bbbb-cccc-333333333333"
            wf_msg_cid = "44444444-aaaa-bbbb-cccc-444444444444"
            read_json_cid = "55555555-aaaa-bbbb-cccc-555555555555"

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-25T10:00:00Z", "content": "Orchestrate wave"},
                    {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:05Z", "model": "gemini-4-neon-high", "input_tokens": 200, "cache_read_tokens": 0, "output_tokens": 50},
                ],
            )
            _write_jsonl(
                brain / wf_task_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-25T10:02:00Z", "content": "wf task child"}],
            )
            _write_jsonl(
                brain / wf_msg_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-25T10:03:00Z", "content": "wf msg child"}],
            )
            _write_jsonl(
                brain / read_json_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-25T10:04:00Z", "content": "independent session"}],
            )

            sg_root = brain / root_cid / ".system_generated"
            (sg_root / "tasks").mkdir(parents=True)
            (sg_root / "tasks" / "task-1.log").write_text(f"[agent:builder] started ({wf_task_cid})\n", encoding="utf-8")
            (sg_root / "messages").mkdir(parents=True)
            (sg_root / "messages" / "m1.json").write_text(
                json.dumps({"tool": "run_workflow", "content": f"[agent:reviewer] done ({wf_msg_cid})"}), encoding="utf-8"
            )
            (sg_root / "messages" / "read.json").write_text(
                json.dumps({"tool": "run_workflow", "content": f"[agent:ignored] ({read_json_cid})"}), encoding="utf-8"
            )

            st = api.get_live_session_state(
                session_id=root_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual([s["conversation_id"] for s in st["sessions"]], [root_cid])
            agent_cids = {a["conversation_id"] for a in st["agents"]}
            self.assertEqual(agent_cids, {root_cid, wf_task_cid, wf_msg_cid})
            self.assertNotIn(read_json_cid, agent_cids)
            self.assertFalse(hasattr(live_provider, "_BRIDGE_SNIFF_CACHE"))
            self.assertGreater(len(live_provider._WF_CHILD_CACHE), 0)

            st_auto = api.get_live_session_state(gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home)
            auto_cids = [s["conversation_id"] for s in st_auto["sessions"]]
            self.assertEqual(set(auto_cids), {read_json_cid, root_cid})
            self.assertNotIn(wf_task_cid, auto_cids)
            self.assertNotIn(wf_msg_cid, auto_cids)

            bytes_before = live_provider.get_live_cache_stats()["bytes_read"]
            tpath = brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl"
            extra = json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "status": "DONE", "input_tokens": 10}) + "\n"
            with tpath.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(extra)
            api.get_live_session_state(
                session_id=root_cid, since_signature=st["signature"], gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            bytes_after = live_provider.get_live_cache_stats()["bytes_read"]
            self.assertEqual(bytes_after - bytes_before, len(extra.encode("utf-8")))

            live_provider.reset_live_cache()
            self.assertEqual(live_provider._WF_CHILD_CACHE, {})

    def test_freshness_filtering_archived_via_signal_bus_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            fresh_cid = "11111111-0000-0000-0000-000000000001"
            arch_cid = "22222222-0000-0000-0000-000000000002"
            stale_cid = "33333333-0000-0000-0000-000000000003"
            cap_stale_cid = "44444444-0000-0000-0000-000000000004"

            for cid in (fresh_cid, arch_cid, stale_cid, cap_stale_cid):
                _write_jsonl(
                    brain / cid / ".system_generated" / "logs" / "transcript.jsonl",
                    [{"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2020-01-01T00:00:00Z", "content": cid}],
                )

            now_ns = int((brain / fresh_cid / ".system_generated" / "logs" / "transcript.jsonl").stat().st_mtime_ns)
            old_ns = now_ns - int(8 * 3600 * 1e9)
            for cid in (stale_cid, cap_stale_cid):
                tp = brain / cid / ".system_generated" / "logs" / "transcript.jsonl"
                os.utime(tp, ns=(old_ns, old_ns))
                os.utime(brain / cid, ns=(old_ns, old_ns))

            ended_iso = datetime.fromtimestamp((now_ns / 1e9) + 10, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            publish_signal(
                "session-metrics",
                "archive-index",
                "gravity-metrics",
                {"archived_cids": {arch_cid: {"status": "archived", "ended_at": ended_iso}}},
                sample_count=1,
                window_size=1,
                gravity_home=g_home,
            )
            (m_home / "active_captures.json").write_text(
                json.dumps({"schema_version": 1, "captures": {cap_stale_cid: {"label": "cap-stale", "start_step": 0}}}),
                encoding="utf-8",
            )
            plugins_root = tmp_path / "plugins"
            _write_spi_plugin(
                plugins_root, mod_id="metrics", plugin_name="gravity-metrics",
                script_body=_LIVE_META_SPI_SCRIPT, views=["metrics", "live-meta"], actions=[],
            )

            st1 = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertEqual([s["conversation_id"] for s in st1["sessions"]], [cap_stale_cid, fresh_cid])
            self.assertFalse(st1["sessions"][0]["archived"])
            self.assertFalse(st1["sessions"][1]["archived"])

            (m_home / "active_captures.json").write_text(json.dumps({"schema_version": 1, "captures": {}}), encoding="utf-8")
            st_fresh = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertEqual([s["conversation_id"] for s in st_fresh["sessions"]], [fresh_cid])
            self.assertFalse(st_fresh["sessions"][0]["archived"])

            st_exp = api.get_live_session_state(
                session_id=arch_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertEqual([s["conversation_id"] for s in st_exp["sessions"]], [arch_cid])
            self.assertTrue(st_exp["sessions"][0]["archived"])

            os.utime(brain / fresh_cid / ".system_generated" / "logs" / "transcript.jsonl", ns=(old_ns, old_ns))
            os.utime(brain / fresh_cid, ns=(old_ns, old_ns))
            st_none = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertFalse(st_none["available"])
            self.assertEqual(st_none["sessions"], [])

    def test_subagent_alive_clean_termination_and_coordinator_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "aaaaaaaa-aaaa-1111-1111-111111111111"
            sub_done_cid = "bbbbbbbb-bbbb-1111-1111-111111111111"
            sub_run_cid = "cccccccc-cccc-1111-1111-111111111111"
            w1_cid = "dddddddd-dddd-1111-1111-111111111111"

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:00Z", "tool_calls": [{"name": "swarm_wait", "args": {}}]},
                    {"step_index": 1, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:01Z", "content": "Swarm wake"},
                ],
            )
            _write_jsonl(
                brain / sub_done_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:02Z"}],
            )
            _write_jsonl(
                brain / sub_run_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "RUNNING", "created_at": "2026-11-25T10:00:03Z"}],
            )
            _write_jsonl(
                brain / w1_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:04Z", "tool_calls": [{"name": "finish", "args": {}}]},
                    {"step_index": 1, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:05Z", "content": "done"},
                ],
            )

            sg_root = brain / root_cid / ".system_generated"
            (sg_root / "subagents").mkdir(parents=True)
            (sg_root / "swarm").mkdir(parents=True)
            (sg_root / "subagents" / f"{sub_done_cid}.json").write_text(
                json.dumps({"conversationId": sub_done_cid, "state": "SUBAGENT_STATE_ALIVE", "subagentDescriptor": {"typeName": "explore", "role": "Done Subagent"}}),
                encoding="utf-8",
            )
            (sg_root / "subagents" / f"{sub_run_cid}.json").write_text(
                json.dumps({"conversationId": sub_run_cid, "state": "SUBAGENT_STATE_ALIVE", "subagentDescriptor": {"typeName": "builder", "role": "Running Subagent"}}),
                encoding="utf-8",
            )
            (sg_root / "swarm" / "members.json").write_text(
                json.dumps({
                    "title": "Swarm",
                    "members": {
                        "coordinator": {"conversation_id": root_cid, "role": "coordinator", "phase": "RUNNING", "wake_mode": "mentions"},
                        "w1": {"conversation_id": w1_cid, "role": "worker", "phase": "STOPPED", "desired_state": "STOPPED", "killed": True},
                    },
                }),
                encoding="utf-8",
            )

            st1 = api.get_live_session_state(session_id=root_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home)
            by_id1 = {a["id"]: a for a in st1["agents"]}
            self.assertEqual(by_id1[f"sub-{sub_done_cid[:8]}"]["status"], "done")
            self.assertTrue(by_id1[f"sub-{sub_done_cid[:8]}"]["clean_termination"])
            self.assertEqual(by_id1[f"sub-{sub_run_cid[:8]}"]["status"], "active")
            self.assertEqual(by_id1["w1"]["status"], "done")
            self.assertEqual(by_id1["coordinator"]["status"], "waiting")

            with (brain / sub_run_cid / ".system_generated" / "logs" / "transcript.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:10Z"}) + "\n")
            st2 = api.get_live_session_state(
                session_id=root_cid, since_signature=st1["signature"], gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertTrue(st2["changed"])
            by_id2 = {a["id"]: a for a in st2["agents"]}
            self.assertEqual(by_id2[f"sub-{sub_run_cid[:8]}"]["status"], "done")
            self.assertEqual(by_id2["coordinator"]["status"], "done")

    def test_recursive_run_workflow_depth2_anti_cycle_and_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "10000000-1111-2222-3333-444444444444"
            wf1_cid = "20000000-1111-2222-3333-444444444444"
            wf2_cid = "30000000-1111-2222-3333-444444444444"

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 3, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:00Z", "content": f"[agent:builder] Builder W1: running ({wf1_cid})"}],
            )
            _write_jsonl(
                brain / wf1_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:05Z"}],
            )
            _write_jsonl(
                brain / wf2_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "RUNNING", "created_at": "2026-11-25T10:00:08Z"}],
            )
            (brain / wf1_cid / ".system_generated" / "messages").mkdir(parents=True)
            (brain / wf1_cid / ".system_generated" / "messages" / "m1.json").write_text(
                json.dumps({"content": f"[agent:reviewer] Code Reviewer: running ({wf2_cid})"}), encoding="utf-8"
            )
            (brain / wf2_cid / ".system_generated" / "messages").mkdir(parents=True)
            (brain / wf2_cid / ".system_generated" / "messages" / "loop.json").write_text(
                json.dumps({"content": f"[agent:root] Loop ({root_cid})"}), encoding="utf-8"
            )

            st1 = api.get_live_session_state(gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home)
            self.assertEqual([s["conversation_id"] for s in st1["sessions"]], [root_cid])
            self.assertEqual(len(st1["agents"]), 3)
            by_cid = {a["conversation_id"]: a for a in st1["agents"]}
            self.assertEqual(by_cid[root_cid]["depth"], 0)
            self.assertEqual(by_cid[root_cid]["children_count"], 1)
            self.assertEqual(by_cid[wf1_cid]["depth"], 1)
            self.assertEqual(by_cid[wf1_cid]["spawn_step"], 3)
            self.assertEqual(by_cid[wf1_cid]["status"], "active")
            self.assertEqual(by_cid[wf2_cid]["depth"], 2)
            self.assertEqual(by_cid[wf2_cid]["parent_name"], "Builder W1")
            self.assertEqual(by_cid[wf2_cid]["status"], "active")

            bytes_before = live_provider.get_live_cache_stats()["bytes_read"]
            extra_wf2 = json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:12Z"}) + "\n"
            with (brain / wf2_cid / ".system_generated" / "logs" / "transcript.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(extra_wf2)
            st2 = api.get_live_session_state(
                since_signature=st1["signature"], gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertTrue(st2["changed"])
            self.assertEqual(live_provider.get_live_cache_stats()["bytes_read"] - bytes_before, len(extra_wf2.encode("utf-8")))
            by_cid2 = {a["conversation_id"]: a for a in st2["agents"]}
            self.assertEqual(by_cid2[wf2_cid]["status"], "done")
            self.assertEqual(by_cid2[wf1_cid]["status"], "done")

            (brain / wf1_cid / ".system_generated" / "messages" / "m2.json").write_text(json.dumps({"content": "update"}), encoding="utf-8")
            st3 = api.get_live_session_state(
                since_signature=st2["signature"], gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertTrue(st3["changed"])

    def test_terminal_errors_shell_nonzero_and_showing_lines_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "40000000-1111-2222-3333-444444444444"
            err_cid = "50000000-1111-2222-3333-444444444444"
            ok_cid = "60000000-1111-2222-3333-444444444444"

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:00Z"}],
            )
            _write_jsonl(
                brain / err_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:01Z", "content": "Command exited with code 2\nCommand output:\nboom"}],
            )
            _write_jsonl(
                brain / ok_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:01Z", "tool_calls": [{"name": "finish", "args": {}}]},
                    {"step_index": 1, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:02Z", "content": "Showing lines 1-5 of 10\nCommand exited with code 2"},
                ],
            )
            sg_root = brain / root_cid / ".system_generated"
            (sg_root / "subagents").mkdir(parents=True)
            for scid in (err_cid, ok_cid):
                (sg_root / "subagents" / f"{scid}.json").write_text(
                    json.dumps({"conversationId": scid, "state": "SUBAGENT_STATE_ALIVE"}), encoding="utf-8"
                )

            st = api.get_live_session_state(session_id=root_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home)
            by_cid = {a["conversation_id"]: a for a in st["agents"]}
            self.assertEqual(by_cid[err_cid]["status"], "error")
            self.assertEqual(by_cid[err_cid]["error_steps"], 1)
            self.assertFalse(by_cid[err_cid]["clean_termination"])
            self.assertEqual(by_cid[ok_cid]["status"], "done")
            self.assertTrue(by_cid[ok_cid]["clean_termination"])

    def test_workflow_transcript_ignores_tool_outputs_and_non_system_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            brain = tmp_path / "brain"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "aaaaaaaa-1111-2222-3333-444444444444"
            fake_read_cid = "bbbbbbbb-1111-2222-3333-444444444444"
            fake_cmd_cid = "cccccccc-1111-2222-3333-444444444444"
            fake_planner_cid = "dddddddd-1111-2222-3333-444444444444"
            fake_user_cid = "eeeeeeee-1111-2222-3333-444444444444"
            real_generic_cid = "f1111111-1111-2222-3333-444444444444"
            real_sys_cid = "f2222222-1111-2222-3333-444444444444"

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-25T10:00:00Z", "content": f"- [agent:builder] User paste: done ({fake_user_cid})"},
                    {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:01Z", "thinking": f"- [agent:reviewer] Thought: done ({fake_planner_cid})"},
                    {"step_index": 2, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:02Z", "content": f"Created At: 2026-11-25T10:00:02Z\nShowing lines 1-3 of 3\n1: - [agent:builder] Read file leak: done ({fake_read_cid})"},
                    {"step_index": 3, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:03Z", "content": f"Created At: 2026-11-25T10:00:03Z\nCommand exited with code 0.\n\nCommand output:\n- [agent:reviewer] Shell grep leak: error ({fake_cmd_cid})"},
                    {"step_index": 4, "type": "GENERIC", "status": "DONE", "created_at": "2026-11-25T10:00:04Z", "content": f"Created At: 2026-11-25T10:00:04Z\nTask: {root_cid}/task-4\nLogs:\n- [agent:builder] Real Generic WF: done ({real_generic_cid})\nOutput:\nok"},
                    {"step_index": 5, "type": "SYSTEM_MESSAGE", "status": "DONE", "created_at": "2026-11-25T10:00:05Z", "content": f"<SYSTEM_MESSAGE>\nTask id {root_cid}/task-5 finished.\n- [agent:reviewer] Real System WF: done ({real_sys_cid})\n</SYSTEM_MESSAGE>"},
                    {"step_index": 6, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:06Z"},
                ],
            )
            (brain / root_cid / ".system_generated" / "subagents").mkdir(parents=True)
            (brain / root_cid / ".system_generated" / "subagents" / f"{fake_read_cid}.json").write_text("[]", encoding="utf-8")
            for child_cid in (fake_read_cid, fake_cmd_cid, fake_planner_cid, fake_user_cid, real_generic_cid, real_sys_cid):
                _write_jsonl(
                    brain / child_cid / ".system_generated" / "logs" / "transcript.jsonl",
                    [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:06Z"}],
                )

            st = api.get_live_session_state(session_id=root_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home)
            cids = {a["conversation_id"] for a in st["agents"]}
            self.assertEqual(cids, {root_cid, real_generic_cid, real_sys_cid})
            self.assertEqual(st["summary"]["total_agents"], 3)
            self.assertEqual(st["summary"]["done_agents"], 3)
            self.assertEqual(st["summary"]["error_agents"], 0)

    def test_windows_repo_normalization_arbitrary_root_code_and_session_workflow_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_parent = Path("D:/Neko/Documents/GitHub")
            self.assertEqual(
                live_provider._normalize_repo_name("d:\\neko\\documents\\github\\gravity-workshop\\tracking\\projects\\gravity.md", root_parent=root_parent),
                "gravity-workshop",
            )
            self.assertEqual(
                live_provider._normalize_repo_name("C:/Users/Test/gravity-workshop/templates/repo-standard.md"),
                "gravity-workshop",
            )
            self.assertEqual(
                live_provider._normalize_repo_name("C:/Users/Test/gravity/dashboard/providers/live_provider.py"),
                "gravity",
            )
            self.assertEqual(live_provider._classify_workspace_kind("my-product", root_ws="my-product"), "code")
            self.assertEqual(live_provider._classify_workspace_kind("gravity-workshop", root_ws="gravity"), "atelier")
            atelier_disk = tmp_path / "custom-ws"
            (atelier_disk / "specs").mkdir(parents=True)
            self.assertEqual(live_provider._classify_workspace_kind("custom-ws", str(atelier_disk), root_ws="custom-ws"), "atelier")

            product_repo = tmp_path / "repos" / "gravity"
            product_repo.mkdir(parents=True)
            other_repo = tmp_path / "repos" / "other-ws"
            other_repo.mkdir(parents=True)
            other_state = wf_home / "workspaces" / "other-ws" / "live_state.json"
            other_state.parent.mkdir(parents=True)
            other_state.write_text(json.dumps({"stage": "build", "progress": "2/8"}), encoding="utf-8")
            (wf_home / "live_workspaces.json").write_text(
                json.dumps({"workspaces": [{"workspace_path": str(other_repo), "state_path": str(other_state), "updated_at": "2026-11-26T00:00:00Z"}]}),
                encoding="utf-8",
            )

            root_cid = "77777777-aaaa-bbbb-cccc-111111111111"
            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-26T00:01:00Z"}],
            )
            (m_home / "session_meta.json").write_text(
                json.dumps({"schema_version": 1, "sessions": {root_cid: {"cwd": str(product_repo), "project": "gravity"}}}),
                encoding="utf-8",
            )
            plugins_root = tmp_path / "plugins"
            _write_spi_plugin(
                plugins_root, mod_id="metrics", plugin_name="gravity-metrics",
                script_body=_LIVE_META_SPI_SCRIPT, views=["metrics", "live-meta"], actions=[],
            )
            _write_spi_plugin(
                plugins_root, mod_id="workflow", plugin_name="gravity-workflow",
                script_body=_WF_LIVE_SPI_SCRIPT, views=["workflow"], actions=[],
            )
            st = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertEqual(live_provider.MAX_RECENT_EVENTS, 80)
            self.assertEqual(st["selected_session"]["project"], "gravity")
            self.assertEqual(st["selected_session"]["workspace_kind"], "code")
            self.assertFalse(st["workflow"]["is_active"])
            self.assertEqual(st["workflow"]["stage"], "idle")
            self.assertEqual(st["workflow"]["progress"], "0/0")

    def test_spi_live_meta_decoupling_neutral_fallback_and_dead_code_removed(self) -> None:
        from dashboard import providers as providers_pkg

        for removed_prog in ("read_workflow_live_c8_ro", "_workspace_slug_hash", "_norm_ws_key", "_select_c8_workspace", "MAX_WORKFLOW_EVENTS"):
            self.assertFalse(hasattr(live_progress, removed_prog), f"{removed_prog} should be removed from live_progress")
        for removed_md in ("classify_verdict_tone", "clean_md_inline", "extract_md_excerpt", "extract_md_title", "extract_md_verdict"):
            self.assertFalse(hasattr(providers_pkg, removed_md), f"{removed_md} should be removed from dashboard.providers")

        for rel in ("plugin/dashboard/providers/live_provider.py", "plugin/dashboard/providers/live_progress.py"):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for forbidden in ("active_captures.json", "session_meta.json", "live_workspaces.json", "live_state.json", "resolve_module_home"):
                self.assertNotIn(forbidden, src, f"{forbidden} must not appear in {rel}")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            m_home.mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "88888888-aaaa-bbbb-cccc-111111111111"
            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-27T10:00:00Z"}],
            )
            (m_home / "active_captures.json").write_text(
                json.dumps({"schema_version": 1, "captures": {root_cid: {"label": "leaked-cap", "project": "leaked-proj"}}}),
                encoding="utf-8",
            )
            (m_home / "session_meta.json").write_text(
                json.dumps({"schema_version": 1, "sessions": {root_cid: {"cwd": "/tmp/leaked-ws", "project": "leaked-proj"}}}),
                encoding="utf-8",
            )
            ws_state = wf_home / "workspaces" / "leaked" / "live_state.json"
            ws_state.parent.mkdir(parents=True)
            ws_state.write_text(json.dumps({"stage": "build", "progress": "7/8"}), encoding="utf-8")
            (wf_home / "live_workspaces.json").write_text(
                json.dumps({"workspaces": [{"workspace_path": "/tmp/leaked-ws", "state_path": str(ws_state)}]}),
                encoding="utf-8",
            )

            st_no_spi = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[]
            )
            self.assertTrue(st_no_spi["available"])
            self.assertFalse(st_no_spi["selected_session"]["captured"])
            self.assertEqual(st_no_spi["selected_session"]["project"], "workspace")
            self.assertFalse(st_no_spi["workflow"]["available"])
            self.assertEqual(st_no_spi["workflow"]["stage"], "idle")
            self.assertEqual(st_no_spi["workflow"]["progress"], "0/0")
            self.assertFalse(st_no_spi["workflow"]["is_active"])

            plugins_root = tmp_path / "plugins"
            err_script = (
                "import argparse, json\n"
                "p = argparse.ArgumentParser()\n"
                "p.add_argument('--view', default='')\n"
                "p.add_argument('--since-signature', default='')\n"
                "p.add_argument('--json', action='store_true')\n"
                "p.parse_args()\n"
                "print(json.dumps({'ok': False, 'error': 'simulated failure'}))\n"
            )
            _write_spi_plugin(
                plugins_root, mod_id="metrics", plugin_name="gravity-metrics",
                script_body=err_script, views=["metrics", "live-meta"], actions=[],
            )
            st_err = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertFalse(st_err["selected_session"]["captured"])
            self.assertEqual(st_err["selected_session"]["project"], "workspace")

            _write_spi_plugin(
                plugins_root, mod_id="metrics", plugin_name="gravity-metrics",
                script_body=_LIVE_META_SPI_SCRIPT, views=["metrics", "live-meta"], actions=[],
            )
            st_v1 = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root]
            )
            self.assertTrue(st_v1["selected_session"]["captured"])
            self.assertEqual(st_v1["selected_session"]["label"], "leaked-cap")
            self.assertTrue(
                api.get_live_session_state(
                    since_signature=st_v1["signature"], gravity_home=g_home, brain_dir=brain,
                    metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root],
                )["unchanged"]
            )
            (m_home / "active_captures.json").write_text(
                json.dumps({"schema_version": 1, "captures": {root_cid: {"label": "updated-cap", "project": "leaked-proj"}}}),
                encoding="utf-8",
            )
            st_v2 = api.get_live_session_state(
                since_signature=st_v1["signature"], gravity_home=g_home, brain_dir=brain,
                metrics_home=m_home, workflow_home=wf_home, plugin_roots=[plugins_root],
            )
            self.assertTrue(st_v2["changed"])
            self.assertEqual(st_v2["selected_session"]["label"], "updated-cap")


class TestLiveProgressAndGenericSpi(unittest.TestCase):
    def test_build_live_progress_structured_and_default(self) -> None:
        self.assertEqual(live_progress.build_live_progress(None)["label"], "0/0")
        self.assertEqual(live_progress.build_live_progress({})["label"], "0/0")
        self.assertEqual(live_progress.build_live_progress({"progress": "3/5"}), {"label": "3/5", "done": 3, "total": 5, "pct": 60, "waves": [], "tasks": []})
        tasks_prog = live_progress.build_live_progress({"tasks": [{"status": "done"}, {"status": "running"}, {"done": True}]})
        self.assertEqual((tasks_prog["label"], tasks_prog["done"], tasks_prog["total"], tasks_prog["pct"]), ("2/3", 2, 3, 67))
        waves_prog = live_progress.build_live_progress({"waves": [{"done": 2, "total": 2}, {"tasks": [{"status": "done"}, {"status": "todo"}]}]})
        self.assertEqual((waves_prog["label"], waves_prog["done"], waves_prog["total"], waves_prog["pct"]), ("3/4", 3, 4, 75))

    def test_generic_provider_spi_and_fallback(self) -> None:
        custom_script = """\
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
print(json.dumps({"available": True, "changed": True, "unchanged": False, "view": a.view, "echo": req.get("params")}))
"""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            _write_spi_plugin(
                plugins_root, mod_id="custom", plugin_name="gravity-custom",
                script_body=custom_script, views=["overview", "detail"], actions=[],
            )
            info = generic_provider.get_module_info("custom", gravity_home=g_home, plugin_roots=[plugins_root])
            self.assertTrue(info["found"])
            self.assertTrue(info["spi"]["enabled"])
            self.assertEqual(info["spi"]["views"], ["overview", "detail"])

            res = generic_provider.get_generic_view(
                "custom", view="detail", params={"item": 42}, gravity_home=g_home, plugin_roots=[plugins_root]
            )
            self.assertTrue(res["available"])
            self.assertEqual(res["view"], "detail")
            self.assertEqual(res["echo"]["item"], 42)


class TestMetricsSpiActionsAndAudits(unittest.TestCase):
    def test_spi_metrics_actions_audits_and_fail_closed(self) -> None:
        met_script = """\
import argparse, json, pathlib, sys
p = argparse.ArgumentParser()
p.add_argument("--view", default="")
p.add_argument("--since-signature", default="")
p.add_argument("--action", default="")
p.add_argument("--json", action="store_true")
a = p.parse_args()
req = json.loads(sys.stdin.read() or "{}")
params = req.get("params") or {}
ctx = req.get("context") or {}
if a.action:
    print(json.dumps({"ok": True, "action": a.action, "message": f"{a.action} ok", "target": params.get("target")}))
elif a.view == "audit-detail":
    rel = str(params.get("path") or "")
    for ad in (ctx.get("audits_dirs") or []):
        cand = pathlib.Path(ad) / rel
        if cand.is_file() and not rel.startswith("_"):
            print(json.dumps({"found": True, "path": rel, "content": cand.read_text(encoding="utf-8")}))
            sys.exit(0)
    print(json.dumps({"found": False, "path": rel, "error": "Audit not found"}))
"""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            plugins_root = tmp_path / "plugins"
            audits_agents = tmp_path / "gravity-workshop" / "audits" / "agents"
            audits_code = tmp_path / "gravity-workshop" / "audits" / "code"
            audits_agents.mkdir(parents=True)
            audits_code.mkdir(parents=True)
            (audits_agents / "2026-11-25-ok.md").write_text("# Audit OK\n\nVerdict: PASS\n\nDetails here.\n", encoding="utf-8")
            (audits_agents / "_TEMPLATE.md").write_text("# Template\n", encoding="utf-8")
            (audits_code / "secret.md").write_text("# Code Audit\n", encoding="utf-8")

            missing = api.run_metrics_cli_action(
                "record", conversation_id="11111111-2222-3333-4444-555555555555", gravity_home=g_home, plugin_roots=[plugins_root]
            )
            self.assertFalse(missing["ok"])
            self.assertTrue(missing["spi_fallback"])

            m_plugin = _write_spi_plugin(
                plugins_root, mod_id="metrics", plugin_name="gravity-metrics", script_body=met_script,
                views=["metrics", "session-detail", "audit-detail"],
                actions=["record", "update", "update-meta", "ignore", "unignore", "remove"],
            )
            write_modules_registry(g_home, [{"id": "metrics", "plugin_name": "gravity-metrics", "plugin_dir": str(m_plugin)}])

            cid = "11111111-2222-3333-4444-555555555555"
            for act in ("record", "update", "update-meta", "ignore", "unignore", "remove"):
                res = api.run_metrics_cli_action(act, target="wave-1" if act != "update" else cid, gravity_home=g_home)
                self.assertTrue(res["ok"], f"Action {act} failed: {res}")
                self.assertEqual(res["action"], act)

            self.assertFalse(api.run_metrics_cli_action("drop-all", target=cid, gravity_home=g_home)["ok"])
            self.assertFalse(api.run_metrics_cli_action("ignore", target="../etc/passwd", gravity_home=g_home)["ok"])

            fallback_cid = api.run_metrics_cli_action(
                "remove",
                target="Session avec espaces",
                conversation_id=cid,
                slug="session-avec-espaces",
                gravity_home=g_home,
            )
            self.assertTrue(fallback_cid["ok"])
            self.assertEqual(fallback_cid["target"], cid)

            fallback_slug = api.run_metrics_cli_action(
                "update-meta",
                target="feat/label invalide",
                conversation_id="",
                slug="feat-label-invalide",
                gravity_home=g_home,
            )
            self.assertTrue(fallback_slug["ok"])
            self.assertEqual(fallback_slug["target"], "feat-label-invalide")

            invalid_all = api.run_metrics_cli_action(
                "remove",
                target="../escape",
                conversation_id="bad id",
                slug="bad/slug",
                gravity_home=g_home,
            )
            self.assertFalse(invalid_all["ok"])
            self.assertIn("../escape", invalid_all["error"])

            aud_ok = api.read_metrics_audit("2026-11-25-ok.md", gravity_home=g_home, audits_dirs=[audits_agents])
            self.assertTrue(aud_ok["found"])
            self.assertIn("Details here.", aud_ok["content"])
            self.assertFalse(api.read_metrics_audit("../outside.md", gravity_home=g_home, audits_dirs=[audits_agents])["found"])
            self.assertFalse(api.read_metrics_audit("_TEMPLATE.md", gravity_home=g_home, audits_dirs=[audits_agents])["found"])
            self.assertFalse(api.read_metrics_audit("code/secret.md", gravity_home=g_home, audits_dirs=[audits_agents])["found"])
            self.assertFalse(api.read_metrics_audit("audits/code/secret.md", gravity_home=g_home, audits_dirs=[audits_agents])["found"])


if __name__ == "__main__":
    unittest.main()

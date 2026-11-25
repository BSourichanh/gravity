"""Isolated unit tests for live_provider, metrics_actions, metrics_audits, and technical KPIs."""

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
from dashboard import api  # noqa: E402
from dashboard.providers import live_provider  # noqa: E402


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
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "status": "DONE",
                    "created_at": "2026-11-25T10:00:00Z",
                    "content": "go",
                },
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

            st1 = api.get_live_session_state(
                gravity_home=g_home,
                brain_dir=brain,
                metrics_home=m_home,
                workflow_home=wf_home,
            )
            self.assertTrue(st1["available"])
            self.assertTrue(st1["changed"])
            self.assertEqual(st1["summary"]["llm_calls"], 1)
            self.assertEqual(st1["summary"]["thinking_est_tokens"], 20)
            bytes_first = live_provider.get_live_cache_stats()["bytes_read"]
            self.assertGreater(bytes_first, 0)

            unchanged = api.get_live_session_state(
                since_signature=st1["signature"],
                gravity_home=g_home,
                brain_dir=brain,
                metrics_home=m_home,
                workflow_home=wf_home,
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
                since_signature=st1["signature"],
                gravity_home=g_home,
                brain_dir=brain,
                metrics_home=m_home,
                workflow_home=wf_home,
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
            atelier = tmp_path / "gravity-studio"
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
                            root_cid: {"cwd": str(atelier), "project": "gravity-studio"},
                            worker_cid: {"cwd": str(atelier), "project": "gravity-studio"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (m_home / "active_captures.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "captures": {
                            root_cid: {"label": "live-cap", "project": "gravity-studio", "start_step": 0}
                        },
                    }
                ),
                encoding="utf-8",
            )

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {
                        "step_index": 0,
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": "2026-11-25T11:00:00Z",
                        "model": "gemini-4-hydrogen-high",
                        "input_tokens": 1000,
                        "cache_read_tokens": 2000,
                        "output_tokens": 100,
                    }
                ],
            )
            _write_jsonl(
                brain / worker_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {
                        "step_index": 0,
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": "2026-11-25T11:00:10Z",
                        "model": "gemini-4-hydrogen-high",
                        "input_tokens": 800,
                        "cache_read_tokens": 1200,
                        "output_tokens": 300,
                        "tool_calls": [
                            {
                                "name": "edit_file",
                                "args": {"Path": "/tmp/gravity-worktrees/gravity-w1/plugin/dashboard/api.py"},
                            }
                        ],
                    }
                ],
            )
            _write_jsonl(
                brain / rev_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {
                        "step_index": 0,
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": "2026-11-25T11:00:20Z",
                        "model": "gemini-4-neon-high",
                        "input_tokens": 400,
                        "cache_read_tokens": 600,
                        "output_tokens": 50,
                        "tool_calls": [
                            {"name": "read_file", "args": {"Path": "/tmp/gravity-metrics/plugin/scripts/cli.py"}}
                        ],
                    }
                ],
            )

            sg_root = brain / root_cid / ".system_generated"
            (sg_root / "swarm").mkdir(parents=True)
            (sg_root / "subagents").mkdir(parents=True)
            (sg_root / "swarm" / "members.json").write_text(
                json.dumps(
                    {
                        "title": "Wave 1",
                        "members": {
                            "coordinator": {
                                "conversation_id": root_cid,
                                "role": "coordinator",
                                "phase": "RUNNING",
                                "wake_mode": "mentions",
                                "model": "gemini-4-hydrogen-high",
                            },
                            "core-w1": {
                                "conversation_id": worker_cid,
                                "role": "worker",
                                "phase": "RUNNING",
                                "wake_mode": "working",
                                "model": "gemini-4-hydrogen-high",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (sg_root / "swarm" / "plan.json").write_text(
                json.dumps(
                    {
                        "goal": {"title": "Unified Dashboard"},
                        "tasks": {"core-w1": "Implement live provider"},
                    }
                ),
                encoding="utf-8",
            )
            _write_jsonl(
                sg_root / "swarm" / "board.jsonl",
                [{"seq": 1, "agent": "core-w1", "text": "Working on live_provider", "time": "2026-11-25 11:00:15", "kind": "update"}],
            )
            (sg_root / "subagents" / f"{worker_cid}.json").write_text(
                json.dumps(
                    {
                        "conversationId": worker_cid,
                        "subagentDescriptor": {"typeName": "worker", "role": "Swarm Worker (core-w1)"},
                        "state": "SUBAGENT_STATE_ALIVE",
                        "workspaceUris": [atelier.as_uri()],
                    }
                ),
                encoding="utf-8",
            )
            (sg_root / "subagents" / f"{rev_cid}.json").write_text(
                json.dumps(
                    {
                        "conversationId": rev_cid,
                        "subagentDescriptor": {"typeName": "explore", "role": "CLI Reader"},
                        "state": "SUBAGENT_STATE_COMPLETED",
                        "workspaceUris": [atelier.as_uri()],
                    }
                ),
                encoding="utf-8",
            )

            wf_home.mkdir(parents=True)
            ws_state_file = wf_home / "workspaces" / "gravity-studio" / "live_state.json"
            ws_state_file.parent.mkdir(parents=True)
            ws_state_file.write_text(
                json.dumps({"stage": "build", "progress": "4/8", "preset_profile": "standard"}),
                encoding="utf-8",
            )
            (wf_home / "live_workspaces.json").write_text(
                json.dumps(
                    {
                        "workspaces": [
                            {
                                "workspace_path": str(atelier),
                                "state_path": str(ws_state_file),
                                "updated_at": "2026-11-25T11:00:25Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            state = api.get_live_session_state(
                gravity_home=g_home,
                brain_dir=brain,
                metrics_home=m_home,
                workflow_home=wf_home,
            )
            self.assertEqual([s["conversation_id"] for s in state["sessions"]], [root_cid])
            self.assertEqual(state["workflow"]["stage"], "build")
            self.assertEqual(state["workflow"]["progress"], "4/8")

            by_id = {a["id"]: a for a in state["agents"]}
            self.assertEqual(set(by_id.keys()), {"coordinator", "core-w1", f"sub-{rev_cid[:8]}"})
            self.assertEqual(by_id["coordinator"]["workspace"], "gravity-studio")
            self.assertEqual(by_id["coordinator"]["workspace_kind"], "atelier")
            self.assertEqual(by_id["core-w1"]["status"], "active")
            self.assertEqual(by_id["core-w1"]["workspace"], "gravity")
            self.assertEqual(by_id["core-w1"]["workspace_kind"], "code")
            self.assertEqual(by_id["core-w1"]["task_title"], "Implement live provider")
            self.assertEqual(by_id[f"sub-{rev_cid[:8]}"]["status"], "done")
            self.assertEqual(by_id[f"sub-{rev_cid[:8]}"]["workspace"], "gravity-metrics")
            self.assertTrue(any(ev["kind"] == "board" for ev in state["recent_events"]))

    def test_excludes_bridge_and_run_workflow_children_without_bytes_read_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            (m_home / "data").mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "11111111-aaaa-bbbb-cccc-111111111111"
            bridge_cid = "22222222-aaaa-bbbb-cccc-222222222222"
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
                brain / bridge_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [{"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-25T10:01:00Z", "content": "<USER_REQUEST>\n[GRAVITY-BRIDGE | job-1] Execute task\n</USER_REQUEST>"}],
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
            (sg_root / "tasks" / "task-1.log").write_text(
                f"[agent:builder] started ({wf_task_cid})\n", encoding="utf-8"
            )
            (sg_root / "messages").mkdir(parents=True)
            (sg_root / "messages" / "m1.json").write_text(
                json.dumps({"tool": "run_workflow", "content": f"[agent:reviewer] done ({wf_msg_cid})"}),
                encoding="utf-8",
            )
            # read.json must be ignored when discovering workflow children
            (sg_root / "messages" / "read.json").write_text(
                json.dumps({"tool": "run_workflow", "content": f"[agent:ignored] ({read_json_cid})"}),
                encoding="utf-8",
            )

            st = api.get_live_session_state(
                session_id=root_cid,
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            cids = [s["conversation_id"] for s in st["sessions"]]
            self.assertEqual(cids, [root_cid])
            agent_cids = {a["conversation_id"] for a in st["agents"]}
            self.assertEqual(agent_cids, {root_cid, wf_task_cid, wf_msg_cid})
            self.assertNotIn(read_json_cid, agent_cids)
            self.assertGreater(len(live_provider._BRIDGE_SNIFF_CACHE), 0)
            self.assertGreater(len(live_provider._WF_CHILD_CACHE), 0)

            # Without explicit session_id: bridge, wf_task and wf_msg are excluded as roots, leaving read_json_cid (newest root)
            st_auto = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual([s["conversation_id"] for s in st_auto["sessions"]], [read_json_cid])

            # Appending to root transcript must only add extra_line bytes to bytes_read
            bytes_before = live_provider.get_live_cache_stats()["bytes_read"]
            tpath = brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl"
            extra = json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "status": "DONE", "input_tokens": 10}) + "\n"
            with tpath.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(extra)
            api.get_live_session_state(
                session_id=root_cid,
                since_signature=st["signature"],
                gravity_home=g_home,
                brain_dir=brain,
                metrics_home=m_home,
                workflow_home=wf_home,
            )
            bytes_after = live_provider.get_live_cache_stats()["bytes_read"]
            self.assertEqual(bytes_after - bytes_before, len(extra.encode("utf-8")))

            live_provider.reset_live_cache()
            self.assertEqual(live_provider._BRIDGE_SNIFF_CACHE, {})
            self.assertEqual(live_provider._WF_CHILD_CACHE, {})

    def test_freshness_filtering_archived_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            g_home = tmp_path / "gravity"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            (m_home / "data").mkdir(parents=True)
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

            # Mark arch_cid as archived with ended_at in the future relative to its mtime -> truly archived
            from datetime import datetime, timezone
            ended_iso = datetime.fromtimestamp((now_ns / 1e9) + 10, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_jsonl(
                m_home / "data" / "history.jsonl",
                [{"conversation_id": arch_cid, "status": "archived", "ended_at": ended_iso}],
            )
            (m_home / "active_captures.json").write_text(
                json.dumps({"schema_version": 1, "captures": {cap_stale_cid: {"label": "cap-stale", "start_step": 0}}}),
                encoding="utf-8",
            )

            # Without explicit session_id: selects only 1 root (non-archived active capture has priority)
            st1 = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual([s["conversation_id"] for s in st1["sessions"]], [cap_stale_cid])
            self.assertFalse(st1["sessions"][0]["archived"])

            # Clear active_captures -> selects the single most recent non-archived fresh root
            (m_home / "active_captures.json").write_text(json.dumps({"schema_version": 1, "captures": {}}), encoding="utf-8")
            st_fresh = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual([s["conversation_id"] for s in st_fresh["sessions"]], [fresh_cid])
            self.assertFalse(st_fresh["sessions"][0]["archived"])

            # Explicitly requesting archived session returns only that session and marks archived=True
            st_exp = api.get_live_session_state(
                session_id=arch_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual([s["conversation_id"] for s in st_exp["sessions"]], [arch_cid])
            self.assertTrue(st_exp["sessions"][0]["archived"])

            # Make fresh_cid stale too -> no current session available (no multi-session archived fallback)
            os.utime(brain / fresh_cid / ".system_generated" / "logs" / "transcript.jsonl", ns=(old_ns, old_ns))
            os.utime(brain / fresh_cid, ns=(old_ns, old_ns))
            st_none = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
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
            (m_home / "data").mkdir(parents=True)
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

            # While sub_run_cid is still RUNNING, coordinator has an active child -> waiting (not done)
            st1 = api.get_live_session_state(
                session_id=root_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            by_id1 = {a["id"]: a for a in st1["agents"]}
            self.assertEqual(by_id1[f"sub-{sub_done_cid[:8]}"]["status"], "done")
            self.assertTrue(by_id1[f"sub-{sub_done_cid[:8]}"]["clean_termination"])
            self.assertEqual(by_id1[f"sub-{sub_run_cid[:8]}"]["status"], "active")
            self.assertEqual(by_id1["w1"]["status"], "done")
            self.assertEqual(by_id1["coordinator"]["status"], "waiting")

            # Finish sub_run_cid cleanly (PLANNER_RESPONSE/DONE without tools) -> all children done -> coordinator becomes done
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
            (m_home / "data").mkdir(parents=True)
            wf_home.mkdir(parents=True)

            root_cid = "10000000-1111-2222-3333-444444444444"
            wf1_cid = "20000000-1111-2222-3333-444444444444"
            wf2_cid = "30000000-1111-2222-3333-444444444444"

            _write_jsonl(
                brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl",
                [
                    {
                        "step_index": 3,
                        "type": "GENERIC",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:00Z",
                        "content": f"[agent:builder] Builder W1: running ({wf1_cid})",
                    }
                ],
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
                json.dumps({"content": f"[agent:reviewer] Code Reviewer: running ({wf2_cid})"}),
                encoding="utf-8",
            )
            # Cycle back to root_cid must be ignored cleanly
            (brain / wf2_cid / ".system_generated" / "messages").mkdir(parents=True)
            (brain / wf2_cid / ".system_generated" / "messages" / "loop.json").write_text(
                json.dumps({"content": f"[agent:root] Loop ({root_cid})"}),
                encoding="utf-8",
            )

            st1 = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual([s["conversation_id"] for s in st1["sessions"]], [root_cid])
            self.assertEqual(len(st1["agents"]), 3)
            by_cid = {a["conversation_id"]: a for a in st1["agents"]}
            self.assertEqual(by_cid[root_cid]["depth"], 0)
            self.assertEqual(by_cid[root_cid]["source"], "root")
            self.assertEqual(by_cid[root_cid]["children_count"], 1)
            self.assertEqual(by_cid[wf1_cid]["depth"], 1)
            self.assertEqual(by_cid[wf1_cid]["source"], "workflow")
            self.assertEqual(by_cid[wf1_cid]["spawn_step"], 3)
            self.assertEqual(by_cid[wf1_cid]["parent_id"], by_cid[root_cid]["id"])
            self.assertEqual(by_cid[wf1_cid]["children_count"], 1)
            self.assertEqual(by_cid[wf1_cid]["status"], "active")
            self.assertEqual(by_cid[wf2_cid]["depth"], 2)
            self.assertEqual(by_cid[wf2_cid]["parent_id"], by_cid[wf1_cid]["id"])
            self.assertEqual(by_cid[wf2_cid]["parent_name"], "Builder W1")
            self.assertEqual(by_cid[wf2_cid]["status"], "active")

            # Updating depth-2 transcript must invalidate signature and update statuses without re-reading root
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

            # Adding a new message file at depth-1 must also change signature
            (brain / wf1_cid / ".system_generated" / "messages" / "m2.json").write_text(
                json.dumps({"content": "update"}), encoding="utf-8"
            )
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
            (m_home / "data").mkdir(parents=True)
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
            (sg_root / "subagents" / f"{err_cid}.json").write_text(
                json.dumps({"conversationId": err_cid, "state": "SUBAGENT_STATE_ALIVE"}), encoding="utf-8"
            )
            (sg_root / "subagents" / f"{ok_cid}.json").write_text(
                json.dumps({"conversationId": ok_cid, "state": "SUBAGENT_STATE_ALIVE"}), encoding="utf-8"
            )

            st = api.get_live_session_state(
                session_id=root_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            by_cid = {a["conversation_id"]: a for a in st["agents"]}
            self.assertEqual(by_cid[err_cid]["status"], "error")
            self.assertEqual(by_cid[err_cid]["error_steps"], 1)
            self.assertFalse(by_cid[err_cid]["clean_termination"])
            self.assertEqual(by_cid[ok_cid]["status"], "done")
            self.assertTrue(by_cid[ok_cid]["clean_termination"])


class TestMetricsActionsAndAudits(unittest.TestCase):
    def test_dip_cli_actions_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            m_plugin = tmp_path / "plugins" / "gravity-metrics"
            (m_plugin / "scripts").mkdir(parents=True)
            fake_cli = m_plugin / "scripts" / "cli.py"
            fake_cli.write_text(
                "import json, sys\nprint(json.dumps({'ok': True, 'argv': sys.argv[1:]}))\n",
                encoding="utf-8",
            )

            # Fail-closed when metrics module is absent
            missing = api.run_metrics_cli_action(
                "record",
                conversation_id="11111111-2222-3333-4444-555555555555",
                gravity_home=g_home,
                plugin_roots=[tmp_path / "empty-plugins"],
            )
            self.assertFalse(missing["ok"])
            self.assertIn("not installed", missing["message"])

            # Register metrics module in modules.json
            write_modules_registry(
                g_home,
                [{"id": "metrics", "plugin_name": "gravity-metrics", "plugin_dir": str(m_plugin)}],
            )

            cid = "11111111-2222-3333-4444-555555555555"
            res_upd = api.run_metrics_cli_action(
                "update",
                conversation_id=cid,
                label="Wave 1",
                note="Updated note",
                gravity_home=g_home,
                metrics_home=g_home / "metrics",
            )
            self.assertTrue(res_upd["ok"])
            argv = res_upd["result"]["argv"]
            self.assertIn("record", argv)
            self.assertIn("--update-sealed", argv)
            self.assertIn("--json", argv)

            for act in ("update-meta", "ignore", "unignore", "remove"):
                res = api.run_metrics_cli_action(
                    act,
                    target="wave-1",
                    label="New",
                    project="gravity",
                    note="Note",
                    reason="Noise",
                    gravity_home=g_home,
                )
                self.assertTrue(res["ok"], f"Action {act} failed: {res}")
                self.assertEqual(res["result"]["argv"][0], act)

            # Input validation fail-closed
            bad_act = api.run_metrics_cli_action("drop-all", target=cid, gravity_home=g_home)
            self.assertFalse(bad_act["ok"])
            bad_target = api.run_metrics_cli_action("ignore", target="../etc/passwd", gravity_home=g_home)
            self.assertFalse(bad_target["ok"])

    def test_metrics_technical_kpis_workspace_kinds_and_confined_audit_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            m_home = g_home / "metrics"
            (m_home / "data").mkdir(parents=True)

            audits_agents = tmp_path / "gravity-studio" / "audits" / "agents"
            audits_code = tmp_path / "gravity-studio" / "audits" / "code"
            audits_agents.mkdir(parents=True)
            audits_code.mkdir(parents=True)
            (audits_agents / "2026-11-25-ok.md").write_text(
                "# Audit OK\n\nVerdict: PASS\n\nDetails here.\n",
                encoding="utf-8",
            )
            (audits_agents / "_TEMPLATE.md").write_text("# Template\n", encoding="utf-8")
            (audits_code / "secret.md").write_text("# Code Audit\n", encoding="utf-8")
            (tmp_path / "outside.md").write_text("# Outside\n", encoding="utf-8")

            records = [
                {
                    "conversation_id": "11111111-0000-0000-0000-000000000001",
                    "label": "sess-1",
                    "project": "gravity-studio",
                    "input_tokens": 1000,
                    "cache_read_tokens": 9000,
                    "output_tokens": 500,
                    "total_tokens": 10500,
                    "max_context_tokens": 150000,
                    "thinking_est_tokens": 350,
                    "compaction_count": 1,
                    "latency_p95_ms": 2400.0,
                    "latency_avg_ms": 900.0,
                    "workspace_share_pct": {"gravity-studio": 25.0, "gravity": 75.0},
                    "workspace_kinds": {"gravity-studio": "atelier", "gravity": "code"},
                    "cost_usd": 0.4,
                }
            ]
            _write_jsonl(m_home / "data" / "history.jsonl", records)

            state = api.get_metrics_state(
                gravity_home=g_home,
                metrics_home=m_home,
                audits_dirs=[audits_agents, audits_code],
            )
            kpis = state["kpis"]
            self.assertEqual(kpis["useful_tokens"], 1500)
            self.assertEqual(kpis["thinking_est_tokens"], 350)
            self.assertEqual(kpis["compaction_count"], 1)
            self.assertEqual(kpis["context_alerts_count"], 1)
            self.assertEqual(kpis["context_critical_count"], 0)
            self.assertEqual(kpis["latency_p95_ms"], 2400.0)
            self.assertEqual(state["workspace_kinds"], {"gravity": "code", "gravity-studio": "atelier"})
            self.assertEqual(state["by_workspace"][0]["workspace"], "gravity")
            self.assertEqual(state["by_workspace"][0]["kind"], "code")

            aid = state["audits"][0]["audit_id"]
            read_ok = api.read_metrics_audit(aid, audits_dirs=[audits_agents])
            self.assertTrue(read_ok["found"])
            self.assertIn("Details here.", read_ok["content"])

            self.assertFalse(api.read_metrics_audit("../outside.md", audits_dirs=[audits_agents])["found"])
            self.assertFalse(api.read_metrics_audit("_TEMPLATE.md", audits_dirs=[audits_agents])["found"])
            self.assertFalse(
                api.read_metrics_audit(str(audits_code / "secret.md"), audits_dirs=[audits_agents])["found"]
            )

            summary = api.build_initial_summary(
                view="live",
                gravity_home=g_home,
                metrics_home=m_home,
                brain_dir=tmp_path / "missing-brain",
                audits_dirs=[audits_agents],
            )
            self.assertIn("Live:", summary)
            self.assertIn("tok. utiles", summary)

    def test_get_session_detail_preserves_over_30_agents_under_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            m_home = g_home / "metrics"
            (m_home / "data").mkdir(parents=True)
            (m_home / "reports").mkdir(parents=True)

            cid = "77777777-1111-2222-3333-444444444444"
            slug = "heavy-session"
            _write_jsonl(
                m_home / "data" / "history.jsonl",
                [{"conversation_id": cid, "label": "heavy-session", "detail_slug": slug, "project": "gravity"}],
            )
            heavy_agents = [
                {
                    "id": f"agent-{idx:03d}",
                    "role": "builder",
                    "by_model": {"gemini-4-hydrogen-high": {"calls": 3}},
                    "tool_calls_total": 12,
                    "step_latencies_ms": [float(i) for i in range(400)],
                    "error_reasons": {"minor_warn": 1, "detail": "x" * 1500},
                    "tool_calls_by_name": {f"tool_{j}": j for j in range(60)},
                    "cost_usd_projection": {"2027": {"total": 0.123, "notes": "p" * 800}},
                    "transcript_path": f"/brain/{cid}/agent-{idx}/transcript.jsonl",
                }
                for idx in range(85)
            ]
            report_payload = {"conversation_id": cid, "agents": heavy_agents}
            self.assertGreater(len(json.dumps(report_payload).encode("utf-8")), 450_000)
            (m_home / "reports" / f"{slug}.json").write_text(json.dumps(report_payload), encoding="utf-8")

            det = api.get_session_detail(slug, gravity_home=g_home, metrics_home=m_home)
            self.assertTrue(det["found"])
            agents_out = det["detail"]["agents"]
            self.assertEqual(len(agents_out), 85)
            self.assertLess(len(json.dumps(det, ensure_ascii=False).encode("utf-8")), 450_000)
            self.assertNotIn("step_latencies_ms", agents_out[0])
            self.assertEqual(agents_out[0]["tool_calls_total"], 12)
            self.assertIn("by_model", agents_out[0])

    def test_workflow_transcript_ignores_tool_outputs_and_non_system_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            m_home = g_home / "metrics"
            wf_home = g_home / "workflow"
            brain = tmp_path / "brain"
            (m_home / "data").mkdir(parents=True)
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
                    {
                        "step_index": 0,
                        "type": "USER_INPUT",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:00Z",
                        "content": f"- [agent:builder] User paste: done ({fake_user_cid})",
                    },
                    {
                        "step_index": 1,
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:01Z",
                        "thinking": f"- [agent:reviewer] Thought: done ({fake_planner_cid})",
                    },
                    {
                        "step_index": 2,
                        "type": "GENERIC",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:02Z",
                        "content": (
                            "Created At: 2026-11-25T10:00:02Z\n"
                            "Showing lines 1-3 of 3\n"
                            f"1: - [agent:builder] Read file leak: done ({fake_read_cid})"
                        ),
                    },
                    {
                        "step_index": 3,
                        "type": "GENERIC",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:03Z",
                        "content": (
                            "Created At: 2026-11-25T10:00:03Z\n"
                            "Command exited with code 0.\n\n"
                            "Command output:\n"
                            f"- [agent:reviewer] Shell grep leak: error ({fake_cmd_cid})"
                        ),
                    },
                    {
                        "step_index": 4,
                        "type": "GENERIC",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:04Z",
                        "content": (
                            "Created At: 2026-11-25T10:00:04Z\n"
                            f"Task: {root_cid}/task-4\n"
                            "Logs:\n"
                            f"- [agent:builder] Real Generic WF: done ({real_generic_cid})\n"
                            "Output:\nok"
                        ),
                    },
                    {
                        "step_index": 5,
                        "type": "SYSTEM_MESSAGE",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:05Z",
                        "content": (
                            "<SYSTEM_MESSAGE>\n"
                            f"Task id {root_cid}/task-5 finished.\n"
                            f"- [agent:reviewer] Real System WF: done ({real_sys_cid})\n"
                            "</SYSTEM_MESSAGE>"
                        ),
                    },
                    {
                        "step_index": 6,
                        "type": "PLANNER_RESPONSE",
                        "status": "DONE",
                        "created_at": "2026-11-25T10:00:06Z",
                    },
                ],
            )
            # Corrupt non-dict subagents/*.json must be ignored identically across discovery & tree signature
            (brain / root_cid / ".system_generated" / "subagents").mkdir(parents=True)
            (brain / root_cid / ".system_generated" / "subagents" / f"{fake_read_cid}.json").write_text(
                "[]", encoding="utf-8"
            )
            for child_cid in (fake_read_cid, fake_cmd_cid, fake_planner_cid, fake_user_cid, real_generic_cid, real_sys_cid):
                _write_jsonl(
                    brain / child_cid / ".system_generated" / "logs" / "transcript.jsonl",
                    [{"step_index": 0, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-25T10:00:06Z"}],
                )

            st = api.get_live_session_state(
                session_id=root_cid,
                gravity_home=g_home,
                brain_dir=brain,
                metrics_home=m_home,
                workflow_home=wf_home,
            )
            cids = {a["conversation_id"] for a in st["agents"]}
            self.assertEqual(cids, {root_cid, real_generic_cid, real_sys_cid})
            self.assertEqual(st["summary"]["total_agents"], 3)
            self.assertEqual(st["summary"]["done_agents"], 3)
            self.assertEqual(st["summary"]["error_agents"], 0)


if __name__ == "__main__":
    unittest.main()

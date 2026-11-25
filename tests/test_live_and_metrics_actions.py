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
            with tpath.open("a", encoding="utf-8") as fh:
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
            cids = {s["conversation_id"] for s in st["sessions"]}
            self.assertEqual(cids, {root_cid, read_json_cid})
            self.assertGreater(len(live_provider._BRIDGE_SNIFF_CACHE), 0)
            self.assertGreater(len(live_provider._WF_CHILD_CACHE), 0)

            # Appending to root transcript must only add extra_line bytes to bytes_read
            bytes_before = live_provider.get_live_cache_stats()["bytes_read"]
            tpath = brain / root_cid / ".system_generated" / "logs" / "transcript.jsonl"
            extra = json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "status": "DONE", "input_tokens": 10}) + "\n"
            with tpath.open("a", encoding="utf-8") as fh:
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

            # When fresh_cid exists, archived & stale (uncaptured) are filtered out; active_capture is kept
            st1 = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertEqual({s["conversation_id"] for s in st1["sessions"]}, {fresh_cid, cap_stale_cid})
            self.assertFalse(st1["sessions"][0]["archived"])

            # Explicitly requesting archived session keeps it and marks archived=True
            st_exp = api.get_live_session_state(
                session_id=arch_cid, gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            by_cid = {s["conversation_id"]: s for s in st_exp["sessions"]}
            self.assertIn(arch_cid, by_cid)
            self.assertTrue(by_cid[arch_cid]["archived"])

            # Make fresh_cid stale too -> fallback keeps up to 3 most recent roots (+ active_captures)
            os.utime(brain / fresh_cid / ".system_generated" / "logs" / "transcript.jsonl", ns=(old_ns, old_ns))
            os.utime(brain / fresh_cid, ns=(old_ns, old_ns))
            st_fb = api.get_live_session_state(
                gravity_home=g_home, brain_dir=brain, metrics_home=m_home, workflow_home=wf_home
            )
            self.assertGreaterEqual(len(st_fb["sessions"]), 3)
            self.assertLessEqual(len(st_fb["sessions"]), 4)
            self.assertTrue(any(s["archived"] for s in st_fb["sessions"]))


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


if __name__ == "__main__":
    unittest.main()

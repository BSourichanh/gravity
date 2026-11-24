"""Isolated unit tests for strict pending_sessions filtering in metrics_provider."""

from __future__ import annotations

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

from dashboard.providers import metrics_provider  # noqa: E402


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


def _create_bridge_db(
    db_path: Path,
    *,
    threads: list[tuple[str, str | None, str | None]] = (),
    jobs: list[tuple[str, str, str, str, str | None, str | None]] = (),
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                from_workspace TEXT NOT NULL DEFAULT 'gravity-studio',
                to_workspace TEXT NOT NULL DEFAULT 'gravity',
                msg_type TEXT NOT NULL DEFAULT 'handoff',
                subject TEXT NOT NULL DEFAULT 'Subject',
                status TEXT NOT NULL DEFAULT 'open',
                target_conversation_id TEXT,
                caller_conversation_id TEXT,
                created_at TEXT NOT NULL DEFAULT '2026-11-24T10:00:00Z',
                updated_at TEXT NOT NULL DEFAULT '2026-11-24T10:00:00Z'
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                message_id INTEGER NOT NULL DEFAULT 1,
                target_workspace TEXT NOT NULL DEFAULT 'gravity',
                action TEXT NOT NULL,
                direction TEXT NOT NULL DEFAULT 'outbound',
                target_conversation_id TEXT,
                caller_conversation_id TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at TEXT NOT NULL DEFAULT '2026-11-24T10:00:00Z'
            );
            """
        )
        if threads:
            conn.executemany(
                "INSERT INTO threads (id, caller_conversation_id, target_conversation_id) VALUES (?, ?, ?)",
                threads,
            )
        if jobs:
            conn.executemany(
                """
                INSERT INTO jobs (
                    id, thread_id, action, direction, target_conversation_id, caller_conversation_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                jobs,
            )
        conn.commit()
    finally:
        conn.close()


class TestMetricsProviderPendingStrict(unittest.TestCase):
    def test_derive_pending_excludes_plain_session_meta_worktrees_and_bridge_targets(self) -> None:
        session_meta = {
            "cid-consultative": {
                "cwd": "/home/user/Documents/Github/gravity",
                "project": "gravity",
                "started_at": "2026-11-24T08:00:00Z",
                "updated_at": "2026-11-24T08:05:00Z",
            },
            "cid-captured": {
                "cwd": "/home/user/Documents/Github/gravity",
                "project": "Gravity",
                "started_at": "2026-11-24T09:00:00Z",
                "updated_at": "2026-11-24T09:30:00Z",
            },
            "cid-bridge-caller": {
                "cwd": "/home/user/Documents/Github/gravity-studio",
                "project": "gravity-studio",
                "started_at": "2026-11-24T10:00:00Z",
                "updated_at": "2026-11-24T10:15:00Z",
            },
            "cid-bridge-child": {
                "cwd": "/home/user/Documents/Github/gravity",
                "project": "gravity",
                "updated_at": "2026-11-24T10:20:00Z",
            },
            "cid-wt-posix": {
                "cwd": "/home/user/.gemini/antigravity/worktrees/gravity/feat-x",
                "project": "gravity",
                "updated_at": "2026-11-24T10:25:00Z",
            },
            "cid-wt-win": {
                "cwd": r"C:\Users\dev\.gemini\antigravity\worktrees\gravity\feat-y",
                "project": "gravity",
                "updated_at": "2026-11-24T10:26:00Z",
            },
            "cid-wt-short": {
                "cwd": r"D:\repos\worktrees\sub-1",
                "project": "gravity",
                "updated_at": "2026-11-24T10:27:00Z",
            },
            "cid-wt-captured": {
                "cwd": "/home/user/.gemini/antigravity/worktrees/gravity/explicit-capture",
                "project": "gravity",
                "updated_at": "2026-11-24T10:28:00Z",
            },
        }
        active_captures = {
            "cid-captured": {"label": "cap-session", "start_step": 1, "updated_at": "2026-11-24T09:35:00Z"},
            "cid-bridge-child": {"label": "child-cap", "start_step": 1},
            "cid-wt-captured": {"label": "wt-cap", "start_step": 2},
        }
        ignored_map = {
            "cid-wt-short": {"ignored_at": "2026-11-24T10:00:00Z", "reason": "noise"},
            "cid-ignored-keep": {"ignored_at": "2026-11-24T10:01:00Z", "reason": "manual"},
        }
        records = [
            {"conversation_id": "cid-archived", "status": "archived", "label": "done"},
            {"conversation_id": "cid-wt-posix", "status": "active", "label": "wt-active"},
        ]
        pending, ignored = metrics_provider._derive_pending_states_ro(
            records=records,
            active_captures=active_captures,
            ignored_map=ignored_map,
            session_meta=session_meta,
            bridge_callers={"cid-bridge-caller", "cid-wt-win", "cid-archived", "cid-bridge-child"},
            bridge_targets={"cid-bridge-child"},
        )

        self.assertEqual(
            [p["conversation_id"] for p in pending],
            ["cid-wt-captured", "cid-bridge-caller", "cid-captured"],
        )
        by_cid = {p["conversation_id"]: p for p in pending}
        self.assertEqual(by_cid["cid-bridge-caller"]["project"], "gravity-studio")
        self.assertEqual(by_cid["cid-bridge-caller"]["cwd"], "/home/user/Documents/Github/gravity-studio")
        self.assertEqual(by_cid["cid-bridge-caller"]["started_at"], "2026-11-24T10:00:00Z")
        self.assertEqual(by_cid["cid-captured"]["project"], "Gravity")
        self.assertEqual([i["conversation_id"] for i in ignored], ["cid-ignored-keep"])

    def test_resolve_bridge_db_path_precedence_and_roles_tolerant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()

            with mock.patch.object(Path, "home", return_value=fake_home):
                self.assertEqual(
                    metrics_provider._resolve_bridge_db_path(),
                    (fake_home / ".gemini" / "gravity" / "bridge" / "bridge.db").resolve(),
                )
                with mock.patch.dict(os.environ, {"GRAVITY_HOME": str(tmp_path / "g-home")}):
                    self.assertEqual(
                        metrics_provider._resolve_bridge_db_path(),
                        (tmp_path / "g-home" / "bridge" / "bridge.db").resolve(),
                    )
                    with mock.patch.dict(os.environ, {"GRAVITY_BRIDGE_HOME": str(tmp_path / "b-home")}):
                        self.assertEqual(
                            metrics_provider._resolve_bridge_db_path(),
                            (tmp_path / "b-home" / "bridge.db").resolve(),
                        )

            # Missing DB -> silent empty sets
            warnings: list[str] = []
            self.assertEqual(
                metrics_provider._load_bridge_roles_ro(tmp_path / "missing" / "bridge.db", warnings),
                (set(), set()),
            )
            self.assertEqual(warnings, [])

            # Corrupt DB -> warning + empty sets
            corrupt_db = tmp_path / "corrupt.db"
            corrupt_db.write_text("not-a-sqlite-file", encoding="utf-8")
            self.assertEqual(
                metrics_provider._load_bridge_roles_ro(corrupt_db, warnings),
                (set(), set()),
            )
            self.assertTrue(warnings)

            # Legacy v0.1.0 schema without caller_conversation_id or jobs.direction
            legacy_db = tmp_path / "legacy-v010.db"
            conn = sqlite3.connect(str(legacy_db))
            try:
                conn.executescript(
                    """
                    CREATE TABLE threads (id TEXT PRIMARY KEY, target_conversation_id TEXT);
                    CREATE TABLE jobs (id TEXT PRIMARY KEY, action TEXT, target_conversation_id TEXT);
                    INSERT INTO threads VALUES ('thr-1', 'child-t1');
                    INSERT INTO jobs VALUES ('j-1', 'new_conversation', 'child-j1');
                    INSERT INTO jobs VALUES ('j-2', 'send_message', 'root-caller');
                    """
                )
                conn.commit()
            finally:
                conn.close()

            legacy_warnings: list[str] = []
            callers, targets = metrics_provider._load_bridge_roles_ro(legacy_db, legacy_warnings)
            self.assertEqual(legacy_warnings, [])
            self.assertEqual(callers, set())
            self.assertEqual(targets, {"child-t1", "child-j1"})
            self.assertNotIn("root-caller", targets)

    def test_get_metrics_state_bridge_filtering_audits_and_cache_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, _clean_env(), clear=True):
            tmp_path = Path(tmp)
            g_home = tmp_path / "gravity-home"
            m_home = g_home / "metrics"
            b_home = g_home / "bridge"
            (m_home / "data").mkdir(parents=True)
            b_home.mkdir(parents=True)

            ws_main = tmp_path / "ws-main"
            (ws_main / "audits" / "agents").mkdir(parents=True)
            (ws_main / "audits" / "agents" / "2026-11-24-check.md").write_text(
                "# Agent Audit\n\nVerdict: PASS\n",
                encoding="utf-8",
            )

            bridge_db = b_home / "bridge.db"
            _create_bridge_db(
                bridge_db,
                threads=[
                    ("thr-1", "cid-root-caller", "cid-child-1"),
                    ("thr-2", "cid-child-1", "cid-grandchild"),
                ],
                jobs=[
                    ("job-out", "thr-1", "new_conversation", "outbound", "cid-child-1", "cid-job-caller"),
                    ("job-cb", "thr-1", "send_message", "callback", "cid-root-caller", "cid-child-1"),
                    ("job-send", "thr-1", "send_message", "outbound", "cid-root-caller", None),
                ],
            )

            (m_home / "data" / "history.jsonl").write_text(
                json.dumps({"conversation_id": "cid-archived", "status": "archived", "label": "done"}) + "\n",
                encoding="utf-8",
            )
            (m_home / "active_captures.json").write_text(
                json.dumps({"schema_version": 1, "captures": {"cid-active": {"label": "active-cap"}}}),
                encoding="utf-8",
            )
            (m_home / "session_meta.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sessions": {
                            "cid-root-caller": {
                                "cwd": str(ws_main),
                                "project": "gravity-studio",
                                "started_at": "2026-11-24T11:00:00Z",
                                "updated_at": "2026-11-24T11:10:00Z",
                            },
                            "cid-child-1": {
                                "cwd": str(ws_main),
                                "project": "gravity",
                                "updated_at": "2026-11-24T11:15:00Z",
                            },
                            "cid-grandchild": {
                                "cwd": str(ws_main),
                                "project": "gravity",
                                "updated_at": "2026-11-24T11:16:00Z",
                            },
                            "cid-consultative": {
                                "cwd": str(ws_main),
                                "project": "gravity",
                                "updated_at": "2026-11-24T11:20:00Z",
                            },
                            "cid-wt": {
                                "cwd": str(tmp_path / ".gemini" / "antigravity" / "worktrees" / "gravity" / "wt1"),
                                "project": "gravity",
                            },
                            "cid-active": {
                                "cwd": str(ws_main),
                                "project": "gravity",
                                "updated_at": "2026-11-24T11:25:00Z",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            state1 = metrics_provider.get_metrics_state(gravity_home=g_home, metrics_home=m_home)
            self.assertTrue(state1["changed"])
            pending_cids = {item["conversation_id"] for item in state1["pending_sessions"]}
            self.assertEqual(pending_cids, {"cid-active", "cid-root-caller", "cid-job-caller"})
            self.assertNotIn("cid-child-1", pending_cids)
            self.assertNotIn("cid-grandchild", pending_cids)
            self.assertNotIn("cid-consultative", pending_cids)
            self.assertNotIn("cid-wt", pending_cids)
            # Audits discovery still uses session_meta.json
            self.assertEqual(len(state1["audits"]), 1)

            unchanged = metrics_provider.get_metrics_state(
                since_signature=state1["signature"],
                gravity_home=g_home,
                metrics_home=m_home,
            )
            self.assertTrue(unchanged["unchanged"])

            # Modifying bridge.db must invalidate since_signature immediately
            conn = sqlite3.connect(str(bridge_db))
            try:
                conn.execute(
                    "INSERT INTO threads (id, caller_conversation_id, target_conversation_id) VALUES (?, ?, ?)",
                    ("thr-3", "cid-new-caller", "cid-new-child"),
                )
                conn.commit()
            finally:
                conn.close()

            state2 = metrics_provider.get_metrics_state(
                since_signature=state1["signature"],
                gravity_home=g_home,
                metrics_home=m_home,
            )
            self.assertTrue(state2["changed"])
            self.assertNotEqual(state2["signature"], state1["signature"])
            pending_cids_2 = {item["conversation_id"] for item in state2["pending_sessions"]}
            self.assertIn("cid-new-caller", pending_cids_2)
            self.assertNotIn("cid-new-child", pending_cids_2)


if __name__ == "__main__":
    unittest.main()

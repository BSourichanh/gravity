"""Isolated unit tests for gravity_shared.transcript_reader."""

from __future__ import annotations

from datetime import timezone
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_ROOT = REPO_ROOT / "shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from gravity_shared.transcript_reader import (  # noqa: E402
    current_turn_start_step,
    discover_known_repos,
    extract_shell_nonzero_code,
    is_worktree_path,
    next_step_index,
    normalize_user_prompt,
    normalize_worktree_path,
    parse_iso_ts,
    parse_transcript_steps,
    read_jsonl_incremental,
    strip_file_uri,
)


def _write_bytes(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _append_bytes(path: Path, data: bytes) -> None:
    with path.open("ab") as fh:
        fh.write(data)


class TestReadJsonlIncremental(unittest.TestCase):
    def test_missing_and_directory_return_fresh_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache: dict[str, dict[str, object]] = {}
            self.assertEqual(
                read_jsonl_incremental(root / "missing.jsonl", cache, list, lambda s, o: s.append(o)),
                [],
            )
            self.assertEqual(cache, {})
            self.assertEqual(
                read_jsonl_incremental(root, cache, list, lambda s, o: s.append(o)),
                [],
            )
            self.assertEqual(cache, {})

    def test_append_partial_line_and_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "transcript.jsonl"
            cache: dict[str, dict[str, object]] = {}
            stats: dict[str, int] = {}
            seen_steps: list[int] = []

            def _apply(state: list[int], obj: dict[str, object]) -> None:
                val = int(obj["step_index"])
                state.append(val)
                seen_steps.append(val)

            # First write: 1 complete line + partial second line (no newline)
            _write_bytes(tpath, b'\xef\xbb\xbf{"step_index": 0}\n{"step_index": 1')
            res1 = read_jsonl_incremental(tpath, cache, list, _apply, stats=stats)
            self.assertEqual(res1, [0])
            self.assertEqual(seen_steps, [0])
            self.assertEqual(stats.get("full_reads"), 1)

            # Re-read unchanged -> cache hit, no extra read
            res_hit = read_jsonl_incremental(tpath, cache, list, _apply, stats=stats)
            self.assertEqual(res_hit, [0])
            self.assertEqual(stats.get("cache_hits"), 1)
            self.assertEqual(seen_steps, [0])

            # Complete partial line + add another line
            _append_bytes(tpath, b'}\n{"step_index": 2}\n')
            res2 = read_jsonl_incremental(tpath, cache, list, _apply, stats=stats)
            self.assertEqual(res2, [0, 1, 2])
            self.assertEqual(seen_steps, [0, 1, 2])
            self.assertEqual(stats.get("incremental_reads"), 1)

    def test_corrupted_non_dict_and_truncation_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "transcript.jsonl"
            cache: dict[str, dict[str, object]] = {}

            _write_bytes(
                tpath,
                b'{"step_index": 1}\n'
                b"{not-valid-json\n"
                b"[1, 2, 3]\n"
                b"\n"
                b'{"step_index": 2}\n',
            )
            res1 = read_jsonl_incremental(
                tpath, cache, list, lambda s, o: s.append(o["step_index"])
            )
            self.assertEqual(res1, [1, 2])

            # Truncate to smaller size -> state must reset from offset 0
            _write_bytes(tpath, b'{"step_index": 9}\n')
            res2 = read_jsonl_incremental(
                tpath, cache, list, lambda s, o: s.append(o["step_index"])
            )
            self.assertEqual(res2, [9])

    def test_rotation_new_inode_and_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1 = root / "a.jsonl"
            p2 = root / "b.jsonl"
            p_rot = root / "a.new.jsonl"
            _write_bytes(p1, b'{"n": 1}\n{"n": 2}\n')
            _write_bytes(p2, b'{"n": 10}\n')
            cache: dict[str, dict[str, object]] = {}

            read_jsonl_incremental(
                p1, cache, list, lambda s, o: s.append(o["n"]), max_cache_entries=1
            )
            self.assertEqual(len(cache), 1)
            read_jsonl_incremental(
                p2, cache, list, lambda s, o: s.append(o["n"]), max_cache_entries=1
            )
            self.assertEqual(len(cache), 1)
            self.assertIn(os.path.abspath(p2), cache)

            # Rotate p1 with a new file (new inode) even if larger than previous offset
            read_jsonl_incremental(p1, cache, list, lambda s, o: s.append(o["n"]))
            _write_bytes(p_rot, b'{"n": 99}\n{"n": 100}\n{"n": 101}\n')
            os.replace(p_rot, p1)
            res_rot = read_jsonl_incremental(p1, cache, list, lambda s, o: s.append(o["n"]))
            self.assertEqual(res_rot, [99, 100, 101])

    def test_rejects_posix_symlink_and_python310_ntfs_junction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.jsonl"
            link = root / "link.jsonl"
            _write_bytes(real, b'{"step_index": 0}\n')
            os.symlink(real, link)

            cache: dict[str, dict[str, object]] = {}
            res_sym = read_jsonl_incremental(link, cache, list, lambda s, o: s.append(o))
            self.assertEqual(res_sym, [])
            self.assertEqual(cache, {})

            # Simulate Windows Python 3.10 NTFS junction (no Path.is_junction / os.path.isjunction)
            junc_stat = types.SimpleNamespace(
                st_mode=stat.S_IFREG | 0o644,
                st_ino=12345,
                st_mtime_ns=999,
                st_size=20,
                st_file_attributes=0x0400,
                st_reparse_tag=0xA0000003,
            )
            with mock.patch("gravity_shared.path_safety.os.name", "nt"), mock.patch.object(
                Path, "is_junction", None, create=True
            ), mock.patch.object(os.path, "isjunction", None, create=True), mock.patch(
                "gravity_shared.path_safety.os.lstat", return_value=junc_stat
            ):
                res_junc = read_jsonl_incremental(real, cache, list, lambda s, o: s.append(o))
                self.assertEqual(res_junc, [])
                self.assertEqual(cache, {})


class TestExtractShellNonzeroCode(unittest.TestCase):
    def test_extracts_header_nonzero_and_ignores_body_and_zero(self) -> None:
        self.assertIsNone(extract_shell_nonzero_code(None))
        self.assertIsNone(extract_shell_nonzero_code(""))
        self.assertIsNone(extract_shell_nonzero_code("Command exited with code 0\nCommand output:\nok"))
        self.assertIsNone(
            extract_shell_nonzero_code(
                "Command exited with code 0\nCommand output:\nCommand exited with code 2\n"
            )
        )
        self.assertIsNone(
            extract_shell_nonzero_code(
                "Showing lines 1-20 of 50\nCommand exited with code 1\n"
            )
        )
        self.assertIsNone(
            extract_shell_nonzero_code(
                "Header note\nShowing lines 1-5 of 10\nCommand exited with code 3\n"
            )
        )
        self.assertIsNone(
            extract_shell_nonzero_code('Quoted text: "Command exited with code 2"')
        )
        self.assertEqual(
            extract_shell_nonzero_code("Command exited with code 2\nCommand output:\nboom"),
            2,
        )
        self.assertEqual(
            extract_shell_nonzero_code("Command exited with code -1\r\nShowing lines 1-2 of 2\r\nerr"),
            -1,
        )
        self.assertEqual(
            extract_shell_nonzero_code("Command exited with code 127"),
            127,
        )


class TestWorktreeNormalization(unittest.TestCase):
    def test_strip_file_uri_and_is_worktree_path(self) -> None:
        self.assertEqual(strip_file_uri(' "file:///workspace/gravity/a.py" '), "/workspace/gravity/a.py")
        self.assertEqual(strip_file_uri("file:///D:/Work/gravity/a.py"), "D:/Work/gravity/a.py")
        self.assertEqual(strip_file_uri("file:///D:/Work/my%20repo/a.py"), "D:/Work/my repo/a.py")
        self.assertEqual(strip_file_uri(None), "")

        self.assertTrue(is_worktree_path("/workspace/.gemini/antigravity/worktrees/gravity-w1/a.py"))
        self.assertTrue(is_worktree_path("~/gravity-worktrees/gravity-metrics-w2/plugin/cli.py"))
        self.assertTrue(is_worktree_path("/workspace/.worktrees/gravity-fix/README.md"))
        self.assertTrue(is_worktree_path("D:\\Work\\worktrees\\gravity-w1"))
        self.assertFalse(is_worktree_path("/workspace/gravity/plugin/core/registry.py"))
        self.assertFalse(is_worktree_path(""))

    def test_normalize_worktree_path_variants(self) -> None:
        self.assertEqual(
            normalize_worktree_path("file:///workspace/.gemini/antigravity/worktrees/gravity-abc123/plugin/a.py"),
            "gravity",
        )
        self.assertEqual(
            normalize_worktree_path("~/gravity-worktrees/gravity-metrics-w2/plugin/metrics/collector.py"),
            "gravity-metrics",
        )
        self.assertEqual(
            normalize_worktree_path("/workspace/.worktrees/gravity-workflow-fix/plugin/hooks/a.py"),
            "gravity-workflow",
        )
        self.assertEqual(
            normalize_worktree_path("D:\\Work\\gravity-worktrees\\gravity-architect-w1\\plugin\\x.py"),
            "gravity-architect",
        )
        self.assertEqual(
            normalize_worktree_path("file:///D:/Work/Github/gravity-workshop/specs/spec1.md"),
            "gravity-workshop",
        )
        self.assertEqual(
            normalize_worktree_path("/workspace/.gemini/antigravity/brain/cid-1/task.md"),
            "",
        )
        self.assertEqual(
            normalize_worktree_path("../gravity-metrics/plugin/cli.py", root_workspace="gravity-workshop"),
            "gravity-metrics",
        )
        self.assertEqual(
            normalize_worktree_path(
                "file:///D:/Work/Github/custom-repo",
                is_workspace_uri=True,
            ),
            "custom-repo",
        )

    def test_discover_known_repos_reads_projects_json_and_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "gravity-workshop"
            sib = root / "custom-sibling"
            ws.mkdir()
            sib.mkdir()
            (ws / "projects.json").write_text(
                json.dumps({"projects": [{"name": "extra-proj", "path": "../extra-dir"}]}),
                encoding="utf-8",
            )
            repos = discover_known_repos("gravity-workshop", ws)
            self.assertIn("gravity", repos)
            self.assertIn("extra-proj", repos)
            self.assertIn("extra-dir", repos)
            self.assertIn("custom-sibling", repos)
            self.assertEqual(
                normalize_worktree_path(
                    str(sib / "src" / "main.py"),
                    root_workspace="gravity-workshop",
                    root_workspace_path=ws,
                    known_repos=repos,
                ),
                "custom-sibling",
            )


class TestTranscriptStepsAndAnchors(unittest.TestCase):
    def test_parse_transcript_steps_window_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "transcript.jsonl"
            lines = [
                json.dumps({"step_index": 0, "type": "USER_INPUT", "content": "hi"}),
                "corrupted-json",
                json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "content": "ok"}),
                json.dumps({"step_index": 2, "type": "USER_INPUT", "content": "next"}),
            ]
            tpath.write_text("\n".join(lines) + "\n", encoding="utf-8")

            all_steps = parse_transcript_steps(tpath)
            self.assertEqual([s["step_index"] for s in all_steps], [0, 1, 2])

            window = parse_transcript_steps(tpath, start_line_idx=1, end_line_idx=3)
            self.assertEqual([s["step_index"] for s in window], [1])

            cache: dict[str, dict[str, object]] = {}
            cached_steps = parse_transcript_steps(tpath, cache=cache)
            self.assertEqual(len(cached_steps), 3)
            self.assertEqual(len(cache), 1)

            link = Path(tmp) / "sym.jsonl"
            os.symlink(tpath, link)
            self.assertEqual(parse_transcript_steps(link), [])

    def test_next_step_index_and_current_turn_start_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "transcript.jsonl"
            self.assertEqual(next_step_index(tpath), 0)
            self.assertEqual(current_turn_start_step(tpath), 0)

            rows = [
                {"step_index": 0, "type": "USER_INPUT", "content": "first"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "ans1"},
                {
                    "step_index": 4,
                    "type": "USER_INPUT",
                    "content": (
                        "<USER_REQUEST>/gravity-architect status</USER_REQUEST>"
                        "<ADDITIONAL_METADATA>ignored</ADDITIONAL_METADATA>"
                    ),
                },
                {"step_index": 5, "type": "SYSTEM_MESSAGE", "content": "hook msg"},
            ]
            tpath.write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(next_step_index(tpath), 6)
            self.assertEqual(current_turn_start_step(tpath), 4)

            # Reactive wakeup: PLANNER_RESPONSE arrives after USER_INPUT; expected_prompt still anchors step 4
            rows.append({"step_index": 6, "type": "PLANNER_RESPONSE", "content": "resumed"})
            rows.append({"step_index": True, "type": "USER_INPUT", "content": "bool ignored"})
            tpath.write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(next_step_index(tpath), 7)
            self.assertEqual(current_turn_start_step(tpath), 7)
            self.assertEqual(
                current_turn_start_step(tpath, expected_prompt="/gravity-architect   status"),
                4,
            )

    def test_normalize_user_prompt_and_parse_iso_ts(self) -> None:
        raw = "<USER_REQUEST> hello \n world </USER_REQUEST><USER_SETTINGS_CHANGE>cfg</USER_SETTINGS_CHANGE>"
        self.assertEqual(normalize_user_prompt(raw), "hello world")
        self.assertEqual(normalize_user_prompt(None), "")

        dt_z = parse_iso_ts("2026-11-26T12:00:00Z")
        self.assertIsNotNone(dt_z)
        self.assertEqual(dt_z.tzinfo, timezone.utc)  # type: ignore[union-attr]

        dt_naive = parse_iso_ts("2026-11-26T12:00:00")
        self.assertIsNotNone(dt_naive)
        self.assertEqual(dt_naive.tzinfo, timezone.utc)  # type: ignore[union-attr]
        self.assertIsNone(parse_iso_ts("not-a-timestamp"))


if __name__ == "__main__":
    unittest.main()

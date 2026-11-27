"""Isolated unit tests for shared/gravity_shared/signal_bus.py (100% stdlib)."""

from __future__ import annotations

import ast
import contextlib
import json
import os
from pathlib import Path, PosixPath
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_PARENT = REPO_ROOT / "shared"
if str(SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(SHARED_PARENT))

from gravity_shared import signal_bus as sb  # noqa: E402
from gravity_shared import validator_core as vc  # noqa: E402


class TestSharedSignalBus(unittest.TestCase):
    def test_resolve_signals_dir_env_override_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            explicit = tmp_path / "explicit-home"
            self.assertEqual(sb.resolve_signals_dir(explicit), explicit / "signals")

            env_home = tmp_path / "env-home"
            with mock.patch.dict(os.environ, {"GRAVITY_HOME": str(env_home)}, clear=False):
                self.assertEqual(sb.resolve_signals_dir(), env_home / "signals")

            fake_user_home = tmp_path / "user-home"
            with mock.patch.dict(os.environ, {"GRAVITY_HOME": ""}, clear=False):
                with mock.patch.object(sb, "safe_home_dir", return_value=fake_user_home):
                    self.assertEqual(sb.resolve_signals_dir(), fake_user_home / ".gemini" / "gravity" / "signals")

            with self.assertRaises(ValueError):
                sb.resolve_signals_dir("   ")

    def test_validate_signal_slug_rejects_traversal_and_unsafe_inputs(self) -> None:
        for ok in ("session-metrics", "metrics", "ws-123-abcd", "a"):
            self.assertEqual(sb.validate_signal_slug(ok), ok)

        bad_inputs: list[object] = [
            "",
            None,
            123,
            ".",
            "..",
            "../secret",
            "topic/sub",
            "topic\\sub",
            "bad\x00slug",
            "bad slug",
            " leadingspace",
            "UpperCase",
            "under_score",
            "-leading",
            "trailing-",
            "double--hyphen",
        ]
        for bad in bad_inputs:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    sb.validate_signal_slug(bad)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            for bad_str in ("../escape", "a/b", "a\\b", "bad\x00name"):
                with self.assertRaises(ValueError):
                    sb.publish_signal(bad_str, "ws-1", "metrics", {}, gravity_home=tmp)
                with self.assertRaises(ValueError):
                    sb.read_signal("session-metrics", bad_str, gravity_home=tmp)
                with self.assertRaises(ValueError):
                    sb.list_topic_signals(bad_str, gravity_home=tmp)

    def test_publish_read_and_list_roundtrip_and_utf8_lf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gh = Path(tmp) / "gravity-home"
            payload = {"avg_cache_hit_pct": 81.5, "avg_error_rate_pct": 2.0, "avg_cold_waste_usd": 0.12}
            out_path = sb.publish_signal(
                "session-metrics",
                "demo-ws-1234",
                "metrics",
                payload,
                sample_count=5,
                window_size=5,
                gravity_home=gh,
            )
            self.assertEqual(out_path, gh / "signals" / "session-metrics" / "demo-ws-1234.json")
            raw = out_path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)

            sig = sb.read_signal("session-metrics", "demo-ws-1234", gravity_home=gh)
            self.assertIsNotNone(sig)
            assert sig is not None
            self.assertEqual(sig["schema_version"], 1)
            self.assertEqual(sig["topic"], "session-metrics")
            self.assertEqual(sig["producer"], "metrics")
            self.assertEqual(sig["sample_count"], 5)
            self.assertEqual(sig["window_size"], 5)
            self.assertEqual(sig["payload"], payload)
            self.assertTrue(sig["emitted_at"].endswith("Z"))

            sb.publish_signal(
                "session-metrics",
                "alpha-ws",
                "metrics",
                {"avg_cache_hit_pct": 90.0},
                sample_count=2,
                window_size=5,
                emitted_at="2026-11-26T12:00:00Z",
                gravity_home=gh,
            )
            listed = sb.list_topic_signals("session-metrics", gravity_home=gh)
            self.assertEqual([item["emitted_at"] for item in listed if item["emitted_at"] == "2026-11-26T12:00:00Z"], ["2026-11-26T12:00:00Z"])
            self.assertEqual(len(listed), 2)

            # Argument validation
            for kwargs in (
                {"sample_count": True},
                {"window_size": True},
                {"sample_count": -1},
                {"window_size": -2},
                {"emitted_at": ""},
            ):
                with self.assertRaises(ValueError):
                    sb.publish_signal("session-metrics", "alpha-ws", "metrics", {}, gravity_home=gh, **kwargs)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                sb.publish_signal("session-metrics", "alpha-ws", "", {}, gravity_home=gh)
            with self.assertRaises(ValueError):
                sb.publish_signal("session-metrics", "alpha-ws", "metrics", ["not-dict"], gravity_home=gh)  # type: ignore[arg-type]

    def test_missing_corrupted_bom_and_wrong_schema_return_none_or_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gh = Path(tmp) / "gh"
            self.assertIsNone(sb.read_signal("session-metrics", "missing-ws", gravity_home=gh))
            self.assertEqual(sb.list_topic_signals("session-metrics", gravity_home=gh), [])

            topic_dir = gh / "signals" / "session-metrics"
            topic_dir.mkdir(parents=True)
            (topic_dir / "corrupt.json").write_text("{not-json", encoding="utf-8")
            (topic_dir / "bom.json").write_bytes(
                b"\xef\xbb\xbf"
                + json.dumps(
                    {
                        "schema_version": 1,
                        "topic": "session-metrics",
                        "producer": "metrics",
                        "emitted_at": "2026-11-26T12:00:00Z",
                        "sample_count": 1,
                        "window_size": 5,
                        "payload": {},
                    }
                ).encode("utf-8")
            )
            (topic_dir / "wrong-ver.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "topic": "session-metrics",
                        "producer": "metrics",
                        "emitted_at": "2026-11-26T12:00:00Z",
                        "sample_count": 1,
                        "window_size": 5,
                        "payload": {},
                    }
                ),
                encoding="utf-8",
            )
            (topic_dir / "bool-ver.json").write_text(
                json.dumps(
                    {
                        "schema_version": True,
                        "topic": "session-metrics",
                        "producer": "metrics",
                        "emitted_at": "2026-11-26T12:00:00Z",
                        "sample_count": 1,
                        "window_size": 5,
                        "payload": {},
                    }
                ),
                encoding="utf-8",
            )
            (topic_dir / "wrong-topic.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "topic": "other-topic",
                        "producer": "metrics",
                        "emitted_at": "2026-11-26T12:00:00Z",
                        "sample_count": 1,
                        "window_size": 5,
                        "payload": {},
                    }
                ),
                encoding="utf-8",
            )
            sb.publish_signal("session-metrics", "valid-one", "metrics", {"ok": True}, gravity_home=gh)

            for bad_slug in ("corrupt", "bom", "wrong-ver", "bool-ver", "wrong-topic"):
                self.assertIsNone(sb.read_signal("session-metrics", bad_slug, gravity_home=gh))
            listed = sb.list_topic_signals("session-metrics", gravity_home=gh)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["payload"], {"ok": True})

    def test_posix_symlink_and_mocked_python310_ntfs_junction_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outside = tmp_path / "outside"
            outside.mkdir()
            (outside / "ws-1.json").write_text("{}", encoding="utf-8")

            gh = tmp_path / "gh"
            signals_dir = gh / "signals"
            signals_dir.mkdir(parents=True)
            os.symlink(outside, signals_dir / "session-metrics")

            with self.assertRaises(ValueError):
                sb.publish_signal("session-metrics", "ws-1", "metrics", {}, gravity_home=gh)
            with self.assertRaises(ValueError):
                sb.read_signal("session-metrics", "ws-1", gravity_home=gh)
            with self.assertRaises(ValueError):
                sb.list_topic_signals("session-metrics", gravity_home=gh)

            # File-level symlink inside valid topic directory
            gh2 = tmp_path / "gh2"
            tdir = gh2 / "signals" / "session-metrics"
            tdir.mkdir(parents=True)
            os.symlink(outside / "ws-1.json", tdir / "ws-1.json")
            with self.assertRaises(ValueError):
                sb.read_signal("session-metrics", "ws-1", gravity_home=gh2)
            with self.assertRaises(ValueError):
                sb.list_topic_signals("session-metrics", gravity_home=gh2)

            # Mocked Python 3.10 Windows NTFS junction (is_junction absent)
            gh3 = tmp_path / "gh3"
            j_topic = gh3 / "signals" / "session-metrics"
            j_topic.mkdir(parents=True)
            mount_stat = types.SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o755,
                st_file_attributes=0x0400,
                st_reparse_tag=0xA0000003,
            )
            real_lstat = os.lstat

            def fake_lstat(path_arg: object, *args: object, **kwargs: object) -> object:
                if os.path.abspath(os.fspath(path_arg)) == os.path.abspath(os.fspath(j_topic)):  # type: ignore[arg-type]
                    return mount_stat
                return real_lstat(path_arg, *args, **kwargs)  # type: ignore[arg-type]

            path_cls = PosixPath if os.sep == "/" else Path
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch("gravity_shared.path_safety.os.name", "nt"))
                if os.sep == "/":
                    stack.enter_context(mock.patch("gravity_shared.path_safety.Path", PosixPath))
                    stack.enter_context(mock.patch("gravity_shared.atomic_io.Path", PosixPath))
                    stack.enter_context(mock.patch("gravity_shared.file_lock.Path", PosixPath))
                stack.enter_context(mock.patch.object(path_cls, "is_junction", None, create=True))
                stack.enter_context(mock.patch.object(os.path, "isjunction", None, create=True))
                stack.enter_context(mock.patch("gravity_shared.path_safety.os.lstat", side_effect=fake_lstat))
                with self.assertRaises(ValueError):
                    sb.read_signal("session-metrics", "ws-1", gravity_home=gh3)
                with self.assertRaises(ValueError):
                    sb.publish_signal("session-metrics", "ws-1", "metrics", {}, gravity_home=gh3)
                with self.assertRaises(ValueError):
                    sb.list_topic_signals("session-metrics", gravity_home=gh3)

    def test_locked_atomic_write_contention_and_concurrent_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gh = Path(tmp) / "gh"
            topic_dir = gh / "signals" / "session-metrics"
            topic_dir.mkdir(parents=True)
            lock_path = topic_dir / ".busy-ws.lock"
            ready_file = Path(tmp) / "ready.flag"
            holder_code = (
                "import fcntl, sys, time; from pathlib import Path, PosixPath; "
                "fh = Path(sys.argv[1]).open('a+b'); fcntl.flock(fh.fileno(), fcntl.LOCK_EX); "
                "Path(sys.argv[2]).write_text('1', encoding='utf-8'); time.sleep(2.0)"
            )
            proc = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", holder_code, str(lock_path), str(ready_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                import time

                for _ in range(100):
                    if ready_file.is_file():
                        break
                    time.sleep(0.02)
                self.assertTrue(ready_file.is_file())
                with self.assertRaises(TimeoutError):
                    sb.publish_signal(
                        "session-metrics",
                        "busy-ws",
                        "metrics",
                        {"seq": 1},
                        gravity_home=gh,
                        timeout_s=0.05,
                    )
            finally:
                proc.terminate()
                proc.wait(timeout=5)

            # Concurrent writers serialize safely under exclusive_file_lock + atomic_io
            errors: list[Exception] = []

            def worker(idx: int) -> None:
                try:
                    for step in range(5):
                        sb.publish_signal(
                            "session-metrics",
                            "shared-ws",
                            "metrics",
                            {"worker": idx, "step": step},
                            sample_count=step,
                            window_size=5,
                            gravity_home=gh,
                            timeout_s=5.0,
                        )
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=10)
            self.assertEqual(errors, [])
            final_sig = sb.read_signal("session-metrics", "shared-ws", gravity_home=gh)
            self.assertIsNotNone(final_sig)
            assert final_sig is not None
            self.assertEqual(final_sig["schema_version"], 1)

    def test_signal_bus_stdlib_310_relative_imports_and_line_budget(self) -> None:
        sfile = REPO_ROOT / "shared" / "gravity_shared" / "signal_bus.py"
        raw = sfile.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        text = raw.decode("utf-8")
        self.assertIsNone(vc.PERSONAL_PATH_RE.search(text))
        self.assertLess(len(text.splitlines()), 350)

        tree = ast.parse(text, filename=str(sfile))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    self.assertNotEqual(mod, "tomllib")
                    self.assertIn(mod, sys.stdlib_module_names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mod = node.module.split(".")[0]
                self.assertNotEqual(mod, "tomllib")
                self.assertIn(mod, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()

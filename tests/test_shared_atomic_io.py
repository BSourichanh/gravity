"""Isolated unit tests for gravity_shared.atomic_io and package exports."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_ROOT = REPO_ROOT / "shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

import gravity_shared  # noqa: E402
from gravity_shared.atomic_io import (  # noqa: E402
    append_jsonl_atomic,
    is_lock_oserror,
    write_bytes_atomic,
    write_json_atomic,
    write_text_atomic,
)


class _WinOSError(OSError):
    def __init__(self, winerror: int, msg: str = "win lock") -> None:
        super().__init__(errno.EACCES, msg)
        self.winerror = winerror


class TestAtomicIO(unittest.TestCase):
    def test_package_exports(self) -> None:
        self.assertEqual(gravity_shared.__version__, "0.1.0")
        for sym in (
            "write_bytes_atomic",
            "write_text_atomic",
            "write_json_atomic",
            "append_jsonl_atomic",
            "is_lock_oserror",
            "exclusive_file_lock",
            "is_symlink_or_junction",
            "read_stdin_json",
        ):
            self.assertIn(sym, gravity_shared.__all__)
            self.assertTrue(hasattr(gravity_shared, sym))

    def test_is_lock_oserror(self) -> None:
        self.assertTrue(is_lock_oserror(PermissionError("denied")))
        self.assertTrue(is_lock_oserror(OSError(errno.EACCES, "eacces")))
        self.assertTrue(is_lock_oserror(OSError(errno.EPERM, "eperm")))
        self.assertTrue(is_lock_oserror(OSError(errno.EBUSY, "ebusy")))
        for code in (5, 32, 33):
            self.assertTrue(is_lock_oserror(_WinOSError(code)))
        self.assertFalse(is_lock_oserror(OSError(errno.ENOENT, "missing")))
        self.assertFalse(is_lock_oserror(ValueError("not oserror")))

    def test_write_text_atomic_utf8_no_bom_lf_and_no_leftover_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "note.txt"
            write_text_atomic(target, "ligne 1 — éàü\r\nligne 2\rligne 3\r\n")
            raw = target.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r", raw)
            self.assertEqual(raw.decode("utf-8"), "ligne 1 — éàü\nligne 2\nligne 3\n")
            leftovers = [p for p in target.parent.iterdir() if p.name != "note.txt"]
            self.assertEqual(leftovers, [])

    def test_write_bytes_atomic_retries_on_winerror_and_cleans_tmp_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data.bin"
            real_replace = os.replace
            calls = {"n": 0}

            def flaky_replace(src: str, dst: str) -> None:
                calls["n"] += 1
                if calls["n"] < 3:
                    raise _WinOSError(32, "sharing violation")
                real_replace(src, dst)

            with mock.patch("gravity_shared.atomic_io.os.replace", side_effect=flaky_replace), mock.patch(
                "gravity_shared.atomic_io.time.sleep"
            ):
                write_bytes_atomic(target, b"hello", retries=5, base_delay_s=0.001)

            self.assertEqual(calls["n"], 3)
            self.assertEqual(target.read_bytes(), b"hello")
            self.assertEqual(list(Path(tmp).iterdir()), [target])

            with mock.patch(
                "gravity_shared.atomic_io.os.replace",
                side_effect=_WinOSError(33, "lock violation"),
            ), mock.patch("gravity_shared.atomic_io.time.sleep"):
                with self.assertRaises(OSError):
                    write_bytes_atomic(target, b"fail", retries=3, base_delay_s=0.001)

            self.assertEqual(target.read_bytes(), b"hello")
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_write_bytes_atomic_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real_file = Path(tmp) / "real.txt"
            real_file.write_text("keep", encoding="utf-8")
            link_file = Path(tmp) / "link.txt"
            os.symlink(real_file, link_file)
            with self.assertRaises(ValueError):
                write_text_atomic(link_file, "overwrite")
            self.assertEqual(real_file.read_text(encoding="utf-8"), "keep")

    def test_write_json_atomic_formats_with_trailing_lf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cfg.json"
            write_json_atomic(target, {"b": 2, "a": "café"}, sort_keys=True)
            raw = target.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertNotIn(b"\r\n", raw)
            parsed = json.loads(raw.decode("utf-8"))
            self.assertEqual(parsed, {"a": "café", "b": 2})

    def test_append_jsonl_atomic_and_lock_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "events.jsonl"
            append_jsonl_atomic(target, {"id": 1, "msg": "alpha\r\nbeta"})
            append_jsonl_atomic(target, {"id": 2, "msg": "café"})
            lines = target.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0]), {"id": 1, "msg": "alpha\r\nbeta"})
            self.assertEqual(json.loads(lines[1]), {"id": 2, "msg": "café"})

            lock_path = target.with_suffix(".lock")
            with mock.patch(
                "gravity_shared.file_lock.fcntl.flock",
                side_effect=BlockingIOError("locked"),
            ), mock.patch("gravity_shared.file_lock.time.sleep"):
                with self.assertRaises(TimeoutError):
                    append_jsonl_atomic(target, {"id": 3}, lock_path=lock_path, timeout_s=0.01)


if __name__ == "__main__":
    unittest.main()

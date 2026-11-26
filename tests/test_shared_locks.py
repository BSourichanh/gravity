"""Isolated unit tests for gravity_shared.file_lock (POSIX fcntl & mocked Windows msvcrt)."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_ROOT = REPO_ROOT / "shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from gravity_shared.file_lock import exclusive_file_lock  # noqa: E402


class TestFileLock(unittest.TestCase):
    def test_posix_lock_acquire_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "sub" / "state.lock"
            with exclusive_file_lock(lock_path, timeout_s=0.5):
                self.assertTrue(lock_path.is_file())
            with exclusive_file_lock(lock_path, timeout_s=0.5):
                pass

    def test_posix_cross_process_contention_raises_timeout_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "busy.lock"
            ready_file = Path(tmp) / "ready.flag"
            holder_code = (
                "import fcntl, sys, time; "
                "from pathlib import Path; "
                "lp = Path(sys.argv[1]); rf = Path(sys.argv[2]); "
                "fh = lp.open('a+b'); "
                "fcntl.flock(fh.fileno(), fcntl.LOCK_EX); "
                "rf.write_text('locked', encoding='utf-8'); "
                "time.sleep(2.0)"
            )
            proc = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", holder_code, str(lock_path), str(ready_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                for _ in range(100):
                    if ready_file.is_file():
                        break
                    import time

                    time.sleep(0.02)
                self.assertTrue(ready_file.is_file(), "Child process did not acquire lock in time")

                entered = False
                with self.assertRaises(TimeoutError):
                    with exclusive_file_lock(lock_path, timeout_s=0.1, poll_interval_s=0.01):
                        entered = True
                self.assertFalse(entered)
            finally:
                proc.terminate()
                proc.wait(timeout=5)

            with exclusive_file_lock(lock_path, timeout_s=0.5):
                pass

    def test_posix_blocking_io_error_and_unexpected_errno(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "mock.lock"
            with mock.patch(
                "gravity_shared.file_lock.fcntl.flock",
                side_effect=BlockingIOError("busy"),
            ), mock.patch("gravity_shared.file_lock.time.sleep"):
                with self.assertRaises(TimeoutError):
                    with exclusive_file_lock(lock_path, timeout_s=0.01, poll_interval_s=0.002):
                        self.fail("Lock yielded while contended")

            with mock.patch(
                "gravity_shared.file_lock.fcntl.flock",
                side_effect=OSError(errno.EBADF, "bad fd"),
            ):
                with self.assertRaises(OSError) as ctx:
                    with exclusive_file_lock(lock_path, timeout_s=0.5):
                        pass
                self.assertEqual(ctx.exception.errno, errno.EBADF)

    def test_windows_msvcrt_lock_unlock_and_fail_closed_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "win.lock"
            calls: list[tuple[int, int]] = []

            def ok_locking(_fd: int, mode: int, nbytes: int) -> None:
                calls.append((mode, nbytes))

            fake_msvcrt = types.SimpleNamespace(
                LK_NBLCK=2,
                LK_UNLCK=0,
                locking=mock.Mock(side_effect=ok_locking),
            )

            class _BodyError(Exception):
                pass

            with mock.patch("gravity_shared.file_lock.os.name", "nt"), mock.patch(
                "gravity_shared.file_lock.msvcrt", fake_msvcrt
            ):
                with self.assertRaises(_BodyError):
                    with exclusive_file_lock(lock_path, timeout_s=0.5):
                        raise _BodyError("body failure")

            self.assertEqual(calls, [(2, 1), (0, 1)])
            self.assertGreaterEqual(lock_path.stat().st_size, 1)

            contended_msvcrt = types.SimpleNamespace(
                LK_NBLCK=2,
                LK_UNLCK=0,
                locking=mock.Mock(side_effect=OSError(errno.EACCES, "locked")),
            )
            with mock.patch("gravity_shared.file_lock.os.name", "nt"), mock.patch(
                "gravity_shared.file_lock.msvcrt", contended_msvcrt
            ), mock.patch("gravity_shared.file_lock.time.sleep"):
                entered = False
                with self.assertRaises(TimeoutError):
                    with exclusive_file_lock(lock_path, timeout_s=0.02, poll_interval_s=0.005):
                        entered = True
                self.assertFalse(entered)

    def test_rejects_symlink_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real_file = Path(tmp) / "real.lock"
            real_file.write_bytes(b"0")
            link_file = Path(tmp) / "sym.lock"
            os.symlink(real_file, link_file)
            with self.assertRaises(ValueError):
                with exclusive_file_lock(link_file, timeout_s=0.2):
                    pass


if __name__ == "__main__":
    unittest.main()

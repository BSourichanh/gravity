"""Isolated unit tests for gravity_shared.path_safety (POSIX symlinks & Python 3.10+ NTFS junctions)."""

from __future__ import annotations

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

from gravity_shared.path_safety import (  # noqa: E402
    ensure_no_symlink_or_junction_under,
    ensure_safe_dir,
    is_symlink_or_junction,
    is_within_root,
    safe_home_dir,
    unlink_or_rmdir_link,
    validate_rel_member_path,
)


class TestPathSafety(unittest.TestCase):
    def test_symlink_detection_and_unlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_dir = root / "real_dir"
            real_dir.mkdir()
            real_file = real_dir / "file.txt"
            real_file.write_text("ok", encoding="utf-8")

            self.assertFalse(is_symlink_or_junction(real_dir))
            self.assertFalse(is_symlink_or_junction(real_file))

            dir_link = root / "dir_link"
            os.symlink(real_dir, dir_link)
            self.assertTrue(is_symlink_or_junction(dir_link))
            unlink_or_rmdir_link(dir_link)
            self.assertFalse(dir_link.exists())
            self.assertTrue(real_dir.is_dir())

    def test_windows_python310_junction_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cand = Path(tmp) / "junc"
            cand.mkdir()

            # Simulate Python 3.10/3.11 where Path.is_junction / os.path.isjunction are absent
            with mock.patch("gravity_shared.path_safety.os.name", "nt"), mock.patch.object(
                Path, "is_junction", None, create=True
            ), mock.patch.object(os.path, "isjunction", None, create=True):
                mount_stat = types.SimpleNamespace(
                    st_mode=stat.S_IFDIR | 0o755,
                    st_file_attributes=0x0400,
                    st_reparse_tag=0xA0000003,
                )
                with mock.patch("gravity_shared.path_safety.os.lstat", return_value=mount_stat):
                    self.assertTrue(is_symlink_or_junction(cand))

                attr_only_stat = types.SimpleNamespace(
                    st_mode=stat.S_IFDIR | 0o755,
                    st_file_attributes=0x0410,
                    st_reparse_tag=0,
                )
                with mock.patch("gravity_shared.path_safety.os.lstat", return_value=attr_only_stat):
                    self.assertTrue(is_symlink_or_junction(cand))

                cloud_stat = types.SimpleNamespace(
                    st_mode=stat.S_IFDIR | 0o755,
                    st_file_attributes=0x0400,
                    st_reparse_tag=0x9000001A,
                )
                with mock.patch("gravity_shared.path_safety.os.lstat", return_value=cloud_stat), mock.patch(
                    "gravity_shared.path_safety.os.readlink",
                    side_effect=OSError(22, "not a link"),
                ):
                    self.assertFalse(is_symlink_or_junction(cand))

                with mock.patch(
                    "gravity_shared.path_safety.os.lstat",
                    side_effect=OSError(2, "stat error"),
                ), mock.patch(
                    "gravity_shared.path_safety._win_get_file_attributes_reparse",
                    return_value=True,
                ):
                    self.assertTrue(is_symlink_or_junction(cand))

                with mock.patch(
                    "gravity_shared.path_safety.os.lstat",
                    return_value=types.SimpleNamespace(
                        st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0, st_reparse_tag=0
                    ),
                ), mock.patch(
                    "gravity_shared.path_safety._win_get_file_attributes_reparse",
                    return_value=False,
                ), mock.patch(
                    "gravity_shared.path_safety.os.readlink",
                    return_value="D:\\target",
                ):
                    self.assertTrue(is_symlink_or_junction(cand))

    def test_ensure_no_symlink_or_junction_under_and_within_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            sub = root / "a" / "b"
            sub.mkdir(parents=True)

            target = ensure_no_symlink_or_junction_under(root, sub / "item.json")
            self.assertEqual(target, Path(os.path.abspath(sub / "item.json")))
            self.assertTrue(is_within_root(root, sub / "item.json"))
            self.assertTrue(is_within_root(root, root))
            self.assertFalse(is_within_root(root, outside))

            mid_link = root / "a" / "mid_link"
            os.symlink(outside, mid_link)
            with self.assertRaises(ValueError):
                ensure_no_symlink_or_junction_under(root, mid_link / "secret.txt")

            root_link = Path(tmp) / "root_link"
            os.symlink(root, root_link)
            with self.assertRaises(ValueError):
                ensure_no_symlink_or_junction_under(root_link, root_link / "a")

            with self.assertRaises(ValueError):
                ensure_no_symlink_or_junction_under(root, outside / "x.txt")

    def test_ensure_safe_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = ensure_safe_dir(root / "one" / "two", root=root)
            self.assertTrue(created.is_dir())

            reg_file = root / "regular"
            reg_file.write_text("data", encoding="utf-8")
            with self.assertRaises(NotADirectoryError):
                ensure_safe_dir(reg_file)

            link_dir = root / "link_dir"
            os.symlink(created, link_dir)
            with self.assertRaises(ValueError):
                ensure_safe_dir(link_dir)
            self.assertEqual(ensure_safe_dir(link_dir, allow_existing_symlink=True), link_dir)

    def test_validate_rel_member_path(self) -> None:
        self.assertEqual(validate_rel_member_path("core/modules.json"), "core/modules.json")
        self.assertEqual(validate_rel_member_path("core/", allow_dir=True), "core/")

        bad_cases = [
            "",
            "a\x00b",
            "a\\b",
            "D:foo",
            "D:\\foo",
            "/etc/passwd",
            ".",
            "..",
            "../secret",
            "a/../b",
            "a/./b",
            "a//b",
            "core/",
        ]
        for bad in bad_cases:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_rel_member_path(bad)

    def test_safe_home_dir_fallback(self) -> None:
        with mock.patch("gravity_shared.path_safety.Path.home", side_effect=RuntimeError("no home")):
            with mock.patch.dict(os.environ, {"USERPROFILE": "/tmp/fake_win_home"}, clear=True):
                self.assertEqual(safe_home_dir(), Path("/tmp/fake_win_home"))
            with mock.patch.dict(os.environ, {"HOME": "/tmp/fake_posix_home"}, clear=True):
                self.assertEqual(safe_home_dir(), Path("/tmp/fake_posix_home"))
            with mock.patch.dict(
                os.environ,
                {"HOMEDRIVE": "D:", "HOMEPATH": "\\Profile"},
                clear=True,
            ):
                self.assertEqual(safe_home_dir(), Path("D:\\Profile"))
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError):
                    safe_home_dir()


if __name__ == "__main__":
    unittest.main()

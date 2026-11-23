"""Isolated tests for install.py (copy install, --force legacy replacement, rollback, uninstall)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import install as installer  # noqa: E402


def _isolated_env(fake_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    return env


def _run_install(args: list[str], fake_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(REPO_ROOT / "install.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_isolated_env(fake_home),
        timeout=30,
        check=False,
    )


class TestInstall(unittest.TestCase):
    def test_check_and_dry_run_do_not_mutate_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            target = tmp_path / "target" / "gravity"

            p_check = _run_install(["--check", "--target", str(target)], fake_home)
            self.assertEqual(p_check.returncode, 0, msg=p_check.stderr)
            self.assertIn("not installed", p_check.stdout)
            self.assertFalse(target.exists())

            p_dry = _run_install(["--dry-run", "--target", str(target)], fake_home)
            self.assertEqual(p_dry.returncode, 0, msg=p_dry.stderr)
            self.assertIn("[DRY-RUN]", p_dry.stdout)
            self.assertFalse(target.exists())

    def test_install_upgrade_and_uninstall_preserve_gravity_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            gravity_data = fake_home / ".gemini" / "gravity" / "core"
            gravity_data.mkdir(parents=True)
            data_file = gravity_data / "modules.json"
            data_file.write_text('{"keep": true}\n', encoding="utf-8")

            target = tmp_path / "plugins" / "gravity"

            p_inst = _run_install(["--target", str(target)], fake_home)
            self.assertEqual(p_inst.returncode, 0, msg=p_inst.stderr or p_inst.stdout)
            self.assertTrue((target / "plugin.json").is_file())
            self.assertTrue((target / "config" / "module.json").is_file())

            # Second install without --force must fail
            p_dup = _run_install(["--target", str(target)], fake_home)
            self.assertEqual(p_dup.returncode, 1)

            # With --force succeeds
            p_force = _run_install(["--target", str(target), "--force"], fake_home)
            self.assertEqual(p_force.returncode, 0, msg=p_force.stderr or p_force.stdout)

            # Uninstall removes plugin dir and preserves $GRAVITY_HOME data
            p_uninst = _run_install(["--uninstall", "--target", str(target)], fake_home)
            self.assertEqual(p_uninst.returncode, 0, msg=p_uninst.stderr or p_uninst.stdout)
            self.assertFalse(target.exists())
            self.assertTrue(data_file.is_file())

    def test_force_overwrites_legacy_gravity_harness_but_refuses_unrelated_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()

            # Legacy gravity harness install (same name='gravity', no config/module.json)
            legacy_target = tmp_path / "legacy" / "gravity"
            (legacy_target / "hooks").mkdir(parents=True)
            (legacy_target / "plugin.json").write_text(
                json.dumps({"name": "gravity", "version": "0.1.4"}),
                encoding="utf-8",
            )
            (legacy_target / "hooks" / "pre_tool_guard.py").write_text("# legacy\n", encoding="utf-8")

            # Without --force must refuse
            p_no_force = _run_install(["--target", str(legacy_target)], fake_home)
            self.assertEqual(p_no_force.returncode, 1)
            self.assertTrue((legacy_target / "hooks" / "pre_tool_guard.py").is_file())

            # With --force cleanly replaces legacy harness with Gravity Core
            p_force = _run_install(["--target", str(legacy_target), "--force"], fake_home)
            self.assertEqual(p_force.returncode, 0, msg=p_force.stderr or p_force.stdout)
            self.assertFalse((legacy_target / "hooks" / "pre_tool_guard.py").exists())
            self.assertTrue((legacy_target / "config" / "module.json").is_file())

            # Unrelated directory must ALWAYS be refused even with --force or --uninstall
            unrelated = tmp_path / "unrelated"
            unrelated.mkdir()
            (unrelated / "plugin.json").write_text('{"name": "other-plugin"}', encoding="utf-8")
            (unrelated / "keep.txt").write_text("important", encoding="utf-8")

            self.assertEqual(_run_install(["--target", str(unrelated), "--force"], fake_home).returncode, 1)
            self.assertEqual(_run_install(["--uninstall", "--target", str(unrelated)], fake_home).returncode, 1)
            self.assertTrue((unrelated / "keep.txt").is_file())

    def test_workspace_scope_and_validation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            ws = tmp_path / "workspace"
            ws.mkdir()

            p_missing_ws = _run_install(["--scope", "workspace"], fake_home)
            self.assertEqual(p_missing_ws.returncode, 2)

            p_bad_agy = _run_install(["--method", "agy", "--target", str(tmp_path / "x")], fake_home)
            self.assertEqual(p_bad_agy.returncode, 2)

            p_ws = _run_install(["--scope", "workspace", "--workspace", str(ws)], fake_home)
            self.assertEqual(p_ws.returncode, 0, msg=p_ws.stderr or p_ws.stdout)
            self.assertTrue((ws / ".agents" / "plugins" / "gravity" / "plugin.json").is_file())

    def test_windows_inplace_fallback_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "gravity"
            self.assertEqual(
                installer.install_copy(installer.PLUGIN_SOURCE, target, skip_validate=True),
                0,
            )
            stale = target / "stale_old_file.txt"
            stale.write_text("stale", encoding="utf-8")

            # Simulate PermissionError on os.rename -> triggers _sync_directory_in_place
            with mock.patch("install.os.rename", side_effect=PermissionError("locked")):
                rc = installer.install_copy(
                    installer.PLUGIN_SOURCE, target, force=True, skip_validate=True
                )
            self.assertEqual(rc, 0)
            self.assertFalse(stale.exists())
            self.assertTrue((target / "plugin.json").is_file())

            # Simulate shutil.move failure after rename -> restores backup
            real_move = shutil.move

            def fail_staged_move(src: str, dst: str) -> str:
                if ".gravity-stage-" in str(src):
                    raise OSError("disk error")
                return real_move(src, dst)

            with mock.patch("install.shutil.move", side_effect=fail_staged_move):
                rc_fail = installer.install_copy(
                    installer.PLUGIN_SOURCE, target, force=True, skip_validate=True
                )
            self.assertEqual(rc_fail, 1)
            self.assertTrue((target / "plugin.json").is_file())

    def test_unsafe_target_rejected(self) -> None:
        self.assertIsNotNone(installer.is_unsafe_target(Path.home(), installer.PLUGIN_SOURCE))
        self.assertIsNotNone(installer.is_unsafe_target(installer.PLUGIN_SOURCE, installer.PLUGIN_SOURCE))
        self.assertIsNotNone(installer.is_unsafe_target(REPO_ROOT, installer.PLUGIN_SOURCE))

    def test_exec_scripts_and_windows_python_cmd_adaptation(self) -> None:
        self.assertIn("mcp/server.py", installer.EXEC_SCRIPTS)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()

            p_check = _run_install(["--check", "--target", str(tmp_path / "t")], fake_home)
            self.assertEqual(p_check.returncode, 0, msg=p_check.stderr)
            self.assertIn("Real 'python3'", p_check.stdout)

            target_fix = tmp_path / "installed-fix"
            with (
                mock.patch("install.os.name", "nt"),
                mock.patch("install.has_real_python3", return_value=False),
            ):
                rc_fix = installer.install_copy(installer.PLUGIN_SOURCE, target_fix)
            self.assertEqual(rc_fix, 0)
            cfg_fix = json.loads((target_fix / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertIn(cfg_fix["mcpServers"]["dashboard"]["command"], ("python", "py"))

            target_nofix = tmp_path / "installed-nofix"
            p_nofix = _run_install(["--target", str(target_nofix), "--no-fix-python"], fake_home)
            self.assertEqual(p_nofix.returncode, 0, msg=p_nofix.stderr or p_nofix.stdout)
            cfg_nofix = json.loads((target_nofix / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg_nofix["mcpServers"]["dashboard"]["command"], "python3")


if __name__ == "__main__":
    unittest.main()

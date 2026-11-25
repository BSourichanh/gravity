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


def _isolated_env(fake_home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env.pop("GRAVITY_HOME", None)
    if extra:
        env.update(extra)
    return env


def _run_install(
    args: list[str],
    fake_home: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(REPO_ROOT / "install.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_isolated_env(fake_home, extra_env),
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

    def test_strict_flag_check_and_overrides_skip_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            target = tmp_path / "target" / "gravity"

            p_check_strict = _run_install(["--check", "--strict", "--target", str(target)], fake_home)
            self.assertEqual(p_check_strict.returncode, 0, msg=p_check_strict.stderr)
            self.assertIn("Strict validation: PASSED (0 error, 0 warning)", p_check_strict.stdout)
            self.assertFalse(target.exists())

            p_dry_skip = _run_install(
                ["--dry-run", "--skip-validate", "--target", str(target)],
                fake_home,
            )
            self.assertEqual(p_dry_skip.returncode, 0, msg=p_dry_skip.stderr)
            self.assertNotIn("validate.py --strict", p_dry_skip.stdout)
            self.assertFalse(target.exists())

            p_dry_strict = _run_install(
                ["--dry-run", "--strict", "--skip-validate", "--target", str(target)],
                fake_home,
            )
            self.assertEqual(p_dry_strict.returncode, 0, msg=p_dry_strict.stderr)
            self.assertIn(
                "[DRY-RUN] Run validate.py --strict on staged copy before committing",
                p_dry_strict.stdout,
            )
            self.assertFalse(target.exists())

            failed_proc = subprocess.CompletedProcess(
                args=["validate.py"],
                returncode=1,
                stdout="",
                stderr="simulated validation error",
            )
            with mock.patch("install.run_plugin_validation", return_value=failed_proc):
                rc_fail = installer.check_environment(
                    installer.PLUGIN_SOURCE,
                    target,
                    "global",
                    "copy",
                    strict=True,
                )
            self.assertEqual(rc_fail, 1)
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
        self.assertIn("hooks/pre_invocation_gravity.py", installer.EXEC_SCRIPTS)
        self.assertIn("mcp/server.py", installer.EXEC_SCRIPTS)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()

            p_check = _run_install(["--check", "--target", str(tmp_path / "t")], fake_home)
            self.assertEqual(p_check.returncode, 0, msg=p_check.stderr)
            self.assertIn("Real 'python3'", p_check.stdout)

            target_fix = tmp_path / "installed-fix"

            class _FakeNtOs:
                name = "nt"

                def __getattr__(self, attr: str) -> object:
                    return getattr(os, attr)

            env_patch: dict[str, str] = {"USERPROFILE": str(fake_home), "HOME": str(fake_home)}
            if os.name != "nt":
                fake_bin = tmp_path / "fake-bin"
                fake_bin.mkdir()
                (fake_bin / "python").symlink_to(sys.executable)
                env_patch["PATH"] = str(fake_bin)

            with (
                mock.patch("install.os", _FakeNtOs()),
                mock.patch("install.has_real_python3", return_value=False),
                mock.patch.dict(os.environ, env_patch),
                mock.patch.object(Path, "home", return_value=fake_home),
            ):
                p_dry_nt = installer.install_copy(installer.PLUGIN_SOURCE, tmp_path / "dry-nt", dry_run=True)
                self.assertEqual(p_dry_nt, 0)
                rc_fix = installer.install_copy(installer.PLUGIN_SOURCE, target_fix)
            self.assertEqual(rc_fix, 0)
            cfg_fix = json.loads((target_fix / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertIn(cfg_fix["mcpServers"]["dashboard"]["command"], ("python", "py"))
            hooks_fix = json.loads((target_fix / "hooks.json").read_text(encoding="utf-8"))
            hook_cmd = hooks_fix["gravity-core-command"]["PreInvocation"][0]["command"]
            self.assertFalse(hook_cmd.startswith("python3 "))

            target_nofix = tmp_path / "installed-nofix"
            p_nofix = _run_install(["--target", str(target_nofix), "--no-fix-python"], fake_home)
            self.assertEqual(p_nofix.returncode, 0, msg=p_nofix.stderr or p_nofix.stdout)
            cfg_nofix = json.loads((target_nofix / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg_nofix["mcpServers"]["dashboard"]["command"], "python3")
            hooks_nofix = json.loads((target_nofix / "hooks.json").read_text(encoding="utf-8"))
            self.assertTrue(hooks_nofix["gravity-core-command"]["PreInvocation"][0]["command"].startswith("python3 "))

    def test_sources_json_recorded_only_on_real_global_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            gravity_home = tmp_path / "custom-gravity-home"
            sources_file = gravity_home / "core" / "sources.json"

            # 1) --dry-run global must NOT write sources.json
            p_dry = _run_install(["--dry-run"], fake_home, extra_env={"GRAVITY_HOME": str(gravity_home)})
            self.assertEqual(p_dry.returncode, 0, msg=p_dry.stderr or p_dry.stdout)
            self.assertFalse(sources_file.exists())

            # 2) --scope workspace must NOT write sources.json
            ws = tmp_path / "ws"
            ws.mkdir()
            p_ws = _run_install(
                ["--scope", "workspace", "--workspace", str(ws)],
                fake_home,
                extra_env={"GRAVITY_HOME": str(gravity_home)},
            )
            self.assertEqual(p_ws.returncode, 0, msg=p_ws.stderr or p_ws.stdout)
            self.assertFalse(sources_file.exists())

            # 3) --target must NOT write sources.json
            p_tgt = _run_install(
                ["--target", str(tmp_path / "explicit-target")],
                fake_home,
                extra_env={"GRAVITY_HOME": str(gravity_home)},
            )
            self.assertEqual(p_tgt.returncode, 0, msg=p_tgt.stderr or p_tgt.stdout)
            self.assertFalse(sources_file.exists())

            # Seed existing companion entry in sources.json to verify preservation
            sources_file.parent.mkdir(parents=True, exist_ok=True)
            sources_file.write_text(
                json.dumps({"schema_version": 1, "sources": {"other-mod": {"repo_dir": "/tmp/other"}}}) + "\n",
                encoding="utf-8",
            )

            # 4) Real global install without --target writes sources.json atomically
            p_glob = _run_install(["--skip-validate"], fake_home, extra_env={"GRAVITY_HOME": str(gravity_home)})
            self.assertEqual(p_glob.returncode, 0, msg=p_glob.stderr or p_glob.stdout)
            self.assertTrue(sources_file.is_file())
            raw = sources_file.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)
            data = json.loads(raw.decode("utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("other-mod", data["sources"])
            grav = data["sources"]["gravity"]
            self.assertEqual(grav["plugin_name"], "gravity")
            self.assertEqual(Path(grav["repo_dir"]), REPO_ROOT.resolve())
            self.assertEqual(grav["install_method"], "copy")
            self.assertEqual(
                Path(grav["target_dir"]),
                (fake_home / ".gemini" / "config" / "plugins" / "gravity").resolve(),
            )
            self.assertTrue(grav["installed_version"])

    def test_windows_winerror_32_lock_triggers_inplace_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "gravity"
            self.assertEqual(
                installer.install_copy(installer.PLUGIN_SOURCE, target, skip_validate=True),
                0,
            )
            stale = target / "stale.txt"
            stale.write_text("stale", encoding="utf-8")
            win_err = OSError("sharing violation")
            win_err.winerror = 32  # type: ignore[attr-defined]
            with mock.patch("install.os.rename", side_effect=win_err):
                rc = installer.install_copy(installer.PLUGIN_SOURCE, target, force=True, skip_validate=True)
            self.assertEqual(rc, 0)
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()

"""Isolated unit tests for shared/gravity_shared/installer_core.py (100% stdlib)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_PARENT = REPO_ROOT / "shared"
if str(SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(SHARED_PARENT))

from gravity_shared import installer_core as ic  # noqa: E402


def _make_mini_plugin(
    root: Path,
    name: str = "demo-plugin",
    version: str = "1.2.3",
    *,
    validate_rc: int = 0,
    with_mcp: bool = True,
) -> Path:
    plugin = root / name
    (plugin / "scripts").mkdir(parents=True, exist_ok=True)
    (plugin / "config").mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": name, "version": version, "repository": "https://example.invalid/demo"}),
        encoding="utf-8",
    )
    (plugin / "config" / "module.json").write_text(
        json.dumps({"schema_version": 1, "id": "demo"}),
        encoding="utf-8",
    )
    if with_mcp:
        (plugin / "mcp_config.json").write_text(
            json.dumps({"mcpServers": {"demo": {"command": "python3", "args": ["scripts/srv.py"]}}}),
            encoding="utf-8",
        )
    (plugin / "scripts" / "srv.py").write_text("print('ok')\n", encoding="utf-8")
    validate_py = (
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "root = pathlib.Path(args[args.index('--plugin-root') + 1])\n"
        "if '--fix-python-cmd' in args:\n"
        "    cfg_p = root / 'mcp_config.json'\n"
        "    if cfg_p.is_file():\n"
        "        data = json.loads(cfg_p.read_text(encoding='utf-8'))\n"
        "        data['mcpServers']['demo']['command'] = 'python'\n"
        "        cfg_p.write_text(json.dumps(data), encoding='utf-8')\n"
        "    sys.exit(0)\n"
        f"sys.exit({validate_rc})\n"
    )
    (plugin / "scripts" / "validate.py").write_text(validate_py, encoding="utf-8")
    return plugin


class TestSharedInstaller(unittest.TestCase):
    def test_11_flags_parser_and_extra_cli_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_mini_plugin(Path(tmp), "demo-plugin")
            spec = ic.InstallSpec(
                plugin_name="demo-plugin",
                plugin_source=plugin,
                extra_cli_fn=lambda p: p.add_argument("--custom-flag", action="store_true"),
            )
            parser = ic.build_parser(spec)
            opts = set(parser._option_string_actions.keys())
            for flag in ic.CORE_INSTALL_FLAGS:
                self.assertIn(flag, opts)
            self.assertIn("--custom-flag", opts)
            ns = parser.parse_args(
                [
                    "--scope", "workspace",
                    "--workspace", tmp,
                    "--target", str(Path(tmp) / "t"),
                    "--method", "copy",
                    "--force",
                    "--skip-validate",
                    "--strict",
                    "--no-fix-python",
                    "--dry-run",
                    "--check",
                    "--uninstall",
                    "--custom-flag",
                ]
            )
            self.assertTrue(ns.strict and ns.skip_validate and ns.force and ns.custom_flag)

    def test_resolve_target_preserves_final_symlink_and_unsafe_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            real_dest = tmp_path / "real_dest"
            real_dest.mkdir()
            link_target = tmp_path / "link_target"
            os.symlink(real_dest, link_target)

            resolved = ic.resolve_target_dir("global", None, link_target, plugin_name="demo-plugin")
            self.assertEqual(os.fspath(resolved), os.path.abspath(os.fspath(link_target)))

            plugin = _make_mini_plugin(tmp_path, "demo-plugin")
            self.assertIsNotNone(ic.is_unsafe_target(Path("/"), plugin))
            self.assertIsNotNone(ic.is_unsafe_target(plugin, plugin))
            self.assertIsNotNone(ic.is_unsafe_target(tmp_path, plugin))
            with mock.patch("os.name", "nt"), mock.patch.dict(os.environ, {"HOME": str(tmp_path)}, clear=False):
                os.environ.pop("USERPROFILE", None)
                self.assertIsNotNone(ic.is_unsafe_target(tmp_path, plugin))

    def test_has_real_python3_filters_windowsapps(self) -> None:
        with mock.patch("os.name", "nt"), mock.patch("shutil.which", return_value=r"C:\Program Files\WindowsApps\python3.exe"):
            self.assertFalse(ic.has_real_python3())
        with mock.patch("os.name", "nt"), mock.patch("shutil.which", return_value=r"C:\Python312\python3.exe"):
            self.assertTrue(ic.has_real_python3())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(ic.has_real_python3())

    def test_cli_install_check_dry_run_strict_override_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            gravity_core = fake_home / ".gemini" / "gravity" / "core"
            gravity_core.mkdir(parents=True)
            keep_file = gravity_core / "modules.json"
            keep_file.write_text('{"keep": true}\n', encoding="utf-8")

            plugin = _make_mini_plugin(tmp_path / "repo", "demo-plugin", version="2.0.0")
            target = tmp_path / "installed" / "demo-plugin"
            spec = ic.InstallSpec(
                plugin_name="demo-plugin",
                display_name="Demo Plugin",
                plugin_source=plugin,
                repo_root=plugin.parent,
                exec_scripts=("scripts/srv.py", "scripts/validate.py"),
                has_executable_manifest=True,
            )

            with mock.patch.dict(os.environ, {"HOME": str(fake_home), "GRAVITY_HOME": str(fake_home / ".gemini" / "gravity")}):
                self.assertEqual(ic.run_installer(spec, ["--check", "--target", str(target)]), 0)
                self.assertEqual(ic.run_installer(spec, ["--dry-run", "--target", str(target)]), 0)
                self.assertFalse(target.exists())

                self.assertEqual(ic.run_installer(spec, ["--target", str(target)]), 0)
                self.assertTrue((target / "plugin.json").is_file())
                mode = (target / "scripts" / "srv.py").stat().st_mode
                self.assertTrue(mode & stat.S_IXUSR)

                sources_json = gravity_core / "sources.json"
                self.assertTrue(sources_json.is_file())
                src_data = json.loads(sources_json.read_text(encoding="utf-8"))
                self.assertEqual(src_data["schema_version"], 1)
                self.assertEqual(src_data["sources"]["demo-plugin"]["installed_version"], "2.0.0")
                self.assertEqual(src_data["sources"]["demo-plugin"]["install_method"], "copy")

                # Reinstall without --force fails, with --force succeeds
                self.assertEqual(ic.run_installer(spec, ["--target", str(target)]), 1)
                self.assertEqual(ic.run_installer(spec, ["--target", str(target), "--force"]), 0)

                # Uninstall preserves $GRAVITY_HOME data
                self.assertEqual(ic.run_installer(spec, ["--uninstall", "--target", str(target)]), 0)
                self.assertFalse(target.exists())
                self.assertTrue(keep_file.is_file())

    def test_strict_overrides_skip_validate_and_aborts_without_modifying_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            good_plugin = _make_mini_plugin(tmp_path / "good", "demo-plugin", version="1.0.0", validate_rc=0)
            bad_plugin = _make_mini_plugin(tmp_path / "bad", "demo-plugin", version="9.9.9", validate_rc=1)
            target = tmp_path / "target" / "demo-plugin"

            good_spec = ic.InstallSpec(plugin_name="demo-plugin", plugin_source=good_plugin, record_sources=False)
            bad_spec = ic.InstallSpec(plugin_name="demo-plugin", plugin_source=bad_plugin, record_sources=False)

            self.assertEqual(ic.run_installer(good_spec, ["--target", str(target)]), 0)
            # --skip-validate alone skips validation and upgrades
            self.assertEqual(ic.run_installer(bad_spec, ["--target", str(target), "--force", "--skip-validate"]), 0)
            self.assertEqual(json.loads((target / "plugin.json").read_text(encoding="utf-8"))["version"], "9.9.9")

            # Reinstall v1.0.0, then pass --skip-validate --strict -> --strict wins, aborts, v1.0.0 preserved
            self.assertEqual(ic.run_installer(good_spec, ["--target", str(target), "--force"]), 0)
            rc = ic.run_installer(bad_spec, ["--target", str(target), "--force", "--skip-validate", "--strict"])
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads((target / "plugin.json").read_text(encoding="utf-8"))["version"], "1.0.0")

    def test_windows_python_rewrite_on_staged_copy_without_userprofile_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            plugin = _make_mini_plugin(tmp_path / "src", "demo-plugin", with_mcp=True)
            spec = ic.InstallSpec(
                plugin_name="demo-plugin",
                plugin_source=plugin,
                has_executable_manifest=True,
                record_sources=False,
            )
            target_fix = tmp_path / "win-fix"
            target_nofix = tmp_path / "win-nofix"

            env_no_userprofile = {k: v for k, v in os.environ.items() if k != "USERPROFILE"}
            env_no_userprofile["HOME"] = str(fake_home)
            with (
                mock.patch.dict(os.environ, env_no_userprofile, clear=True),
                mock.patch("os.name", "nt"),
                mock.patch("gravity_shared.installer_core.has_real_python3", return_value=False),
            ):
                self.assertEqual(ic.install_copy(spec, target_fix), 0)
                self.assertEqual(ic.install_copy(spec, target_nofix, no_fix_python=True), 0)

            fixed_cfg = json.loads((target_fix / "mcp_config.json").read_text(encoding="utf-8"))
            nofix_cfg = json.loads((target_nofix / "mcp_config.json").read_text(encoding="utf-8"))
            src_cfg = json.loads((plugin / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertEqual(fixed_cfg["mcpServers"]["demo"]["command"], "python")
            self.assertEqual(nofix_cfg["mcpServers"]["demo"]["command"], "python3")
            self.assertEqual(src_cfg["mcpServers"]["demo"]["command"], "python3")

    def test_inplace_locked_identical_and_transactional_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plugin = _make_mini_plugin(tmp_path / "src", "demo-plugin", version="2.0.0")
            spec = ic.InstallSpec(plugin_name="demo-plugin", plugin_source=plugin, record_sources=False)
            target = tmp_path / "target"
            self.assertEqual(ic.install_copy(spec, target, skip_validate=True), 0)
            (target / "stale.txt").write_text("old", encoding="utf-8")

            # Locked identical file tolerated when os.rename raises PermissionError
            real_copy2 = shutil.copy2

            def lock_identical(src: str, dst: str) -> str:
                if os.path.basename(dst) == "srv.py":
                    raise PermissionError("locked identical")
                return real_copy2(src, dst)

            with (
                mock.patch("gravity_shared.installer_core.os.rename", side_effect=PermissionError("dir in use")),
                mock.patch("gravity_shared.installer_core.shutil.copy2", side_effect=lock_identical),
            ):
                self.assertEqual(ic.install_copy(spec, target, force=True, skip_validate=True), 0)
            self.assertFalse((target / "stale.txt").exists())

            # Non-identical locked file fails and rolls back modifications
            (target / "plugin.json").write_text(json.dumps({"name": "demo-plugin", "version": "1.0.0"}), encoding="utf-8")
            (target / "scripts" / "srv.py").write_text("print('old')\n", encoding="utf-8")

            def lock_different(src: str, dst: str) -> str:
                if os.path.basename(dst) == "srv.py":
                    raise PermissionError("locked changed")
                return real_copy2(src, dst)

            with (
                mock.patch("gravity_shared.installer_core.os.rename", side_effect=PermissionError("dir in use")),
                mock.patch("gravity_shared.installer_core.shutil.copy2", side_effect=lock_different),
            ):
                self.assertEqual(ic.install_copy(spec, target, force=True, skip_validate=True), 1)
            self.assertEqual(json.loads((target / "plugin.json").read_text(encoding="utf-8"))["version"], "1.0.0")

            # shutil.move failure after os.rename restores backup
            real_move = shutil.move

            def fail_staged_move(src: str, dst: str) -> str:
                if ".demo-plugin-stage-" in str(src):
                    raise OSError("disk error")
                return real_move(src, dst)

            with mock.patch("gravity_shared.installer_core.shutil.move", side_effect=fail_staged_move):
                self.assertEqual(ic.install_copy(spec, target, force=True, skip_validate=True), 1)
            self.assertTrue((target / "plugin.json").is_file())

    def test_workspace_scope_legacy_replacement_check_strict_and_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plugin = _make_mini_plugin(tmp_path / "src", "demo-plugin", version="3.0.0")
            ws = tmp_path / "ws"
            ws.mkdir()
            ws_target = ws / ".agents" / "plugins" / "demo-plugin"
            (ws_target / "hooks").mkdir(parents=True)
            (ws_target / "plugin.json").write_text(json.dumps({"name": "demo-plugin", "version": "0.1.0"}), encoding="utf-8")
            (ws_target / "hooks" / "legacy.py").write_text("# old\n", encoding="utf-8")

            events: list[str] = []
            spec = ic.InstallSpec(
                plugin_name="demo-plugin",
                plugin_source=plugin,
                installed_check_fn=lambda d: (d / "config" / "module.json").is_file(),
                legacy_check_fn=lambda d: (d / "hooks" / "legacy.py").is_file(),
                post_install_fn=lambda args, sp, td: events.append("post_install") or 0,
                post_uninstall_fn=lambda args, sp, td: events.append("post_uninstall") or 0,
                next_steps_fn=lambda td, args: events.append("next_steps"),
                record_sources=False,
            )

            self.assertEqual(ic.run_installer(spec, ["--check", "--strict", "--scope", "workspace", "--workspace", str(ws)]), 0)
            self.assertEqual(ic.run_installer(spec, ["--scope", "workspace", "--workspace", str(ws)]), 1)
            self.assertEqual(ic.run_installer(spec, ["--scope", "workspace", "--workspace", str(ws), "--force"]), 0)
            self.assertFalse((ws_target / "hooks" / "legacy.py").exists())
            self.assertTrue((ws_target / "config" / "module.json").is_file())
            self.assertEqual(events, ["post_install", "next_steps"])

            self.assertEqual(ic.run_installer(spec, ["--uninstall", "--scope", "workspace", "--workspace", str(ws)]), 0)
            self.assertEqual(events, ["post_install", "next_steps", "post_uninstall"])

            bad_plugin = _make_mini_plugin(tmp_path / "bad_src", "demo-plugin", validate_rc=1)
            bad_spec = ic.InstallSpec(plugin_name="demo-plugin", plugin_source=bad_plugin, record_sources=False)
            self.assertEqual(ic.run_installer(bad_spec, ["--check", "--strict", "--target", str(tmp_path / "x")]), 1)

    def test_symlink_and_junction_target_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plugin = _make_mini_plugin(tmp_path / "src", "demo-plugin")
            spec = ic.InstallSpec(plugin_name="demo-plugin", plugin_source=plugin, record_sources=False)
            real_dir = tmp_path / "real"
            real_dir.mkdir()
            sym_target = tmp_path / "sym_target"
            os.symlink(real_dir, sym_target)

            self.assertEqual(ic.install_copy(spec, sym_target, force=True, skip_validate=True), 1)
            self.assertEqual(ic.uninstall_plugin(spec, sym_target), 1)

            junc_target = tmp_path / "junc_target"
            junc_target.mkdir()
            with mock.patch("gravity_shared.installer_core.is_symlink_or_junction", side_effect=lambda p: os.fspath(p) == os.fspath(junc_target)):
                self.assertEqual(ic.install_copy(spec, junc_target, force=True, skip_validate=True), 1)
                self.assertEqual(ic.uninstall_plugin(spec, junc_target), 1)

    def test_sources_json_rejects_symlink_and_method_agy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plugin = _make_mini_plugin(tmp_path / "src", "demo-plugin")
            spec = ic.InstallSpec(plugin_name="demo-plugin", plugin_source=plugin)
            real_gh = tmp_path / "real_gh"
            real_gh.mkdir()
            link_gh = tmp_path / "link_gh"
            os.symlink(real_gh, link_gh)
            self.assertIsNone(ic.record_source_provenance(spec, method="copy", target_dir=tmp_path / "t", gravity_home=link_gh))

            ok_proc = subprocess.CompletedProcess(args=["agy"], returncode=0, stdout="ok", stderr="")
            with mock.patch("shutil.which", return_value="/usr/bin/agy"), mock.patch("gravity_shared.installer_core._run_subprocess", return_value=ok_proc):
                self.assertEqual(ic.run_installer(spec, ["--method", "agy", "--dry-run"]), 0)
            self.assertEqual(ic.run_installer(spec, ["--scope", "workspace"]), 2)
            self.assertEqual(ic.run_installer(spec, ["--method", "agy", "--target", str(tmp_path / "x")]), 2)


if __name__ == "__main__":
    unittest.main()

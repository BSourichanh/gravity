"""Isolated CLI and module tests for plugin/scripts/init_env.py."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
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
PLUGIN_ROOT = REPO_ROOT / "plugin"
INIT_SCRIPT = PLUGIN_ROOT / "scripts" / "init_env.py"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from scripts import init_env  # noqa: E402


def _isolated_env(fake_home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env.pop("GRAVITY_HOME", None)
    env.pop("GRAVITY_CORE_HOME", None)
    env.pop("GRAVITY_METRICS_HOME", None)
    env.pop("GRAVITY_BRIDGE_HOME", None)
    env.pop("GRAVITY_ARCHITECT_HOME", None)
    if extra:
        env.update(extra)
    return env


def _create_fake_module(plugins_dir: Path, mod_id: str, plugin_name: str, env_override: str) -> None:
    mod_dir = plugins_dir / plugin_name
    (mod_dir / "config").mkdir(parents=True)
    (mod_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_name,
                "displayName": plugin_name.title(),
                "version": "0.1.0",
                "description": "Test module",
                "logo": "assets/logo.svg",
                "suggestedPrompts": ["A", "B", "C"],
                "author": {"name": "Gravity Contributors"},
                "homepage": f"https://github.com/BSourichanh/{plugin_name}",
                "repository": f"https://github.com/BSourichanh/{plugin_name}.git",
            }
        ),
        encoding="utf-8",
    )
    (mod_dir / "config" / "module.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": mod_id,
                "plugin_name": plugin_name,
                "role": f"Role {mod_id}",
                "storage": {"subdir": mod_id, "env_override": env_override},
                "commands": [f"/{plugin_name}"],
                "capabilities": ["test-cap"],
                "ui": {"mode": "none", "target": "gravity"},
                "signals": {"produces": [], "consumes": []},
            }
        ),
        encoding="utf-8",
    )


class TestInitEnvCLI(unittest.TestCase):
    def test_init_creates_core_subdirs_registry_and_detects_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            legacy_metrics = fake_home / ".gemini" / "gravity-metrics"
            legacy_metrics.mkdir(parents=True)
            sentinel = legacy_metrics / "history.jsonl"
            sentinel.write_text('{"id":"keep"}\n', encoding="utf-8")

            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            _create_fake_module(plugins_dir, "metrics", "gravity-metrics", "GRAVITY_METRICS_HOME")

            gravity_home = tmp_path / "gravity-home"
            custom_metrics = tmp_path / "custom-metrics-store"
            env = _isolated_env(fake_home, {"GRAVITY_METRICS_HOME": str(custom_metrics)})

            proc = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            out = json.loads(proc.stdout)
            self.assertTrue(out["ok"])
            self.assertEqual(out["mode"], "init")
            self.assertEqual(out["valid_count"], 2)
            self.assertEqual([m["id"] for m in out["modules"]], ["core", "metrics"])
            self.assertTrue((gravity_home / "core" / "modules.json").is_file())
            self.assertTrue(custom_metrics.is_dir())
            self.assertEqual(len(out["legacy_homes"]), 1)
            self.assertEqual(out["legacy_homes"][0]["name"], "gravity-metrics")
            # Legacy files untouched
            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"id":"keep"}\n')

    def test_status_and_check_are_strictly_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            gravity_home = tmp_path / "uninitialized-home"
            env = _isolated_env(fake_home)

            for flag in ("--status", "--check"):
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(INIT_SCRIPT),
                        "--gravity-home",
                        str(gravity_home),
                        "--plugins-dir",
                        str(plugins_dir),
                        flag,
                        "--json",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                out = json.loads(proc.stdout)
                self.assertFalse(out["initialized"])
                self.assertFalse(gravity_home.exists())

    def test_check_fails_on_invalid_module_and_human_output_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            broken = plugins_dir / "broken"
            (broken / "config").mkdir(parents=True)
            (broken / "config" / "module.json").write_text('{"schema_version": 99}', encoding="utf-8")

            gravity_home = tmp_path / "check-home"
            env = _isolated_env(fake_home)

            proc = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--check",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("INVALID", proc.stdout)
            self.assertFalse(gravity_home.exists())

    def test_dashboard_flag_is_read_only_and_reports_mcp_and_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            _create_fake_module(plugins_dir, "bridge", "gravity-bridge", "GRAVITY_BRIDGE_HOME")

            gravity_home = tmp_path / "uninit-dash-home"
            env = _isolated_env(fake_home)

            p_json = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--dashboard",
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_json.returncode, 0, msg=p_json.stderr or p_json.stdout)
            self.assertFalse(gravity_home.exists())
            out = json.loads(p_json.stdout)
            self.assertEqual(out["mode"], "dashboard")
            self.assertTrue(out["ok"])
            self.assertTrue(out["dashboard"]["mcp_config_ok"])
            self.assertTrue(out["dashboard"]["server_exists"])
            self.assertTrue(out["dashboard"]["api_exists"])
            self.assertEqual([t["id"] for t in out["tabs"]], ["overview", "bridge"])

            p_txt = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--dashboard",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_txt.returncode, 0, msg=p_txt.stderr)
            self.assertIn("open_gravity_dashboard", p_txt.stdout)
            self.assertFalse(gravity_home.exists())

            p_mutex = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--dashboard", "--status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(p_mutex.returncode, 2)

    def test_guide_flag_is_read_only_lists_discovered_commands_and_caps_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            _create_fake_module(plugins_dir, "metrics", "gravity-metrics", "GRAVITY_METRICS_HOME")

            gravity_home = tmp_path / "uninit-guide-home"
            env = _isolated_env(fake_home)

            p_json = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--guide",
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_json.returncode, 0, msg=p_json.stderr or p_json.stdout)
            self.assertFalse(gravity_home.exists())
            out = json.loads(p_json.stdout)
            self.assertEqual(out["mode"], "guide")
            self.assertTrue(out["ok"])
            self.assertEqual([m["id"] for m in out["installed_modules"]], ["core", "metrics"])
            self.assertEqual(len(out["quickstart"]), 3)
            self.assertIn("core", out["commands"])
            self.assertEqual(out["commands"]["metrics"], ["/gravity-metrics"])
            self.assertEqual(
                out["docs"],
                [
                    "docs/getting-started.md",
                    "docs/user-journey.md",
                    "docs/command-cheatsheet.md",
                    "docs/troubleshooting-and-lifecycle.md",
                ],
            )

            p_txt = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--guide",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_txt.returncode, 0, msg=p_txt.stderr)
            self.assertFalse(gravity_home.exists())
            lines = p_txt.stdout.splitlines()
            self.assertLessEqual(len(lines), 20)
            self.assertIn("/gravity-metrics", p_txt.stdout)
            self.assertIn("docs/getting-started.md", p_txt.stdout)

            p_mutex = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--guide", "--status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(p_mutex.returncode, 2)

            p_help = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=10,
                check=False,
            )
            self.assertEqual(p_help.returncode, 0)
            self.assertIn("--guide", p_help.stdout)

    def test_check_warns_non_blocking_for_missing_architect_registry_and_bridge_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            _create_fake_module(plugins_dir, "architect", "gravity-architect", "GRAVITY_ARCHITECT_HOME")
            _create_fake_module(plugins_dir, "bridge", "gravity-bridge", "GRAVITY_BRIDGE_HOME")

            gravity_home = tmp_path / "doctor-home"
            empty_bin = tmp_path / "empty-bin"
            empty_bin.mkdir()
            env = _isolated_env(fake_home, {"PATH": str(empty_bin)})

            # 1) Missing ateliers.json and missing bridge.db -> non-blocking warnings, exit 0, strictly RO
            p_missing = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--check",
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_missing.returncode, 0, msg=p_missing.stderr or p_missing.stdout)
            self.assertFalse(gravity_home.exists())
            out = json.loads(p_missing.stdout)
            self.assertTrue(out["ok"])
            self.assertEqual(len(out["warnings"]), 2)
            joined = "\n".join(out["warnings"])
            self.assertIn("ateliers.json", joined)
            self.assertIn("/gravity-architect init", joined)
            self.assertIn("bridge.db", joined)
            self.assertIn("/gravity-bridge", joined)

            # Human-readable output also displays non-blocking warnings
            p_txt = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--check",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_txt.returncode, 0, msg=p_txt.stderr)
            self.assertIn("[WARN]", p_txt.stdout)
            self.assertIn("/gravity-architect", p_txt.stdout)
            self.assertIn("/gravity-bridge", p_txt.stdout)
            self.assertFalse(gravity_home.exists())

            # 2) Empty ateliers.json (0 valid ateliers) -> still warns for architect
            arch_home = gravity_home / "architect"
            arch_home.mkdir(parents=True)
            (arch_home / "ateliers.json").write_text(
                json.dumps({"schema_version": 1, "ateliers": [{"workspace_path": str(tmp_path / "missing-ws")}]}),
                encoding="utf-8",
            )
            p_empty_reg = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--check",
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_empty_reg.returncode, 0)
            out_empty = json.loads(p_empty_reg.stdout)
            self.assertTrue(out_empty["ok"])
            self.assertEqual(len(out_empty["warnings"]), 2)

            # 3) Valid atelier + bridge.db present -> 0 warning
            atelier_dir = tmp_path / "atelier-ok"
            atelier_dir.mkdir()
            (atelier_dir / "ECOSYSTEM.md").write_text("# Atelier\n", encoding="utf-8")
            (atelier_dir / "projects.json").write_text("{}", encoding="utf-8")
            (arch_home / "ateliers.json").write_text(
                json.dumps({"schema_version": 1, "ateliers": [{"workspace_path": str(atelier_dir)}]}),
                encoding="utf-8",
            )
            bridge_home = gravity_home / "bridge"
            bridge_home.mkdir(parents=True)
            (bridge_home / "bridge.db").write_bytes(b"")

            p_clean = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INIT_SCRIPT),
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--check",
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(p_clean.returncode, 0)
            out_clean = json.loads(p_clean.stdout)
            self.assertTrue(out_clean["ok"])
            self.assertEqual(out_clean["warnings"], [])

    def test_detect_antigravity_app_version_probes_and_integration(self) -> None:
        # 1) Snap 2.33.0 -> below 2.34.0
        with mock.patch.object(
            init_env.shutil,
            "which",
            side_effect=lambda cmd: "/usr/bin/snap" if cmd == "snap" else None,
        ), mock.patch.object(
            init_env.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/bin/snap", "list", "antigravity"],
                returncode=0,
                stdout="Nom          Version  Revision\nantigravity  2.33.0   75\n",
                stderr="",
            ),
        ) as run_mock:
            info_old = init_env._detect_antigravity_app_version()
            self.assertEqual(info_old["version"], "2.33.0")
            self.assertEqual(info_old["source"], "snap")
            self.assertFalse(info_old["meets_mcp_app_min"])
            self.assertEqual(info_old["min_required"], "2.34.0")
            self.assertIn("sudo snap refresh antigravity", info_old["update_hint"])
            called_bins = [Path(c.args[0][0]).name for c in run_mock.call_args_list]
            self.assertEqual(called_bins, ["snap"])
            self.assertNotIn("antigravity", called_bins)

        # 2) Snap 2.35.0 -> meets 2.34.0
        with mock.patch.object(
            init_env.shutil,
            "which",
            side_effect=lambda cmd: "/usr/bin/snap" if cmd == "snap" else None,
        ), mock.patch.object(
            init_env.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/bin/snap", "list", "antigravity"],
                returncode=0,
                stdout="Name         Version  Rev\nantigravity  2.35.0   79\n",
                stderr="",
            ),
        ):
            info_ok = init_env._detect_antigravity_app_version()
            self.assertEqual(info_ok["version"], "2.35.0")
            self.assertEqual(info_ok["source"], "snap")
            self.assertTrue(info_ok["meets_mcp_app_min"])

        # 3) Fallback to dpkg-query when snap unavailable (or misses package)
        def _which_dpkg(cmd: str) -> str | None:
            return "/usr/bin/dpkg-query" if cmd == "dpkg-query" else None

        with mock.patch.object(init_env.shutil, "which", side_effect=_which_dpkg), mock.patch.object(
            init_env.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/bin/dpkg-query", "-W", "-f=${Version}", "antigravity"],
                returncode=0,
                stdout="2.33.0-1732400000",
                stderr="",
            ),
        ) as run_dpkg:
            info_dpkg = init_env._detect_antigravity_app_version()
            self.assertEqual(info_dpkg["version"], "2.33.0")
            self.assertEqual(info_dpkg["source"], "dpkg")
            self.assertFalse(info_dpkg["meets_mcp_app_min"])
            self.assertEqual(info_dpkg["update_hint"], "sudo apt update && sudo apt upgrade antigravity")
            self.assertEqual(Path(run_dpkg.call_args.args[0][0]).name, "dpkg-query")

        # 4) Neither snap nor dpkg-query -> unknown (silent)
        with mock.patch.object(init_env.shutil, "which", return_value=None):
            info_none = init_env._detect_antigravity_app_version()
            self.assertIsNone(info_none["version"])
            self.assertEqual(info_none["source"], "none")
            self.assertIsNone(info_none["meets_mcp_app_min"])
            self.assertEqual(info_none["update_hint"], "")

        # 5) Integration with run_environment(--check & --dashboard) via detector injection
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            gravity_home = tmp_path / "gravity-home"

            # 5a) Old version 2.33.0 -> non-blocking warning in --check & --dashboard
            p_chk_old, rc_chk_old = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                check_only=True,
                app_version_detector=lambda: info_old,
            )
            self.assertEqual(rc_chk_old, 0)
            self.assertTrue(p_chk_old["ok"])
            self.assertEqual(len(p_chk_old["warnings"]), 1)
            self.assertIn("2.33.0", p_chk_old["warnings"][0])
            self.assertIn("2.34.0", p_chk_old["warnings"][0])
            self.assertIn("sudo snap refresh antigravity", p_chk_old["warnings"][0])

            p_dash_old, rc_dash_old = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                dashboard=True,
                app_version_detector=lambda: info_old,
            )
            self.assertEqual(rc_dash_old, 0)
            self.assertTrue(p_dash_old["ok"])
            self.assertEqual(p_dash_old["antigravity_app"]["version"], "2.33.0")
            buf_old = io.StringIO()
            with redirect_stdout(buf_old):
                init_env._print_dashboard_report(p_dash_old)
            self.assertIn("Antigravity   : [WARN] v2.33.0", buf_old.getvalue())

            # 5b) Version 2.35.0 -> clean --check & OK in --dashboard
            p_chk_ok, rc_chk_ok = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                check_only=True,
                app_version_detector=lambda: info_ok,
            )
            self.assertEqual(rc_chk_ok, 0)
            self.assertEqual(p_chk_ok["warnings"], [])

            p_dash_ok, rc_dash_ok = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                dashboard=True,
                app_version_detector=lambda: info_ok,
            )
            self.assertEqual(rc_dash_ok, 0)
            buf_ok = io.StringIO()
            with redirect_stdout(buf_ok):
                init_env._print_dashboard_report(p_dash_ok)
            self.assertIn("Antigravity   : OK (v2.35.0 via snap, >= 2.34.0)", buf_ok.getvalue())

            # 5c) Unavailable -> silent in --check & unknown in --dashboard
            p_chk_none, rc_chk_none = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                check_only=True,
                app_version_detector=lambda: info_none,
            )
            self.assertEqual(rc_chk_none, 0)
            self.assertEqual(p_chk_none["warnings"], [])

            p_dash_none, rc_dash_none = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                dashboard=True,
                app_version_detector=lambda: info_none,
            )
            self.assertEqual(rc_dash_none, 0)
            buf_none = io.StringIO()
            with redirect_stdout(buf_none):
                init_env._print_dashboard_report(p_dash_none)
            self.assertIn("Antigravity   : unknown", buf_none.getvalue())


if __name__ == "__main__":
    unittest.main()

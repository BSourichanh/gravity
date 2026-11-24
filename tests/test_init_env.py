"""Isolated CLI and module tests for plugin/scripts/init_env.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_SCRIPT = REPO_ROOT / "plugin" / "scripts" / "init_env.py"


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
            env = _isolated_env(fake_home)

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


if __name__ == "__main__":
    unittest.main()

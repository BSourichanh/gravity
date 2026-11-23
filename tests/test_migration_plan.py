"""Isolated tests for plugin/scripts/init_env.py --migration-plan."""

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
    for var in (
        "GRAVITY_HOME",
        "GRAVITY_CORE_HOME",
        "GRAVITY_BRIDGE_HOME",
        "GRAVITY_METRICS_HOME",
        "GRAVITY_WORKFLOW_HOME",
        "GRAVITY_ARCHITECT_HOME",
    ):
        env.pop(var, None)
    if extra:
        env.update(extra)
    return env


def _run_init_env(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(INIT_SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=15,
        check=False,
    )


class TestMigrationPlan(unittest.TestCase):
    def test_no_legacy_dirs_returns_empty_plan_with_zero_writes(self) -> None:
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
            env = _isolated_env(fake_home)

            proc = _run_init_env(
                [
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--migration-plan",
                    "--json",
                ],
                env,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            out = json.loads(proc.stdout)
            self.assertTrue(out["ok"])
            self.assertEqual(out["mode"], "migration-plan")
            self.assertEqual(out["plan_count"], 0)
            self.assertFalse(out["has_conflicts"])
            self.assertEqual(out["plans"], [])
            self.assertFalse(gravity_home.exists())
            self.assertFalse((fake_home / "gravity-legacy-backup").exists())

    def test_non_collision_powershell_and_bash_zero_disk_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            legacy_metrics = fake_home / ".gemini" / "gravity-metrics"
            (legacy_metrics / "reports").mkdir(parents=True)
            f1 = legacy_metrics / "history.jsonl"
            f2 = legacy_metrics / "reports" / "summary.md"
            f1.write_text('{"a":1}\n', encoding="utf-8")
            f2.write_text("# Report\n", encoding="utf-8")
            expected_bytes = f1.stat().st_size + f2.stat().st_size

            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            gravity_home = tmp_path / "gravity-home"
            env = _isolated_env(fake_home)

            # PowerShell JSON + human
            p_ps = _run_init_env(
                [
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--migration-plan",
                    "--shell",
                    "powershell",
                    "--json",
                ],
                env,
            )
            self.assertEqual(p_ps.returncode, 0, msg=p_ps.stderr or p_ps.stdout)
            out_ps = json.loads(p_ps.stdout)
            self.assertEqual(out_ps["shell"], "powershell")
            self.assertEqual(out_ps["plan_count"], 1)
            self.assertFalse(out_ps["has_conflicts"])
            plan = out_ps["plans"][0]
            self.assertEqual(plan["name"], "gravity-metrics")
            self.assertEqual(plan["target_module"], "metrics")
            self.assertEqual(plan["file_count"], 2)
            self.assertEqual(plan["total_bytes"], expected_bytes)
            self.assertFalse(plan["conflict"])
            self.assertEqual(plan["collisions"], [])
            steps_ps = plan["steps"]
            self.assertEqual(len(steps_ps), 4)
            self.assertIn("gravity-legacy-backup", steps_ps[0]["command"])
            self.assertIn("Copy-Item", steps_ps[1]["command"])
            self.assertIn("python scripts/init_env.py --check", steps_ps[2]["command"])
            self.assertTrue(steps_ps[3]["command"].lstrip().startswith("#"))

            # Bash JSON + human
            p_bash = _run_init_env(
                [
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--migration-plan",
                    "--shell",
                    "bash",
                    "--json",
                ],
                env,
            )
            self.assertEqual(p_bash.returncode, 0, msg=p_bash.stderr or p_bash.stdout)
            out_bash = json.loads(p_bash.stdout)
            self.assertEqual(out_bash["shell"], "bash")
            steps_bash = out_bash["plans"][0]["steps"]
            self.assertIn("gravity-legacy-backup", steps_bash[0]["command"])
            self.assertIn("cp -n", steps_bash[1]["command"])
            self.assertIn("python scripts/init_env.py --check", steps_bash[2]["command"])
            self.assertTrue(steps_bash[3]["command"].lstrip().startswith("#"))

            # Strictly zero disk writes
            self.assertFalse(gravity_home.exists())
            self.assertFalse((fake_home / "gravity-legacy-backup").exists())
            self.assertEqual(f1.read_text(encoding="utf-8"), '{"a":1}\n')
            self.assertEqual(f2.read_text(encoding="utf-8"), "# Report\n")

    def test_collision_detection_and_human_output_zero_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            legacy_bridge = fake_home / ".gemini" / "gravity-bridge"
            (legacy_bridge / "sub").mkdir(parents=True)
            (legacy_bridge / "bridge.db").write_text("legacy-db", encoding="utf-8")
            (legacy_bridge / "sub" / "extra.txt").write_text("extra", encoding="utf-8")

            gravity_home = tmp_path / "gravity-home"
            target_bridge = gravity_home / "bridge"
            target_bridge.mkdir(parents=True)
            target_db = target_bridge / "bridge.db"
            target_db.write_text("existing-new-db", encoding="utf-8")

            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            env = _isolated_env(fake_home)

            p_json = _run_init_env(
                [
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--migration-plan",
                    "--shell",
                    "bash",
                    "--json",
                ],
                env,
            )
            self.assertEqual(p_json.returncode, 0, msg=p_json.stderr or p_json.stdout)
            out = json.loads(p_json.stdout)
            self.assertTrue(out["has_conflicts"])
            plan = out["plans"][0]
            self.assertTrue(plan["conflict"])
            self.assertEqual(plan["collision_count"], 1)
            self.assertEqual(plan["collisions"], ["bridge.db"])
            self.assertEqual(plan["file_count"], 2)

            p_human = _run_init_env(
                [
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--migration-plan",
                    "--shell",
                    "powershell",
                ],
                env,
            )
            self.assertEqual(p_human.returncode, 0, msg=p_human.stderr)
            self.assertIn("[CONFLICT]", p_human.stdout)
            self.assertIn("bridge.db", p_human.stdout)
            self.assertIn("# Remove-Item", p_human.stdout)

            # Target and source files untouched
            self.assertEqual(target_db.read_text(encoding="utf-8"), "existing-new-db")
            self.assertFalse((target_bridge / "sub" / "extra.txt").exists())
            self.assertFalse((fake_home / "gravity-legacy-backup").exists())

    def test_symlink_escape_is_not_followed_and_mutual_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            legacy_wf = fake_home / ".gemini" / "gravity-workflow"
            legacy_wf.mkdir(parents=True)
            (legacy_wf / "state.json").write_text("{}", encoding="utf-8")

            outside = tmp_path / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")
            link_path = legacy_wf / "escape-link"
            symlink_created = False
            try:
                os.symlink(outside, link_path, target_is_directory=True)
                symlink_created = True
            except OSError:
                # Windows without Developer Mode / symlink privilege
                symlink_created = False

            plugins_dir = tmp_path / "plugins"
            shutil.copytree(
                REPO_ROOT / "plugin",
                plugins_dir / "gravity",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            gravity_home = tmp_path / "gravity-home"
            env = _isolated_env(fake_home)

            proc = _run_init_env(
                [
                    "--gravity-home",
                    str(gravity_home),
                    "--plugins-dir",
                    str(plugins_dir),
                    "--migration-plan",
                    "--json",
                ],
                env,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            out = json.loads(proc.stdout)
            self.assertEqual(out["plans"][0]["file_count"], 1)
            if symlink_created:
                self.assertEqual(out["plans"][0]["collisions"], [])

            # Mutually exclusive with --check and --status
            p_mut = _run_init_env(["--migration-plan", "--check"], env)
            self.assertNotEqual(p_mut.returncode, 0)


if __name__ == "__main__":
    unittest.main()

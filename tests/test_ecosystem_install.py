"""Isolated tests for scripts/ecosystem_install.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = REPO_ROOT / "scripts" / "ecosystem_install.py"

ALL_REPOS = (
    "gravity",
    "gravity-workflow",
    "gravity-metrics",
    "gravity-architect",
    "gravity-bridge",
)


def _isolated_env(fake_home: Path, gravity_home: Path, log_file: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env["GRAVITY_HOME"] = str(gravity_home)
    env["GRAVITY_TEST_EXEC_LOG"] = str(log_file)
    for var in (
        "GRAVITY_CORE_HOME",
        "GRAVITY_WORKFLOW_HOME",
        "GRAVITY_METRICS_HOME",
        "GRAVITY_ARCHITECT_HOME",
        "GRAVITY_BRIDGE_HOME",
    ):
        env.pop(var, None)
    return env


def _create_stub_repos(
    repos_root: Path,
    repos: tuple[str, ...] = ALL_REPOS,
    *,
    fail_on: str | None = None,
    include_init_env: bool = True,
) -> None:
    stub_installer = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "repo = Path(__file__).resolve().parent.name\n"
        "log_path = Path(os.environ['GRAVITY_TEST_EXEC_LOG'])\n"
        "with log_path.open('a', encoding='utf-8') as fh:\n"
        "    fh.write(json.dumps({'repo': repo, 'args': sys.argv[1:]}) + '\\n')\n"
        "print(f'stub:{repo}:' + ' '.join(sys.argv[1:]))\n"
        f"if repo == {fail_on!r}:\n"
        "    print(f'forced failure on {repo}', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
    )
    for name in repos:
        repo_dir = repos_root / name
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "install.py").write_text(stub_installer, encoding="utf-8", newline="\n")

    if include_init_env and "gravity" in repos:
        init_dir = repos_root / "gravity" / "plugin" / "scripts"
        init_dir.mkdir(parents=True, exist_ok=True)
        stub_init = (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "gh = Path(os.environ['GRAVITY_HOME'])\n"
            "mode = 'status' if '--status' in sys.argv else 'init'\n"
            "reg = gh / 'core' / 'modules.json'\n"
            "if mode == 'init':\n"
            "    reg.parent.mkdir(parents=True, exist_ok=True)\n"
            "    reg.write_text(json.dumps({'ok': True, 'modules': []}) + '\\n', encoding='utf-8')\n"
            "print(json.dumps({'ok': True, 'mode': mode, 'registry_path': str(reg), 'module_count': 5, 'valid_count': 5}))\n"
        )
        (init_dir / "init_env.py").write_text(stub_init, encoding="utf-8", newline="\n")


def _read_exec_log(log_file: Path) -> list[dict]:
    if not log_file.is_file():
        return []
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_orchestrator(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(ORCHESTRATOR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=20,
        check=False,
    )


class TestEcosystemInstall(unittest.TestCase):
    def test_default_check_and_install_follow_topological_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            gravity_home = tmp_path / "gravity-home"
            repos_root = tmp_path / "repos"
            _create_stub_repos(repos_root)

            # Default action (no verb) -> --check in topological order, no modules.json created
            check_log = tmp_path / "check.log"
            p_check = _run_orchestrator(
                ["--repos-root", str(repos_root), "--json"],
                _isolated_env(fake_home, gravity_home, check_log),
            )
            self.assertEqual(p_check.returncode, 0, msg=p_check.stderr or p_check.stdout)
            out_check = json.loads(p_check.stdout)
            self.assertTrue(out_check["ok"])
            self.assertEqual(out_check["action"], "check")
            self.assertEqual(out_check["ordered_repos"], list(ALL_REPOS))
            entries = _read_exec_log(check_log)
            self.assertEqual([e["repo"] for e in entries], list(ALL_REPOS))
            self.assertTrue(all(e["args"] == ["--check"] for e in entries))
            self.assertFalse((gravity_home / "core" / "modules.json").exists())

            # --install -> topological order + refreshes core/modules.json
            inst_log = tmp_path / "install.log"
            p_inst = _run_orchestrator(
                ["--install", "--repos-root", str(repos_root), "--json"],
                _isolated_env(fake_home, gravity_home, inst_log),
            )
            self.assertEqual(p_inst.returncode, 0, msg=p_inst.stderr or p_inst.stdout)
            out_inst = json.loads(p_inst.stdout)
            self.assertTrue(out_inst["ok"])
            self.assertEqual([e["repo"] for e in _read_exec_log(inst_log)], list(ALL_REPOS))
            self.assertEqual(out_inst["registry"]["mode"], "refresh")
            self.assertTrue((gravity_home / "core" / "modules.json").is_file())

    def test_uninstall_reverses_order_and_skips_registry_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            gravity_home = tmp_path / "gravity-home"
            repos_root = tmp_path / "repos"
            _create_stub_repos(repos_root)
            log_file = tmp_path / "uninstall.log"

            proc = _run_orchestrator(
                ["--uninstall", "--repos-root", str(repos_root), "--json"],
                _isolated_env(fake_home, gravity_home, log_file),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            out = json.loads(proc.stdout)
            expected_rev = list(reversed(ALL_REPOS))
            self.assertEqual(out["ordered_repos"], expected_rev)
            entries = _read_exec_log(log_file)
            self.assertEqual([e["repo"] for e in entries], expected_rev)
            self.assertTrue(all(e["args"] == ["--uninstall"] for e in entries))
            self.assertEqual(out["registry"]["status"], "skipped")
            self.assertFalse((gravity_home / "core" / "modules.json").exists())

    def test_tiers_modules_and_update_force_propagation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            gravity_home = tmp_path / "gravity-home"
            repos_root = tmp_path / "repos"
            _create_stub_repos(repos_root)

            tier_expectations = {
                1: ["gravity", "gravity-workflow"],
                2: ["gravity", "gravity-workflow", "gravity-metrics"],
                3: list(ALL_REPOS),
            }
            for tier, expected in tier_expectations.items():
                log_file = tmp_path / f"tier{tier}.log"
                proc = _run_orchestrator(
                    ["--check", "--tier", str(tier), "--repos-root", str(repos_root), "--json"],
                    _isolated_env(fake_home, gravity_home, log_file),
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                self.assertEqual([e["repo"] for e in _read_exec_log(log_file)], expected)

            # --modules reorders according to topological order and --update injects --force
            upd_log = tmp_path / "update.log"
            ws = tmp_path / "ws"
            ws.mkdir()
            p_upd = _run_orchestrator(
                [
                    "--update",
                    "--modules",
                    "gravity-bridge,gravity",
                    "--repos-root",
                    str(repos_root),
                    "--scope",
                    "workspace",
                    "--workspace",
                    str(ws),
                    "--method",
                    "copy",
                    "--strict",
                    "--skip-validate",
                    "--dry-run",
                    "--json",
                ],
                _isolated_env(fake_home, gravity_home, upd_log),
            )
            self.assertEqual(p_upd.returncode, 0, msg=p_upd.stderr or p_upd.stdout)
            entries = _read_exec_log(upd_log)
            self.assertEqual([e["repo"] for e in entries], ["gravity", "gravity-bridge"])
            for entry in entries:
                self.assertIn("--force", entry["args"])
                self.assertIn("--dry-run", entry["args"])
                self.assertIn("--strict", entry["args"])
                self.assertIn("--skip-validate", entry["args"])
                self.assertIn("--scope", entry["args"])
                self.assertIn("workspace", entry["args"])
                self.assertIn("--workspace", entry["args"])
                self.assertIn(str(ws), entry["args"])
                self.assertIn("--method", entry["args"])
            # dry-run must not write modules.json
            self.assertFalse((gravity_home / "core" / "modules.json").exists())

            # Mutual exclusion --tier + --modules
            p_mut = _run_orchestrator(
                ["--tier", "1", "--modules", "gravity", "--repos-root", str(repos_root)],
                _isolated_env(fake_home, gravity_home, tmp_path / "mut.log"),
            )
            self.assertNotEqual(p_mut.returncode, 0)

    def test_fail_closed_missing_repo_or_installer_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            gravity_home = tmp_path / "gravity-home"
            repos_root = tmp_path / "repos"
            # Only 4 of 5 repos present (missing gravity-bridge)
            _create_stub_repos(repos_root, repos=ALL_REPOS[:4])

            miss_log = tmp_path / "miss.log"
            p_miss = _run_orchestrator(
                ["--install", "--repos-root", str(repos_root), "--json"],
                _isolated_env(fake_home, gravity_home, miss_log),
            )
            self.assertNotEqual(p_miss.returncode, 0)
            out_miss = json.loads(p_miss.stdout)
            self.assertFalse(out_miss["ok"])
            self.assertEqual(out_miss["missing"][0]["repo"], "gravity-bridge")
            # Fail-closed before running any installer
            self.assertEqual(_read_exec_log(miss_log), [])
            self.assertFalse((gravity_home / "core" / "modules.json").exists())

            # Missing install.py inside present repo directory
            (repos_root / "gravity-bridge").mkdir()
            p_no_inst = _run_orchestrator(
                ["--check", "--repos-root", str(repos_root), "--json"],
                _isolated_env(fake_home, gravity_home, miss_log),
            )
            self.assertNotEqual(p_no_inst.returncode, 0)
            out_no_inst = json.loads(p_no_inst.stdout)
            self.assertEqual(out_no_inst["missing"][0]["reason"], "install.py not found in repository")

            # Mid-run installer failure aborts remaining repos and skips modules.json refresh
            repos_fail = tmp_path / "repos-fail"
            _create_stub_repos(repos_fail, fail_on="gravity-metrics")
            fail_log = tmp_path / "fail.log"
            p_fail = _run_orchestrator(
                ["--install", "--repos-root", str(repos_fail), "--json"],
                _isolated_env(fake_home, gravity_home, fail_log),
            )
            self.assertNotEqual(p_fail.returncode, 0)
            out_fail = json.loads(p_fail.stdout)
            self.assertFalse(out_fail["ok"])
            self.assertEqual(out_fail["failed_repo"], "gravity-metrics")
            self.assertEqual(
                [e["repo"] for e in _read_exec_log(fail_log)],
                ["gravity", "gravity-workflow", "gravity-metrics"],
            )
            self.assertFalse((gravity_home / "core" / "modules.json").exists())

            # Unknown module name in --modules fails closed
            p_unk = _run_orchestrator(
                ["--modules", "gravity,unknown-mod", "--repos-root", str(repos_root), "--json"],
                _isolated_env(fake_home, gravity_home, miss_log),
            )
            self.assertNotEqual(p_unk.returncode, 0)
            self.assertFalse(json.loads(p_unk.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()

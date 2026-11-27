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

from core import doctor  # noqa: E402
from scripts import init_env  # noqa: E402


def _isolated_env(fake_home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    for var in (
        "GRAVITY_HOME",
        "GRAVITY_CORE_HOME",
        "GRAVITY_METRICS_HOME",
        "GRAVITY_ARCHITECT_HOME",
        "GRAVITY_WORKFLOW_HOME",
    ):
        env.pop(var, None)
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


def _create_fake_spi_health_module(
    plugins_dir: Path,
    mod_id: str,
    plugin_name: str,
    env_override: str,
    script_body: str,
    *,
    views: list[str] | None = None,
) -> None:
    _create_fake_module(plugins_dir, mod_id, plugin_name, env_override)
    mod_dir = plugins_dir / plugin_name
    mod_json_path = mod_dir / "config" / "module.json"
    mod_data = json.loads(mod_json_path.read_text(encoding="utf-8"))
    mod_data["dashboard"] = {
        "provider_script": "scripts/dashboard_provider.py",
        "views": list(views) if views is not None else ["health"],
        "actions": [],
    }
    mod_json_path.write_text(json.dumps(mod_data), encoding="utf-8")
    (mod_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (mod_dir / "scripts" / "dashboard_provider.py").write_text(script_body, encoding="utf-8")


_ARCHITECT_HEALTH_STUB = """import json, os, sys
from pathlib import Path

def main():
    g_home = Path(os.environ.get("GRAVITY_HOME") or (Path.home() / ".gemini" / "gravity"))
    a_home = Path(os.environ["GRAVITY_ARCHITECT_HOME"]) if os.environ.get("GRAVITY_ARCHITECT_HOME", "").strip() else (g_home / "architect")
    ap = a_home / "ateliers.json"
    if not ap.is_file():
        print(json.dumps({"ok": True, "status": "WARN", "summary": "ateliers.json absent", "warnings": [f"Module 'architect' actif mais {ap} absent : lancez /gravity-architect init."]}))
        return 0
    data = json.loads(ap.read_text(encoding="utf-8"))
    valid = sum(1 for e in (data.get("ateliers") or []) if isinstance(e, dict) and e.get("workspace_path") and (Path(e["workspace_path"]) / "ECOSYSTEM.md").is_file())
    if valid == 0:
        print(json.dumps({"ok": True, "status": "WARN", "summary": "0 atelier valide", "warnings": [f"Module 'architect' actif mais {ap} ne contient aucun atelier valide."]}))
        return 0
    print(json.dumps({"ok": True, "status": "OK", "summary": f"{valid} atelier(s) valide(s)", "warnings": []}))
    return 0

raise SystemExit(main())
"""

_METRICS_HEALTH_STUB = """import json, os
from pathlib import Path

def main():
    g_home = Path(os.environ.get("GRAVITY_HOME") or (Path.home() / ".gemini" / "gravity"))
    m_home = Path(os.environ["GRAVITY_METRICS_HOME"]) if os.environ.get("GRAVITY_METRICS_HOME", "").strip() else (g_home / "metrics")
    hp, md = m_home / "data" / "history.jsonl", m_home / "METRICS.md"
    if not hp.is_file() or not md.is_file():
        print(json.dumps({"ok": True, "status": "WARN", "summary": "history.jsonl/METRICS.md absent(s)", "warnings": [f"Module 'metrics' actif mais {hp} ou {md} absent : exécutez /gravity-metrics."]}))
        return 0
    for ln in hp.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                json.loads(ln)
            except ValueError as exc:
                print(json.dumps({"ok": True, "status": "WARN", "summary": "history.jsonl invalide", "warnings": [f"Module 'metrics' : {hp} corrompu ({exc})."]}))
                return 0
    print(json.dumps({"ok": True, "status": "OK", "summary": "1 session(s)", "warnings": []}))
    return 0

raise SystemExit(main())
"""

_WORKFLOW_HEALTH_STUB = """import json, os
from pathlib import Path

def main():
    g_home = Path(os.environ.get("GRAVITY_HOME") or (Path.home() / ".gemini" / "gravity"))
    w_home = Path(os.environ["GRAVITY_WORKFLOW_HOME"]) if os.environ.get("GRAVITY_WORKFLOW_HOME", "").strip() else (g_home / "workflow")
    ws_dir = w_home / "workspaces"
    if ws_dir.is_dir():
        for sub in ws_dir.iterdir():
            rj = sub / "runs.jsonl"
            if rj.is_file():
                for ln in rj.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        try:
                            json.loads(ln)
                        except ValueError as exc:
                            print(json.dumps({"ok": True, "status": "WARN", "summary": "runs.jsonl invalide", "warnings": [f"Module 'workflow' : {rj} corrompu ({exc})."]}))
                            return 0
    print(json.dumps({"ok": True, "status": "OK", "summary": "hooks.json OK", "warnings": []}))
    return 0

raise SystemExit(main())
"""


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
            _create_fake_module(plugins_dir, "metrics", "gravity-metrics", "GRAVITY_METRICS_HOME")

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
            self.assertEqual([t["id"] for t in out["tabs"]], ["live", "metrics", "overview"])

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

    def test_check_warns_non_blocking_for_missing_architect_and_metrics_without_bridge(self) -> None:
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
            _create_fake_spi_health_module(plugins_dir, "architect", "gravity-architect", "GRAVITY_ARCHITECT_HOME", _ARCHITECT_HEALTH_STUB)
            _create_fake_spi_health_module(plugins_dir, "metrics", "gravity-metrics", "GRAVITY_METRICS_HOME", _METRICS_HEALTH_STUB)

            gravity_home = tmp_path / "doctor-home"
            empty_bin = tmp_path / "empty-bin"
            empty_bin.mkdir()
            env = _isolated_env(fake_home, {"PATH": str(empty_bin)})

            # 1) Missing ateliers.json and missing history.jsonl/METRICS.md -> non-blocking warnings, exit 0, strictly RO
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
            self.assertIn("history.jsonl", joined)
            self.assertIn("/gravity-metrics", joined)
            self.assertNotIn("bridge", joined.lower())

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
            self.assertIn("/gravity-metrics", p_txt.stdout)
            self.assertFalse(gravity_home.exists())

            # 2) Empty ateliers.json (0 valid ateliers) -> still warns for architect + metrics
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

            # 3) Valid atelier + valid metrics + residual bridge/ directory -> 0 warning
            atelier_dir = tmp_path / "atelier-ok"
            atelier_dir.mkdir()
            (atelier_dir / "ECOSYSTEM.md").write_text("# Atelier\n", encoding="utf-8")
            (atelier_dir / "projects.json").write_text("{}", encoding="utf-8")
            (arch_home / "ateliers.json").write_text(
                json.dumps({"schema_version": 1, "ateliers": [{"workspace_path": str(atelier_dir)}]}),
                encoding="utf-8",
            )
            metrics_home = gravity_home / "metrics"
            (metrics_home / "data").mkdir(parents=True)
            (metrics_home / "data" / "history.jsonl").write_text('{"id":"s1"}\n', encoding="utf-8")
            (metrics_home / "METRICS.md").write_text("# Metrics\n", encoding="utf-8")
            residual_bridge = gravity_home / "bridge"
            residual_bridge.mkdir(parents=True)
            (residual_bridge / "bridge.db").write_bytes(b"corrupt residual")

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
            doctor, "_detect_windows_app_version", return_value=None
        ), mock.patch.object(
            doctor.shutil,
            "which",
            side_effect=lambda cmd: "/usr/bin/snap" if cmd == "snap" else None,
        ), mock.patch.object(
            doctor.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/bin/snap", "list", "antigravity"],
                returncode=0,
                stdout="Nom          Version  Revision\nantigravity  2.33.0   75\n",
                stderr="",
            ),
        ) as run_mock:
            info_old = doctor._detect_antigravity_app_version()
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
            doctor, "_detect_windows_app_version", return_value=None
        ), mock.patch.object(
            doctor.shutil,
            "which",
            side_effect=lambda cmd: "/usr/bin/snap" if cmd == "snap" else None,
        ), mock.patch.object(
            doctor.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/bin/snap", "list", "antigravity"],
                returncode=0,
                stdout="Name         Version  Rev\nantigravity  2.35.0   79\n",
                stderr="",
            ),
        ):
            info_ok = doctor._detect_antigravity_app_version()
            self.assertEqual(info_ok["version"], "2.35.0")
            self.assertEqual(info_ok["source"], "snap")
            self.assertTrue(info_ok["meets_mcp_app_min"])

        # 3) Fallback to dpkg-query when snap unavailable
        def _which_dpkg(cmd: str) -> str | None:
            return "/usr/bin/dpkg-query" if cmd == "dpkg-query" else None

        with mock.patch.object(
            doctor, "_detect_windows_app_version", return_value=None
        ), mock.patch.object(doctor.shutil, "which", side_effect=_which_dpkg), mock.patch.object(
            doctor.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/bin/dpkg-query", "-W", "-f=${Version}", "antigravity"],
                returncode=0,
                stdout="2.33.0-1732400000",
                stderr="",
            ),
        ) as run_dpkg:
            info_dpkg = doctor._detect_antigravity_app_version()
            self.assertEqual(info_dpkg["version"], "2.33.0")
            self.assertEqual(info_dpkg["source"], "dpkg")
            self.assertFalse(info_dpkg["meets_mcp_app_min"])
            self.assertEqual(info_dpkg["update_hint"], "sudo apt update && sudo apt upgrade antigravity")
            self.assertEqual(Path(run_dpkg.call_args.args[0][0]).name, "dpkg-query")

        # 4) Neither snap nor dpkg-query -> unknown (silent)
        with mock.patch.object(
            doctor, "_detect_windows_app_version", return_value=None
        ), mock.patch.object(doctor.shutil, "which", return_value=None):
            info_none = doctor._detect_antigravity_app_version()
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

    def test_detect_windows_app_version_winreg_mocked(self) -> None:
        class _FakeKey:
            def __init__(self, path: object, data: dict) -> None:
                self.path = path
                self.data = data

            def __enter__(self) -> "_FakeKey":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        class _FakeWinreg:
            HKEY_CURRENT_USER = "HKCU"
            HKEY_LOCAL_MACHINE = "HKLM"

            def __init__(self, tree: dict[tuple[str, str], dict[str, dict[str, str]]]) -> None:
                self.tree = tree

            def OpenKey(self, hive: object, subkey: str) -> _FakeKey:
                if isinstance(hive, _FakeKey):
                    parent = self.tree[hive.path]  # type: ignore[index]
                    if subkey not in parent:
                        raise OSError("missing subkey")
                    return _FakeKey((hive.path[0], hive.path[1], subkey), self.tree)  # type: ignore[index]
                key = (str(hive), subkey)
                if key not in self.tree:
                    raise OSError("missing root")
                return _FakeKey(key, self.tree)

            def EnumKey(self, key: _FakeKey, idx: int) -> str:
                names = list(self.tree[key.path].keys())  # type: ignore[index]
                if idx >= len(names):
                    raise OSError("no more")
                return names[idx]

            def QueryValueEx(self, key: _FakeKey, value_name: str) -> tuple[str, int]:
                hive, root_sub, app_sub = key.path  # type: ignore[misc]
                entry = self.tree[(hive, root_sub)][app_sub]
                if value_name not in entry:
                    raise OSError("missing value")
                return entry[value_name], 1

        class _NtOs:
            name = "nt"

        uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        tree_ok = {("HKCU", uninstall): {"ag": {"DisplayName": "Google Antigravity", "DisplayVersion": "2.35.1"}}}
        with mock.patch.object(doctor, "os", _NtOs()), mock.patch.object(doctor, "winreg", _FakeWinreg(tree_ok)):
            res_ok = doctor._detect_windows_app_version()
            self.assertIsNotNone(res_ok)
            assert res_ok is not None
            self.assertEqual(res_ok["version"], "2.35.1")
            self.assertEqual(res_ok["source"], "winreg")
            self.assertTrue(res_ok["meets_mcp_app_min"])

        wow = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        tree_old = {("HKLM", wow): {"ag": {"DisplayName": "Antigravity IDE", "DisplayVersion": "2.33.0"}}}
        with mock.patch.object(doctor, "os", _NtOs()), mock.patch.object(doctor, "winreg", _FakeWinreg(tree_old)):
            res_old = doctor._detect_windows_app_version()
            self.assertIsNotNone(res_old)
            assert res_old is not None
            self.assertEqual(res_old["version"], "2.33.0")
            self.assertFalse(res_old["meets_mcp_app_min"])

        with mock.patch.object(doctor, "os", _NtOs()), mock.patch.object(doctor, "winreg", _FakeWinreg({})):
            self.assertIsNone(doctor._detect_windows_app_version())

    def test_check_metrics_workflow_health_and_residual_bridge_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(REPO_ROOT / "plugin", plugins_dir / "gravity", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            _create_fake_spi_health_module(plugins_dir, "metrics", "gravity-metrics", "GRAVITY_METRICS_HOME", _METRICS_HEALTH_STUB)
            _create_fake_spi_health_module(plugins_dir, "workflow", "gravity-workflow", "GRAVITY_WORKFLOW_HOME", _WORKFLOW_HEALTH_STUB)
            (plugins_dir / "gravity-workflow" / "hooks.json").write_text('{"g": {"enabled": true}}\n', encoding="utf-8")

            gravity_home = tmp_path / "g-home"
            (gravity_home / "bridge").mkdir(parents=True)
            (gravity_home / "bridge" / "bridge.db").write_bytes(b"residual corrupt")

            (gravity_home / "metrics" / "data").mkdir(parents=True)
            (gravity_home / "metrics" / "data" / "history.jsonl").write_text('{"id":"s1"}\n', encoding="utf-8")
            (gravity_home / "metrics" / "METRICS.md").write_text("# Metrics\n", encoding="utf-8")

            wf_ws = gravity_home / "workflow" / "workspaces" / "ws-a"
            wf_ws.mkdir(parents=True)
            (wf_ws / "live_state.json").write_text('{"stage":"idle"}\n', encoding="utf-8")
            (wf_ws / "runs.jsonl").write_text('{"run":1}\n', encoding="utf-8")

            p_ok, rc_ok = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                check_only=True,
                app_version_detector=lambda: {"version": "2.35.0", "source": "winreg", "meets_mcp_app_min": True, "min_required": "2.34.0", "update_hint": ""},
            )
            self.assertEqual(rc_ok, 0)
            self.assertEqual(p_ok["warnings"], [])

            (gravity_home / "metrics" / "data" / "history.jsonl").write_text("{corrupt\n", encoding="utf-8")
            (wf_ws / "runs.jsonl").write_text("{corrupt\n", encoding="utf-8")
            p_warn, rc_warn = init_env.run_environment(
                gravity_home=gravity_home,
                plugins_dirs=[plugins_dir],
                home_dir=fake_home,
                check_only=True,
                app_version_detector=lambda: {"version": None, "source": "none", "meets_mcp_app_min": None, "min_required": "2.34.0", "update_hint": ""},
            )
            self.assertEqual(rc_warn, 0)
            joined = "\n".join(p_warn["warnings"])
            self.assertNotIn("bridge", joined.lower())
            self.assertIn("metrics", joined)
            self.assertIn("workflow", joined)

    def test_overview_mode_read_only_and_guide_no_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(REPO_ROOT / "plugin", plugins_dir / "gravity", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for i in range(1, 11):
                _create_fake_module(plugins_dir, f"mod{i}", f"gravity-mod{i}", f"GRAVITY_MOD{i}_HOME")

            gravity_home = tmp_path / "uninit-overview"
            env = _isolated_env(fake_home)

            p_ov = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(gravity_home), "--plugins-dir", str(plugins_dir), "--overview", "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15, check=False,
            )
            self.assertEqual(p_ov.returncode, 0, msg=p_ov.stderr or p_ov.stdout)
            self.assertFalse(gravity_home.exists())
            ov = json.loads(p_ov.stdout)
            self.assertEqual(ov["mode"], "overview")
            self.assertTrue(ov["ok"])
            self.assertEqual(len(ov["help"]), 5)
            self.assertTrue(all("status" in h for h in ov["module_health"]))

            p_ov_txt = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(gravity_home), "--plugins-dir", str(plugins_dir), "--overview"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15, check=False,
            )
            self.assertEqual(p_ov_txt.returncode, 0)
            self.assertIn("[OK]", p_ov_txt.stdout)
            self.assertIn("Démarrage / Init", p_ov_txt.stdout)
            self.assertFalse(gravity_home.exists())

            p_guide = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(gravity_home), "--plugins-dir", str(plugins_dir), "--guide"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15, check=False,
            )
            self.assertEqual(p_guide.returncode, 0)
            self.assertGreater(len(p_guide.stdout.splitlines()), 20)
            for i in range(1, 11):
                self.assertIn(f"mod{i}", p_guide.stdout)

            core_only_plugins = tmp_path / "core-only-plugins"
            shutil.copytree(REPO_ROOT / "plugin", core_only_plugins / "gravity", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            p_core_ov = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(gravity_home), "--plugins-dir", str(core_only_plugins), "--overview"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15, check=False,
            )
            self.assertEqual(p_core_ov.returncode, 0)
            self.assertNotIn("bridge", p_core_ov.stdout.lower())
            p_core_guide = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(gravity_home), "--plugins-dir", str(core_only_plugins), "--guide"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15, check=False,
            )
            self.assertEqual(p_core_guide.returncode, 0)
            self.assertNotIn("bridge", p_core_guide.stdout.lower())

            # --set-drive-dir + --update is rejected cleanly at argument parsing
            drive_dir = tmp_path / "drive"
            drive_dir.mkdir()
            p_bad = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--set-drive-dir", str(drive_dir), "--update"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15, check=False,
            )
            self.assertEqual(p_bad.returncode, 2)

    def test_init_rejects_symlinked_gravity_home_arg_and_env_without_target_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "user-home"
            fake_home.mkdir()
            plugins_dir = tmp_path / "plugins"
            shutil.copytree(REPO_ROOT / "plugin", plugins_dir / "gravity", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

            real_target = tmp_path / "real-target"
            real_target.mkdir()
            sym_home = tmp_path / "sym-home"
            os.symlink(real_target, sym_home)
            env_base = _isolated_env(fake_home)
            env_sym = _isolated_env(fake_home, {"GRAVITY_HOME": str(sym_home)})

            for extra_args, cur_env, expect_json in (
                (["--gravity-home", str(sym_home), "--json"], env_base, True),
                (["--gravity-home", str(sym_home)], env_base, False),
                (["--json"], env_sym, True),
            ):
                proc = subprocess.run(
                    [sys.executable, "-B", str(INIT_SCRIPT), "--plugins-dir", str(plugins_dir), *extra_args],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", env=cur_env, timeout=15, check=False,
                )
                self.assertEqual(proc.returncode, 1)
                if expect_json:
                    out = json.loads(proc.stdout)
                    self.assertFalse(out["ok"])
                    self.assertIn("symlink", out["error"].lower())
                else:
                    self.assertIn("symlink", (proc.stdout + proc.stderr).lower())
                self.assertEqual(list(real_target.rglob("*")), [])

            g_home_core = tmp_path / "real-gravity-home"
            g_home_core.mkdir()
            core_target = tmp_path / "core-target"
            core_target.mkdir()
            os.symlink(core_target, g_home_core / "core")
            p_core = subprocess.run(
                [sys.executable, "-B", str(INIT_SCRIPT), "--gravity-home", str(g_home_core), "--plugins-dir", str(plugins_dir), "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env_base, timeout=15, check=False,
            )
            self.assertEqual(p_core.returncode, 1)
            self.assertFalse(json.loads(p_core.stdout)["ok"])
            self.assertEqual(list(core_target.rglob("*")), [])

    def test_doctor_spi_health_fallback_boundaries_and_no_dashboard_import(self) -> None:
        import ast

        core_dir = PLUGIN_ROOT / "core"
        for py_path in sorted(core_dir.glob("*.py")):
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name.startswith("dashboard"), msg=f"{py_path.name} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod_name = node.module or ""
                    self.assertFalse(mod_name.startswith("dashboard"), msg=f"{py_path.name} imports from {mod_name}")
                elif isinstance(node, ast.Call) and py_path.name in ("doctor.py", "overview.py"):
                    if isinstance(node.func, ast.Name):
                        self.assertNotEqual(node.func.id, "print", msg=f"{py_path.name} calls print()")

        doctor_src = (core_dir / "doctor.py").read_text(encoding="utf-8")
        for forbidden in ("ateliers.json", "history.jsonl", "METRICS.md", "hooks.json", "live_workspaces.json", "live_state.json", "runs.jsonl"):
            self.assertNotIn(forbidden, doctor_src)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mod_home = tmp_path / "comp-home"
            mod_base = {
                "id": "architect",
                "plugin_name": "gravity-architect",
                "version": "1.0.0",
                "valid": True,
                "commands": ["/gravity-architect"],
                "resolved_home": str(mod_home),
                "dashboard": {"provider_script": "scripts/dashboard_provider.py", "views": ["health"]},
            }

            # 1) health_provider_fn=None -> generic safe fallback (does not read internal files)
            res_none = doctor._inspect_module_health_ro(mod_base, health_provider_fn=None)
            self.assertEqual(res_none["status"], "OK")
            self.assertEqual(res_none["summary"], "home non initialisé")
            self.assertEqual(res_none["warnings"], [])

            mod_home.mkdir()
            res_present = doctor._inspect_module_health_ro(mod_base, health_provider_fn=None)
            self.assertEqual(res_present["summary"], "home présent")

            # 2) "health" not declared in dashboard.views -> generic safe fallback, provider not called
            mod_no_health = {**mod_base, "dashboard": {"provider_script": "scripts/dashboard_provider.py", "views": ["architect"]}}
            called: list[str] = []

            def _should_not_run(mid: str, **_: object) -> dict[str, object]:
                called.append(mid)
                return {"ok": True, "status": "WARN", "summary": "unexpected", "warnings": ["unexpected"]}

            res_no_view = doctor._inspect_module_health_ro(mod_no_health, health_provider_fn=_should_not_run)
            self.assertEqual(called, [])
            self.assertEqual(res_no_view["status"], "OK")
            self.assertEqual(res_no_view["summary"], "home présent")

            # 3) spi_fallback=True -> generic safe fallback
            res_spi_fb = doctor._inspect_module_health_ro(
                mod_base,
                health_provider_fn=lambda mid, **kw: {"available": False, "spi_fallback": True, "error": "timeout"},
            )
            self.assertEqual(res_spi_fb["status"], "OK")
            self.assertEqual(res_spi_fb["summary"], "home présent")
            self.assertEqual(res_spi_fb["warnings"], [])

            # 4) Valid SPI-1 --view health response & propagation of gravity_home/plugin_roots/home_dir
            seen_kwargs: dict[str, object] = {}

            def _fake_health(mid: str, **kw: object) -> dict[str, object]:
                seen_kwargs["mod_id"] = mid
                seen_kwargs.update(kw)
                return {"ok": True, "status": "WARN", "summary": "2 alertes", "warnings": ["Module 'architect' : alerte test"]}

            g_home = tmp_path / "g-home"
            p_root = tmp_path / "plugins"
            u_home = tmp_path / "user"
            res_ok = doctor._inspect_module_health_ro(
                mod_base,
                gravity_home=g_home,
                plugin_roots=[p_root],
                home_dir=u_home,
                health_provider_fn=_fake_health,
            )
            self.assertEqual(seen_kwargs, {"mod_id": "architect", "gravity_home": g_home, "plugin_roots": [p_root], "home_dir": u_home})
            self.assertEqual(res_ok["status"], "WARN")
            self.assertEqual(res_ok["summary"], "2 alertes")
            self.assertEqual(res_ok["warnings"], ["Module 'architect' : alerte test"])

            # 5) Symlinked mod_home -> WARN without calling provider
            sym_home = tmp_path / "sym-home"
            os.symlink(mod_home, sym_home)
            res_sym = doctor._inspect_module_health_ro({**mod_base, "resolved_home": str(sym_home)}, health_provider_fn=_should_not_run)
            self.assertEqual(called, [])
            self.assertEqual(res_sym["status"], "WARN")
            self.assertEqual(res_sym["summary"], "home symlink refusé")

            # 6) init_env._invoke_health_provider forwards view="health" and timeout_s=5.0
            from dashboard.providers import spi as spi_mod  # noqa: E402

            with mock.patch.object(spi_mod, "invoke_dashboard_provider", return_value={"ok": True, "status": "OK", "summary": "ok", "warnings": []}) as inv_mock:
                init_env._invoke_health_provider("architect", gravity_home=g_home, plugin_roots=[p_root], home_dir=u_home)
                inv_mock.assert_called_once_with(
                    "architect",
                    view="health",
                    gravity_home=g_home,
                    plugin_roots=[p_root],
                    home_dir=u_home,
                    timeout_s=5.0,
                )

            # 7) format_guide_report is pure and _print_guide_report prints it
            from core import overview  # noqa: E402

            guide_payload, _ = overview.run_guide_mode(gravity_home=g_home, plugins_dirs=[], home_dir=u_home)
            buf_guide = io.StringIO()
            with redirect_stdout(buf_guide):
                guide_str = overview.format_guide_report(guide_payload)
            self.assertEqual(buf_guide.getvalue(), "")
            self.assertIn("Gravity Core — Guide rapide", guide_str)
            buf_cli_guide = io.StringIO()
            with redirect_stdout(buf_cli_guide):
                init_env._print_guide_report(guide_payload)
            self.assertEqual(buf_cli_guide.getvalue(), guide_str + "\n")


if __name__ == "__main__":
    unittest.main()

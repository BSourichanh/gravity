"""Isolated unit tests for scripts/audit_ecosystem.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDITOR = REPO_ROOT / "scripts" / "audit_ecosystem.py"

ALL_FLAGS = (
    "--scope",
    "--workspace",
    "--target",
    "--method",
    "--force",
    "--skip-validate",
    "--strict",
    "--no-fix-python",
    "--dry-run",
    "--check",
    "--uninstall",
)


def _write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _make_installer_source(flags: tuple[str, ...] = ALL_FLAGS) -> str:
    lines = [
        "import argparse",
        "def build_parser():",
        "    parser = argparse.ArgumentParser()",
    ]
    for flag in flags:
        lines.append(f"    parser.add_argument({flag!r})")
    lines.append("    return parser")
    return "\n".join(lines) + "\n"


def _make_validator_source(*, include_fix_python: bool = True) -> str:
    fix_line = "    parser.add_argument('--fix-python-cmd', action='store_true')\n" if include_fix_python else ""
    return (
        "import argparse\n"
        "import sys\n"
        "OFFICIAL_PLUGIN_FIELDS = {\n"
        "    'name', 'displayName', 'version', 'description', 'logo',\n"
        "    'suggestedPrompts', 'author', 'homepage', 'repository',\n"
        "}\n"
        "UTF8_BOM = b'\\xef\\xbb\\xbf'\n"
        "def check():\n"
        "    _ = ('plugin.json', 'config/module.json', 'schema_version', sys.stdlib_module_names, b'\\r\\n')\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--strict', action='store_true')\n"
        + fix_line
        + "    return 0\n"
    )


def _make_agents_md(repo_name: str) -> str:
    return (
        f"# {repo_name}\n\n"
        "## Périmètre & Architecture\n"
        "Plugin autonome 100 % stdlib Python 3.10+.\n\n"
        "## Invariants\n"
        "KISS, YAGNI, DRY, SOLID, CUPID ; UTF-8 sans BOM, LF.\n\n"
        "## Vérifications obligatoires\n"
        "- `python plugin/scripts/validate.py --strict`\n"
    )


def _make_manifest(
    name: str,
    *,
    version: str = "0.2.0",
    prompts: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    data = {
        "name": name,
        "displayName": name.title(),
        "version": version,
        "description": "Plugin Gravity conforme pour tests isolés.",
        "logo": "assets/logo.svg",
        "suggestedPrompts": prompts
        if prompts is not None
        else [
            f"/{name} init — Initialiser le module",
            f"/{name} status — Consulter l'état",
            f"/{name} doctor — Diagnostiquer l'installation",
        ],
        "author": {"name": "Gravity Contributors"},
        "homepage": f"https://github.com/BSourichanh/{name}",
        "repository": f"https://github.com/BSourichanh/{name}.git",
    }
    if extra:
        data.update(extra)
    return data


def _make_changelog(version: str = "0.2.0") -> str:
    return (
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        f"## [{version}] - 2026-11-23\n\n"
        "### Added\n"
        "- Initial release.\n"
    )


def _make_module_contract(
    name: str,
    *,
    mod_id: str | None = None,
    commands: list[str] | None = None,
    ui_mode: str | None = None,
) -> dict:
    resolved_id = mod_id or ("core" if name == "gravity" else name.removeprefix("gravity-"))
    return {
        "schema_version": 1,
        "id": resolved_id,
        "plugin_name": name,
        "role": f"Role {resolved_id}",
        "storage": {"subdir": resolved_id, "env_override": f"GRAVITY_{resolved_id.upper()}_HOME"},
        "commands": commands if commands is not None else [f"/{name}"],
        "capabilities": ["test-cap"],
        "ui": {"mode": ui_mode or ("core" if name == "gravity" else "none"), "target": "gravity"},
        "signals": {"produces": [], "consumes": []},
    }


def _create_compliant_repo(
    repos_root: Path,
    name: str,
    *,
    with_rules: bool = True,
    with_mcp_config: bool = False,
) -> Path:
    repo_dir = repos_root / name
    plugin_dir = repo_dir / "plugin"
    _write_lf(repo_dir / "install.py", _make_installer_source())
    _write_lf(repo_dir / "AGENTS.md", _make_agents_md(name))
    _write_lf(repo_dir / "CHANGELOG.md", _make_changelog("0.2.0"))
    _write_lf(repo_dir / "README.md", f"# {name}\n\nCommande `/{name}` · [Plugin](plugin/README.md)\n")
    _write_lf(plugin_dir / "README.md", f"# {name} Plugin\n")
    _write_lf(
        plugin_dir / "skills" / name / "SKILL.md",
        f"---\nname: {name}\ndescription: \"Skill {name}\"\n---\n\n# {name}\n\nUtiliser `/{name}`.\n",
    )
    _write_lf(
        plugin_dir / "config" / "module.json",
        json.dumps(_make_module_contract(name), indent=2, ensure_ascii=False) + "\n",
    )
    _write_lf(
        plugin_dir / "plugin.json",
        json.dumps(_make_manifest(name), indent=2, ensure_ascii=False) + "\n",
    )
    _write_lf(
        plugin_dir / "scripts" / "validate.py",
        _make_validator_source(include_fix_python=with_mcp_config),
    )
    if with_mcp_config:
        _write_lf(
            plugin_dir / "mcp_config.json",
            '{"mcpServers": {"srv": {"command": "python3", "args": ["${PLUGIN_ROOT}/mcp/server.py"]}}}\n',
        )
    if with_rules:
        _write_lf(plugin_dir / "rules" / "AGENTS.md", f"# {name}\n\n- Règle légère D4.\n")
    return repo_dir


def _run_auditor(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(AUDITOR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=20,
        check=False,
    )


class TestAuditEcosystem(unittest.TestCase):
    def test_compliant_ecosystem_passes_even_strict_with_mcp_ui_exemption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _create_compliant_repo(root, "gravity", with_mcp_config=True)
            _create_compliant_repo(root, "gravity-workflow", with_rules=False, with_mcp_config=True)
            _create_compliant_repo(root, "gravity-metrics", with_mcp_config=True)
            _create_compliant_repo(root, "gravity-architect", with_mcp_config=False)
            _write_lf(
                root / "gravity-architect" / "plugin" / "rules" / "AGENTS.md",
                "# Gravity Architect\n\n- Hot/Cold, `audits/code/` isolé d'`audits/agents/`.\n",
            )
            _create_compliant_repo(root, "gravity-bridge", with_mcp_config=True)

            # Embedded frontend bundle > 1500 lines under plugin/mcp/ui/ must be exempted
            _write_lf(
                root / "gravity" / "plugin" / "mcp" / "ui" / "views_js.py",
                "JS = '''\n" + ("console.log(1);\n" * 1600) + "'''\n",
            )

            proc = _run_auditor(["--repos-root", str(root), "--strict", "--json"])
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["pass_count"], 5)
            self.assertEqual(payload["summary"]["total_errors"], 0)
            self.assertEqual(payload["summary"]["total_warnings"], 0)

            gw = next(r for r in payload["repos"] if r["repo"] == "gravity-workflow")
            self.assertTrue(gw["checks"]["rules_d4"]["exempt"])
            gr = next(r for r in payload["repos"] if r["repo"] == "gravity")
            self.assertEqual(len(gr["checks"]["monoliths"]["exempt_files"]), 1)

    def test_incomplete_install_cli_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity")
            incomplete_flags = tuple(f for f in ALL_FLAGS if f not in ("--strict", "--no-fix-python"))
            _write_lf(repo / "install.py", _make_installer_source(incomplete_flags))

            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["ok"])
            missing = payload["repos"][0]["checks"]["install_cli"]["missing"]
            self.assertEqual(missing, ["--strict", "--no-fix-python"])

    def test_validate_contract_detects_missing_fix_python_cmd_when_manifest_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-bridge", with_mcp_config=True)
            _write_lf(
                repo / "plugin" / "scripts" / "validate.py",
                _make_validator_source(include_fix_python=False),
            )

            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-bridge", "--json"])
            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            missing = payload["repos"][0]["checks"]["validate_contract"]["missing"]
            self.assertIn("--fix-python-cmd", missing)

    def test_rules_d4_warn_at_650b_and_error_at_1050b(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_warn = _create_compliant_repo(root, "gravity")
            _write_lf(repo_warn / "plugin" / "rules" / "AGENTS.md", "# Rule\n" + ("a" * 643))

            # 650 bytes: exit 0 without --strict, exit 1 with --strict
            p_nonstrict = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_nonstrict.returncode, 0, msg=p_nonstrict.stdout)
            out_ns = json.loads(p_nonstrict.stdout)
            self.assertEqual(out_ns["repos"][0]["status"], "WARN")
            self.assertEqual(out_ns["repos"][0]["checks"]["rules_d4"]["severity"], "warn")

            p_strict = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--strict"])
            self.assertEqual(p_strict.returncode, 1)

            # 1050 bytes: error even without --strict
            _write_lf(repo_warn / "plugin" / "rules" / "AGENTS.md", "# Rule\n" + ("b" * 1043))
            p_err = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_err.returncode, 1)
            out_err = json.loads(p_err.stdout)
            self.assertEqual(out_err["repos"][0]["status"], "FAIL")
            self.assertEqual(out_err["repos"][0]["checks"]["rules_d4"]["severity"], "error")

    def test_rules_d4_rejects_yaml_frontmatter_and_root_agents_checks_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-metrics")
            _write_lf(repo / "plugin" / "rules" / "AGENTS.md", "---\ntrigger: always_on\n---\n# Rule\n")
            _write_lf(repo / "AGENTS.md", "# Title\n\n## Only Two\nfoo\n\n## Sections\nbar\n")

            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-metrics", "--json"])
            self.assertEqual(proc.returncode, 1)
            errs = "\n".join(json.loads(proc.stdout)["repos"][0]["errors"])
            self.assertIn("frontmatter YAML", errs)
            self.assertIn("2 section(s) '##'", errs)

    def test_manifest_changelog_sync_and_suggested_prompts_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-architect")
            bad_manifest = _make_manifest(
                "gravity-architect",
                version="0.9.9",
                prompts=[
                    "/gravity-architect init Sans séparateur",
                    "/gravity-architect sync — " + ("x" * 90),
                    "/gravity-architect audit — OK",
                ],
                extra={"$schema": "https://example.com/schema.json"},
            )
            _write_lf(
                repo / "plugin" / "plugin.json",
                json.dumps(bad_manifest, indent=2, ensure_ascii=False) + "\n",
            )

            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-architect", "--json"])
            self.assertEqual(proc.returncode, 1)
            errs = "\n".join(json.loads(proc.stdout)["repos"][0]["errors"])
            self.assertIn("champs non officiels", errs)
            self.assertIn("Désynchronisation SemVer", errs)
            self.assertIn("suggestedPrompts[0]", errs)
            self.assertIn("suggestedPrompts[1]", errs)

    def test_monolith_thresholds_warn_error_and_ui_exemption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity")
            _write_lf(repo / "plugin" / "mcp" / "ui" / "styles.py", "CSS = ''\n" + ("x = 1\n" * 1700))
            _write_lf(repo / "plugin" / "core" / "medium.py", "x = 1\n" * 850)

            p_warn = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_warn.returncode, 0, msg=p_warn.stdout)
            r0 = json.loads(p_warn.stdout)["repos"][0]
            self.assertEqual(r0["status"], "WARN")
            self.assertEqual(len(r0["checks"]["monoliths"]["warn_files"]), 1)
            self.assertEqual(len(r0["checks"]["monoliths"]["exempt_files"]), 1)

            p_strict = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--strict"])
            self.assertEqual(p_strict.returncode, 1)

            _write_lf(repo / "plugin" / "core" / "huge.py", "x = 1\n" * 1550)
            p_err = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_err.returncode, 1)
            r1 = json.loads(p_err.stdout)["repos"][0]
            self.assertEqual(r1["status"], "FAIL")
            self.assertEqual(len(r1["checks"]["monoliths"]["error_files"]), 1)

    def test_int_checks_01_02_03_04_08(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-metrics")
            # INT-01: invalid ui.mode + plugin_name mismatch
            bad_mod = _make_module_contract("gravity-metrics", ui_mode="invalid-mode")
            bad_mod["plugin_name"] = "wrong-name"
            _write_lf(repo / "plugin" / "config" / "module.json", json.dumps(bad_mod, indent=2) + "\n")
            # INT-02: broken link and file: URI
            _write_lf(repo / "docs" / "guide.md", "[Missing](missing.md)\n[Local](file:///tmp/x)\n")
            # INT-03: CRLF in yaml file
            (repo / "plugin" / "extra.yaml").write_bytes(b"key: val\r\n")
            # INT-04: personal path outside tests/ (tests/ must be ignored)
            _write_lf(repo / "tests" / "sample.py", "P = 'C:\\\\Users\\\\Demo\\\\file'\n")
            _write_lf(repo / "plugin" / "leak.py", "P = '/home/alice/secret/'\n")
            # INT-08: undocumented command
            bad_mod["commands"] = ["/gravity-metrics", "/undocumented-cmd"]
            _write_lf(repo / "plugin" / "config" / "module.json", json.dumps(bad_mod, indent=2) + "\n")

            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-metrics", "--json"])
            self.assertEqual(proc.returncode, 1)
            rep = json.loads(proc.stdout)["repos"][0]
            errs = "\n".join(rep["errors"])
            self.assertIn("INT-01", errs)
            self.assertIn("INT-02", errs)
            self.assertIn("INT-03", errs)
            self.assertIn("INT-04", errs)
            self.assertIn("INT-08", errs)
            self.assertNotIn("tests/sample.py", errs)

    def test_int_03_skips_root_dot_agents_but_scans_template_dot_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-architect")
            (repo / ".agents" / "rules").mkdir(parents=True)
            (repo / ".agents" / "rules" / "05-git-versioning.md").write_bytes(b"# Rule\r\n")

            ok_proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-architect", "--json"])
            self.assertEqual(ok_proc.returncode, 0, msg=ok_proc.stdout + ok_proc.stderr)
            self.assertTrue(json.loads(ok_proc.stdout)["repos"][0]["checks"]["encoding_hygiene"]["ok"])

            (repo / "workspace-template" / ".agents" / "rules").mkdir(parents=True)
            (repo / "workspace-template" / ".agents" / "rules" / "05-git-versioning.md").write_bytes(b"# Rule\r\n")
            bad_proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-architect", "--json"])
            self.assertEqual(bad_proc.returncode, 1)
            errs = "\n".join(json.loads(bad_proc.stdout)["repos"][0]["errors"])
            self.assertIn("INT-03", errs)
            self.assertIn("workspace-template/.agents/rules/05-git-versioning.md", errs)

    def test_int_05_check_installed_tolerates_windows_python_adaptation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity", with_mcp_config=True)
            _write_lf(
                repo / "plugin" / "hooks.json",
                '{"g": {"PreInvocation": [{"type": "command", "command": "python3 hooks/p.py"}]}}\n',
            )
            plugins_dir = root / "installed-plugins"
            inst = plugins_dir / "gravity"
            import shutil

            shutil.copytree(repo / "plugin", inst)
            # Simulate Windows install adaptation (python3 -> py -3 / python)
            _write_lf(
                inst / "mcp_config.json",
                '{"mcpServers": {"srv": {"command": "py", "args": ["-3", "${PLUGIN_ROOT}/mcp/server.py"]}}}\n',
            )
            _write_lf(
                inst / "hooks.json",
                '{"g": {"PreInvocation": [{"type": "command", "command": "python hooks/p.py"}]}}\n',
            )

            ok_proc = _run_auditor(
                [
                    "--repos-root", str(root),
                    "--repos", "gravity",
                    "--check-installed",
                    "--plugins-dir", str(plugins_dir),
                    "--strict",
                    "--json",
                ]
            )
            self.assertEqual(ok_proc.returncode, 0, msg=ok_proc.stdout + ok_proc.stderr)
            self.assertTrue(json.loads(ok_proc.stdout)["repos"][0]["checks"]["installed_sync"]["ok"])

            # Introduce real drift in installed copy
            _write_lf(inst / "README.md", "# Drifted\n")
            bad_proc = _run_auditor(
                [
                    "--repos-root", str(root),
                    "--repos", "gravity",
                    "--check-installed",
                    "--plugins-dir", str(plugins_dir),
                    "--json",
                ]
            )
            self.assertEqual(bad_proc.returncode, 1)
            self.assertIn("INT-05", "\n".join(json.loads(bad_proc.stdout)["repos"][0]["errors"]))

    def test_cross_repo_cumulative_rules_budget_contradictions_and_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ("gravity", "gravity-metrics", "gravity-architect", "gravity-bridge")
            for n in names:
                _create_compliant_repo(root, n)

            # 4 * 850 B = 3400 B (> 3000 warn, <= 4500 error) -> each repo > 600 warn too
            for n in names:
                _write_lf(root / n / "plugin" / "rules" / "AGENTS.md", "# R\n" + ("x" * 846))

            p_warn = _run_auditor(["--repos-root", str(root), "--repos", ",".join(names), "--json"])
            self.assertEqual(p_warn.returncode, 0, msg=p_warn.stdout)
            payload_w = json.loads(p_warn.stdout)
            self.assertEqual(payload_w["cross_repo"]["warnings"] != [], True)
            self.assertEqual(payload_w["cross_repo"]["errors"], [])

            p_strict = _run_auditor(["--repos-root", str(root), "--repos", ",".join(names), "--strict"])
            self.assertEqual(p_strict.returncode, 1)

            # Exceed 4500 B cumulative? Wait: keep each <= 1000 B? With 5 repos * 950 B = 4750 B > 4500 error!
            _create_compliant_repo(root, "gravity-extra")
            for n in (*names, "gravity-extra"):
                _write_lf(root / n / "plugin" / "rules" / "AGENTS.md", "# R\n" + ("x" * 946))

            # Add rule contradictions + id/command collision (keep gravity-bridge rules at 950 B -> total 4750 B > 4500)
            bridge_rule = "# Bridge\n- Activer le dispatch proactif automatique.\n"
            _write_lf(
                root / "gravity-bridge" / "plugin" / "rules" / "AGENTS.md",
                bridge_rule + ("x" * (950 - len(bridge_rule.encode("utf-8")))),
            )
            _write_lf(
                root / "gravity-architect" / "AGENTS.md",
                "## A\ndev direct sur main.\n\n## B\nStocker audits/code/ et audits/agents/ ensemble.\n\n## C\nok\n",
            )
            _write_lf(
                root / "gravity-extra" / "plugin" / "config" / "module.json",
                json.dumps(_make_module_contract("gravity-extra", mod_id="core", commands=["/gravity"]), indent=2) + "\n",
            )
            _write_lf(root / "gravity-extra" / "README.md", "# Extra\n/gravity\n")

            p_err = _run_auditor(
                ["--repos-root", str(root), "--repos", ",".join((*names, "gravity-extra")), "--json"]
            )
            self.assertEqual(p_err.returncode, 1)
            cross = json.loads(p_err.stdout)["cross_repo"]
            cross_errs = "\n".join(cross["errors"])
            self.assertIn("Budget cumulé", cross_errs)
            self.assertIn("core", cross["id_collisions"])
            self.assertIn("/gravity", cross["command_collisions"])
            self.assertTrue(any("Bridge" in c for c in cross["contradictions"]))
            self.assertTrue(any("main" in c for c in cross["contradictions"]))
            self.assertTrue(any("audits/" in c for c in cross["contradictions"]))


if __name__ == "__main__":
    unittest.main()

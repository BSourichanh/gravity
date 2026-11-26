"""Isolated unit tests for scripts/audit_ecosystem.py and scripts/audit_checks.py."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDITOR = REPO_ROOT / "scripts" / "audit_ecosystem.py"
REAL_SHARED_DIR = REPO_ROOT / "plugin" / "_shared"

ALL_FLAGS = (
    "--scope", "--workspace", "--target", "--method", "--force",
    "--skip-validate", "--strict", "--no-fix-python", "--dry-run", "--check", "--uninstall",
)


def _write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _make_installer_source(flags: tuple[str, ...] = ALL_FLAGS) -> str:
    lines = ["import argparse", "def build_parser():", "    parser = argparse.ArgumentParser()"]
    lines.extend(f"    parser.add_argument({flag!r})" for flag in flags)
    lines.append("    return parser")
    return "\n".join(lines) + "\n"


def _make_validator_source(*, include_fix_python: bool = True) -> str:
    fix_line = "    parser.add_argument('--fix-python-cmd', action='store_true')\n" if include_fix_python else ""
    return (
        "import argparse\nimport sys\n"
        "OFFICIAL_PLUGIN_FIELDS = {\n"
        "    'name', 'displayName', 'version', 'description', 'logo',\n"
        "    'suggestedPrompts', 'author', 'homepage', 'repository',\n}\n"
        "UTF8_BOM = b'\\xef\\xbb\\xbf'\n"
        "def check():\n"
        "    _ = ('plugin.json', 'config/module.json', 'schema_version', sys.stdlib_module_names, b'\\r\\n')\n"
        "def main():\n    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--strict', action='store_true')\n"
        + fix_line + "    return 0\n"
    )


def _make_agents_md(repo_name: str) -> str:
    return (
        f"# {repo_name}\n\n"
        "## Périmètre & Architecture\nPlugin autonome 100 % stdlib Python 3.10+.\n\n"
        "## Invariants\nKISS, YAGNI, DRY, SOLID, CUPID ; UTF-8 sans BOM, LF.\n\n"
        "## Vérifications obligatoires\n- `python plugin/scripts/validate.py --strict`\n"
    )


def _make_manifest(
    name: str, *, version: str = "0.2.0", prompts: list[str] | None = None, extra: dict | None = None,
) -> dict:
    data = {
        "name": name, "displayName": name.title(), "version": version,
        "description": "Plugin Gravity conforme pour tests isolés.", "logo": "assets/logo.svg",
        "suggestedPrompts": prompts if prompts is not None else [
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
    return f"# Changelog\n\n## [Unreleased]\n\n## [{version}] - 2026-11-23\n\n### Added\n- Initial release.\n"


def _make_module_contract(
    name: str, *, mod_id: str | None = None, commands: list[str] | None = None, ui_mode: str | None = None,
) -> dict:
    resolved_id = mod_id or ("core" if name == "gravity" else name.removeprefix("gravity-"))
    return {
        "schema_version": 1, "id": resolved_id, "plugin_name": name, "role": f"Role {resolved_id}",
        "storage": {"subdir": resolved_id, "env_override": f"GRAVITY_{resolved_id.upper()}_HOME"},
        "commands": commands if commands is not None else [f"/{name}"],
        "capabilities": ["test-cap"],
        "ui": {"mode": ui_mode or ("core" if name == "gravity" else "none"), "target": "gravity"},
        "signals": {"produces": [], "consumes": []},
    }


def _create_compliant_repo(
    repos_root: Path, name: str, *, with_rules: bool = True, with_mcp_config: bool = False,
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
    _write_lf(plugin_dir / "config" / "module.json", json.dumps(_make_module_contract(name), indent=2, ensure_ascii=False) + "\n")
    _write_lf(plugin_dir / "plugin.json", json.dumps(_make_manifest(name), indent=2, ensure_ascii=False) + "\n")
    _write_lf(plugin_dir / "scripts" / "validate.py", _make_validator_source(include_fix_python=with_mcp_config))
    if with_mcp_config:
        _write_lf(plugin_dir / "mcp_config.json", '{"mcpServers": {"srv": {"command": "python3", "args": ["${PLUGIN_ROOT}/mcp/server.py"]}}}\n')
    if with_rules:
        _write_lf(plugin_dir / "rules" / "AGENTS.md", f"# {name}\n\n- Règle légère D4.\n")
    return repo_dir


def _seed_shared_sync(repos_root: Path, repos: tuple[str, ...]) -> None:
    ssot = repos_root / "gravity" / "shared" / "gravity_shared"
    ssot.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for fname in ("__init__.py", "atomic_io.py"):
        raw = (REAL_SHARED_DIR / fname).read_bytes()
        (ssot / fname).write_bytes(raw)
        hashes[fname] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema_version": 1, "source_repo": "gravity",
        "source_path": "shared/gravity_shared", "generated_at": "2026-11-26T00:00:00Z", "files": hashes,
    }
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    for rname in repos:
        pdir = repos_root / rname / "plugin"
        sdir = pdir / "_shared"
        sdir.mkdir(parents=True, exist_ok=True)
        for fname in hashes:
            (sdir / fname).write_bytes((ssot / fname).read_bytes())
        _write_lf(pdir / ".shared_manifest.json", manifest_text)


def _run_auditor(args: list[str], *, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-B", str(AUDITOR), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30, check=False,
    )


def _install_fake_agy(bin_dir: Path, *, fail_repo: str | None = None) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    runner = bin_dir / "agy_runner.py"
    _write_lf(
        runner,
        (
            "import sys\nfrom pathlib import Path\nrepo = Path.cwd().name\n"
            "print(f'agy:{repo}:' + ' '.join(sys.argv[1:]))\n"
            f"if repo == {fail_repo!r}:\n    print(f'forced agy failure on {{repo}}', file=sys.stderr)\n    raise SystemExit(1)\n"
        ),
    )
    if os.name == "nt":
        (bin_dir / "agy.cmd").write_text(f'@echo off\r\n"{sys.executable}" -B "%~dp0agy_runner.py" %*\r\n', encoding="utf-8")
    else:
        sh_path = bin_dir / "agy"
        _write_lf(sh_path, f'#!/bin/sh\nexec "{sys.executable}" -B "$(dirname "$0")/agy_runner.py" "$@"\n')
        sh_path.chmod(0o755)


class TestAuditEcosystem(unittest.TestCase):
    def test_compliant_ecosystem_passes_even_strict_with_mcp_ui_exemption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _create_compliant_repo(root, "gravity", with_mcp_config=True)
            _create_compliant_repo(root, "gravity-workflow", with_rules=False, with_mcp_config=True)
            _create_compliant_repo(root, "gravity-metrics", with_mcp_config=True)
            _create_compliant_repo(root, "gravity-architect", with_mcp_config=False)
            _write_lf(root / "gravity-architect" / "plugin" / "rules" / "AGENTS.md", "# Gravity Architect\n\n- Hot/Cold, `audits/code/` isolé d'`audits/agents/`.\n")
            (root / "gravity-bridge").mkdir()
            _write_lf(root / "gravity" / "plugin" / "mcp" / "ui" / "views_js.py", "JS = '''\n" + ("console.log(1);\n" * 1600) + "'''\n")

            proc = _run_auditor(["--repos-root", str(root), "--strict", "--json"])
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["repo_count"], 4)
            self.assertEqual(payload["summary"]["pass_count"], 4)
            self.assertNotIn("gravity-bridge", [r["repo"] for r in payload["repos"]])
            self.assertEqual(payload["summary"]["total_errors"], 0)
            self.assertEqual(payload["summary"]["total_warnings"], 0)
            self.assertTrue(next(r for r in payload["repos"] if r["repo"] == "gravity-workflow")["checks"]["rules_d4"]["exempt"])
            self.assertEqual(len(next(r for r in payload["repos"] if r["repo"] == "gravity")["checks"]["monoliths"]["exempt_files"]), 1)

    def test_incomplete_install_cli_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity")
            _write_lf(repo / "install.py", _make_installer_source(tuple(f for f in ALL_FLAGS if f not in ("--strict", "--no-fix-python"))))
            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["repos"][0]["checks"]["install_cli"]["missing"], ["--strict", "--no-fix-python"])

    def test_shared_ast_delegation_pass_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity", with_mcp_config=True)
            _write_lf(repo / "install.py", "from _shared.installer_core import InstallSpec, run_installer\ndef main():\n    return run_installer(InstallSpec('gravity', 'plugin'))\n")
            _write_lf(repo / "plugin" / "scripts" / "validate.py", "from _shared.validator_core import ValidatorConfig, run_cli\ndef main():\n    return run_cli(ValidatorConfig('plugin'))\n")

            # Missing _shared/{installer_core,validator_core}.py must fail closed
            p_miss = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_miss.returncode, 1)
            rep_miss = json.loads(p_miss.stdout)["repos"][0]
            self.assertFalse(rep_miss["checks"]["install_cli"]["ok"])
            self.assertFalse(rep_miss["checks"]["validate_contract"]["ok"])

            # Copy real _shared/{installer_core,validator_core}.py -> must pass AST delegation
            sdir = repo / "plugin" / "_shared"
            sdir.mkdir(parents=True, exist_ok=True)
            manifest_files = {}
            for fn in ("__init__.py", "atomic_io.py", "file_lock.py", "hook_runtime.py", "installer_core.py", "path_safety.py", "validator_core.py"):
                raw = (REAL_SHARED_DIR / fn).read_bytes()
                (sdir / fn).write_bytes(raw)
                manifest_files[fn] = hashlib.sha256(raw).hexdigest()
            _write_lf(repo / "plugin" / ".shared_manifest.json", json.dumps({"schema_version": 1, "source_repo": "gravity", "source_path": "shared/gravity_shared", "files": manifest_files}) + "\n")

            p_ok = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--strict", "--json"])
            self.assertEqual(p_ok.returncode, 0, msg=p_ok.stdout + p_ok.stderr)
            rep_ok = json.loads(p_ok.stdout)["repos"][0]
            self.assertTrue(rep_ok["checks"]["install_cli"]["delegated_to_shared"])
            self.assertTrue(rep_ok["checks"]["validate_contract"]["delegated_to_shared"])

    def test_validate_contract_detects_missing_fix_python_cmd_when_manifest_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-metrics", with_mcp_config=True)
            _write_lf(repo / "plugin" / "scripts" / "validate.py", _make_validator_source(include_fix_python=False))
            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-metrics", "--json"])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--fix-python-cmd", json.loads(proc.stdout)["repos"][0]["checks"]["validate_contract"]["missing"])

    def test_rules_d4_warn_at_650b_and_error_at_1050b(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity")
            _write_lf(repo / "plugin" / "rules" / "AGENTS.md", "# Rule\n" + ("a" * 643))
            p_ns = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_ns.returncode, 0, msg=p_ns.stdout)
            self.assertEqual(json.loads(p_ns.stdout)["repos"][0]["status"], "WARN")
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--repos", "gravity", "--strict"]).returncode, 1)

            _write_lf(repo / "plugin" / "rules" / "AGENTS.md", "# Rule\n" + ("b" * 1043))
            p_err = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_err.returncode, 1)
            self.assertEqual(json.loads(p_err.stdout)["repos"][0]["status"], "FAIL")

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
            bad = _make_manifest(
                "gravity-architect", version="0.9.9",
                prompts=["/gravity-architect init Sans séparateur", "/gravity-architect sync — " + ("x" * 90), "/gravity-architect audit — OK"],
                extra={"$schema": "https://example.com/schema.json"},
            )
            _write_lf(repo / "plugin" / "plugin.json", json.dumps(bad, indent=2, ensure_ascii=False) + "\n")
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
            p_w = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"])
            self.assertEqual(p_w.returncode, 0, msg=p_w.stdout)
            self.assertEqual(json.loads(p_w.stdout)["repos"][0]["status"], "WARN")
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--repos", "gravity", "--strict"]).returncode, 1)
            _write_lf(repo / "plugin" / "core" / "huge.py", "x = 1\n" * 1550)
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--repos", "gravity", "--json"]).returncode, 1)

    def test_int_checks_01_02_03_04_08_and_spi_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-metrics")
            # Valid SPI-1..3 module.json passes
            mod_ok = _make_module_contract("gravity-metrics")
            mod_ok["dashboard"] = {"provider_script": "scripts/dashboard_provider.py", "views": ["metrics"], "actions": ["record"]}
            mod_ok["capture_policy"] = {"commands": ["/gravity-metrics"], "exclude_subcommands": ["status"], "consultative_bypass": True, "label_prefix": "metrics"}
            mod_ok["signals"] = {"produces": ["session-metrics"], "consumes": ["*"]}
            _write_lf(repo / "plugin" / "scripts" / "dashboard_provider.py", "print('{}')\n")
            _write_lf(repo / "plugin" / "config" / "module.json", json.dumps(mod_ok, indent=2) + "\n")
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--repos", "gravity-metrics", "--strict"]).returncode, 0)

            # Invalid SPI-1..3 + INT-01..04, INT-08
            bad_mod = _make_module_contract("gravity-metrics", ui_mode="invalid-mode")
            bad_mod["plugin_name"] = "wrong-name"
            bad_mod["commands"] = ["/gravity-metrics", "/undocumented-cmd"]
            bad_mod["dashboard"] = {"provider_script": "scripts/missing_provider.py", "views": ["metrics"], "actions": []}
            bad_mod["capture_policy"] = {"commands": [], "exclude_subcommands": [], "consultative_bypass": "yes", "label_prefix": ""}
            bad_mod["signals"] = {"produces": ["BadSignalName"], "consumes": []}
            _write_lf(repo / "plugin" / "config" / "module.json", json.dumps(bad_mod, indent=2) + "\n")
            _write_lf(repo / "docs" / "guide.md", "[Missing](missing.md)\n[Local](file:///tmp/x)\n")
            (repo / "plugin" / "extra.yaml").write_bytes(b"key: val\r\n")
            _write_lf(repo / "tests" / "sample.py", "P = 'C:\\\\Users\\\\Demo\\\\file'\n")
            _write_lf(repo / "plugin" / "leak.py", "P = '/home/alice/secret/'\n")

            proc = _run_auditor(["--repos-root", str(root), "--repos", "gravity-metrics", "--json"])
            self.assertEqual(proc.returncode, 1)
            errs = "\n".join(json.loads(proc.stdout)["repos"][0]["errors"])
            for code in ("INT-01", "INT-02", "INT-03", "INT-04", "INT-08"):
                self.assertIn(code, errs)
            self.assertIn("provider_script", errs)
            self.assertIn("consultative_bypass", errs)
            self.assertIn("signals.produces", errs)
            self.assertNotIn("tests/sample.py", errs)

    def test_check_shared_sync_sha256_drift_and_legacy_studio_and_aud_05_09(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repos = ("gravity", "gravity-workflow", "gravity-metrics", "gravity-architect")
            for n in repos:
                _create_compliant_repo(root, n, with_rules=(n != "gravity-workflow"))
            _seed_shared_sync(root, repos)

            # Valid gravity-workshop R2 task
            ws = root / "gravity-workshop"
            _write_lf(ws / "specs" / "spec-ok.md", "# Spec\n\n- **Spec ID :** `SPEC-01`\n- **Statut :** `validated`\n")
            _write_lf(ws / "tasks" / "t1.md", "# T1\n\n- **Spec ID :** `SPEC-01`\n- **Spec source :** `specs/spec-ok.md`\n- **Date / Statut :** `2026-11-26` — `ready`\n")
            # Historical CHANGELOG + tests/ mention of legacy name must be allowed
            _write_lf(root / "gravity" / "CHANGELOG.md", _make_changelog("0.2.0") + f"- Old ref {'gravity-' 'studio'}.\n")
            _write_lf(root / "gravity" / "tests" / "test_neg.py", f"BAD = '{'gravity-' 'studio'}'\n")

            p_ok = _run_auditor(["--repos-root", str(root), "--strict", "--json"])
            self.assertEqual(p_ok.returncode, 0, msg=p_ok.stdout + p_ok.stderr)

            # Introduce SHA-256 drift, extra file, legacy studio ref in active doc, and stale ready task (AUD-05-09)
            _write_lf(root / "gravity-metrics" / "plugin" / "_shared" / "atomic_io.py", "# tampered\n")
            _write_lf(root / "gravity-metrics" / "plugin" / "_shared" / "extra.py", "# extra\n")
            _write_lf(root / "gravity" / "docs" / "old.md", f"Legacy {'gravity-' 'studio'} reference.\n")
            _write_lf(ws / "specs" / "spec-draft.md", "# Draft\n\n- **Spec ID :** `SPEC-02`\n- **Statut :** `draft`\n")
            _write_lf(ws / "tasks" / "t2.md", "# T2\n\n- **Spec ID :** `SPEC-02`\n- **Spec source :** `specs/spec-draft.md`\n- **Date / Statut :** `2026-11-26` — `ready`\n")

            p_bad = _run_auditor(["--repos-root", str(root), "--json"])
            self.assertEqual(p_bad.returncode, 1)
            out = json.loads(p_bad.stdout)
            gm_errs = "\n".join(next(r for r in out["repos"] if r["repo"] == "gravity-metrics")["errors"])
            gr_errs = "\n".join(next(r for r in out["repos"] if r["repo"] == "gravity")["errors"])
            cross_errs = "\n".join(out["cross_repo"]["errors"])
            self.assertIn("HASH_MISMATCH", gm_errs)
            self.assertIn("EXTRA_FILE", gm_errs)
            self.assertIn("LEGACY-REF", gr_errs)
            self.assertIn("AUD-05-09", cross_errs)

    def test_int_03_skips_root_dot_agents_but_scans_template_dot_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity-architect")
            (repo / ".agents" / "rules").mkdir(parents=True)
            (repo / ".agents" / "rules" / "05-git-versioning.md").write_bytes(b"# Rule\r\n")
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--repos", "gravity-architect", "--json"]).returncode, 0)

            (repo / "workspace-template" / ".agents" / "rules").mkdir(parents=True)
            (repo / "workspace-template" / ".agents" / "rules" / "05-git-versioning.md").write_bytes(b"# Rule\r\n")
            bad = _run_auditor(["--repos-root", str(root), "--repos", "gravity-architect", "--json"])
            self.assertEqual(bad.returncode, 1)
            self.assertIn("workspace-template/.agents/rules/05-git-versioning.md", "\n".join(json.loads(bad.stdout)["repos"][0]["errors"]))

    def test_int_05_check_installed_tolerates_windows_python_adaptation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _create_compliant_repo(root, "gravity", with_mcp_config=True)
            _write_lf(repo / "plugin" / "hooks.json", '{"g": {"PreInvocation": [{"type": "command", "command": "python3 hooks/p.py"}]}}\n')
            plugins_dir = root / "installed-plugins"
            inst = plugins_dir / "gravity"
            shutil.copytree(repo / "plugin", inst)
            _write_lf(inst / "mcp_config.json", '{"mcpServers": {"srv": {"command": "py", "args": ["-3", "${PLUGIN_ROOT}/mcp/server.py"]}}}\n')
            _write_lf(inst / "hooks.json", '{"g": {"PreInvocation": [{"type": "command", "command": "python hooks/p.py"}]}}\n')

            ok_p = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--check-installed", "--plugins-dir", str(plugins_dir), "--strict", "--json"])
            self.assertEqual(ok_p.returncode, 0, msg=ok_p.stdout + ok_p.stderr)
            self.assertTrue(json.loads(ok_p.stdout)["repos"][0]["checks"]["installed_sync"]["ok"])

            _write_lf(inst / "README.md", "# Drifted\n")
            bad_p = _run_auditor(["--repos-root", str(root), "--repos", "gravity", "--check-installed", "--plugins-dir", str(plugins_dir), "--json"])
            self.assertEqual(bad_p.returncode, 1)
            self.assertIn("INT-05", "\n".join(json.loads(bad_p.stdout)["repos"][0]["errors"]))

    def test_cross_repo_cumulative_rules_budget_contradictions_and_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ("gravity", "gravity-workflow", "gravity-metrics", "gravity-architect")
            for n in names:
                _create_compliant_repo(root, n)
                _write_lf(root / n / "plugin" / "rules" / "AGENTS.md", "# R\n" + ("x" * 846))

            p_warn = _run_auditor(["--repos-root", str(root), "--repos", ",".join(names), "--json"])
            self.assertEqual(p_warn.returncode, 0, msg=p_warn.stdout)
            self.assertTrue(json.loads(p_warn.stdout)["cross_repo"]["warnings"] != [])
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--repos", ",".join(names), "--strict"]).returncode, 1)

            _create_compliant_repo(root, "gravity-extra")
            for n in (*names, "gravity-extra"):
                _write_lf(root / n / "plugin" / "rules" / "AGENTS.md", "# R\n" + ("x" * 946))
            br = "# Bridge\n- Activer le dispatch proactif automatique.\n"
            _write_lf(root / "gravity-workflow" / "plugin" / "rules" / "AGENTS.md", br + ("x" * (950 - len(br.encode("utf-8")))))
            _write_lf(root / "gravity-architect" / "AGENTS.md", "## A\ndev direct sur main.\n\n## B\nStocker audits/code/ et audits/agents/ ensemble.\n\n## C\nok\n")
            _write_lf(root / "gravity-extra" / "plugin" / "config" / "module.json", json.dumps(_make_module_contract("gravity-extra", mod_id="core", commands=["/gravity"]), indent=2) + "\n")
            _write_lf(root / "gravity-extra" / "README.md", "# Extra\n/gravity\n")

            p_err = _run_auditor(["--repos-root", str(root), "--repos", ",".join((*names, "gravity-extra")), "--json"])
            self.assertEqual(p_err.returncode, 1)
            cross = json.loads(p_err.stdout)["cross_repo"]
            self.assertIn("Budget cumulé", "\n".join(cross["errors"]))
            self.assertIn("core", cross["id_collisions"])
            self.assertIn("/gravity", cross["command_collisions"])
            self.assertTrue(any("Bridge" in c for c in cross["contradictions"]))
            self.assertTrue(any("main" in c for c in cross["contradictions"]))
            self.assertTrue(any("audits/" in c for c in cross["contradictions"]))

    def test_verify_parallel_pass_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repos = ("gravity", "gravity-workflow", "gravity-metrics", "gravity-architect")
            for name in repos:
                repo = _create_compliant_repo(root, name, with_rules=(name != "gravity-workflow"))
                _write_lf(repo / "tests" / "test_ok.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")

            fake_bin = Path(tmp) / "fake-bin"
            _install_fake_agy(fake_bin)
            env_agy = {"PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", "")}

            proc = _run_auditor(["--repos-root", str(root), "--verify-parallel", "--strict", "--json"], env_overrides=env_agy)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["checks_passed"], 12)

            p_con = _run_auditor(["--repos-root", str(root), "--verify-parallel", "--strict"], env_overrides=env_agy)
            self.assertEqual(p_con.returncode, 0)
            self.assertIn("[PASS] 4/4 dépôts validés en parallèle", p_con.stdout)

            # Fail unittest -> fail-closed
            _write_lf(root / "gravity-metrics" / "tests" / "test_ok.py", "import unittest\nclass T(unittest.TestCase):\n    def test_fail(self):\n        self.fail('boom')\n")
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--verify-parallel", "--strict", "--json"], env_overrides=env_agy).returncode, 1)

            # Missing agy -> fail-closed
            empty_bin = Path(tmp) / "empty-bin"
            empty_bin.mkdir()
            self.assertEqual(_run_auditor(["--repos-root", str(root), "--verify-parallel", "--repos", "gravity", "--json"], env_overrides={"PATH": str(empty_bin)}).returncode, 1)


if __name__ == "__main__":
    unittest.main()

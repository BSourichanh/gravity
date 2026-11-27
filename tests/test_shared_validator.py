"""Isolated unit tests for shared/gravity_shared/validator_core.py (100% stdlib)."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_PARENT = REPO_ROOT / "shared"
if str(SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(SHARED_PARENT))

from gravity_shared import validator_core as vc  # noqa: E402


def _write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _make_valid_plugin(root: Path, *, name: str = "demo-plugin", mod_id: str = "demo") -> Path:
    plugin = root / "plugin"
    _write_lf(
        plugin / "plugin.json",
        json.dumps(
            {
                "name": name,
                "displayName": "Demo Plugin",
                "version": "1.2.3",
                "description": "Plugin de démonstration pour tests.",
                "logo": "assets/logo.svg",
                "suggestedPrompts": [
                    f"/{name} init — Initialiser le plugin",
                    f"/{name} status — Vérifier l'état",
                    "Analyser le dépôt courant",
                ],
                "author": {"name": "Gravity Contributors"},
                "homepage": "https://example.invalid/demo",
                "repository": "https://example.invalid/demo.git",
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )
    _write_lf(plugin / "assets" / "logo.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"></svg>\n')
    _write_lf(
        plugin / "config" / "module.json",
        json.dumps(
            {
                "schema_version": 1,
                "id": mod_id,
                "plugin_name": name,
                "role": "Demo role",
                "storage": {"subdir": mod_id, "env_override": "GRAVITY_DEMO_HOME"},
                "commands": [f"/{name}"],
                "capabilities": ["demo-cap"],
                "ui": {"mode": "none", "target": "gravity"},
                "signals": {"produces": ["demo-signal"], "consumes": []},
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )
    _write_lf(
        plugin / "skills" / name / "SKILL.md",
        f"---\nname: {name}\ndescription: Skill de test concis.\n---\n\n# {name}\n",
    )
    _write_lf(plugin / "rules" / "AGENTS.md", "# Demo Rules\n\n- Keep things clean.\n")
    _write_lf(plugin / "README.md", "# Demo\n")
    return plugin


def _safe_home_in_temp_dir() -> bool:
    if os.name == "nt":
        return False
    home_abs = os.path.abspath(os.fspath(vc.safe_home_dir()))
    home_res = os.path.realpath(home_abs)
    tmp_abs = os.path.abspath(tempfile.gettempdir())
    tmp_res = os.path.realpath(tmp_abs)
    for cand in (home_abs, home_res):
        if Path(cand).parts[:2] == ("/", "tmp"):
            return True
        for tb in (tmp_abs, tmp_res):
            if cand == tb or cand.startswith(tb.rstrip(os.sep) + os.sep):
                return True
    return False


class TestSharedValidator(unittest.TestCase):
    def test_valid_plugin_tree_and_allowed_local_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_valid_plugin(Path(tmp))
            _write_lf(plugin / "_shared" / "__init__.py", "from .atomic_io import write_json_atomic\n")
            _write_lf(plugin / "_shared" / "atomic_io.py", "def write_json_atomic(): pass\n")
            _write_lf(
                plugin / "scripts" / "demo_script.py",
                "import _shared\nfrom _shared.atomic_io import write_json_atomic\nimport dashboard_provider\n",
            )
            rep = vc.validate_plugin_tree(vc.ValidatorConfig(plugin_root=plugin))
            self.assertEqual(rep.errors, [])
            self.assertEqual(rep.warnings, [])
            self.assertTrue(rep.ok(strict=True))
            self.assertIn("_shared", vc.ALLOWED_LOCAL_MODULES)
            self.assertIn("dashboard_provider", vc.ALLOWED_LOCAL_MODULES)

    def test_plugin_manifest_validation_edge_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_valid_plugin(Path(tmp))
            mpath = plugin / "plugin.json"
            data = json.loads(mpath.read_text(encoding="utf-8"))
            # Valid optional disabled=True + string author + dict repository
            valid_alt = dict(data, disabled=True, author="Gravity Team", repository={"type": "git", "url": "https://example.invalid/repo.git"})
            _write_lf(mpath, json.dumps(valid_alt))
            rep_alt = vc.Report()
            vc.validate_plugin_manifest(plugin, rep_alt)
            self.assertEqual(rep_alt.errors, [])

            data["disabled"] = "yes"
            data["extraField"] = 1
            data["version"] = "not-semver"
            data["description"] = "x" * 161
            data["suggestedPrompts"] = ["/demo badprompt", "x" * 101]
            _write_lf(mpath, json.dumps(data))
            _write_lf(plugin / "assets" / "logo.svg", '<svg viewBox="0 0 64 32"></svg>\n')
            rep = vc.Report()
            vc.validate_plugin_manifest(plugin, rep)
            joined = "\n".join(rep.errors)
            self.assertIn("'disabled'", joined)
            self.assertIn("extraField", joined)
            self.assertIn("SemVer", joined)
            self.assertIn("description", joined)
            self.assertIn("suggestedPrompts", joined)
            self.assertIn("viewBox", joined)

    def test_module_contract_c2_and_spi_1_to_3_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_valid_plugin(Path(tmp))
            mpath = plugin / "config" / "module.json"
            base = json.loads(mpath.read_text(encoding="utf-8"))

            # Backward compatible when optional SPI-1/SPI-2 blocks are omitted
            rep_min = vc.Report()
            vc.validate_module_contract(plugin, rep_min, expected_plugin_name="demo-plugin", expected_module_id="demo")
            self.assertEqual(rep_min.errors, [])

            # Valid SPI-1 (dashboard), SPI-2 (capture_policy), SPI-3 (kebab-case signals)
            valid_spi = dict(base)
            valid_spi["dashboard"] = {"provider_script": "scripts/dashboard_provider.py", "views": ["overview"], "actions": []}
            valid_spi["capture_policy"] = {"commands": ["/demo"], "exclude_subcommands": ["help"], "consultative_bypass": True, "label_prefix": "demo"}
            valid_spi["signals"] = {"produces": ["demo-signal", "other-2"], "consumes": ["session-metrics"]}
            _write_lf(mpath, json.dumps(valid_spi))
            rep_ok = vc.Report()
            vc.validate_module_contract(plugin, rep_ok, expected_plugin_name="demo-plugin", expected_module_id="demo")
            self.assertEqual(rep_ok.errors, [])

            # Invalid SPI-1 (bad dashboard types & traversal), SPI-2 (bad types), SPI-3 (non-kebab-case & '*' in produces)
            bad_spi = dict(base)
            bad_spi["dashboard"] = {"provider_script": "../escape.py", "views": "overview", "actions": [123]}
            bad_spi["capture_policy"] = {"commands": [1], "exclude_subcommands": "help", "consultative_bypass": "yes", "label_prefix": ""}
            bad_spi["signals"] = {"produces": ["Bad_Signal", "*"], "consumes": ["NotKebab", "foo bar"]}
            rep_spi_bad = vc.Report()
            vc.validate_module_contract(bad_spi, rep_spi_bad)
            joined_spi = "\n".join(rep_spi_bad.errors)
            self.assertIn("dashboard.provider_script", joined_spi)
            self.assertIn("dashboard.views", joined_spi)
            self.assertIn("dashboard.actions", joined_spi)
            self.assertIn("capture_policy.commands", joined_spi)
            self.assertIn("capture_policy.exclude_subcommands", joined_spi)
            self.assertIn("capture_policy.consultative_bypass", joined_spi)
            self.assertIn("capture_policy.label_prefix", joined_spi)
            self.assertIn("signals.produces", joined_spi)
            self.assertIn("signals.consumes", joined_spi)

            # Non-dict dashboard / capture_policy rejected
            rep_types = vc.Report()
            vc.validate_module_contract(dict(base, dashboard=[], capture_policy="bad"), rep_types)
            self.assertEqual(len(rep_types.errors), 2)

            bad = dict(base, schema_version=True, id="BAD!", commands=["no_slash"], ui={"mode": "", "target": ""})
            rep_bad = vc.Report()
            vc.validate_module_contract(bad, rep_bad)
            self.assertGreaterEqual(len(rep_bad.errors), 4)
            self.assertTrue(any("ui.mode" in err and "ui.target" in err for err in rep_bad.errors))

            # Existing gravity/plugin/config/module.json (with consumes: ["*"]) passes
            rep_core_mod = vc.Report()
            vc.validate_module_contract(REPO_ROOT / "plugin", rep_core_mod, expected_plugin_name="gravity", expected_module_id="core")
            self.assertEqual(rep_core_mod.errors, [])

    def test_skills_description_limit_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_valid_plugin(Path(tmp))
            skill_md = plugin / "skills" / "demo-plugin" / "SKILL.md"
            _write_lf(skill_md, f"---\nname: wrong-name\ndescription: >-\n  {'a' * 165}\n---\n# Body\n")
            rep = vc.Report()
            vc.validate_skills(plugin, rep)
            joined = "\n".join(rep.errors)
            self.assertIn("name", joined)
            self.assertIn("description", joined)

    def test_stdlib_only_rejects_third_party_and_python_lt_310(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            py_bad = Path(tmp) / "bad.py"
            _write_lf(py_bad, "import requests\nfrom yaml import safe_load\n")
            rep = vc.Report()
            vc.check_stdlib_only(py_bad, rep)
            self.assertEqual(len(rep.errors), 2)

            py_ok = Path(tmp) / "ok.py"
            _write_lf(py_ok, "from .helper import run\nimport _shared\nimport dashboard_provider\n")
            rep_ok = vc.Report()
            vc.check_stdlib_only(py_ok, rep_ok)
            self.assertEqual(rep_ok.errors, [])

            rep_old = vc.Report()
            with mock.patch.object(sys, "stdlib_module_names", frozenset(), create=True):
                vc.check_stdlib_only(py_ok, rep_old)
            self.assertTrue(any("Python 3.10+" in e for e in rep_old.errors))

    def test_hygiene_bom_crlf_personal_paths_extra_patterns_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_valid_plugin(Path(tmp))
            bad_md = plugin / "notes.md"
            fake_home_path = "/" + "home" + "/alice/repo"
            bad_md.write_bytes(b"\xef\xbb\xbfModule 01 in " + fake_home_path.encode("utf-8") + b"\r\n")
            secret_py = plugin / "scripts" / "leak.py"
            _write_lf(secret_py, 'TOKEN = "ghp_1234567890abcdefghij123456"\nBENCH = "benchmarks"\n')
            target_ext = Path(tmp) / "outside.txt"
            _write_lf(target_ext, "outside\n")
            os.symlink(target_ext, plugin / "link.md")

            cfg = vc.ValidatorConfig(plugin_root=plugin, extra_forbidden_patterns=(("terme hors périmètre", r"\bbenchmarks?\b"),))
            rep = vc.validate_plugin_tree(cfg)
            joined = "\n".join(rep.errors)
            self.assertIn("BOM UTF-8", joined)
            self.assertIn("CRLF", joined)
            self.assertIn("Jargon interdit", joined)
            self.assertIn("Chemin personnel", joined)
            self.assertIn("Secret potentiel", joined)
            self.assertIn("terme hors périmètre", joined)
            self.assertIn("Lien symbolique", joined)

    def test_hooks_enabled_false_validation_and_fix_python_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_valid_plugin(Path(tmp))
            for rel in ("hooks/session_start_caveman.py", "hooks/pre_tool_guard.py", "hooks/session_start_metrics.py", "hooks/pre_invocation_metrics.py", "mcp/server.py"):
                _write_lf(plugin / rel, "print('ok')\n")

            # Case 1: disabled SessionStart + active PreToolUse + active PreInvocation
            hooks_data = {
                "harness-pre-tool-guard": {
                    "enabled": True,
                    "PreToolUse": [{"matcher": "run_command", "hooks": [{"type": "command", "command": "python3 hooks/pre_tool_guard.py"}]}],
                },
                "harness-session-caveman": {
                    "enabled": False,
                    "SessionStart": [{"type": "command", "command": "python3 hooks/session_start_caveman.py"}],
                },
                "gravity-metrics-session-start": {
                    "enabled": False,
                    "SessionStart": [{"type": "command", "command": "python3 hooks/session_start_metrics.py"}],
                },
                "gravity-metrics-command": {
                    "enabled": True,
                    "PreInvocation": [{"type": "command", "command": "python3 hooks/pre_invocation_metrics.py"}],
                },
            }
            _write_lf(plugin / "hooks.json", json.dumps(hooks_data, indent=2) + "\n")
            _write_lf(
                plugin / "mcp_config.json",
                json.dumps({"mcpServers": {"dashboard": {"command": "python3", "args": ["-B", "${PLUGIN_ROOT}/mcp/server.py"]}}}, indent=2) + "\n",
            )
            rep = vc.validate_plugin_tree(plugin)
            self.assertEqual(rep.errors, [])

            # Case 2: non-bool "enabled" and missing script inside disabled entry MUST fail
            bad_hooks = {
                "bad-group": {"enabled": "false", "SessionStart": [{"type": "command", "command": "python3 hooks/missing.py"}]},
                "bad-handler": {"enabled": True, "PreInvocation": [{"enabled": 0, "type": "command", "command": "python3 hooks/pre_invocation_metrics.py"}]},
            }
            _write_lf(plugin / "hooks.json", json.dumps(bad_hooks, indent=2) + "\n")
            rep_bad = vc.Report()
            vc.validate_hooks_config(plugin / "hooks.json", rep_bad, plugin_root=plugin)
            joined = "\n".join(rep_bad.errors)
            self.assertIn("'enabled' doit être un booléen", joined)
            self.assertIn("missing.py", joined)

            # Case 3: fix_python_cmd rewrites python3 inside disabled hooks.json entries + mcp_config.json
            _write_lf(plugin / "hooks.json", json.dumps(hooks_data, indent=2) + "\n")
            with mock.patch.object(vc, "has_real_python3", return_value=False), mock.patch.object(vc, "_detect_portable_python_cmd", return_value="py -3"):
                out_buf = io.StringIO()
                with contextlib.redirect_stdout(out_buf):
                    rc = vc.run_cli(argv=["--plugin-root", str(plugin), "--fix-python-cmd", "--json"])
            self.assertEqual(rc, 0)
            fix_res = json.loads(out_buf.getvalue())
            self.assertTrue(fix_res["ok"])
            self.assertEqual(sorted(fix_res["fixed_files"]), ["hooks.json", "mcp_config.json"])
            fixed_hooks = json.loads((plugin / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(fixed_hooks["harness-session-caveman"]["SessionStart"][0]["command"], "py -3 hooks/session_start_caveman.py")
            self.assertEqual(fixed_hooks["gravity-metrics-session-start"]["SessionStart"][0]["command"], "py -3 hooks/session_start_metrics.py")
            self.assertEqual(fixed_hooks["harness-pre-tool-guard"]["PreToolUse"][0]["hooks"][0]["command"], "py -3 hooks/pre_tool_guard.py")
            fixed_mcp = json.loads((plugin / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertEqual(fixed_mcp["mcpServers"]["dashboard"]["command"], "py")
            self.assertEqual(fixed_mcp["mcpServers"]["dashboard"]["args"][0], "-3")
            self.assertNotIn(b"\r\n", (plugin / "hooks.json").read_bytes())

    def test_cli_json_and_strict_warning_handling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _make_valid_plugin(Path(tmp))
            _write_lf(plugin / "rules" / "AGENTS.md", "# Rules\n\n" + ("x" * 700) + "\n")
            buf_loose = io.StringIO()
            with contextlib.redirect_stdout(buf_loose):
                rc_loose = vc.run_cli(argv=["--plugin-root", str(plugin), "--json"])
            self.assertEqual(rc_loose, 0)
            parsed_loose = json.loads(buf_loose.getvalue())
            self.assertTrue(parsed_loose["ok"])
            self.assertFalse(parsed_loose["strict"])
            self.assertEqual(len(parsed_loose["warnings"]), 1)

            buf_strict = io.StringIO()
            with contextlib.redirect_stdout(buf_strict):
                rc_strict = vc.run_cli(argv=["--plugin-root", str(plugin), "--strict", "--json"])
            self.assertEqual(rc_strict, 1)
            parsed_strict = json.loads(buf_strict.getvalue())
            self.assertFalse(parsed_strict["ok"])
            self.assertTrue(parsed_strict["strict"])

            # Optional --workspace callback hook + Windows python3 stub detection
            ws_dir = Path(tmp) / "ws"
            ws_dir.mkdir()
            base_cfg = vc.ValidatorConfig(plugin_root=plugin, workspace_validator_fn=lambda p, r: r.info(f"checked:{p.name}"))
            buf_ws = io.StringIO()
            with contextlib.redirect_stdout(buf_ws):
                rc_ws = vc.run_cli(base_cfg, argv=["--workspace", str(ws_dir), "--json"])
            self.assertEqual(rc_ws, 0)
            self.assertEqual(json.loads(buf_ws.getvalue())["infos"], ["checked:ws"])

            win_stub = "C:\\" + "Users" + "\\demo\\AppData\\Local\\Microsoft\\WindowsApps\\python3.exe"
            with mock.patch("os.name", "nt"), mock.patch("shutil.which", return_value=win_stub):
                self.assertFalse(vc.has_real_python3())

    def test_run_agy_plugin_validate_mock_cleanup_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home_dir"
            fake_home.mkdir()
            hidden_plugin = _make_valid_plugin(tmp_path / ".hidden")
            with mock.patch.object(vc, "safe_home_dir", return_value=fake_home), mock.patch("subprocess.run", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    vc.run_agy_plugin_validate(hidden_plugin, strict=True, agy_bin="/snap/bin/agy")
            self.assertEqual(list(fake_home.glob("gravity-validate-*")), [])

            proc_ok = mock.Mock(returncode=0, stdout="ok", stderr="")
            with mock.patch.object(vc, "safe_home_dir", return_value=fake_home), mock.patch("subprocess.run", return_value=proc_ok) as m_run:
                res = vc.run_agy_plugin_validate(hidden_plugin, strict=True, agy_bin="/snap/bin/agy")
            self.assertEqual(res["rc"], 0)
            self.assertTrue(res["staged"])
            called_cmd = m_run.call_args[0][0]
            self.assertEqual(called_cmd[:3], ["/snap/bin/agy", "plugin", "validate"])
            self.assertIn("--strict", called_cmd)
            self.assertTrue(called_cmd[3].startswith(str(fake_home / "gravity-validate-")))
            self.assertEqual(list(fake_home.glob("gravity-validate-*")), [])

    @unittest.skipUnless(os.path.isfile("/snap/bin/agy"), "/snap/bin/agy non installé")
    def test_run_agy_plugin_validate_live_snap_with_shared_and_manifest(self) -> None:
        if _safe_home_in_temp_dir():
            self.skipTest("Snap /snap/bin/agy AppArmor refuse $HOME sous le dossier temporaire")
        with tempfile.TemporaryDirectory() as tmp:
            hidden_root = Path(tmp) / ".gemini" / "plugins"
            plugin = _make_valid_plugin(hidden_root, name="gravity-demo", mod_id="demo")
            shutil.copytree(REPO_ROOT / "shared" / "gravity_shared", plugin / "_shared", ignore=shutil.ignore_patterns("__pycache__"))
            _write_lf(
                plugin / ".shared_manifest.json",
                json.dumps({"schema_version": 1, "source_repo": "gravity", "source_path": "shared/gravity_shared", "files": {"__init__.py": "0" * 64}}, indent=2) + "\n",
            )
            home_before = set(vc.safe_home_dir().glob("gravity-validate-*"))
            res = vc.run_agy_plugin_validate(plugin, strict=True, agy_bin="/snap/bin/agy")
            home_after = set(vc.safe_home_dir().glob("gravity-validate-*"))
            self.assertEqual(res["rc"], 0, msg=f"stdout={res['stdout']}\nstderr={res['stderr']}")
            self.assertTrue(res["ok"])
            self.assertTrue(res["staged"])
            self.assertEqual(home_after - home_before, set())

    def test_validator_core_stdlib_310_and_line_budget(self) -> None:
        vfile = REPO_ROOT / "shared" / "gravity_shared" / "validator_core.py"
        raw = vfile.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        text = raw.decode("utf-8")
        self.assertIsNone(vc.PERSONAL_PATH_RE.search(text))
        lines = text.splitlines()
        self.assertLess(len(lines), 650)
        tree = ast.parse(text, filename=str(vfile))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    mod = a.name.split(".")[0]
                    self.assertNotEqual(mod, "tomllib")
                    self.assertIn(mod, sys.stdlib_module_names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mod = node.module.split(".")[0]
                self.assertNotEqual(mod, "tomllib")
                self.assertIn(mod, sys.stdlib_module_names)
        rep = vc.validate_plugin_tree(
            vc.ValidatorConfig(
                plugin_root=REPO_ROOT / "plugin",
                expected_plugin_name="gravity",
                expected_module_id="core",
                allowed_local_modules=vc.ALLOWED_LOCAL_MODULES | frozenset({"hooks", "scripts"}),
            )
        )
        self.assertTrue(rep.ok(strict=True), msg=f"errors={rep.errors}, warnings={rep.warnings}")


if __name__ == "__main__":
    unittest.main()

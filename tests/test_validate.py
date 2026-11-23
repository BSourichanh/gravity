"""Isolated tests for plugin/scripts/validate.py."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import validate as plugin_validator  # noqa: E402


class TestValidate(unittest.TestCase):
    def _validate_copy(self, plugin_dir: Path) -> plugin_validator.Report:
        report = plugin_validator.Report()
        plugin_validator.validate_plugin(plugin_dir, report)
        return report

    def test_repo_plugin_passes_strict(self) -> None:
        rc = plugin_validator.main(["--plugin-root", str(PLUGIN_ROOT), "--strict"])
        self.assertEqual(rc, 0)

    def test_rejects_extra_manifest_field_and_bom_and_bad_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))

            manifest_path = copy_dir / "plugin.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["$schema"] = "https://example.com/schema.json"
            data["suggestedPrompts"] = ["Only one"]
            data["description"] = "x" * 161
            manifest_path.write_bytes(b"\xef\xbb\xbf" + json.dumps(data).encode("utf-8"))

            report = self._validate_copy(copy_dir)
            self.assertFalse(report.ok(strict=True))
            joined = "\n".join(report.errors)
            self.assertIn("BOM UTF-8", joined)
            self.assertIn("champs non officiels", joined)
            self.assertIn("suggestedPrompts", joined)
            self.assertIn("160", joined)

    def test_rejects_bad_svg_rules_skill_and_non_stdlib(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))

            (copy_dir / "assets" / "logo.svg").write_text(
                '<svg viewBox="0 0 128 64"></svg>\n', encoding="utf-8"
            )
            (copy_dir / "rules" / "AGENTS.md").write_text(
                "---\nfoo: bar\n---\n" + ("a" * 2100), encoding="utf-8"
            )
            (copy_dir / "skills" / "gravity" / "SKILL.md").write_text(
                f"---\nname: gravity\ndescription: {'z' * 165}\n---\n# Body\n",
                encoding="utf-8",
            )
            (copy_dir / "core" / "extra_dep.py").write_text(
                "import requests\n", encoding="utf-8"
            )
            (copy_dir / "dashboard" / "bad_dep.py").write_text(
                "import httpx\n", encoding="utf-8"
            )
            (copy_dir / "config" / "module.json").write_text(
                '{"schema_version": 2}', encoding="utf-8"
            )

            report = self._validate_copy(copy_dir)
            self.assertFalse(report.ok(strict=True))
            joined = "\n".join(report.errors)
            self.assertIn("viewBox carré", joined)
            self.assertIn("1000", joined)
            self.assertIn("frontmatter", joined)
            self.assertIn("160", joined)
            self.assertIn("requests", joined)
            self.assertIn("httpx", joined)
            self.assertIn("schema_version", joined)

    def test_rejects_missing_dashboard_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.rmtree(copy_dir / "dashboard")

            report = self._validate_copy(copy_dir)
            self.assertFalse(report.ok(strict=True))
            self.assertTrue(any("dashboard/" in err for err in report.errors))

    def test_rules_agents_md_d4_thresholds_and_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))
            rules_path = copy_dir / "rules" / "AGENTS.md"

            rules_path.write_bytes(b"# Regle\n" + (b"a" * 700) + b"\n")
            report_mid = self._validate_copy(copy_dir)
            self.assertTrue(report_mid.ok(strict=False))
            self.assertFalse(report_mid.ok(strict=True))
            self.assertTrue(any("600" in warn for warn in report_mid.warnings))

            rules_path.write_bytes(b"# Regle\n" + (b"b" * 1005) + b"\n")
            report_over = self._validate_copy(copy_dir)
            self.assertFalse(report_over.ok(strict=True))
            self.assertTrue(any("1000" in err for err in report_over.errors))

            rules_path.write_bytes(b"\xef\xbb\xbf# Regle\r\n- item\r\n")
            report_enc = self._validate_copy(copy_dir)
            self.assertFalse(report_enc.ok(strict=True))
            joined_enc = "\n".join(report_enc.errors)
            self.assertIn("BOM UTF-8", joined_enc)
            self.assertIn("CRLF", joined_enc)

    def test_skill_md_budget_and_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))
            skill_path = copy_dir / "skills" / "gravity" / "SKILL.md"
            base = (
                "---\nname: gravity\ndescription: \"Skill test\"\n---\n"
                "init status modules doctor dashboard help\n"
            )

            skill_path.write_bytes((base + ("x" * 6000) + "\n").encode("utf-8"))
            report_over = self._validate_copy(copy_dir)
            self.assertFalse(report_over.ok(strict=True))
            self.assertTrue(any("6000" in err for err in report_over.errors))

            skill_path.write_bytes(b"\xef\xbb\xbf" + base.replace("\n", "\r\n").encode("utf-8"))
            report_enc = self._validate_copy(copy_dir)
            self.assertFalse(report_enc.ok(strict=True))
            joined_enc = "\n".join(report_enc.errors)
            self.assertIn("BOM UTF-8", joined_enc)
            self.assertIn("CRLF", joined_enc)

            skill_path.write_text(
                "---\nname: gravity\ndescription: \"Skill test\"\n---\ninit status modules doctor dashboard\n",
                encoding="utf-8",
            )
            report_no_help = self._validate_copy(copy_dir)
            self.assertFalse(report_no_help.ok(strict=True))
            self.assertTrue(any("help" in err for err in report_no_help.errors))

    def test_repo_root_agents_md_budget_and_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "repo"
            copy_dir = repo_dir / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))
            root_agents = repo_dir / "AGENTS.md"

            root_agents.write_bytes(b"# Repo\n\n- ok\n")
            report_ok = self._validate_copy(copy_dir)
            self.assertTrue(report_ok.ok(strict=True))

            root_agents.write_bytes(b"\xef\xbb\xbf# Repo\r\n" + (b"x" * 2550) + b"\r\n")
            report_bad = self._validate_copy(copy_dir)
            self.assertFalse(report_bad.ok(strict=True))
            joined_bad = "\n".join(report_bad.errors)
            self.assertIn("AGENTS.md", joined_bad)
            self.assertIn("BOM UTF-8", joined_bad)
            self.assertIn("CRLF", joined_bad)
            self.assertIn("2500", joined_bad)

    def test_rejects_forbidden_jargon_and_personal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))

            (copy_dir / "README.md").write_text(
                "Mod" + "ule 01 at C:\\Users\\alice\\repo\n", encoding="utf-8"
            )
            report = self._validate_copy(copy_dir)
            self.assertFalse(report.ok(strict=True))
            joined = "\n".join(report.errors)
            self.assertIn("Jargon interdit", joined)
            self.assertIn("Chemin personnel", joined)

    def test_mcp_config_validation_and_fix_python_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))

            # Windows portable python3 info (never warn)
            with (
                mock.patch("validate.os.name", "nt"),
                mock.patch("validate.has_real_python3", return_value=False),
            ):
                rep_info = plugin_validator.Report()
                plugin_validator._validate_mcp_config(copy_dir, rep_info)
                self.assertTrue(rep_info.ok(strict=True))
                self.assertTrue(any("python3" in msg for msg in rep_info.infos))

            # fix_python_cmd adapts python3 -> python on copy
            with (
                mock.patch("validate.has_real_python3", return_value=False),
                mock.patch("validate._detect_portable_python_cmd", return_value="python"),
            ):
                rc = plugin_validator.main(["--plugin-root", str(copy_dir), "--fix-python-cmd"])
                self.assertEqual(rc, 0)
            fixed = json.loads((copy_dir / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertEqual(fixed["mcpServers"]["dashboard"]["command"], "python")

            # Missing server path & BOM in mcp_config.json are rejected
            bad_cfg = {"mcpServers": {"dashboard": {"command": "python3", "args": ["${PLUGIN_ROOT}/mcp/missing.py"]}}}
            (copy_dir / "mcp_config.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(bad_cfg).encode("utf-8"))
            rep_bad = plugin_validator.Report()
            plugin_validator._validate_mcp_config(copy_dir, rep_bad)
            self.assertFalse(rep_bad.ok(strict=True))
            joined = "\n".join(rep_bad.errors)
            self.assertIn("BOM UTF-8", joined)
            self.assertIn("introuvable", joined)

    def test_mcp_dry_run_rejects_innerhtml_and_external_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))
            (copy_dir / "mcp" / "widget_html.py").write_text(
                'def render_dashboard_html():\n    return "<script>x.innerHTML=1; // https://bad</script>"\n',
                encoding="utf-8",
            )
            rep = plugin_validator.Report()
            plugin_validator._run_mcp_dry_run(copy_dir, rep)
            self.assertFalse(rep.ok(strict=True))
            joined = "\n".join(rep.errors)
            self.assertIn("innerHTML", joined)
            self.assertIn("https://", joined)

    def test_suggested_prompts_ux_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))
            manifest_path = copy_dir / "plugin.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))

            # Valid prompts using '-', '—', and plain text <= 100 chars
            data["suggestedPrompts"] = [
                "/gravity init - Initialiser Gravity",
                "/gravity doctor — Auditer les modules",
                "Explorer l'architecture Gravity",
            ]
            manifest_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
            rep_ok = plugin_validator.Report()
            plugin_validator._validate_manifest(copy_dir, rep_ok)
            self.assertTrue(rep_ok.ok(strict=True), msg=rep_ok.errors)

            # Invalid: >100 chars, missing separator, empty summary
            data["suggestedPrompts"] = [
                "/gravity init — " + ("x" * 90),
                "/gravity status",
                "/gravity doctor —   ",
            ]
            manifest_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
            rep_bad = plugin_validator.Report()
            plugin_validator._validate_manifest(copy_dir, rep_bad)
            self.assertFalse(rep_bad.ok(strict=True))
            self.assertEqual(len(rep_bad.errors), 3)

    def test_markdown_links_and_ux_guides_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "repo"
            copy_dir = repo_dir / "plugin"
            shutil.copytree(PLUGIN_ROOT, copy_dir, ignore=shutil.ignore_patterns("__pycache__"))
            docs_dir = repo_dir / "docs"
            docs_dir.mkdir(parents=True)
            for name in plugin_validator.UX_GUIDE_FILES:
                (docs_dir / name).write_bytes(
                    (
                        "# Guide\n\n"
                        "Voir [Accueil](../README.md), [Section](#sec), "
                        "[Web](https://example.com), [Mail](mailto:test@example.com), "
                        "[Custom](customization://open).\n\n"
                        "```markdown\n[Ignore](missing-in-fence.md)\n```\n"
                        "`[IgnoreInline](missing-inline.md)`\n"
                    ).encode("utf-8")
                )
            (repo_dir / "README.md").write_bytes(
                b"# Repo\n\n[Start](docs/getting-started.md)\n"
            )

            rep_ok = plugin_validator.Report()
            plugin_validator._validate_markdown_links(copy_dir, rep_ok)
            self.assertTrue(rep_ok.ok(strict=True), msg=rep_ok.errors)

            # Broken relative links + missing guide + oversized guide
            (copy_dir / "README.md").write_text("[Broken](no-such-file.md)\n", encoding="utf-8")
            (docs_dir / "user-journey.md").unlink()
            (docs_dir / "getting-started.md").write_bytes(b"# Guide\n" + (b"a" * 15400) + b"\n")
            (repo_dir / "README.md").write_text("[BrokenRoot](docs/absent.md)\n", encoding="utf-8")

            rep_bad = plugin_validator.Report()
            plugin_validator._validate_markdown_links(copy_dir, rep_bad)
            self.assertFalse(rep_bad.ok(strict=True))
            joined = "\n".join(rep_bad.errors)
            self.assertIn("no-such-file.md", joined)
            self.assertIn("docs/user-journey.md", joined)
            self.assertIn("15360", joined)
            self.assertIn("docs/absent.md", joined)


if __name__ == "__main__":
    unittest.main()

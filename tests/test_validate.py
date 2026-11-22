"""Isolated tests for plugin/scripts/validate.py."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

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
            (copy_dir / "config" / "module.json").write_text(
                '{"schema_version": 2}', encoding="utf-8"
            )

            report = self._validate_copy(copy_dir)
            self.assertFalse(report.ok(strict=True))
            joined = "\n".join(report.errors)
            self.assertIn("viewBox carré", joined)
            self.assertIn("2048", joined)
            self.assertIn("frontmatter", joined)
            self.assertIn("160", joined)
            self.assertIn("requests", joined)
            self.assertIn("schema_version", joined)

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


if __name__ == "__main__":
    unittest.main()

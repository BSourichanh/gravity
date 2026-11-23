#!/usr/bin/env python3
"""Strict standalone validator for the Gravity Core Antigravity plugin (100% stdlib)."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT_DEFAULT = SCRIPT_DIR.parent

OFFICIAL_PLUGIN_FIELDS = {
    "name",
    "displayName",
    "version",
    "description",
    "logo",
    "suggestedPrompts",
    "author",
    "homepage",
    "repository",
    "disabled",
}
REQUIRED_PLUGIN_FIELDS = OFFICIAL_PLUGIN_FIELDS - {"disabled"}
ALLOWED_LOCAL_MODULES = {"core", "dashboard", "registry", "init_env", "validate"}
REQUIRED_DIRS = ("assets", "config", "core", "dashboard", "rules", "scripts", "skills")
RULES_EDITORIAL_TARGET_BYTES = 600
RULES_MAX_BYTES = 1000
SKILL_MAX_BYTES = 6000
REPO_AGENTS_MAX_BYTES = 2500

FORBIDDEN_MOD_RE = re.compile(r"\bMod" + r"ule\s+0?\d\b", re.IGNORECASE)
PERSONAL_PATH_RE = re.compile(
    r"(?:"
    + r"[A-Za-z]:\\"
    + r"(?:Users|Documents)\\"
    + r"|[A-Za-z]:\\[^\\\s\"'`]+\\"
    + r"Documents\\"
    + r"|/Us"
    + r"ers/[^/\s\"'`]+/"
    + r"|/ho"
    + r"me/[^/\s\"'`]+/"
    + r")",
    re.IGNORECASE,
)


class Report:
    """Collector for validation errors, warnings, and info messages."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def ok(self, strict: bool) -> bool:
        return len(self.errors) == 0 and (not strict or len(self.warnings) == 0)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _load_validate_module_contract(plugin_root: Path):
    root_str = str(plugin_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from core.registry import validate_module_contract

    return validate_module_contract


def _validate_manifest(root: Path, report: Report) -> Optional[dict[str, Any]]:
    manifest_path = root / "plugin.json"
    if not manifest_path.is_file():
        report.error("plugin.json introuvable à la racine du plugin.")
        return None

    raw_bytes = manifest_path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        report.error("plugin.json ne doit pas contenir de BOM UTF-8.")
        raw_bytes = raw_bytes[3:]

    try:
        manifest = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        report.error(f"plugin.json invalide : {exc}")
        return None

    if not isinstance(manifest, dict):
        report.error("plugin.json doit contenir un objet JSON.")
        return None

    unknown_keys = sorted(set(manifest.keys()) - OFFICIAL_PLUGIN_FIELDS)
    if unknown_keys:
        report.error(f"plugin.json : champs non officiels détectés : {unknown_keys}")

    missing_req = sorted(k for k in REQUIRED_PLUGIN_FIELDS if k not in manifest)
    if missing_req:
        report.error(f"plugin.json : champs requis manquants : {missing_req}")

    if manifest.get("name") != "gravity":
        report.error(f"plugin.json : 'name' doit être 'gravity', obtenu {manifest.get('name')!r}.")

    for str_field in ("displayName", "version", "homepage", "repository"):
        val = manifest.get(str_field)
        if not isinstance(val, str) or not val.strip():
            report.error(f"plugin.json : '{str_field}' doit être une chaîne non vide.")

    author = manifest.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"].strip():
        report.error("plugin.json : 'author.name' doit être une chaîne non vide.")

    desc = manifest.get("description")
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 160:
        desc_len = len(desc) if isinstance(desc, str) else 0
        report.error(f"plugin.json : 'description' vide ou > 160 caractères ({desc_len}).")

    prompts = manifest.get("suggestedPrompts")
    if (
        not isinstance(prompts, list)
        or len(prompts) != 3
        or not all(isinstance(p, str) and p.strip() for p in prompts)
    ):
        report.error("plugin.json : exactement 3 'suggestedPrompts' non vides sont requis.")

    logo_rel = manifest.get("logo")
    if not isinstance(logo_rel, str) or not logo_rel.strip():
        report.error("plugin.json : 'logo' manquant.")
    else:
        logo_path = (root / logo_rel).resolve()
        if not logo_path.is_file():
            report.error(f"Logo introuvable : {logo_rel!r}")
        elif logo_path.suffix.lower() == ".svg":
            svg = logo_path.read_text(encoding="utf-8", errors="replace")
            vb = re.search(
                r"""viewBox\s*=\s*["']0\s+0\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)["']""",
                svg,
            )
            if not vb or float(vb.group(1)) <= 0 or float(vb.group(1)) != float(vb.group(2)):
                report.error(f"Logo {logo_rel} : viewBox carré 1:1 non détecté.")

    return manifest


def _validate_module_json(
    root: Path, manifest: Optional[dict[str, Any]], report: Report
) -> None:
    module_path = root / "config" / "module.json"
    if not module_path.is_file():
        report.error("config/module.json introuvable.")
        return

    raw_bytes = module_path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        report.error("config/module.json ne doit pas contenir de BOM UTF-8.")
        raw_bytes = raw_bytes[3:]

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        report.error(f"config/module.json invalide : {exc}")
        return

    validate_contract = _load_validate_module_contract(root)
    for err in validate_contract(data):
        report.error(f"config/module.json : {err}")

    if isinstance(data, dict):
        if data.get("id") != "core":
            report.error(f"config/module.json : 'id' doit être 'core', obtenu {data.get('id')!r}.")
        expected_name = manifest.get("name") if manifest else "gravity"
        if data.get("plugin_name") != expected_name:
            report.error(
                f"config/module.json : 'plugin_name' ({data.get('plugin_name')!r}) "
                f"diffère de plugin.json ({expected_name!r})."
            )


def _extract_yaml_scalar(fm: str, key: str) -> Optional[str]:
    lines = fm.splitlines()
    for idx, line in enumerate(lines):
        match = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if not match:
            continue
        raw_val = match.group(1).strip()
        if raw_val in (">-", ">", "|-", "|"):
            parts: list[str] = []
            for sub in lines[idx + 1 :]:
                if re.match(r"^[A-Za-z0-9_-]+:\s*", sub):
                    break
                if sub.startswith((" ", "\t")) or not sub.strip():
                    if sub.strip():
                        parts.append(sub.strip())
                else:
                    break
            return " ".join(parts).strip()
        if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ('"', "'"):
            return raw_val[1:-1].strip()
        return raw_val
    return None


def _validate_skills(root: Path, report: Report) -> None:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        report.error("Dossier requis manquant : skills/gravity/")
        return

    names = [p.name for p in sorted(skills_dir.iterdir()) if p.is_dir()]
    if names != ["gravity"]:
        report.error(f"skills/ doit contenir uniquement 'gravity/' (trouvé : {names}).")
        return

    skill_md = skills_dir / "gravity" / "SKILL.md"
    if not skill_md.is_file():
        report.error("skills/gravity/SKILL.md introuvable.")
        return

    payload = _check_utf8_lf_budget(skill_md, "skills/gravity/SKILL.md", SKILL_MAX_BYTES, report)
    txt = payload.decode("utf-8", errors="replace")
    fm_match = re.match(r"^\s*---\r?\n(.*?)\r?\n---\r?\n", txt, re.DOTALL)
    if not fm_match:
        report.error("skills/gravity/SKILL.md : frontmatter YAML manquant.")
        return

    fm = fm_match.group(1)
    if _extract_yaml_scalar(fm, "name") != "gravity":
        report.error("skills/gravity/SKILL.md : 'name: gravity' manquant dans le frontmatter.")

    desc = _extract_yaml_scalar(fm, "description")
    if not desc or len(desc) > 160:
        desc_len = len(desc) if desc else 0
        report.error(
            f"skills/gravity/SKILL.md : 'description' manquante, vide ou > 160 caractères ({desc_len})."
        )

    for subcmd in ("init", "status", "modules", "doctor"):
        if subcmd not in txt:
            report.error(f"skills/gravity/SKILL.md : sous-commande '/gravity {subcmd}' non documentée.")


def _check_utf8_lf_budget(
    file_path: Path, label: str, max_bytes: int, report: Report
) -> bytes:
    """Validate UTF-8 without BOM, LF line endings, and byte budget for a markdown file."""
    raw_bytes = file_path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        report.error(f"{label} ne doit pas contenir de BOM UTF-8.")
        payload = raw_bytes[3:]
    else:
        payload = raw_bytes
    if b"\r\n" in raw_bytes:
        report.error(f"{label} doit utiliser des fins de ligne LF (CRLF détecté).")
    if len(raw_bytes) > max_bytes:
        report.error(f"{label} doit faire <= {max_bytes} octets UTF-8 (actuel : {len(raw_bytes)}).")
    return payload


def _validate_rules(root: Path, report: Report) -> None:
    rules_file = root / "rules" / "AGENTS.md"
    if not rules_file.is_file():
        report.error("rules/AGENTS.md introuvable.")
        return

    raw_bytes = rules_file.read_bytes()
    payload = _check_utf8_lf_budget(rules_file, "rules/AGENTS.md", RULES_MAX_BYTES, report)
    if RULES_EDITORIAL_TARGET_BYTES < len(raw_bytes) <= RULES_MAX_BYTES:
        report.warn(
            f"rules/AGENTS.md dépasse la cible éditoriale de {RULES_EDITORIAL_TARGET_BYTES} octets "
            f"(actuel : {len(raw_bytes)}, plafond strict : {RULES_MAX_BYTES})."
        )

    rules_txt = payload.decode("utf-8", errors="replace")
    if rules_txt.lstrip().startswith("---"):
        report.error("rules/AGENTS.md ne doit pas contenir de frontmatter YAML.")


def _validate_repo_agents_md(root: Path, report: Report) -> None:
    """Validate root repository AGENTS.md when auditing a repo's plugin/ directory."""
    agents_file = root.parent / "AGENTS.md"
    if not agents_file.is_file():
        return
    _check_utf8_lf_budget(agents_file, "AGENTS.md", REPO_AGENTS_MAX_BYTES, report)


def _check_stdlib_only(py_file: Path, report: Report) -> None:
    stdlib_names_raw = getattr(sys, "stdlib_module_names", None)
    if not stdlib_names_raw:
        report.error("Python 3.10+ requis pour la validation stdlib.")
        return
    allowed = set(stdlib_names_raw) | ALLOWED_LOCAL_MODULES
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError as exc:
        report.error(f"Syntaxe Python invalide dans {py_file}: {exc}")
        return
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module.split(".")[0]]
        for mod in mods:
            if mod not in allowed:
                report.error(f"Import non stdlib {mod!r} détecté dans {py_file}")


def _run_e2e_dry_run(root: Path, report: Report) -> None:
    init_script = root / "scripts" / "init_env.py"
    if not init_script.is_file():
        report.error("Script scripts/init_env.py manquant.")
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir(parents=True)
        shutil.copytree(
            root,
            plugins_dir / "gravity",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        gravity_home = tmp_path / "gravity-home"
        fake_user_home = tmp_path / "user-home"
        fake_user_home.mkdir(parents=True)

        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["HOME"] = str(fake_user_home)
        env["USERPROFILE"] = str(fake_user_home)
        env.pop("GRAVITY_HOME", None)
        env.pop("GRAVITY_CORE_HOME", None)

        check_home = tmp_path / "uninitialized-check"
        p_check = subprocess.run(
            [
                sys.executable,
                "-B",
                str(init_script),
                "--gravity-home",
                str(check_home),
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
            timeout=10,
            check=False,
        )
        if p_check.returncode != 0:
            report.error(f"Dry-run init_env.py --check échoué : {p_check.stderr or p_check.stdout}")
            return
        if check_home.exists():
            report.error("Dry-run init_env.py --check a créé un dossier alors qu'il doit rester lecture seule.")

        p_init = subprocess.run(
            [
                sys.executable,
                "-B",
                str(init_script),
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
            timeout=10,
            check=False,
        )
        if p_init.returncode != 0:
            report.error(f"Dry-run init_env.py échoué : {p_init.stderr or p_init.stdout}")
            return

        try:
            out = json.loads(p_init.stdout)
        except Exception as exc:
            report.error(f"Dry-run init_env.py : JSON invalide ({exc})")
            return

        modules = out.get("modules") or []
        core_mod = next((m for m in modules if m.get("id") == "core"), None)
        if not core_mod or not core_mod.get("valid"):
            report.error(f"Dry-run init_env.py : module 'core' invalide ou absent : {modules!r}")
        if not (gravity_home / "core" / "modules.json").is_file():
            report.error("Dry-run init_env.py : core/modules.json non créé.")


def validate_plugin(root: Path, report: Report) -> None:
    """Audit manifest, module contract, rules, skills, stdlib compliance, hygiene, and E2E init."""
    for sub in REQUIRED_DIRS:
        if not (root / sub).is_dir():
            report.error(f"Dossier requis manquant : {sub}/")

    if not (root / "README.md").is_file():
        report.error("README.md manquant à la racine du plugin.")

    manifest = _validate_manifest(root, report)
    _validate_module_json(root, manifest, report)
    _validate_skills(root, report)
    _validate_rules(root, report)
    if root.name == "plugin" and (root.parent / "AGENTS.md").is_file():
        _validate_repo_agents_md(root, report)

    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        _check_stdlib_only(py_file, report)

    for fpath in sorted(root.rglob("*")):
        if not fpath.is_file() or "__pycache__" in fpath.parts:
            continue
        if fpath.suffix.lower() not in (".py", ".md", ".json", ".svg"):
            continue
        raw = fpath.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            report.error(f"BOM UTF-8 interdit dans {fpath}")
        content = raw.decode("utf-8", errors="replace")
        if FORBIDDEN_MOD_RE.search(content):
            report.error(f"Jargon interdit détecté dans {fpath}")
        if PERSONAL_PATH_RE.search(content):
            report.error(f"Chemin personnel détecté dans {fpath}")

    _run_e2e_dry_run(root, report)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Validateur strict Gravity Core")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Échoue également sur les avertissements.",
    )
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=PLUGIN_ROOT_DEFAULT,
        help="Racine du plugin Gravity Core à auditer.",
    )
    args = parser.parse_args(argv)
    plugin_root = args.plugin_root.expanduser().resolve()

    report = Report()
    validate_plugin(plugin_root, report)

    for info in report.infos:
        print(f"[INFO]  {info}")
    for err in report.errors:
        print(f"[ERROR] {err}")
    for warn in report.warnings:
        print(f"[WARN]  {warn}")

    if report.ok(args.strict):
        print(f"[PASS] Validation Plugin réussie (0 erreur, {len(report.warnings)} avertissement).")
        return 0
    print(
        f"[FAIL] Validation Plugin échouée ({len(report.errors)} erreur(s), {len(report.warnings)} avertissement(s))."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

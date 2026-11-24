"""Shared static audit checks (INT-01..05, INT-08, cross-repo budgets and rule contradictions)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional, Sequence

_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugin"
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from core.registry import validate_module_contract  # noqa: E402

UTF8_BOM = b"\xef\xbb\xbf"
ALLOWED_UI_MODES = frozenset({"none", "core", "transition-sidecar", "transition-mcp", "mcp-app"})
RULES_TOTAL_WARN_BYTES = 3000
RULES_TOTAL_ERROR_BYTES = 4500

SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv"})
ENCODING_EXTS = frozenset({".py", ".md", ".json", ".svg", ".toml", ".yaml", ".yml"})
PERSONAL_PATH_EXTS = frozenset({".py", ".md", ".json", ".svg"})
WIN_ADAPT_JSON_PATHS = frozenset({"hooks.json", "mcp_config.json", "sidecar.json"})

CHANGELOG_RELEASE_RE = re.compile(r"^##\s+\[(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\]", re.MULTILINE)
H2_HEADING_RE = re.compile(r"^##\s+\S")
MD_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\n]+)\)")
INLINE_CODE_RE = re.compile(r"(`+)([^`\n]*?)\1")
IGNORED_LINK_PREFIXES = ("#", "http://", "https://", "mailto:", "customization://")

# Split path regex literals so audit_checks.py never matches itself under INT-04.
PERSONAL_PATH_RE = re.compile(
    r"(?:"
    + r"[A-Za-z]:" + r"\\(?:Us" + r"ers|Doc" + r"uments)\\"
    + r"|[A-Za-z]:" + r"\\[^\\\s\"'`]+\\" + r"Doc" + r"uments\\"
    + r"|/Us" + r"ers/[^/\s\"'`]+/"
    + r"|/ho" + r"me/[^/\s\"'`]+/"
    + r")",
    re.IGNORECASE,
)

_NEG_RE = re.compile(r"(?:0\s+appel|aucun|jamais|interdit|ne\s+pas|proscrit|refus|exclut|pas\s+d[e']|pas\s+m[ée]lang|hors\b|sauf\b|avant\b)", re.IGNORECASE)
_BRIDGE_PROACTIVE_RE = re.compile(
    r"(?:\bappel(?:er|s)?\s+proactif|\bdispatch\w*\s+proacti\w*|\bproactive\s+(?:call|dispatch)|dispatch\s*=\s*true[^.\n]*sans\s+(?:feu\s+vert|accord|validation))",
    re.IGNORECASE,
)
_DEV_ON_MAIN_RE = re.compile(
    r"\b(?:dev(?:eloppement)?|travailler|commit(?:ter|s)?|push(?:er)?)\s+(?:direct(?:ement)?\s+)?sur\s+[`'\"]?main[`'\"]?",
    re.IGNORECASE,
)
_AUDIT_SEPARATION_NEG_RE = re.compile(
    r"(?:s[ée]par|isol[ée]|exclusi|hors\b|jamais|ne\s+pas|distinct|pas\s+m[ée]lang|sans\s+m[ée]lang|interdit|\bvs\b)",
    re.IGNORECASE,
)
_AUDIT_MIX_RE = re.compile(r"(?:m[ée]lang|fusionn|combin)\w*[^.\n]*audits/(?:code|agents)", re.IGNORECASE)


def read_utf8_text(
    path: Path,
    label: str,
    errors: list[str],
    *,
    require_no_bom: bool = True,
    require_lf: bool = True,
) -> tuple[Optional[str], int]:
    """Read a file safely, validating UTF-8, absence of BOM, and LF line endings."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append(f"{label} illisible : {exc}")
        return None, 0

    size = len(raw)
    if require_no_bom and raw.startswith(UTF8_BOM):
        errors.append(f"{label} : BOM UTF-8 interdit.")
        payload = raw[len(UTF8_BOM) :]
    else:
        payload = raw

    if require_lf and b"\r\n" in raw:
        errors.append(f"{label} : fins de ligne CRLF interdites (LF requis).")

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{label} : encodage UTF-8 invalide ({exc}).")
        return None, size
    return text, size


def extract_declared_cli_flags(py_path: Path) -> tuple[Optional[set[str]], Optional[str]]:
    """Inspect a Python file AST and collect `--*` option flags declared via add_argument()."""
    try:
        source = py_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"illisible/non-UTF-8 ({exc})"

    try:
        tree = ast.parse(source, filename=str(py_path))
    except SyntaxError as exc:
        return None, f"SyntaxError ({exc})"

    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_add_arg = (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument")
            or (isinstance(node.func, ast.Name) and node.func.id == "add_argument")
        )
        if not is_add_arg:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
                flags.add(arg.value)
            elif isinstance(arg, (ast.Tuple, ast.List)):
                for elt in arg.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and elt.value.startswith("--"):
                        flags.add(elt.value)
    return flags, None


def has_executable_manifest(plugin_dir: Path) -> bool:
    """Return True if the plugin declares an executable manifest requiring --fix-python-cmd."""
    for rel in ("hooks.json", "mcp_config.json", "sidecar.json"):
        if (plugin_dir / rel).is_file():
            return True
    sidecars_dir = plugin_dir / "sidecars"
    if sidecars_dir.is_dir():
        return any(sc.is_file() for sc in sidecars_dir.rglob("sidecar.json"))
    return False


def collect_validator_sources(plugin_dir: Path) -> tuple[str, list[ast.AST]]:
    """Load source text and parsed ASTs for validate.py and optional validators/*.py helpers."""
    scripts_dir = plugin_dir / "scripts"
    py_files: list[Path] = []
    main_val = scripts_dir / "validate.py"
    if main_val.is_file():
        py_files.append(main_val)
    validators_pkg = scripts_dir / "validators"
    if validators_pkg.is_dir():
        for py in sorted(validators_pkg.rglob("*.py")):
            if "__pycache__" not in py.parts:
                py_files.append(py)

    texts: list[str] = []
    trees: list[ast.AST] = []
    for py in py_files:
        try:
            src = py.read_text(encoding="utf-8")
            texts.append(src)
            trees.append(ast.parse(src, filename=str(py)))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
    return "\n".join(texts), trees


def collect_ast_literals(trees: Sequence[ast.AST]) -> tuple[set[str], set[bytes]]:
    """Collect all string and bytes constant literals from parsed ASTs."""
    str_lits: set[str] = set()
    bytes_lits: set[bytes] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    str_lits.add(node.value)
                elif isinstance(node.value, bytes):
                    bytes_lits.add(node.value)
    return str_lits, bytes_lits


def count_h2_sections(md_text: str) -> int:
    """Count top-level Markdown `##` headings outside fenced code blocks."""
    count = 0
    in_fence = False
    fence_char = ""
    fence_len = 0
    for line in md_text.splitlines():
        fence_match = MD_FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence, fence_char, fence_len = True, marker[0], len(marker)
                continue
            if marker[0] == fence_char and len(marker) >= fence_len and line.strip() == marker:
                in_fence, fence_char, fence_len = False, "", 0
                continue
        if not in_fence and H2_HEADING_RE.match(line):
            count += 1
    return count


def extract_latest_changelog_version(changelog_text: str) -> Optional[str]:
    match = CHANGELOG_RELEASE_RE.search(changelog_text)
    return match.group(1) if match else None


def audit_module_contract(
    repo_dir: Path,
    plugin_manifest: Optional[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    """INT-01: Validate plugin/config/module.json contract, plugin_name alignment, and ui.mode."""
    module_path = repo_dir / "plugin" / "config" / "module.json"
    if not module_path.is_file():
        errors.append("INT-01 : plugin/config/module.json introuvable.")
        return {"ok": False, "id": None, "plugin_name": None, "commands": [], "ui_mode": None}

    err_before = len(errors)
    text, _ = read_utf8_text(module_path, "plugin/config/module.json", errors)
    if text is None:
        return {"ok": False, "id": None, "plugin_name": None, "commands": [], "ui_mode": None}

    try:
        mod_data = json.loads(text)
    except ValueError as exc:
        errors.append(f"INT-01 : plugin/config/module.json JSON invalide ({exc}).")
        return {"ok": False, "id": None, "plugin_name": None, "commands": [], "ui_mode": None}

    for cerr in validate_module_contract(mod_data):
        errors.append(f"INT-01 : plugin/config/module.json : {cerr}")

    if not isinstance(mod_data, dict):
        return {"ok": False, "id": None, "plugin_name": None, "commands": [], "ui_mode": None}

    if isinstance(plugin_manifest, dict):
        expected_plugin = plugin_manifest.get("name")
        actual_plugin = mod_data.get("plugin_name")
        if isinstance(expected_plugin, str) and expected_plugin.strip() and actual_plugin != expected_plugin:
            errors.append(
                f"INT-01 : module.json plugin_name ({actual_plugin!r}) != plugin.json name ({expected_plugin!r})."
            )

    ui = mod_data.get("ui")
    ui_mode = ui.get("mode") if isinstance(ui, dict) else None
    if isinstance(ui_mode, str) and ui_mode not in ALLOWED_UI_MODES:
        errors.append(
            f"INT-01 : ui.mode invalide ({ui_mode!r}), attendu dans {sorted(ALLOWED_UI_MODES)}."
        )

    raw_cmds = mod_data.get("commands")
    commands = [str(c) for c in raw_cmds if isinstance(c, str) and c.strip()] if isinstance(raw_cmds, list) else []
    return {
        "ok": len(errors) == err_before,
        "id": mod_data.get("id") if isinstance(mod_data.get("id"), str) else None,
        "plugin_name": mod_data.get("plugin_name") if isinstance(mod_data.get("plugin_name"), str) else None,
        "commands": commands,
        "ui_mode": ui_mode if isinstance(ui_mode, str) else None,
    }


def _extract_markdown_targets(md_text: str) -> list[str]:
    targets: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for line in md_text.splitlines():
        fence_match = MD_FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence, fence_char, fence_len = True, marker[0], len(marker)
                continue
            if marker[0] == fence_char and len(marker) >= fence_len and line.strip() == marker:
                in_fence, fence_char, fence_len = False, "", 0
                continue
        if in_fence:
            continue
        cleaned = INLINE_CODE_RE.sub("", line)
        for match in MD_LINK_RE.finditer(cleaned):
            raw_target = match.group(1).strip()
            if not raw_target:
                continue
            target = raw_target[1 : raw_target.index(">")].strip() if raw_target.startswith("<") and ">" in raw_target else raw_target.split()[0]
            if target:
                targets.append(target)
    return targets


def audit_markdown_links(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """INT-02: Validate relative local Markdown links and reject file: URIs."""
    candidates: list[Path] = []
    for fixed in (repo_dir / "README.md", repo_dir / "plugin" / "README.md", repo_dir / "AGENTS.md"):
        if fixed.is_file():
            candidates.append(fixed)
    skills_dir = repo_dir / "plugin" / "skills"
    if skills_dir.is_dir():
        candidates.extend(sorted(skills_dir.glob("*/SKILL.md")))
    docs_dir = repo_dir / "docs"
    if docs_dir.is_dir():
        candidates.extend(sorted(docs_dir.glob("*.md")))

    err_before = len(errors)
    broken: list[str] = []
    for md_path in candidates:
        rel_lbl = md_path.relative_to(repo_dir).as_posix()
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"INT-02 : impossible de lire {rel_lbl} ({exc}).")
            continue
        for target in _extract_markdown_targets(text):
            lower = target.lower()
            if lower.startswith("file:"):
                msg = f"INT-02 : lien 'file:' interdit dans {rel_lbl} : {target!r}"
                errors.append(msg)
                broken.append(msg)
                continue
            if lower.startswith(IGNORED_LINK_PREFIXES):
                continue
            rel = target.split("#", 1)[0].split("?", 1)[0]
            if not rel:
                continue
            if not (md_path.parent / rel).resolve().exists():
                msg = f"INT-02 : lien Markdown relatif cassé dans {rel_lbl} : {target!r}"
                errors.append(msg)
                broken.append(msg)
    return {"ok": len(errors) == err_before, "files_checked": len(candidates), "broken": broken}


def _iter_repo_files(repo_dir: Path, exts: frozenset[str], *, skip_tests: bool = False) -> list[Path]:
    found: list[Path] = []
    for path in sorted(repo_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(repo_dir)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] == ".agents":
            continue
        if skip_tests and rel.parts and rel.parts[0] == "tests":
            continue
        if path.suffix.lower() in exts:
            found.append(path)
    return found


def audit_encoding_hygiene(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """INT-03: Exhaustive UTF-8 without BOM + LF check across repo source/doc/config files."""
    files = _iter_repo_files(repo_dir, ENCODING_EXTS)
    err_before = len(errors)
    violations: list[str] = []
    for fpath in files:
        rel_lbl = fpath.relative_to(repo_dir).as_posix()
        try:
            raw = fpath.read_bytes()
        except OSError as exc:
            errors.append(f"INT-03 : {rel_lbl} illisible ({exc}).")
            violations.append(rel_lbl)
            continue
        bad = False
        if raw.startswith(UTF8_BOM):
            errors.append(f"INT-03 : {rel_lbl} : BOM UTF-8 interdit.")
            raw = raw[len(UTF8_BOM) :]
            bad = True
        if b"\r\n" in raw:
            errors.append(f"INT-03 : {rel_lbl} : fins de ligne CRLF interdites (LF requis).")
            bad = True
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"INT-03 : {rel_lbl} : encodage UTF-8 invalide ({exc}).")
            bad = True
        if bad:
            violations.append(rel_lbl)
    return {"ok": len(errors) == err_before, "files_checked": len(files), "violations": violations}


def audit_personal_paths(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """INT-04: Reject personal machine paths in repo files outside tests/."""
    files = _iter_repo_files(repo_dir, PERSONAL_PATH_EXTS, skip_tests=True)
    err_before = len(errors)
    matches: list[str] = []
    for fpath in files:
        rel_lbl = fpath.relative_to(repo_dir).as_posix()
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if PERSONAL_PATH_RE.search(text):
            errors.append(f"INT-04 : chemin personnel détecté dans {rel_lbl}.")
            matches.append(rel_lbl)
    return {"ok": len(errors) == err_before, "files_checked": len(files), "matches": matches}


def audit_commands_doc(repo_dir: Path, module_info: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """INT-08: Verify every module.json command is documented in SKILL.md union or README.md."""
    commands = list(module_info.get("commands") or [])
    err_before = len(errors)
    texts: list[str] = []
    readme = repo_dir / "README.md"
    if readme.is_file():
        texts.append(readme.read_text(encoding="utf-8", errors="replace"))
    skills_dir = repo_dir / "plugin" / "skills"
    if skills_dir.is_dir():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            texts.append(skill_md.read_text(encoding="utf-8", errors="replace"))
    union_text = "\n".join(texts)
    missing = [cmd for cmd in commands if cmd not in union_text]
    for cmd in missing:
        errors.append(f"INT-08 : commande {cmd!r} absente de plugin/skills/*/SKILL.md et README.md.")
    return {"ok": len(errors) == err_before, "commands": commands, "missing": missing}


def _normalize_python3_cmd_str(cmd: str) -> str:
    if cmd in ("python", "py -3"):
        return "python3"
    if cmd.startswith("python "):
        return "python3 " + cmd[len("python ") :]
    if cmd.startswith("py -3 "):
        return "python3 " + cmd[len("py -3 ") :]
    return cmd


def _normalize_win_json_node(node: Any) -> Any:
    if isinstance(node, list):
        return [_normalize_win_json_node(x) for x in node]
    if isinstance(node, dict):
        out = {k: _normalize_win_json_node(v) for k, v in node.items()}
        cmd = out.get("command")
        if isinstance(cmd, str):
            args = out.get("args")
            if cmd == "py" and isinstance(args, list) and args and args[0] == "-3":
                out["command"] = "python3"
                out["args"] = args[1:]
            else:
                out["command"] = _normalize_python3_cmd_str(cmd)
        return out
    return node


def _is_win_adapt_json(rel_posix: str) -> bool:
    if rel_posix in WIN_ADAPT_JSON_PATHS:
        return True
    parts = rel_posix.split("/")
    return len(parts) == 3 and parts[0] == "sidecars" and parts[2] == "sidecar.json"


def _collect_plugin_hashes(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if not root.is_dir():
        return files
    for fpath in sorted(root.rglob("*")):
        if fpath.is_symlink() or not fpath.is_file():
            continue
        rel = fpath.relative_to(root)
        if "__pycache__" in rel.parts or fpath.suffix.lower() in (".pyc", ".pyo") or fpath.name == ".DS_Store":
            continue
        files[rel.as_posix()] = fpath
    return files


def audit_installed_sync(
    repo_dir: Path,
    plugin_name: str,
    plugins_dir: Path,
    errors: list[str],
) -> dict[str, Any]:
    """INT-05: Compare repo/plugin/ vs <plugins_dir>/<plugin_name>/ allowing Windows python3 adaptation."""
    src_dir = repo_dir / "plugin"
    installed_dir = plugins_dir / plugin_name
    err_before = len(errors)
    if not installed_dir.is_dir():
        errors.append(f"INT-05 : copie installée introuvable : {installed_dir}")
        return {"ok": False, "installed_dir": str(installed_dir), "missing_dir": True, "diff_files": []}

    src_files = _collect_plugin_hashes(src_dir)
    inst_files = _collect_plugin_hashes(installed_dir)
    missing = sorted(set(src_files) - set(inst_files))
    extra = sorted(set(inst_files) - set(src_files))
    mismatched: list[str] = []

    for rel in missing:
        errors.append(f"INT-05 : fichier manquant dans {installed_dir} : {rel}")
    for rel in extra:
        errors.append(f"INT-05 : fichier supplémentaire dans {installed_dir} : {rel}")

    for rel in sorted(set(src_files) & set(inst_files)):
        src_bytes = src_files[rel].read_bytes()
        inst_bytes = inst_files[rel].read_bytes()
        if hashlib.sha256(src_bytes).hexdigest() == hashlib.sha256(inst_bytes).hexdigest():
            continue
        if _is_win_adapt_json(rel):
            try:
                src_norm = _normalize_win_json_node(json.loads(src_bytes.decode("utf-8-sig")))
                inst_norm = _normalize_win_json_node(json.loads(inst_bytes.decode("utf-8-sig")))
                if src_norm == inst_norm:
                    continue
            except (UnicodeDecodeError, ValueError):
                pass
        mismatched.append(rel)
        errors.append(f"INT-05 : divergence SHA-256 entre plugin/ et {installed_dir} : {rel}")

    return {
        "ok": len(errors) == err_before,
        "installed_dir": str(installed_dir),
        "missing_dir": False,
        "missing_files": missing,
        "extra_files": extra,
        "diff_files": mismatched,
    }


def _scan_rule_contradictions(repo_name: str, repo_dir: Path) -> list[str]:
    findings: list[str] = []
    targets: list[Path] = []
    for p in (repo_dir / "AGENTS.md", repo_dir / "plugin" / "rules" / "AGENTS.md"):
        if p.is_file():
            targets.append(p)
    skills_dir = repo_dir / "plugin" / "skills"
    if skills_dir.is_dir():
        targets.extend(sorted(skills_dir.glob("*/SKILL.md")))

    for path in targets:
        rel_lbl = f"{repo_name}/{path.relative_to(repo_dir).as_posix()}"
        text = path.read_text(encoding="utf-8", errors="replace")
        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if MD_FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence or not line.strip():
                continue
            if _BRIDGE_PROACTIVE_RE.search(line) and not _NEG_RE.search(line):
                findings.append(f"{rel_lbl}:{lineno} : directive Bridge proactive sans garde-fou humain.")
            if _DEV_ON_MAIN_RE.search(line) and not _NEG_RE.search(line):
                findings.append(f"{rel_lbl}:{lineno} : directive de dev/commit direct sur 'main' (attendu: 'dev').")
            has_both_audits = ("audits/code" in line.lower()) and ("audits/agents" in line.lower())
            if (_AUDIT_MIX_RE.search(line) or has_both_audits) and not _AUDIT_SEPARATION_NEG_RE.search(line):
                findings.append(f"{rel_lbl}:{lineno} : mélange potentiel entre audits/code/ et audits/agents/.")
    return findings


def audit_cross_repo(
    repo_reports: Sequence[dict[str, Any]],
    repos_root: Path,
) -> dict[str, Any]:
    """Validate cumulative rules budget, module id/command collisions, and rule contradictions."""
    errors: list[str] = []
    warnings: list[str] = []

    total_rules_bytes = 0
    id_owners: dict[str, list[str]] = {}
    cmd_owners: dict[str, list[str]] = {}
    contradictions: list[str] = []

    for rep in repo_reports:
        if not rep.get("exists"):
            continue
        rname = str(rep["repo"])
        checks = rep.get("checks") or {}
        rules = checks.get("rules_d4") or {}
        if not rules.get("exempt") and isinstance(rules.get("bytes"), int):
            total_rules_bytes += rules["bytes"]

        mod = checks.get("module_contract") or {}
        mod_id = mod.get("id")
        if isinstance(mod_id, str) and mod_id:
            id_owners.setdefault(mod_id, []).append(rname)
        for cmd in mod.get("commands") or []:
            cmd_owners.setdefault(cmd, []).append(rname)

        contradictions.extend(_scan_rule_contradictions(rname, repos_root / rname))

    if total_rules_bytes > RULES_TOTAL_ERROR_BYTES:
        errors.append(
            f"Budget cumulé plugin/rules/AGENTS.md dépassé : {total_rules_bytes} o > {RULES_TOTAL_ERROR_BYTES} o."
        )
    elif total_rules_bytes > RULES_TOTAL_WARN_BYTES:
        warnings.append(
            f"Budget cumulé plugin/rules/AGENTS.md élevé : {total_rules_bytes} o > {RULES_TOTAL_WARN_BYTES} o."
        )

    id_collisions = {k: v for k, v in sorted(id_owners.items()) if len(v) > 1}
    for mod_id, owners in id_collisions.items():
        errors.append(f"Collision module.json id {mod_id!r} entre dépôts : {owners}.")

    cmd_collisions = {k: v for k, v in sorted(cmd_owners.items()) if len(v) > 1}
    for cmd, owners in cmd_collisions.items():
        errors.append(f"Collision commande {cmd!r} entre dépôts : {owners}.")

    errors.extend(contradictions)
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "rules_total_bytes": total_rules_bytes,
        "rules_warn_threshold": RULES_TOTAL_WARN_BYTES,
        "rules_error_threshold": RULES_TOTAL_ERROR_BYTES,
        "id_collisions": id_collisions,
        "command_collisions": cmd_collisions,
        "contradictions": contradictions,
    }

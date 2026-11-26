"""Shared static audit checks (INT-01..05, INT-08, _shared SHA-256, SPI-1..3, legacy refs, AUD-05-09)."""

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

from _shared.path_safety import is_symlink_or_junction, is_within_root  # noqa: E402
from _shared.validator_core import Report, validate_module_contract as vc_validate_module_contract  # noqa: E402

UTF8_BOM = b"\xef\xbb\xbf"
ALLOWED_UI_MODES = frozenset({"none", "core", "transition-sidecar", "transition-mcp", "mcp-app"})
RULES_TOTAL_WARN_BYTES, RULES_TOTAL_ERROR_BYTES = 3000, 4500

SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv"})
ARCHIVE_DIRS = frozenset({"archive", "archives"})
ENCODING_EXTS = frozenset({".py", ".md", ".json", ".svg", ".toml", ".yaml", ".yml"})
PERSONAL_PATH_EXTS = frozenset({".py", ".md", ".json", ".svg"})
WIN_ADAPT_JSON_PATHS = frozenset({"hooks.json", "mcp_config.json", "sidecar.json"})
SHARED_SOURCE_REPO, SHARED_SOURCE_REL, SHARED_MANIFEST_NAME = "gravity", "shared/gravity_shared", ".shared_manifest.json"

CHANGELOG_RELEASE_RE = re.compile(r"^##\s+\[(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\]", re.MULTILINE)
H2_HEADING_RE = re.compile(r"^##\s+\S")
MD_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\n]+)\)")
INLINE_CODE_RE = re.compile(r"(`+)([^`\n]*?)\1")
IGNORED_LINK_PREFIXES = ("#", "http://", "https://", "mailto:", "customization://")

# Split regex literals so audit_checks.py never self-triggers on personal paths or legacy brand refs.
PERSONAL_PATH_RE = re.compile(
    r"(?:" + r"[A-Za-z]:" + r"\\(?:Us" + r"ers|Doc" + r"uments)\\"
    + r"|[A-Za-z]:" + r"\\[^\\\s\"'`]+\\" + r"Doc" + r"uments\\"
    + r"|/Us" + r"ers/[^/\s\"'`]+/" + r"|/ho" + r"me/[^/\s\"'`]+/" + r")",
    re.IGNORECASE,
)
LEGACY_STUDIO_RE = re.compile(r"\bgravity-" + r"studio\b", re.IGNORECASE)

_NEG_RE = re.compile(r"(?:0\s+appel|aucun|jamais|interdit|ne\s+pas|proscrit|refus|exclut|pas\s+d[e']|pas\s+m[ée]lang|hors\b|sauf\b|avant\b)", re.IGNORECASE)
_BRIDGE_PROACTIVE_RE = re.compile(r"(?:\bappel(?:er|s)?\s+proactif|\bdispatch\w*\s+proacti\w*|\bproactive\s+(?:call|dispatch)|dispatch\s*=\s*true[^.\n]*sans\s+(?:feu\s+vert|accord|validation))", re.IGNORECASE)
_DEV_ON_MAIN_RE = re.compile(r"\b(?:dev(?:eloppement)?|travailler|commit(?:ter|s)?|push(?:er)?)\s+(?:direct(?:ement)?\s+)?sur\s+[`'\"]?main[`'\"]?", re.IGNORECASE)
_AUDIT_SEPARATION_NEG_RE = re.compile(r"(?:s[ée]par|isol[ée]|exclusi|hors\b|jamais|ne\s+pas|distinct|pas\s+m[ée]lang|sans\s+m[ée]lang|interdit|\bvs\b)", re.IGNORECASE)
_AUDIT_MIX_RE = re.compile(r"(?:m[ée]lang|fusionn|combin)\w*[^.\n]*audits/(?:code|agents)", re.IGNORECASE)
_TASK_STATUS_RE = re.compile(r"^\s*-\s*\*\*(?:Date\s*/\s*)?(?:Statut|Status)\s*:\*\*.*?\b(draft|ready|in_progress|done|archived|blocked)\b", re.MULTILINE | re.IGNORECASE)
_TASK_SPEC_SRC_RE = re.compile(r"^\s*-\s*\*\*Spec\s+source\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_SPEC_ID_RE = re.compile(r"^\s*-\s*\*\*Spec\s+ID\s*:\*\*\s*`?([A-Za-z0-9_-]+)`?", re.MULTILINE | re.IGNORECASE)
_SPEC_STATUS_RE = re.compile(r"^\s*-\s*\*\*(?:Statut|Status)\s*:\*\*\s*`?([A-Za-z0-9_-]+)`?", re.MULTILINE | re.IGNORECASE)


def read_utf8_text(
    path: Path, label: str, errors: list[str], *, require_no_bom: bool = True, require_lf: bool = True,
) -> tuple[Optional[str], int]:
    """Read a file safely, validating UTF-8, absence of BOM, and LF line endings."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append(f"{label} illisible : {exc}")
        return None, 0
    size = len(raw)
    payload = raw[len(UTF8_BOM) :] if (require_no_bom and raw.startswith(UTF8_BOM)) else raw
    if require_no_bom and raw.startswith(UTF8_BOM):
        errors.append(f"{label} : BOM UTF-8 interdit.")
    if require_lf and b"\r\n" in raw:
        errors.append(f"{label} : fins de ligne CRLF interdites (LF requis).")
    try:
        return payload.decode("utf-8"), size
    except UnicodeDecodeError as exc:
        errors.append(f"{label} : encodage UTF-8 invalide ({exc}).")
        return None, size


def _collect_loop_flag_bindings(tree: ast.AST) -> dict[str, set[str]]:
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.iter, (ast.Tuple, ast.List)):
            continue
        if isinstance(node.target, ast.Name):
            for elt in node.iter.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and elt.value.startswith("--"):
                    bindings.setdefault(node.target.id, set()).add(elt.value)
        elif isinstance(node.target, (ast.Tuple, ast.List)):
            for idx, tgt in enumerate(node.target.elts):
                if isinstance(tgt, ast.Name):
                    for elt in node.iter.elts:
                        if isinstance(elt, (ast.Tuple, ast.List)) and idx < len(elt.elts):
                            val = elt.elts[idx]
                            if isinstance(val, ast.Constant) and isinstance(val.value, str) and val.value.startswith("--"):
                                bindings.setdefault(tgt.id, set()).add(val.value)
    return bindings


def extract_declared_cli_flags(py_path: Path) -> tuple[Optional[set[str]], Optional[str]]:
    """Inspect a Python file AST and collect `--*` option flags declared via add_argument()."""
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"illisible/non-UTF-8 ({exc})"
    except SyntaxError as exc:
        return None, f"SyntaxError ({exc})"

    loop_bindings = _collect_loop_flag_bindings(tree)
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_add = (isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument") or (isinstance(node.func, ast.Name) and node.func.id == "add_argument")
        if not is_add:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
                flags.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in loop_bindings:
                flags.update(loop_bindings[arg.id])
            elif isinstance(arg, (ast.Tuple, ast.List)):
                for elt in arg.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and elt.value.startswith("--"):
                        flags.add(elt.value)
    return flags, None


def imports_shared_module(py_path: Path, mod_name: str) -> tuple[bool, Optional[str]]:
    """Return True if py_path AST imports `_shared.<mod_name>` or `<mod_name>`."""
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return False, f"illisible/SyntaxError ({exc})"

    targets = {f"_shared.{mod_name}", mod_name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in targets or (node.module == "_shared" and any(a.name == mod_name for a in node.names)):
                return True, None
        elif isinstance(node, ast.Import) and any(a.name in targets for a in node.names):
            return True, None
    return False, None


def has_executable_manifest(plugin_dir: Path) -> bool:
    """Return True if the plugin declares an executable manifest requiring --fix-python-cmd."""
    if any((plugin_dir / rel).is_file() for rel in ("hooks.json", "mcp_config.json", "sidecar.json")):
        return True
    sidecars_dir = plugin_dir / "sidecars"
    return sidecars_dir.is_dir() and any(sc.is_file() for sc in sidecars_dir.rglob("sidecar.json"))


def collect_validator_sources(plugin_dir: Path) -> tuple[str, list[ast.AST]]:
    """Load source text and ASTs for validate.py, validators/*.py, and delegated _shared/validator_core.py."""
    scripts_dir = plugin_dir / "scripts"
    py_files: list[Path] = []
    if (main_val := scripts_dir / "validate.py").is_file():
        py_files.append(main_val)
        delegates, _ = imports_shared_module(main_val, "validator_core")
        shared_val = plugin_dir / "_shared" / "validator_core.py"
        if delegates and shared_val.is_file() and not is_symlink_or_junction(shared_val):
            py_files.append(shared_val)
    if (validators_pkg := scripts_dir / "validators").is_dir():
        py_files.extend(p for p in sorted(validators_pkg.rglob("*.py")) if "__pycache__" not in p.parts)

    texts, trees = [], []
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
    count, in_fence, fchar, flen = 0, False, "", 0
    for line in md_text.splitlines():
        if (fm := MD_FENCE_RE.match(line)):
            marker = fm.group(1)
            if not in_fence:
                in_fence, fchar, flen = True, marker[0], len(marker)
                continue
            if marker[0] == fchar and len(marker) >= flen and line.strip() == marker:
                in_fence = False
                continue
        if not in_fence and H2_HEADING_RE.match(line):
            count += 1
    return count


def extract_latest_changelog_version(changelog_text: str) -> Optional[str]:
    match = CHANGELOG_RELEASE_RE.search(changelog_text)
    return match.group(1) if match else None


def audit_module_contract(repo_dir: Path, plugin_manifest: Optional[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    """INT-01: Validate module.json v1 + SPI-1..3, provider_script path, plugin_name, and ui.mode."""
    plugin_dir = repo_dir / "plugin"
    module_path = plugin_dir / "config" / "module.json"
    empty = {"ok": False, "id": None, "plugin_name": None, "commands": [], "ui_mode": None}
    if not module_path.is_file():
        errors.append("INT-01 : plugin/config/module.json introuvable.")
        return empty
    err_before = len(errors)
    text, _ = read_utf8_text(module_path, "plugin/config/module.json", errors)
    if text is None:
        return empty
    try:
        mod_data = json.loads(text)
    except ValueError as exc:
        errors.append(f"INT-01 : plugin/config/module.json JSON invalide ({exc}).")
        return empty
    if not isinstance(mod_data, dict):
        errors.append("INT-01 : plugin/config/module.json doit contenir un objet JSON.")
        return empty

    rep = Report()
    vc_validate_module_contract(mod_data, rep)
    errors.extend(f"INT-01 : plugin/config/module.json : {cerr}" for cerr in rep.errors)

    dash = mod_data.get("dashboard")
    if isinstance(dash, dict) and isinstance(dash.get("provider_script"), str) and dash["provider_script"].strip():
        raw_ps = dash["provider_script"].strip()
        norm_ps = raw_ps.replace("\\", "/")
        ps_path = plugin_dir / norm_ps
        if "\x00" in norm_ps or norm_ps.startswith("/") or ".." in norm_ps.split("/"):
            errors.append(f"INT-01 : plugin/config/module.json : dashboard.provider_script invalide ({raw_ps!r}).")
        elif is_symlink_or_junction(ps_path) or not is_within_root(plugin_dir, ps_path) or not ps_path.is_file():
            errors.append(f"INT-01 : plugin/config/module.json : dashboard.provider_script introuvable ou hors plugin/ ({raw_ps!r}).")

    if isinstance(plugin_manifest, dict):
        exp_p, act_p = plugin_manifest.get("name"), mod_data.get("plugin_name")
        if isinstance(exp_p, str) and exp_p.strip() and act_p != exp_p:
            errors.append(f"INT-01 : module.json plugin_name ({act_p!r}) != plugin.json name ({exp_p!r}).")

    ui_mode = mod_data["ui"].get("mode") if isinstance(mod_data.get("ui"), dict) else None
    if isinstance(ui_mode, str) and ui_mode not in ALLOWED_UI_MODES:
        errors.append(f"INT-01 : ui.mode invalide ({ui_mode!r}), attendu dans {sorted(ALLOWED_UI_MODES)}.")

    raw_cmds = mod_data.get("commands")
    commands = [str(c) for c in raw_cmds if isinstance(c, str) and c.strip()] if isinstance(raw_cmds, list) else []
    return {
        "ok": len(errors) == err_before,
        "id": mod_data.get("id") if isinstance(mod_data.get("id"), str) else None,
        "plugin_name": mod_data.get("plugin_name") if isinstance(mod_data.get("plugin_name"), str) else None,
        "commands": commands,
        "ui_mode": ui_mode if isinstance(ui_mode, str) else None,
        "has_dashboard_spi": isinstance(dash, dict),
        "has_capture_policy": isinstance(mod_data.get("capture_policy"), dict),
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest_dict(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file() or is_symlink_or_junction(path):
        return None
    try:
        raw = path.read_bytes()
        if raw.startswith(UTF8_BOM):
            return None
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def check_shared_sync(repos_root: Path, repo_name: str, repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Fail-closed SHA-256 parity check between gravity_shared SSOT and repo/plugin/_shared."""
    ssot_dir = repos_root / SHARED_SOURCE_REPO / "shared" / "gravity_shared"
    plugin_dir = repo_dir / "plugin"
    shared_dir, manifest_path = plugin_dir / "_shared", plugin_dir / SHARED_MANIFEST_NAME
    ssot_present = ssot_dir.is_dir() or is_symlink_or_junction(ssot_dir)
    repo_has_shared = any(p.exists() or is_symlink_or_junction(p) for p in (shared_dir, manifest_path))
    if not ssot_present and not repo_has_shared:
        return {"ok": True, "skipped": True, "issues": []}

    issues: list[dict[str, str]] = []

    def _add(code: str, path: Path, detail: str) -> None:
        issues.append({"code": code, "path": str(path), "detail": detail})
        errors.append(f"SHARED-SYNC ({code}) : {detail}")

    for path in (repo_dir, plugin_dir, shared_dir, manifest_path):
        if is_symlink_or_junction(path):
            _add("SYMLINK_OR_JUNCTION", path, f"Lien symbolique ou jonction interdit : {path}")
    if shared_dir.is_dir() and not is_symlink_or_junction(shared_dir):
        for ent in sorted(shared_dir.iterdir(), key=lambda p: p.name):
            if is_symlink_or_junction(ent):
                _add("SYMLINK_OR_JUNCTION", ent, f"Lien symbolique ou jonction dans _shared : {ent}")

    expected_hashes: Optional[dict[str, str]] = None
    if ssot_present:
        if is_symlink_or_junction(ssot_dir):
            _add("SYMLINK_OR_JUNCTION", ssot_dir, f"SSOT ne doit pas être un lien/jonction : {ssot_dir}")
        else:
            collected: dict[str, str] = {}
            for ent in sorted(ssot_dir.iterdir(), key=lambda p: p.name):
                if ent.name == "__pycache__" or ent.suffix != ".py":
                    continue
                if is_symlink_or_junction(ent):
                    _add("SYMLINK_OR_JUNCTION", ent, f"Fichier SSOT lien/jonction interdit : {ent}")
                elif ent.is_file():
                    try:
                        raw = ent.read_bytes()
                        norm = (raw[len(UTF8_BOM) :] if raw.startswith(UTF8_BOM) else raw).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
                        collected[ent.name] = _sha256_bytes(norm)
                    except (OSError, UnicodeDecodeError) as exc:
                        _add("HASH_MISMATCH", ent, f"SSOT illisible ({ent.name}) : {exc}")
            if collected:
                expected_hashes = collected

    manifest = _read_manifest_dict(manifest_path)
    if not manifest_path.exists() and not is_symlink_or_junction(manifest_path):
        _add("MISSING", manifest_path, f"Manifest manquant : {manifest_path}")
    elif not is_symlink_or_junction(manifest_path):
        m_files = manifest.get("files") if manifest else None
        valid_meta = (
            manifest is not None and manifest.get("schema_version") == 1
            and manifest.get("source_repo") == SHARED_SOURCE_REPO
            and manifest.get("source_path") == SHARED_SOURCE_REL and isinstance(m_files, dict) and bool(m_files)
        )
        if not valid_meta or (expected_hashes is not None and m_files != expected_hashes):
            _add("MANIFEST_STALE", manifest_path, f"Manifeste {SHARED_MANIFEST_NAME} invalide ou désynchronisé ({repo_name}).")
        elif expected_hashes is None and valid_meta:
            expected_hashes = {str(k): str(v) for k, v in m_files.items()}  # type: ignore[union-attr]

    if not shared_dir.is_dir() and not is_symlink_or_junction(shared_dir):
        _add("MISSING", shared_dir, f"Dossier _shared manquant : {shared_dir}")
    elif expected_hashes is not None and not is_symlink_or_junction(shared_dir):
        for ent in sorted(shared_dir.iterdir(), key=lambda p: p.name):
            if not is_symlink_or_junction(ent) and ent.is_file() and ent.suffix == ".py" and ent.name not in expected_hashes:
                _add("EXTRA_FILE", ent, f"Fichier obsolète inattendu dans _shared : {ent.name}")
        for name, exp_sha in sorted(expected_hashes.items()):
            dst = shared_dir / name
            if is_symlink_or_junction(dst):
                continue
            if not dst.is_file():
                _add("MISSING", dst, f"Fichier _shared manquant : {name}")
            else:
                try:
                    actual_sha = _sha256_bytes(dst.read_bytes())
                except OSError:
                    actual_sha = ""
                if actual_sha != exp_sha:
                    _add("HASH_MISMATCH", dst, f"Divergence SHA-256 dans _shared/{name}")

    return {"ok": not issues, "skipped": False, "issues": issues}


def _extract_markdown_targets(md_text: str) -> list[str]:
    targets: list[str] = []
    in_fence, fchar, flen = False, "", 0
    for line in md_text.splitlines():
        if (fm := MD_FENCE_RE.match(line)):
            marker = fm.group(1)
            if not in_fence:
                in_fence, fchar, flen = True, marker[0], len(marker)
                continue
            if marker[0] == fchar and len(marker) >= flen and line.strip() == marker:
                in_fence = False
                continue
        if in_fence:
            continue
        for match in MD_LINK_RE.finditer(INLINE_CODE_RE.sub("", line)):
            raw_target = match.group(1).strip()
            if not raw_target:
                continue
            target = raw_target[1 : raw_target.index(">")].strip() if raw_target.startswith("<") and ">" in raw_target else raw_target.split()[0]
            if target:
                targets.append(target)
    return targets


def audit_markdown_links(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """INT-02: Validate relative local Markdown links and reject file: URIs."""
    candidates = [p for p in (repo_dir / "README.md", repo_dir / "plugin" / "README.md", repo_dir / "AGENTS.md") if p.is_file()]
    if (skills_dir := repo_dir / "plugin" / "skills").is_dir():
        candidates.extend(sorted(skills_dir.glob("*/SKILL.md")))
    if (docs_dir := repo_dir / "docs").is_dir():
        candidates.extend(sorted(docs_dir.glob("*.md")))

    err_before, broken = len(errors), []
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
            elif not lower.startswith(IGNORED_LINK_PREFIXES):
                rel = target.split("#", 1)[0].split("?", 1)[0]
                if rel and not (md_path.parent / rel).resolve().exists():
                    msg = f"INT-02 : lien Markdown relatif cassé dans {rel_lbl} : {target!r}"
                    errors.append(msg)
                    broken.append(msg)
    return {"ok": len(errors) == err_before, "files_checked": len(candidates), "broken": broken}


def _iter_repo_files(repo_dir: Path, exts: frozenset[str], *, skip_tests: bool = False, skip_archive: bool = False) -> list[Path]:
    found: list[Path] = []
    for path in sorted(repo_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(repo_dir)
        if any(p in SKIP_DIRS for p in rel.parts) or (skip_archive and any(p in ARCHIVE_DIRS for p in rel.parts)):
            continue
        if (rel.parts and rel.parts[0] == ".agents") or (skip_tests and rel.parts and rel.parts[0] == "tests"):
            continue
        if path.suffix.lower() in exts:
            found.append(path)
    return found


def audit_encoding_hygiene(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """INT-03: Exhaustive UTF-8 without BOM + LF check across repo source/doc/config files."""
    files, err_before, violations = _iter_repo_files(repo_dir, ENCODING_EXTS), len(errors), []
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
            raw, bad = raw[len(UTF8_BOM) :], True
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
    files, err_before, matches = _iter_repo_files(repo_dir, PERSONAL_PATH_EXTS, skip_tests=True), len(errors), []
    for fpath in files:
        rel_lbl = fpath.relative_to(repo_dir).as_posix()
        try:
            if PERSONAL_PATH_RE.search(fpath.read_text(encoding="utf-8", errors="replace")):
                errors.append(f"INT-04 : chemin personnel détecté dans {rel_lbl}.")
                matches.append(rel_lbl)
        except OSError:
            continue
    return {"ok": len(errors) == err_before, "files_checked": len(files), "matches": matches}


def audit_clean_legacy_refs(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Reject active legacy brand references outside CHANGELOG.md, archive/, and tests/."""
    files, err_before, matches = _iter_repo_files(repo_dir, ENCODING_EXTS, skip_tests=True, skip_archive=True), len(errors), []
    for fpath in files:
        rel_lbl = fpath.relative_to(repo_dir).as_posix()
        if rel_lbl == "CHANGELOG.md":
            continue
        try:
            if LEGACY_STUDIO_RE.search(fpath.read_text(encoding="utf-8", errors="replace")):
                errors.append(f"LEGACY-REF : référence '{'gravity-' 'studio'}' active détectée dans {rel_lbl}.")
                matches.append(rel_lbl)
        except OSError:
            continue
    return {"ok": len(errors) == err_before, "files_checked": len(files), "matches": matches}


def audit_commands_doc(repo_dir: Path, module_info: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """INT-08: Verify every module.json command is documented in SKILL.md union or README.md."""
    commands, err_before = list(module_info.get("commands") or []), len(errors)
    texts = [repo_dir / "README.md"] if (repo_dir / "README.md").is_file() else []
    if (skills_dir := repo_dir / "plugin" / "skills").is_dir():
        texts.extend(sorted(skills_dir.glob("*/SKILL.md")))
    union_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in texts)
    missing = [cmd for cmd in commands if cmd not in union_text]
    errors.extend(f"INT-08 : commande {cmd!r} absente de plugin/skills/*/SKILL.md et README.md." for cmd in missing)
    return {"ok": len(errors) == err_before, "commands": commands, "missing": missing}


def _normalize_win_json_node(node: Any) -> Any:
    if isinstance(node, list):
        return [_normalize_win_json_node(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: _normalize_win_json_node(v) for k, v in node.items()}
    cmd = out.get("command")
    if isinstance(cmd, str):
        args = out.get("args")
        if cmd == "py" and isinstance(args, list) and args and args[0] == "-3":
            out["command"], out["args"] = "python3", args[1:]
        elif cmd in ("python", "py -3"):
            out["command"] = "python3"
        elif cmd.startswith("python "):
            out["command"] = "python3 " + cmd[7:]
        elif cmd.startswith("py -3 "):
            out["command"] = "python3 " + cmd[6:]
    return out


def _is_win_adapt_json(rel_posix: str) -> bool:
    parts = rel_posix.split("/")
    return rel_posix in WIN_ADAPT_JSON_PATHS or (len(parts) == 3 and parts[0] == "sidecars" and parts[2] == "sidecar.json")


def _collect_plugin_hashes(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    out: dict[str, Path] = {}
    for fp in sorted(root.rglob("*")):
        if not fp.is_symlink() and fp.is_file():
            rel = fp.relative_to(root)
            if "__pycache__" not in rel.parts and fp.suffix.lower() not in (".pyc", ".pyo") and fp.name != ".DS_Store":
                out[rel.as_posix()] = fp
    return out


def audit_installed_sync(repo_dir: Path, plugin_name: str, plugins_dir: Path, errors: list[str]) -> dict[str, Any]:
    """INT-05: Compare repo/plugin/ vs <plugins_dir>/<plugin_name>/ allowing Windows python3 adaptation."""
    src_dir, installed_dir, err_before = repo_dir / "plugin", plugins_dir / plugin_name, len(errors)
    if not installed_dir.is_dir():
        errors.append(f"INT-05 : copie installée introuvable : {installed_dir}")
        return {"ok": False, "installed_dir": str(installed_dir), "missing_dir": True, "diff_files": []}

    src_files, inst_files = _collect_plugin_hashes(src_dir), _collect_plugin_hashes(installed_dir)
    missing, extra = sorted(set(src_files) - set(inst_files)), sorted(set(inst_files) - set(src_files))
    errors.extend(f"INT-05 : fichier manquant dans {installed_dir} : {rel}" for rel in missing)
    errors.extend(f"INT-05 : fichier supplémentaire dans {installed_dir} : {rel}" for rel in extra)

    mismatched: list[str] = []
    for rel in sorted(set(src_files) & set(inst_files)):
        sb, ib = src_files[rel].read_bytes(), inst_files[rel].read_bytes()
        if _sha256_bytes(sb) == _sha256_bytes(ib):
            continue
        if _is_win_adapt_json(rel):
            try:
                if _normalize_win_json_node(json.loads(sb.decode("utf-8-sig"))) == _normalize_win_json_node(json.loads(ib.decode("utf-8-sig"))):
                    continue
            except (UnicodeDecodeError, ValueError):
                pass
        mismatched.append(rel)
        errors.append(f"INT-05 : divergence SHA-256 entre plugin/ et {installed_dir} : {rel}")

    return {"ok": len(errors) == err_before, "installed_dir": str(installed_dir), "missing_dir": False, "missing_files": missing, "extra_files": extra, "diff_files": mismatched}


def _scan_rule_contradictions(repo_name: str, repo_dir: Path) -> list[str]:
    findings: list[str] = []
    targets = [p for p in (repo_dir / "AGENTS.md", repo_dir / "plugin" / "rules" / "AGENTS.md") if p.is_file()]
    if (skills_dir := repo_dir / "plugin" / "skills").is_dir():
        targets.extend(sorted(skills_dir.glob("*/SKILL.md")))
    for path in targets:
        rel_lbl, in_fence = f"{repo_name}/{path.relative_to(repo_dir).as_posix()}", False
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if MD_FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence or not line.strip():
                continue
            if _BRIDGE_PROACTIVE_RE.search(line) and not _NEG_RE.search(line):
                findings.append(f"{rel_lbl}:{lineno} : directive Bridge proactive sans garde-fou humain.")
            if _DEV_ON_MAIN_RE.search(line) and not _NEG_RE.search(line):
                findings.append(f"{rel_lbl}:{lineno} : directive de dev/commit direct sur 'main' (attendu: 'dev').")
            has_both = ("audits/code" in line.lower()) and ("audits/agents" in line.lower())
            if (_AUDIT_MIX_RE.search(line) or has_both) and not _AUDIT_SEPARATION_NEG_RE.search(line):
                findings.append(f"{rel_lbl}:{lineno} : mélange potentiel entre audits/code/ et audits/agents/.")
    return findings


def audit_workshop_r2(repos_root: Path, errors: list[str]) -> dict[str, Any]:
    """AUD-05-09: Reject active ready tasks in gravity-workshop/tasks/*.md whose spec is missing, archived, or unvalidated."""
    workshop_dir = repos_root / "gravity-workshop"
    tasks_dir = workshop_dir / "tasks"
    if not workshop_dir.is_dir() or not tasks_dir.is_dir():
        return {"ok": True, "skipped": True, "tasks_checked": 0, "stale_tasks": []}

    stale_tasks, tasks_checked = [], 0
    for task_path in sorted(tasks_dir.glob("*.md")):
        if task_path.name.startswith("_") or is_symlink_or_junction(task_path):
            continue
        tasks_checked += 1
        try:
            txt = task_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"AUD-05-09 : tâche '{task_path.name}' illisible ({exc}).")
            stale_tasks.append(task_path.name)
            continue
        if not (st_m := _TASK_STATUS_RE.search(txt)) or st_m.group(1).lower() != "ready":
            continue
        raw_src = (src_m.group(1).strip() if (src_m := _TASK_SPEC_SRC_RE.search(txt)) else "")
        if (lm := re.match(r"^\[[^\]]*\]\(([^)]+)\)$", raw_src)):
            raw_src = lm.group(1).strip()
        spec_rel = raw_src.strip("`'\"").replace("\\", "/")

        reason: Optional[str] = None
        if not spec_rel:
            reason = "Spec source manquante"
        elif spec_rel.startswith("/") or ".." in spec_rel.split("/") or "archive" in spec_rel.split("/"):
            reason = f"Spec source archivée ou invalide ({spec_rel!r})"
        else:
            spec_path = workshop_dir / spec_rel
            if is_symlink_or_junction(spec_path) or not is_within_root(workshop_dir, spec_path) or not spec_path.is_file():
                reason = f"Spec source introuvable ({spec_rel!r})"
            else:
                spec_txt = spec_path.read_text(encoding="utf-8", errors="replace")
                sp_st = _SPEC_STATUS_RE.search(spec_txt)
                actual_st = sp_st.group(1).lower() if sp_st else ""
                if actual_st != "validated":
                    reason = f"spec {spec_rel!r} a status={actual_st or 'missing'!r} != 'validated'"
                else:
                    t_sid, s_sid = _SPEC_ID_RE.search(txt), _SPEC_ID_RE.search(spec_txt)
                    if t_sid and s_sid and t_sid.group(1) != s_sid.group(1):
                        reason = f"Spec ID discordant ({t_sid.group(1)} != {s_sid.group(1)})"

        if reason:
            stale_tasks.append(task_path.name)
            errors.append(f"AUD-05-09 : tâche ready '{task_path.name}' obsolète ({reason}).")
    return {"ok": not stale_tasks, "skipped": False, "tasks_checked": tasks_checked, "stale_tasks": stale_tasks}


def audit_cross_repo(repo_reports: Sequence[dict[str, Any]], repos_root: Path, *, required_repos: Sequence[str] = ()) -> dict[str, Any]:
    """Validate cumulative rules budget, module id/command collisions, contradictions, and AUD-05-09."""
    errors, warnings, total_rules_bytes = [], [], 0
    id_owners: dict[str, list[str]] = {}
    cmd_owners: dict[str, list[str]] = {}
    contradictions: list[str] = []
    audited_names: set[str] = set()

    for rep in repo_reports:
        if not rep.get("exists"):
            continue
        rname = str(rep["repo"])
        audited_names.add(rname)
        checks = rep.get("checks") or {}
        rules = checks.get("rules_d4") or {}
        if not rules.get("exempt") and isinstance(rules.get("bytes"), int):
            total_rules_bytes += rules["bytes"]
        mod = checks.get("module_contract") or {}
        if isinstance(mod.get("id"), str) and mod["id"]:
            id_owners.setdefault(mod["id"], []).append(rname)
        for cmd in mod.get("commands") or []:
            cmd_owners.setdefault(cmd, []).append(rname)
        contradictions.extend(_scan_rule_contradictions(rname, repos_root / rname))

    if total_rules_bytes > RULES_TOTAL_ERROR_BYTES:
        errors.append(f"Budget cumulé plugin/rules/AGENTS.md dépassé : {total_rules_bytes} o > {RULES_TOTAL_ERROR_BYTES} o.")
    elif total_rules_bytes > RULES_TOTAL_WARN_BYTES:
        warnings.append(f"Budget cumulé plugin/rules/AGENTS.md élevé : {total_rules_bytes} o > {RULES_TOTAL_WARN_BYTES} o.")

    id_collisions = {k: v for k, v in sorted(id_owners.items()) if len(v) > 1}
    errors.extend(f"Collision module.json id {mid!r} entre dépôts : {owners}." for mid, owners in id_collisions.items())
    cmd_collisions = {k: v for k, v in sorted(cmd_owners.items()) if len(v) > 1}
    errors.extend(f"Collision commande {cmd!r} entre dépôts : {owners}." for cmd, owners in cmd_collisions.items())
    errors.extend(contradictions)

    workshop_r2: dict[str, Any] = {"ok": True, "skipped": True, "tasks_checked": 0, "stale_tasks": []}
    if (repos_root / "gravity-workshop" / "tasks").is_dir() and (not required_repos or set(required_repos).issubset(audited_names)):
        workshop_r2 = audit_workshop_r2(repos_root, errors)

    return {
        "ok": not errors, "errors": errors, "warnings": warnings,
        "rules_total_bytes": total_rules_bytes, "rules_warn_threshold": RULES_TOTAL_WARN_BYTES, "rules_error_threshold": RULES_TOTAL_ERROR_BYTES,
        "id_collisions": id_collisions, "command_collisions": cmd_collisions, "contradictions": contradictions, "workshop_r2": workshop_r2,
    }

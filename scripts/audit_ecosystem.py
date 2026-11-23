#!/usr/bin/env python3
"""Read-only cross-repo drift detector for the 5 Gravity repositories (100% stdlib Python 3.10+)."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOS_ROOT = REPO_ROOT.parent

DEFAULT_REPOS: tuple[str, ...] = (
    "gravity",
    "gravity-workflow",
    "gravity-metrics",
    "gravity-architect",
    "gravity-bridge",
)

REQUIRED_INSTALL_FLAGS: tuple[str, ...] = (
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

OFFICIAL_PLUGIN_FIELDS: frozenset[str] = frozenset(
    {
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
)
REQUIRED_PLUGIN_FIELDS: frozenset[str] = OFFICIAL_PLUGIN_FIELDS - {"disabled"}

REPO_AGENTS_MAX_BYTES = 2500
REPO_AGENTS_EXPECTED_H2 = 3
RULES_WARN_BYTES = 600
RULES_ERROR_BYTES = 1000
RULES_EXEMPT_REPOS: frozenset[str] = frozenset({"gravity-workflow"})
SUGGESTED_PROMPT_MAX_CHARS = 100
PY_WARN_LINES = 800
PY_ERROR_LINES = 1500
UTF8_BOM = b"\xef\xbb\xbf"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
CHANGELOG_RELEASE_RE = re.compile(
    r"^##\s+\[(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\]",
    re.MULTILINE,
)
H2_HEADING_RE = re.compile(r"^##\s+\S")
MD_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _configure_stdio() -> None:
    """Force stdout/stderr to UTF-8 so Windows cp1252 consoles never crash."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _read_utf8_text(
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


def _extract_declared_cli_flags(py_path: Path) -> tuple[Optional[set[str]], Optional[str]]:
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
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith("--"):
                    flags.add(arg.value)
            elif isinstance(arg, (ast.Tuple, ast.List)):
                for elt in arg.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        if elt.value.startswith("--"):
                            flags.add(elt.value)
    return flags, None


def _audit_install_cli(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Verify the 11-flag common CLI contract in install.py using AST inspection."""
    installer = repo_dir / "install.py"
    if not installer.is_file():
        errors.append("install.py introuvable à la racine du dépôt.")
        return {"ok": False, "present": [], "missing": list(REQUIRED_INSTALL_FLAGS)}

    flags, parse_err = _extract_declared_cli_flags(installer)
    if parse_err is not None or flags is None:
        errors.append(f"install.py : échec inspection AST ({parse_err}).")
        return {"ok": False, "present": [], "missing": list(REQUIRED_INSTALL_FLAGS)}

    present = [flag for flag in REQUIRED_INSTALL_FLAGS if flag in flags]
    missing = [flag for flag in REQUIRED_INSTALL_FLAGS if flag not in flags]
    if missing:
        errors.append(
            f"install.py : drapeau(x) CLI manquant(s) ({len(missing)}/11) : {', '.join(missing)}."
        )
    return {"ok": not missing, "present": present, "missing": missing}


def _has_executable_manifest(plugin_dir: Path) -> bool:
    """Return True if the plugin declares an executable manifest requiring --fix-python-cmd."""
    for rel in ("hooks.json", "mcp_config.json", "sidecar.json"):
        if (plugin_dir / rel).is_file():
            return True
    sidecars_dir = plugin_dir / "sidecars"
    if sidecars_dir.is_dir():
        for sc in sidecars_dir.rglob("sidecar.json"):
            if sc.is_file():
                return True
    return False


def _collect_validator_sources(plugin_dir: Path) -> tuple[str, list[ast.AST]]:
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


def _collect_ast_literals(trees: Sequence[ast.AST]) -> tuple[set[str], set[bytes]]:
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


def _audit_validate_contract(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Verify plugin/scripts/validate.py presence, flags, and required validation checks."""
    plugin_dir = repo_dir / "plugin"
    validate_path = plugin_dir / "scripts" / "validate.py"
    requires_fix = _has_executable_manifest(plugin_dir)

    if not validate_path.is_file():
        errors.append("plugin/scripts/validate.py introuvable.")
        return {
            "ok": False,
            "missing": ["validate.py"],
            "requires_fix_python_cmd": requires_fix,
        }

    flags, parse_err = _extract_declared_cli_flags(validate_path)
    if parse_err is not None or flags is None:
        errors.append(f"plugin/scripts/validate.py : échec inspection AST ({parse_err}).")
        return {
            "ok": False,
            "missing": ["valid_ast"],
            "requires_fix_python_cmd": requires_fix,
        }

    missing_items: list[str] = []
    if "--strict" not in flags:
        missing_items.append("--strict")
        errors.append("plugin/scripts/validate.py : drapeau '--strict' non déclaré.")

    if requires_fix and "--fix-python-cmd" not in flags:
        missing_items.append("--fix-python-cmd")
        errors.append(
            "plugin/scripts/validate.py : drapeau '--fix-python-cmd' requis "
            "(manifeste exécutable présent)."
        )

    combined_src, trees = _collect_validator_sources(plugin_dir)
    str_lits, bytes_lits = _collect_ast_literals(trees)

    has_plugin_json_9 = (
        ("plugin.json" in combined_src)
        and all(field in str_lits or f'"{field}"' in combined_src for field in REQUIRED_PLUGIN_FIELDS)
    )
    if not has_plugin_json_9:
        missing_items.append("check:plugin.json(9)")
        errors.append("plugin/scripts/validate.py : contrôle plugin.json (9 champs) non détecté.")

    has_module_json = ("module.json" in combined_src) and (
        "schema_version" in combined_src or "validate_module_contract" in combined_src
    )
    if not has_module_json:
        missing_items.append("check:config/module.json")
        errors.append("plugin/scripts/validate.py : contrôle config/module.json non détecté.")

    has_stdlib = "stdlib_module_names" in combined_src
    if not has_stdlib:
        missing_items.append("check:stdlib-only")
        errors.append("plugin/scripts/validate.py : contrôle stdlib-only (stdlib_module_names) non détecté.")

    has_bom_check = (UTF8_BOM in bytes_lits) or ("\\xef\\xbb\\xbf" in combined_src.lower())
    has_lf_check = (
        (b"\r\n" in bytes_lits)
        or ("\r\n" in str_lits)
        or ("\\r\\n" in combined_src)
    )
    if not (has_bom_check and has_lf_check):
        missing_items.append("check:utf8-bom-lf")
        errors.append("plugin/scripts/validate.py : contrôle UTF-8 sans BOM / LF non détecté.")

    return {
        "ok": not missing_items,
        "missing": missing_items,
        "requires_fix_python_cmd": requires_fix,
    }


def _count_h2_sections(md_text: str) -> int:
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
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                continue
            if marker[0] == fence_char and len(marker) >= fence_len and line.strip() == marker:
                in_fence = False
                fence_char = ""
                fence_len = 0
                continue
        if not in_fence and H2_HEADING_RE.match(line):
            count += 1
    return count


def _audit_root_agents(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Verify root AGENTS.md budget (<= 2 500 B), UTF-8 no-BOM, LF, and 3 `##` sections."""
    agents_path = repo_dir / "AGENTS.md"
    if not agents_path.is_file():
        errors.append("AGENTS.md racine introuvable.")
        return {"ok": False, "bytes": None, "sections": 0}

    err_before = len(errors)
    text, size = _read_utf8_text(agents_path, "AGENTS.md", errors)
    if size > REPO_AGENTS_MAX_BYTES:
        errors.append(
            f"AGENTS.md : dépasse {REPO_AGENTS_MAX_BYTES} octets ({size} o)."
        )

    sections = _count_h2_sections(text) if text is not None else 0
    if text is not None and sections != REPO_AGENTS_EXPECTED_H2:
        errors.append(
            f"AGENTS.md : {sections} section(s) '##' détectée(s), {REPO_AGENTS_EXPECTED_H2} attendues."
        )

    return {"ok": len(errors) == err_before, "bytes": size, "sections": sections}


def _audit_rules_d4(
    repo_name: str,
    repo_dir: Path,
    errors: list[str],
    warnings: list[str],
    infos: list[str],
) -> dict[str, Any]:
    """Verify plugin/rules/AGENTS.md D4 budgets and zero YAML frontmatter."""
    rules_path = repo_dir / "plugin" / "rules" / "AGENTS.md"
    if not rules_path.is_file():
        if repo_name in RULES_EXEMPT_REPOS:
            infos.append(f"plugin/rules/AGENTS.md absent (exception documentée SRP {repo_name}).")
            return {"ok": True, "exempt": True, "bytes": None, "severity": "exempt"}
        errors.append("plugin/rules/AGENTS.md introuvable.")
        return {"ok": False, "exempt": False, "bytes": None, "severity": "error"}

    err_before = len(errors)
    warn_before = len(warnings)
    text, size = _read_utf8_text(rules_path, "plugin/rules/AGENTS.md", errors)

    if size > RULES_ERROR_BYTES:
        errors.append(
            f"plugin/rules/AGENTS.md : dépasse {RULES_ERROR_BYTES} octets ({size} o)."
        )
    elif size > RULES_WARN_BYTES:
        warnings.append(
            f"plugin/rules/AGENTS.md : dépasse la cible éditoriale de {RULES_WARN_BYTES} octets ({size} o <= {RULES_ERROR_BYTES} o)."
        )

    if text is not None and text.lstrip().startswith("---"):
        errors.append("plugin/rules/AGENTS.md : frontmatter YAML interdit.")

    severity = "ok"
    if len(errors) > err_before:
        severity = "error"
    elif len(warnings) > warn_before:
        severity = "warn"

    return {"ok": severity == "ok", "exempt": False, "bytes": size, "severity": severity}


def _extract_latest_changelog_version(changelog_text: str) -> Optional[str]:
    """Extract the most recent released `## [X.Y.Z]` version from CHANGELOG.md."""
    match = CHANGELOG_RELEASE_RE.search(changelog_text)
    return match.group(1) if match else None


def _audit_manifest_and_changelog(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Verify plugin.json (9 fields, suggestedPrompts <= 100 c, /cmd — summary) and CHANGELOG sync."""
    manifest_path = repo_dir / "plugin" / "plugin.json"
    changelog_path = repo_dir / "CHANGELOG.md"
    err_before = len(errors)

    plugin_version: Optional[str] = None
    changelog_version: Optional[str] = None
    prompts_ok = True

    if not manifest_path.is_file():
        errors.append("plugin/plugin.json introuvable.")
    else:
        manifest_text, _ = _read_utf8_text(manifest_path, "plugin/plugin.json", errors)
        if manifest_text is not None:
            try:
                manifest = json.loads(manifest_text)
            except ValueError as exc:
                errors.append(f"plugin/plugin.json : JSON invalide ({exc}).")
                manifest = None

            if isinstance(manifest, dict):
                unknown = sorted(set(manifest.keys()) - OFFICIAL_PLUGIN_FIELDS)
                if unknown:
                    errors.append(
                        f"plugin/plugin.json : champs non officiels détectés : {unknown}."
                    )
                missing = sorted(REQUIRED_PLUGIN_FIELDS - set(manifest.keys()))
                if missing:
                    errors.append(
                        f"plugin/plugin.json : champs officiels requis manquants : {missing}."
                    )

                desc = manifest.get("description")
                if not isinstance(desc, str) or not desc.strip() or len(desc) > 160:
                    dlen = len(desc) if isinstance(desc, str) else 0
                    errors.append(
                        f"plugin/plugin.json : 'description' vide ou > 160 caractères ({dlen})."
                    )

                raw_ver = manifest.get("version")
                if not isinstance(raw_ver, str) or not SEMVER_RE.match(raw_ver.strip()):
                    errors.append(f"plugin/plugin.json : 'version' SemVer invalide ({raw_ver!r}).")
                else:
                    plugin_version = raw_ver.strip()

                prompts = manifest.get("suggestedPrompts")
                if (
                    not isinstance(prompts, list)
                    or len(prompts) != 3
                    or not all(isinstance(p, str) and p.strip() for p in prompts)
                ):
                    prompts_ok = False
                    errors.append(
                        "plugin/plugin.json : exactement 3 'suggestedPrompts' non vides sont requis."
                    )
                else:
                    for idx, prompt in enumerate(prompts):
                        if len(prompt) > SUGGESTED_PROMPT_MAX_CHARS:
                            prompts_ok = False
                            errors.append(
                                f"plugin/plugin.json : suggestedPrompts[{idx}] > {SUGGESTED_PROMPT_MAX_CHARS} car. ({len(prompt)})."
                            )
                        stripped = prompt.lstrip()
                        if stripped.startswith("/"):
                            sep = " — " if " — " in stripped else (" - " if " - " in stripped else None)
                            if sep is None:
                                prompts_ok = False
                                errors.append(
                                    f"plugin/plugin.json : suggestedPrompts[{idx}] débutant par '/' doit suivre '/cmd — résumé'."
                                )
                            else:
                                cmd_part, summary_part = stripped.split(sep, 1)
                                if len(cmd_part.strip()) <= 1 or not summary_part.strip():
                                    prompts_ok = False
                                    errors.append(
                                        f"plugin/plugin.json : suggestedPrompts[{idx}] commande ou résumé vide."
                                    )
            elif manifest is not None:
                errors.append("plugin/plugin.json doit contenir un objet JSON.")

    if not changelog_path.is_file():
        errors.append("CHANGELOG.md introuvable.")
    else:
        cl_text, _ = _read_utf8_text(changelog_path, "CHANGELOG.md", errors)
        if cl_text is not None:
            changelog_version = _extract_latest_changelog_version(cl_text)
            if changelog_version is None:
                errors.append("CHANGELOG.md : aucune release '## [X.Y.Z]' détectée.")
            elif plugin_version is not None and plugin_version != changelog_version:
                errors.append(
                    f"Désynchronisation SemVer : plugin.json={plugin_version!r} != CHANGELOG.md={changelog_version!r}."
                )

    return {
        "ok": len(errors) == err_before,
        "plugin_version": plugin_version,
        "changelog_version": changelog_version,
        "prompts_ok": prompts_ok,
    }


def _is_mcp_ui_bundle(py_file: Path, plugin_dir: Path) -> bool:
    """Return True for embedded frontend vanilla JS/CSS bundles under plugin/mcp/ui/*.py."""
    try:
        rel = py_file.relative_to(plugin_dir)
    except ValueError:
        return False
    return len(rel.parts) == 3 and rel.parts[0] == "mcp" and rel.parts[1] == "ui"


def _audit_python_monoliths(
    repo_dir: Path,
    errors: list[str],
    warnings: list[str],
    infos: list[str],
) -> dict[str, Any]:
    """Detect oversized Python modules under plugin/**/*.py with exemption for plugin/mcp/ui/*.py."""
    plugin_dir = repo_dir / "plugin"
    warn_files: list[dict[str, Any]] = []
    error_files: list[dict[str, Any]] = []
    exempt_files: list[dict[str, Any]] = []

    if not plugin_dir.is_dir():
        return {"ok": True, "warn_files": [], "error_files": [], "exempt_files": []}

    for py_file in sorted(plugin_dir.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{py_file.relative_to(repo_dir).as_posix()} illisible : {exc}")
            continue

        lines = len(content.splitlines())
        rel_posix = py_file.relative_to(repo_dir).as_posix()

        if _is_mcp_ui_bundle(py_file, plugin_dir):
            if lines > PY_WARN_LINES:
                exempt_files.append({"path": rel_posix, "lines": lines})
                infos.append(
                    f"{rel_posix} ({lines} L) exempté (bundle JS/CSS embarqué sous plugin/mcp/ui/)."
                )
            continue

        if lines > PY_ERROR_LINES:
            entry = {"path": rel_posix, "lines": lines}
            error_files.append(entry)
            errors.append(
                f"{rel_posix} : dette monolithique critique ({lines} L > {PY_ERROR_LINES} L)."
            )
        elif lines > PY_WARN_LINES:
            entry = {"path": rel_posix, "lines": lines}
            warn_files.append(entry)
            warnings.append(
                f"{rel_posix} : alerte dette monolithique ({lines} L > {PY_WARN_LINES} L)."
            )

    return {
        "ok": not error_files,
        "warn_files": warn_files,
        "error_files": error_files,
        "exempt_files": exempt_files,
    }


def audit_repo(repo_name: str, repo_dir: Path) -> dict[str, Any]:
    """Run all read-only compliance checks on a single Gravity repository."""
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    if not repo_dir.is_dir():
        errors.append(f"Dépôt introuvable : {repo_dir}")
        return {
            "repo": repo_name,
            "path": str(repo_dir),
            "exists": False,
            "status": "FAIL",
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
            "checks": {},
        }

    install_res = _audit_install_cli(repo_dir, errors)
    validate_res = _audit_validate_contract(repo_dir, errors)
    agents_res = _audit_root_agents(repo_dir, errors)
    rules_res = _audit_rules_d4(repo_name, repo_dir, errors, warnings, infos)
    manifest_res = _audit_manifest_and_changelog(repo_dir, errors)
    monolith_res = _audit_python_monoliths(repo_dir, errors, warnings, infos)

    if errors:
        status = "FAIL"
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "repo": repo_name,
        "path": str(repo_dir),
        "exists": True,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "checks": {
            "install_cli": install_res,
            "validate_contract": validate_res,
            "agents_root": agents_res,
            "rules_d4": rules_res,
            "manifest_changelog": manifest_res,
            "monoliths": monolith_res,
        },
    }


def audit_ecosystem(
    repos_root: Path,
    repos: Sequence[str],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Audit all requested Gravity repositories under repos_root in strict read-only mode."""
    repo_reports = [audit_repo(name, repos_root / name) for name in repos]
    total_errors = sum(len(r["errors"]) for r in repo_reports)
    total_warnings = sum(len(r["warnings"]) for r in repo_reports)
    ok = total_errors == 0 and (not strict or total_warnings == 0)

    return {
        "ok": ok,
        "strict": strict,
        "repos_root": str(repos_root),
        "repos": repo_reports,
        "summary": {
            "repo_count": len(repo_reports),
            "pass_count": sum(1 for r in repo_reports if r["status"] == "PASS"),
            "warn_count": sum(1 for r in repo_reports if r["status"] == "WARN"),
            "fail_count": sum(1 for r in repo_reports if r["status"] == "FAIL"),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
        },
    }


def _format_cell_install(checks: dict[str, Any]) -> str:
    ic = checks.get("install_cli") or {}
    present = len(ic.get("present") or [])
    return f"{present}/11" if ic else "-"


def _format_cell_validate(checks: dict[str, Any]) -> str:
    vc = checks.get("validate_contract") or {}
    if not vc:
        return "-"
    return "OK" if vc.get("ok") else f"ERR({len(vc.get('missing') or [])})"


def _format_cell_agents(checks: dict[str, Any]) -> str:
    ag = checks.get("agents_root") or {}
    b = ag.get("bytes")
    if b is None:
        return "MISSING"
    tag = "OK" if ag.get("ok") else "ERR"
    return f"{b}o({tag})"


def _format_cell_rules(checks: dict[str, Any]) -> str:
    rl = checks.get("rules_d4") or {}
    if rl.get("exempt"):
        return "EXEMPT"
    b = rl.get("bytes")
    if b is None:
        return "MISSING"
    sev = rl.get("severity", "ok").upper()
    return f"{b}o({sev})"


def _format_cell_manifest(checks: dict[str, Any]) -> str:
    mc = checks.get("manifest_changelog") or {}
    if not mc:
        return "-"
    pv = mc.get("plugin_version") or "?"
    cv = mc.get("changelog_version") or "?"
    if mc.get("ok"):
        return f"{pv}=={cv}"
    return f"{pv}!={cv}" if pv != cv else f"{pv}(ERR)"


def _format_cell_monoliths(checks: dict[str, Any]) -> str:
    mn = checks.get("monoliths") or {}
    if not mn:
        return "-"
    n_err = len(mn.get("error_files") or [])
    n_warn = len(mn.get("warn_files") or [])
    n_ex = len(mn.get("exempt_files") or [])
    parts = [f"E:{n_err}", f"W:{n_warn}"]
    if n_ex:
        parts.append(f"Ex:{n_ex}")
    return " ".join(parts)


def format_console_report(report: dict[str, Any], *, strict: bool = False) -> str:
    """Render a compact summary table plus detailed findings for console output."""
    headers = ("Repo", "Status", "install", "validate", "AGENTS", "rules D4", "SemVer/UX", "Monoliths")
    rows: list[tuple[str, ...]] = []
    for item in report["repos"]:
        checks = item.get("checks") or {}
        rows.append(
            (
                item["repo"],
                item["status"],
                _format_cell_install(checks),
                _format_cell_validate(checks),
                _format_cell_agents(checks),
                _format_cell_rules(checks),
                _format_cell_manifest(checks),
                _format_cell_monoliths(checks),
            )
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)] if rows else [len(h) for h in headers]

    def fmt_row(vals: Sequence[str]) -> str:
        return " | ".join(vals[i].ljust(widths[i]) for i in range(len(headers)))

    lines: list[str] = [
        f"Gravity Ecosystem Drift Audit (repos-root={report['repos_root']}, strict={strict})",
        fmt_row(headers),
        "-+-".join("-" * w for w in widths),
    ]
    for row in rows:
        lines.append(fmt_row(row))

    for item in report["repos"]:
        if not (item["errors"] or item["warnings"] or item["infos"]):
            continue
        lines.append("")
        lines.append(f"[{item['repo']}] ({item['status']})")
        for err in item["errors"]:
            lines.append(f"  [ERROR] {err}")
        for warn in item["warnings"]:
            lines.append(f"  [WARN]  {warn}")
        for info in item["infos"]:
            lines.append(f"  [INFO]  {info}")

    summary = report["summary"]
    verdict = "PASS" if report["ok"] else "FAIL"
    lines.append("")
    lines.append(
        f"[{verdict}] {summary['repo_count']} dépôts audités "
        f"(PASS={summary['pass_count']}, WARN={summary['warn_count']}, FAIL={summary['fail_count']}; "
        f"erreurs={summary['total_errors']}, avertissements={summary['total_warnings']})."
    )
    return "\n".join(lines)


def _parse_repos_csv(raw_csv: str) -> list[str]:
    repos = [tok.strip() for tok in raw_csv.split(",") if tok.strip()]
    if not repos:
        raise ValueError("--repos requiert au moins un nom de dépôt.")
    seen: set[str] = set()
    ordered: list[str] = []
    for name in repos:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auditeur lecture seule de dérive multi-dépôts Gravity (100% stdlib)."
    )
    parser.add_argument(
        "--repos-root",
        type=Path,
        default=DEFAULT_REPOS_ROOT,
        help="Dossier parent contenant les dépôts Gravity (défaut : parent du dépôt gravity).",
    )
    parser.add_argument(
        "--repos",
        default=",".join(DEFAULT_REPOS),
        help="Liste CSV des dépôts à auditer.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Émet le rapport complet en JSON (CI-ready).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Échoue (exit 1) également en présence d'avertissements.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        repos = _parse_repos_csv(args.repos)
    except ValueError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    repos_root = args.repos_root.expanduser().resolve()
    report = audit_ecosystem(repos_root, repos, strict=args.strict)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_console_report(report, strict=args.strict))

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

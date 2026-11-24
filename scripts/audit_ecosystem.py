#!/usr/bin/env python3
"""Read-only cross-repo drift detector and parallel verifier for the 4 active Gravity repositories (100% stdlib Python 3.10+)."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Optional, Sequence

try:
    from scripts.audit_checks import (
        UTF8_BOM,
        audit_commands_doc,
        audit_cross_repo,
        audit_encoding_hygiene,
        audit_installed_sync,
        audit_markdown_links,
        audit_module_contract,
        audit_personal_paths,
        collect_ast_literals,
        collect_validator_sources,
        count_h2_sections,
        extract_declared_cli_flags,
        extract_latest_changelog_version,
        has_executable_manifest,
        read_utf8_text,
    )
except ImportError:
    _SCRIPT_DIR = Path(__file__).resolve().parent
    if str(_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPT_DIR))
    from audit_checks import (  # type: ignore[no-redef]
        UTF8_BOM,
        audit_commands_doc,
        audit_cross_repo,
        audit_encoding_hygiene,
        audit_installed_sync,
        audit_markdown_links,
        audit_module_contract,
        audit_personal_paths,
        collect_ast_literals,
        collect_validator_sources,
        count_h2_sections,
        extract_declared_cli_flags,
        extract_latest_changelog_version,
        has_executable_manifest,
        read_utf8_text,
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOS_ROOT = REPO_ROOT.parent
DEFAULT_PLUGINS_DIR = Path.home() / ".gemini" / "config" / "plugins"

DEFAULT_REPOS: tuple[str, ...] = (
    "gravity",
    "gravity-workflow",
    "gravity-metrics",
    "gravity-architect",
)
VERIFY_PARALLEL_MAX_WORKERS = 4
VERIFY_CMD_TIMEOUT_SECONDS = 300.0

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
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _configure_stdio() -> None:
    """Force stdout/stderr to UTF-8 so Windows cp1252 consoles never crash."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _audit_install_cli(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Verify the 11-flag common CLI contract in install.py using AST inspection."""
    installer = repo_dir / "install.py"
    if not installer.is_file():
        errors.append("install.py introuvable à la racine du dépôt.")
        return {"ok": False, "present": [], "missing": list(REQUIRED_INSTALL_FLAGS)}

    flags, parse_err = extract_declared_cli_flags(installer)
    if parse_err is not None or flags is None:
        errors.append(f"install.py : échec inspection AST ({parse_err}).")
        return {"ok": False, "present": [], "missing": list(REQUIRED_INSTALL_FLAGS)}

    present = [flag for flag in REQUIRED_INSTALL_FLAGS if flag in flags]
    missing = [flag for flag in REQUIRED_INSTALL_FLAGS if flag not in flags]
    if missing:
        errors.append(f"install.py : drapeau(x) CLI manquant(s) ({len(missing)}/11) : {', '.join(missing)}.")
    return {"ok": not missing, "present": present, "missing": missing}


def _audit_validate_contract(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Verify plugin/scripts/validate.py presence, flags, and required validation checks."""
    plugin_dir = repo_dir / "plugin"
    validate_path = plugin_dir / "scripts" / "validate.py"
    requires_fix = has_executable_manifest(plugin_dir)

    if not validate_path.is_file():
        errors.append("plugin/scripts/validate.py introuvable.")
        return {"ok": False, "missing": ["validate.py"], "requires_fix_python_cmd": requires_fix}

    flags, parse_err = extract_declared_cli_flags(validate_path)
    if parse_err is not None or flags is None:
        errors.append(f"plugin/scripts/validate.py : échec inspection AST ({parse_err}).")
        return {"ok": False, "missing": ["valid_ast"], "requires_fix_python_cmd": requires_fix}

    missing_items: list[str] = []
    if "--strict" not in flags:
        missing_items.append("--strict")
        errors.append("plugin/scripts/validate.py : drapeau '--strict' non déclaré.")

    if requires_fix and "--fix-python-cmd" not in flags:
        missing_items.append("--fix-python-cmd")
        errors.append("plugin/scripts/validate.py : drapeau '--fix-python-cmd' requis (manifeste exécutable présent).")

    combined_src, trees = collect_validator_sources(plugin_dir)
    str_lits, bytes_lits = collect_ast_literals(trees)

    has_plugin_json_9 = ("plugin.json" in combined_src) and all(
        field in str_lits or f'"{field}"' in combined_src for field in REQUIRED_PLUGIN_FIELDS
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

    if "stdlib_module_names" not in combined_src:
        missing_items.append("check:stdlib-only")
        errors.append("plugin/scripts/validate.py : contrôle stdlib-only (stdlib_module_names) non détecté.")

    has_bom_check = (UTF8_BOM in bytes_lits) or ("\\xef\\xbb\\xbf" in combined_src.lower())
    has_lf_check = (b"\r\n" in bytes_lits) or ("\r\n" in str_lits) or ("\\r\\n" in combined_src)
    if not (has_bom_check and has_lf_check):
        missing_items.append("check:utf8-bom-lf")
        errors.append("plugin/scripts/validate.py : contrôle UTF-8 sans BOM / LF non détecté.")

    return {"ok": not missing_items, "missing": missing_items, "requires_fix_python_cmd": requires_fix}


def _audit_root_agents(repo_dir: Path, errors: list[str]) -> dict[str, Any]:
    """Verify root AGENTS.md budget (<= 2 500 B), UTF-8 no-BOM, LF, and 3 `##` sections."""
    agents_path = repo_dir / "AGENTS.md"
    if not agents_path.is_file():
        errors.append("AGENTS.md racine introuvable.")
        return {"ok": False, "bytes": None, "sections": 0}

    err_before = len(errors)
    text, size = read_utf8_text(agents_path, "AGENTS.md", errors)
    if size > REPO_AGENTS_MAX_BYTES:
        errors.append(f"AGENTS.md : dépasse {REPO_AGENTS_MAX_BYTES} octets ({size} o).")

    sections = count_h2_sections(text) if text is not None else 0
    if text is not None and sections != REPO_AGENTS_EXPECTED_H2:
        errors.append(f"AGENTS.md : {sections} section(s) '##' détectée(s), {REPO_AGENTS_EXPECTED_H2} attendues.")

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
    text, size = read_utf8_text(rules_path, "plugin/rules/AGENTS.md", errors)

    if size > RULES_ERROR_BYTES:
        errors.append(f"plugin/rules/AGENTS.md : dépasse {RULES_ERROR_BYTES} octets ({size} o).")
    elif size > RULES_WARN_BYTES:
        warnings.append(
            f"plugin/rules/AGENTS.md : dépasse la cible éditoriale de {RULES_WARN_BYTES} octets ({size} o <= {RULES_ERROR_BYTES} o)."
        )

    if text is not None and text.lstrip().startswith("---"):
        errors.append("plugin/rules/AGENTS.md : frontmatter YAML interdit.")

    severity = "error" if len(errors) > err_before else ("warn" if len(warnings) > warn_before else "ok")
    return {"ok": severity == "ok", "exempt": False, "bytes": size, "severity": severity}


def _audit_manifest_and_changelog(repo_dir: Path, errors: list[str]) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Verify plugin.json (9 fields, suggestedPrompts <= 100 c, /cmd — summary) and CHANGELOG sync."""
    manifest_path = repo_dir / "plugin" / "plugin.json"
    changelog_path = repo_dir / "CHANGELOG.md"
    err_before = len(errors)

    plugin_version: Optional[str] = None
    changelog_version: Optional[str] = None
    prompts_ok = True
    manifest: Optional[dict[str, Any]] = None

    if not manifest_path.is_file():
        errors.append("plugin/plugin.json introuvable.")
    else:
        manifest_text, _ = read_utf8_text(manifest_path, "plugin/plugin.json", errors)
        if manifest_text is not None:
            try:
                parsed = json.loads(manifest_text)
            except ValueError as exc:
                errors.append(f"plugin/plugin.json : JSON invalide ({exc}).")
                parsed = None

            if isinstance(parsed, dict):
                manifest = parsed
                unknown = sorted(set(manifest.keys()) - OFFICIAL_PLUGIN_FIELDS)
                if unknown:
                    errors.append(f"plugin/plugin.json : champs non officiels détectés : {unknown}.")
                missing = sorted(REQUIRED_PLUGIN_FIELDS - set(manifest.keys()))
                if missing:
                    errors.append(f"plugin/plugin.json : champs officiels requis manquants : {missing}.")

                desc = manifest.get("description")
                if not isinstance(desc, str) or not desc.strip() or len(desc) > 160:
                    dlen = len(desc) if isinstance(desc, str) else 0
                    errors.append(f"plugin/plugin.json : 'description' vide ou > 160 caractères ({dlen}).")

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
                    errors.append("plugin/plugin.json : exactement 3 'suggestedPrompts' non vides sont requis.")
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
            elif parsed is not None:
                errors.append("plugin/plugin.json doit contenir un objet JSON.")

    if not changelog_path.is_file():
        errors.append("CHANGELOG.md introuvable.")
    else:
        cl_text, _ = read_utf8_text(changelog_path, "CHANGELOG.md", errors)
        if cl_text is not None:
            changelog_version = extract_latest_changelog_version(cl_text)
            if changelog_version is None:
                errors.append("CHANGELOG.md : aucune release '## [X.Y.Z]' détectée.")
            elif plugin_version is not None and plugin_version != changelog_version:
                errors.append(
                    f"Désynchronisation SemVer : plugin.json={plugin_version!r} != CHANGELOG.md={changelog_version!r}."
                )

    return (
        {
            "ok": len(errors) == err_before,
            "plugin_version": plugin_version,
            "changelog_version": changelog_version,
            "prompts_ok": prompts_ok,
        },
        manifest,
    )


def _is_mcp_ui_bundle(py_file: Path, plugin_dir: Path) -> bool:
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
                infos.append(f"{rel_posix} ({lines} L) exempté (bundle JS/CSS embarqué sous plugin/mcp/ui/).")
            continue

        entry = {"path": rel_posix, "lines": lines}
        if lines > PY_ERROR_LINES:
            error_files.append(entry)
            errors.append(f"{rel_posix} : dette monolithique critique ({lines} L > {PY_ERROR_LINES} L).")
        elif lines > PY_WARN_LINES:
            warn_files.append(entry)
            warnings.append(f"{rel_posix} : alerte dette monolithique ({lines} L > {PY_WARN_LINES} L).")

    return {"ok": not error_files, "warn_files": warn_files, "error_files": error_files, "exempt_files": exempt_files}


def audit_repo(
    repo_name: str,
    repo_dir: Path,
    *,
    check_installed: bool = False,
    plugins_dir: Optional[Path] = None,
) -> dict[str, Any]:
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
    manifest_res, manifest_obj = _audit_manifest_and_changelog(repo_dir, errors)
    monolith_res = _audit_python_monoliths(repo_dir, errors, warnings, infos)
    module_res = audit_module_contract(repo_dir, manifest_obj, errors)
    links_res = audit_markdown_links(repo_dir, errors)
    encoding_res = audit_encoding_hygiene(repo_dir, errors)
    paths_res = audit_personal_paths(repo_dir, errors)
    cmds_res = audit_commands_doc(repo_dir, module_res, errors)

    checks: dict[str, Any] = {
        "install_cli": install_res,
        "validate_contract": validate_res,
        "agents_root": agents_res,
        "rules_d4": rules_res,
        "manifest_changelog": manifest_res,
        "monoliths": monolith_res,
        "module_contract": module_res,
        "markdown_links": links_res,
        "encoding_hygiene": encoding_res,
        "personal_paths": paths_res,
        "commands_doc": cmds_res,
    }
    if check_installed:
        plugin_name = (
            (manifest_obj.get("name") if isinstance(manifest_obj, dict) else None)
            or module_res.get("plugin_name")
            or repo_name
        )
        resolved_plugins = (plugins_dir or DEFAULT_PLUGINS_DIR).expanduser().resolve()
        checks["installed_sync"] = audit_installed_sync(repo_dir, str(plugin_name), resolved_plugins, errors)

    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "repo": repo_name,
        "path": str(repo_dir),
        "exists": True,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "checks": checks,
    }


def _tail_lines(text: str, max_lines: int = 12) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def _failed_check_result(
    error: str,
    *,
    cmd: Optional[list[str]] = None,
    returncode: int = 1,
    duration_s: float = 0.0,
) -> dict[str, Any]:
    return {
        "cmd": list(cmd or []),
        "returncode": returncode,
        "ok": False,
        "duration_s": round(duration_s, 3),
        "stdout_tail": "",
        "stderr_tail": error,
        "error": error,
    }


def _run_verify_cmd(cmd: list[str], cwd: Path, timeout_s: float) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        res = _failed_check_result(
            f"Timeout après {timeout_s:.0f}s : {' '.join(cmd)}",
            cmd=cmd,
            returncode=124,
            duration_s=elapsed,
        )
        if exc.stdout:
            out_txt = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout)
            res["stdout_tail"] = _tail_lines(out_txt)
        if exc.stderr:
            err_txt = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr)
            res["stderr_tail"] = _tail_lines(err_txt)
        return res
    except OSError as exc:
        return _failed_check_result(
            f"Erreur exécution ({exc}) : {' '.join(cmd)}",
            cmd=cmd,
            returncode=127,
            duration_s=time.monotonic() - started,
        )

    elapsed = round(time.monotonic() - started, 3)
    ok = proc.returncode == 0
    result: dict[str, Any] = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "ok": ok,
        "duration_s": elapsed,
        "stdout_tail": _tail_lines(proc.stdout),
        "stderr_tail": _tail_lines(proc.stderr),
    }
    if not ok:
        detail = result["stderr_tail"] or result["stdout_tail"] or f"exit {proc.returncode}"
        result["error"] = f"Échec commande (rc={proc.returncode}) : {detail.splitlines()[-1]}"
    return result


def verify_repo_checks(
    repo_name: str,
    repo_dir: Path,
    *,
    agy_bin: Optional[str] = None,
    timeout_s: float = VERIFY_CMD_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run validate.py --strict, agy plugin validate ./plugin --strict, and unittest discover for one repo."""
    started = time.monotonic()
    if not repo_dir.is_dir():
        msg = f"Dépôt introuvable : {repo_dir}"
        return {
            "repo": repo_name,
            "path": str(repo_dir),
            "exists": False,
            "ok": False,
            "status": "FAIL",
            "duration_s": 0.0,
            "errors": [msg],
            "checks": {
                "validate": _failed_check_result(msg),
                "agy": _failed_check_result(msg),
                "unittest": _failed_check_result(msg),
            },
        }

    checks: dict[str, dict[str, Any]] = {}
    val_script = repo_dir / "plugin" / "scripts" / "validate.py"
    if not val_script.is_file():
        checks["validate"] = _failed_check_result("plugin/scripts/validate.py introuvable.")
    else:
        checks["validate"] = _run_verify_cmd(
            [sys.executable, "-B", str(val_script), "--strict"],
            repo_dir,
            timeout_s,
        )

    plugin_dir = repo_dir / "plugin"
    resolved_agy = agy_bin if agy_bin is not None else shutil.which("agy")
    if not plugin_dir.is_dir():
        checks["agy"] = _failed_check_result("Dossier plugin/ introuvable.")
    elif not resolved_agy:
        checks["agy"] = _failed_check_result("Exécutable 'agy' introuvable dans PATH (fail-closed).", returncode=127)
    else:
        checks["agy"] = _run_verify_cmd(
            [resolved_agy, "plugin", "validate", "./plugin", "--strict"],
            repo_dir,
            timeout_s,
        )

    tests_dir = repo_dir / "tests"
    if not tests_dir.is_dir():
        checks["unittest"] = _failed_check_result("Dossier tests/ introuvable.")
    else:
        checks["unittest"] = _run_verify_cmd(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
            repo_dir,
            timeout_s,
        )

    errors: list[str] = []
    for cname, res in checks.items():
        if not res.get("ok"):
            errors.append(f"{cname}: {res.get('error') or 'failed'}")

    repo_ok = len(errors) == 0 and all(bool(c.get("ok")) for c in checks.values())
    return {
        "repo": repo_name,
        "path": str(repo_dir),
        "exists": True,
        "ok": repo_ok,
        "status": "PASS" if repo_ok else "FAIL",
        "duration_s": round(time.monotonic() - started, 3),
        "errors": errors,
        "checks": checks,
    }


def verify_ecosystem_parallel(
    repos_root: Path,
    repos: Sequence[str],
    *,
    strict: bool = False,
    max_workers: int = VERIFY_PARALLEL_MAX_WORKERS,
    agy_bin: Optional[str] = None,
    timeout_s: float = VERIFY_CMD_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run all 3 verification commands across target repositories in parallel (fail-closed)."""
    started = time.monotonic()
    repo_list = list(repos)
    if not repo_list:
        return {
            "ok": False,
            "mode": "verify-parallel",
            "strict": strict,
            "repos_root": str(repos_root),
            "max_workers": max_workers,
            "duration_s": 0.0,
            "repos": [],
            "errors": ["Aucun dépôt cible fourni (fail-closed)."],
            "summary": {
                "repo_count": 0,
                "pass_count": 0,
                "fail_count": 0,
                "total_errors": 1,
                "checks_total": 0,
                "checks_passed": 0,
                "checks_failed": 0,
            },
        }

    ordered_results: list[Optional[dict[str, Any]]] = [None] * len(repo_list)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                verify_repo_checks,
                name,
                repos_root / name,
                agy_bin=agy_bin,
                timeout_s=timeout_s,
            ): idx
            for idx, name in enumerate(repo_list)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            repo_name = repo_list[idx]
            try:
                ordered_results[idx] = future.result()
            except Exception as exc:
                msg = f"Exception interne worker ({exc})"
                ordered_results[idx] = {
                    "repo": repo_name,
                    "path": str(repos_root / repo_name),
                    "exists": (repos_root / repo_name).is_dir(),
                    "ok": False,
                    "status": "FAIL",
                    "duration_s": 0.0,
                    "errors": [msg],
                    "checks": {
                        "validate": _failed_check_result(msg),
                        "agy": _failed_check_result(msg),
                        "unittest": _failed_check_result(msg),
                    },
                }

    repo_results = [r for r in ordered_results if r is not None]
    pass_count = sum(1 for r in repo_results if r.get("ok"))
    fail_count = len(repo_results) - pass_count
    total_errors = sum(len(r.get("errors") or []) for r in repo_results)
    checks_total = sum(len(r.get("checks") or {}) for r in repo_results)
    checks_passed = sum(
        1 for r in repo_results for c in (r.get("checks") or {}).values() if c.get("ok")
    )
    checks_failed = checks_total - checks_passed
    overall_ok = (len(repo_results) == len(repo_list)) and (fail_count == 0) and (total_errors == 0)

    return {
        "ok": overall_ok,
        "mode": "verify-parallel",
        "strict": strict,
        "repos_root": str(repos_root),
        "max_workers": max_workers,
        "duration_s": round(time.monotonic() - started, 3),
        "repos": repo_results,
        "summary": {
            "repo_count": len(repo_results),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "total_errors": total_errors,
            "checks_total": checks_total,
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
        },
    }


def audit_ecosystem(
    repos_root: Path,
    repos: Sequence[str],
    *,
    strict: bool = False,
    check_installed: bool = False,
    plugins_dir: Optional[Path] = None,
    verify_parallel: bool = False,
) -> dict[str, Any]:
    """Audit or parallel-verify all requested Gravity repositories under repos_root."""
    if verify_parallel:
        return verify_ecosystem_parallel(repos_root, repos, strict=strict)
    repo_reports = [
        audit_repo(name, repos_root / name, check_installed=check_installed, plugins_dir=plugins_dir)
        for name in repos
    ]
    cross_repo = audit_cross_repo(repo_reports, repos_root)
    total_errors = sum(len(r["errors"]) for r in repo_reports) + len(cross_repo["errors"])
    total_warnings = sum(len(r["warnings"]) for r in repo_reports) + len(cross_repo["warnings"])
    ok = total_errors == 0 and (not strict or total_warnings == 0)

    return {
        "ok": ok,
        "strict": strict,
        "repos_root": str(repos_root),
        "repos": repo_reports,
        "cross_repo": cross_repo,
        "summary": {
            "repo_count": len(repo_reports),
            "pass_count": sum(1 for r in repo_reports if r["status"] == "PASS"),
            "warn_count": sum(1 for r in repo_reports if r["status"] == "WARN"),
            "fail_count": sum(1 for r in repo_reports if r["status"] == "FAIL"),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "cross_repo_errors": len(cross_repo["errors"]),
            "cross_repo_warnings": len(cross_repo["warnings"]),
            "rules_total_bytes": cross_repo["rules_total_bytes"],
        },
    }


def _format_cell_install(checks: dict[str, Any]) -> str:
    ic = checks.get("install_cli") or {}
    return f"{len(ic.get('present') or [])}/11" if ic else "-"


def _format_cell_validate(checks: dict[str, Any]) -> str:
    vc = checks.get("validate_contract") or {}
    return "-" if not vc else ("OK" if vc.get("ok") else f"ERR({len(vc.get('missing') or [])})")


def _format_cell_agents(checks: dict[str, Any]) -> str:
    ag = checks.get("agents_root") or {}
    b = ag.get("bytes")
    return "MISSING" if b is None else f"{b}o({'OK' if ag.get('ok') else 'ERR'})"


def _format_cell_rules(checks: dict[str, Any]) -> str:
    rl = checks.get("rules_d4") or {}
    if rl.get("exempt"):
        return "EXEMPT"
    b = rl.get("bytes")
    return "MISSING" if b is None else f"{b}o({rl.get('severity', 'ok').upper()})"


def _format_cell_manifest(checks: dict[str, Any]) -> str:
    mc = checks.get("manifest_changelog") or {}
    if not mc:
        return "-"
    pv, cv = mc.get("plugin_version") or "?", mc.get("changelog_version") or "?"
    return f"{pv}=={cv}" if mc.get("ok") else (f"{pv}!={cv}" if pv != cv else f"{pv}(ERR)")


def _format_cell_monoliths(checks: dict[str, Any]) -> str:
    mn = checks.get("monoliths") or {}
    if not mn:
        return "-"
    parts = [f"E:{len(mn.get('error_files') or [])}", f"W:{len(mn.get('warn_files') or [])}"]
    n_ex = len(mn.get("exempt_files") or [])
    if n_ex:
        parts.append(f"Ex:{n_ex}")
    return " ".join(parts)


def _format_cell_integrity(checks: dict[str, Any]) -> str:
    keys = ("module_contract", "markdown_links", "encoding_hygiene", "personal_paths", "commands_doc")
    if not any(k in checks for k in keys):
        return "-"
    fails = sum(1 for k in keys if checks.get(k) and not checks[k].get("ok"))
    inst = checks.get("installed_sync")
    if inst is not None:
        return f"ERR({fails + (0 if inst.get('ok') else 1)})" if (fails or not inst.get("ok")) else "OK+INST"
    return "OK" if fails == 0 else f"ERR({fails})"


def _format_verify_cell(checks: dict[str, Any], key: str) -> str:
    res = checks.get(key)
    if not isinstance(res, dict):
        return "-"
    tag = "OK" if res.get("ok") else f"ERR({res.get('returncode', 1)})"
    return f"{tag} {float(res.get('duration_s') or 0.0):.1f}s"


def format_verify_parallel_report(report: dict[str, Any]) -> str:
    """Render a compact summary table and failure details for --verify-parallel output."""
    headers = ("Repo", "Status", "validate", "agy", "unittest", "Duration")
    rows: list[tuple[str, ...]] = []
    for item in report.get("repos") or []:
        checks = item.get("checks") or {}
        rows.append(
            (
                str(item.get("repo") or "?"),
                str(item.get("status") or "FAIL"),
                _format_verify_cell(checks, "validate"),
                _format_verify_cell(checks, "agy"),
                _format_verify_cell(checks, "unittest"),
                f"{float(item.get('duration_s') or 0.0):.2f}s",
            )
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)] if rows else [len(h) for h in headers]

    def fmt_row(vals: Sequence[str]) -> str:
        return " | ".join(vals[i].ljust(widths[i]) for i in range(len(headers)))

    lines: list[str] = [
        f"Gravity Ecosystem Parallel Verify (repos-root={report.get('repos_root')}, "
        f"workers={report.get('max_workers', VERIFY_PARALLEL_MAX_WORKERS)}, strict={bool(report.get('strict'))})",
        fmt_row(headers),
        "-+-".join("-" * w for w in widths),
    ]
    lines.extend(fmt_row(row) for row in rows)

    for item in report.get("repos") or []:
        errs = item.get("errors") or []
        if not errs:
            continue
        lines.extend(["", f"[{item.get('repo')}] ({item.get('status')})"])
        lines.extend(f"  [ERROR] {err}" for err in errs)
        checks = item.get("checks") or {}
        for cname in ("validate", "agy", "unittest"):
            cres = checks.get(cname) or {}
            if not cres.get("ok"):
                tail = cres.get("stderr_tail") or cres.get("stdout_tail") or ""
                if tail:
                    lines.append(f"  [{cname} tail]")
                    lines.extend(f"    {ln}" for ln in tail.splitlines())

    summary = report.get("summary") or {}
    verdict = "PASS" if report.get("ok") else "FAIL"
    lines.extend(
        [
            "",
            f"[{verdict}] {summary.get('pass_count', 0)}/{summary.get('repo_count', 0)} dépôts validés en parallèle "
            f"({summary.get('checks_passed', 0)}/{summary.get('checks_total', 0)} vérifs OK, "
            f"erreurs={summary.get('total_errors', 0)}, durée={float(report.get('duration_s') or 0.0):.2f}s).",
        ]
    )
    return "\n".join(lines)


def format_console_report(report: dict[str, Any], *, strict: bool = False) -> str:
    """Render a compact summary table plus detailed findings for console output."""
    if report.get("mode") == "verify-parallel":
        return format_verify_parallel_report(report)
    headers = ("Repo", "Status", "install", "validate", "AGENTS", "rules D4", "SemVer/UX", "Monoliths", "INT")
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
                _format_cell_integrity(checks),
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
    lines.extend(fmt_row(row) for row in rows)

    for item in report["repos"]:
        if not (item["errors"] or item["warnings"] or item["infos"]):
            continue
        lines.extend(["", f"[{item['repo']}] ({item['status']})"])
        lines.extend(f"  [ERROR] {err}" for err in item["errors"])
        lines.extend(f"  [WARN]  {warn}" for warn in item["warnings"])
        lines.extend(f"  [INFO]  {info}" for info in item["infos"])

    cross = report.get("cross_repo") or {}
    if cross.get("errors") or cross.get("warnings"):
        lines.extend(["", f"[cross-repo] (rules_total={cross.get('rules_total_bytes', 0)} o)"])
        lines.extend(f"  [ERROR] {err}" for err in cross.get("errors") or [])
        lines.extend(f"  [WARN]  {warn}" for warn in cross.get("warnings") or [])

    summary = report["summary"]
    verdict = "PASS" if report["ok"] else "FAIL"
    lines.extend(
        [
            "",
            f"[{verdict}] {summary['repo_count']} dépôts audités "
            f"(PASS={summary['pass_count']}, WARN={summary['warn_count']}, FAIL={summary['fail_count']}; "
            f"erreurs={summary['total_errors']}, avertissements={summary['total_warnings']}; "
            f"rules_cumul={summary.get('rules_total_bytes', 0)} o).",
        ]
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
    parser = argparse.ArgumentParser(description="Auditeur lecture seule de dérive multi-dépôts Gravity (100% stdlib).")
    parser.add_argument("--repos-root", type=Path, default=DEFAULT_REPOS_ROOT, help="Dossier parent contenant les dépôts Gravity.")
    parser.add_argument("--repos", default=",".join(DEFAULT_REPOS), help="Liste CSV des dépôts à auditer.")
    parser.add_argument("--check-installed", action="store_true", help="Compare plugin/ aux copies installées (INT-05).")
    parser.add_argument("--plugins-dir", type=Path, default=DEFAULT_PLUGINS_DIR, help="Dossier des plugins installés (défaut: ~/.gemini/config/plugins).")
    parser.add_argument("--json", action="store_true", help="Émet le rapport complet en JSON (CI-ready).")
    parser.add_argument("--strict", action="store_true", help="Échoue (exit 1) également en présence d'avertissements.")
    parser.add_argument(
        "--verify-parallel",
        action="store_true",
        help="Exécute en parallèle (max_workers=4) validate.py --strict, agy plugin validate ./plugin --strict et unittest discover.",
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
    plugins_dir = args.plugins_dir.expanduser().resolve() if args.plugins_dir else None
    report = audit_ecosystem(
        repos_root,
        repos,
        strict=args.strict,
        check_installed=args.check_installed,
        plugins_dir=plugins_dir,
        verify_parallel=args.verify_parallel,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_console_report(report, strict=args.strict))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

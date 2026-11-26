#!/usr/bin/env python3
"""Strict standalone validator for the Gravity Core Antigravity plugin (100% stdlib)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT_DEFAULT = SCRIPT_DIR.parent
if str(PLUGIN_ROOT_DEFAULT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT_DEFAULT))

from _shared.validator_core import (  # noqa: E402
    ALLOWED_LOCAL_MODULES,
    PERSONAL_PATH_RE,
    Report,
    ValidatorConfig,
    _check_markdown_links,
    check_utf8_no_bom_lf,
    fix_python_cmd,
    has_real_python3,
    run_cli,
    validate_hooks_config,
    validate_mcp_config,
    validate_module_contract,
    validate_plugin_manifest,
    validate_plugin_tree,
)

CORE_ALLOWED_LOCAL_MODULES = ALLOWED_LOCAL_MODULES | frozenset({"hooks", "scripts"})
REQUIRED_DIRS: tuple[str, ...] = (
    "assets",
    "config",
    "core",
    "dashboard",
    "hooks",
    "mcp",
    "rules",
    "scripts",
    "skills",
)
DOC_GUIDE_MAX_BYTES = 15_360
UX_GUIDE_FILES: tuple[str, ...] = (
    "getting-started.md",
    "user-journey.md",
    "command-cheatsheet.md",
    "troubleshooting-and-lifecycle.md",
)
MCP_APP_URI = "ui://gravity/dashboard.html"
MCP_APP_MIME = "text/html;profile=mcp-app"
MCP_HTML_MAX_BYTES = 150 * 1024
MCP_TRAJECTORY_MAX_BYTES = 450_000
EXPECTED_MCP_TOOLS: frozenset[str] = frozenset({
    "open_gravity_dashboard",
    "gravity_get_live_session",
    "gravity_get_overview",
    "gravity_get_workflow_state",
    "gravity_get_metrics_state",
    "gravity_get_session_detail",
    "gravity_metrics_action",
    "gravity_read_audit",
    "gravity_get_architect_state",
    "gravity_get_module_info",
})
SKILL_REQUIRED_SUBCOMMANDS: tuple[str, ...] = (
    "init",
    "status",
    "modules",
    "doctor",
    "dashboard",
    "update",
    "help",
)
STUDIO_REF_RE = re.compile(r"\bgravity-" + r"studio\b", re.IGNORECASE)


def _check_doc_hygiene(doc_path: Path, label: str, report: Report, *, max_bytes: Optional[int] = None) -> None:
    payload = check_utf8_no_bom_lf(doc_path, label, report, max_bytes=max_bytes)
    if payload is None:
        return
    txt = payload.decode("utf-8", errors="replace")
    if PERSONAL_PATH_RE.search(txt):
        report.error(f"Chemin personnel détecté dans {label}")
    if STUDIO_REF_RE.search(txt):
        report.error(f"Référence legacy {'gravity-' 'studio'} détectée dans {label}")


def _validate_core_skills(root: Path, report: Report) -> None:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return
    names = [p.name for p in sorted(skills_dir.iterdir()) if p.is_dir()]
    if names != ["gravity"]:
        report.error(f"skills/ doit contenir uniquement 'gravity/' (trouvé : {names}).")
        return
    skill_md = skills_dir / "gravity" / "SKILL.md"
    if not skill_md.is_file():
        return
    txt = skill_md.read_text(encoding="utf-8", errors="replace")
    for subcmd in SKILL_REQUIRED_SUBCOMMANDS:
        if subcmd not in txt:
            report.error(f"skills/gravity/SKILL.md : sous-commande '/gravity {subcmd}' non documentée.")


def _validate_markdown_links(root: Path, report: Report) -> None:
    """Validate relative local Markdown links and UX guide presence/budgets."""
    if (plugin_readme := root / "README.md").is_file():
        _check_markdown_links(plugin_readme, "README.md", report)
    if (skills_dir := root / "skills").is_dir():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            _check_markdown_links(skill_md, skill_md.relative_to(root).as_posix(), report)

    docs_dir = root.parent / "docs"
    if root.name == "plugin" and docs_dir.is_dir():
        for guide_name in UX_GUIDE_FILES:
            guide_path = docs_dir / guide_name
            if not guide_path.is_file():
                report.error(f"Guide UX manquant : docs/{guide_name}")
            else:
                _check_doc_hygiene(guide_path, f"docs/{guide_name}", report, max_bytes=DOC_GUIDE_MAX_BYTES)
        if (repo_readme := root.parent / "README.md").is_file():
            _check_markdown_links(repo_readme, "../README.md", report)
            _check_doc_hygiene(repo_readme, "../README.md", report)
        for doc_md in sorted(docs_dir.glob("*.md")):
            _check_markdown_links(doc_md, f"../docs/{doc_md.name}", report)
            if doc_md.name not in UX_GUIDE_FILES:
                _check_doc_hygiene(doc_md, f"../docs/{doc_md.name}", report)


def _run_e2e_dry_run(root: Path, report: Report) -> None:
    init_script = root / "scripts" / "init_env.py"
    if not init_script.is_file():
        report.error("Script scripts/init_env.py manquant.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir(parents=True)
        shutil.copytree(root, plugins_dir / "gravity", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        gravity_home = tmp_path / "gravity-home"
        fake_user_home = tmp_path / "user-home"
        fake_user_home.mkdir(parents=True)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(fake_user_home), "USERPROFILE": str(fake_user_home)}
        env.pop("GRAVITY_HOME", None)
        env.pop("GRAVITY_CORE_HOME", None)

        check_home = tmp_path / "uninitialized-check"
        p_check = subprocess.run(
            [sys.executable, "-B", str(init_script), "--gravity-home", str(check_home), "--plugins-dir", str(plugins_dir), "--check", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=10, check=False,
        )
        if p_check.returncode != 0:
            report.error(f"Dry-run init_env.py --check échoué : {p_check.stderr or p_check.stdout}")
            return
        if check_home.exists():
            report.error("Dry-run init_env.py --check a créé un dossier alors qu'il doit rester lecture seule.")

        p_init = subprocess.run(
            [sys.executable, "-B", str(init_script), "--gravity-home", str(gravity_home), "--plugins-dir", str(plugins_dir), "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=10, check=False,
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


def _run_mcp_dry_run(root: Path, report: Report) -> None:
    server_script = root / "mcp" / "server.py"
    if not server_script.is_file():
        report.error(f"Serveur MCP introuvable : {server_script}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "user-home"
        fake_home.mkdir(parents=True)
        gravity_home = tmp_path / "gravity-home"
        gravity_home.mkdir(parents=True)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(fake_home), "USERPROFILE": str(fake_home), "GRAVITY_HOME": str(gravity_home)}
        for key in ("GRAVITY_CORE_HOME", "GRAVITY_WORKFLOW_HOME", "GRAVITY_METRICS_HOME", "GRAVITY_ARCHITECT_HOME", "GRAVITY_ARCHITECT_WORKSPACE", "GRAVITY_AUDITS_DIR"):
            env.pop(key, None)

        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "gravity-validator", "version": "1.0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": MCP_APP_URI}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "open_gravity_dashboard", "arguments": {}}},
        ]
        proc = subprocess.run(
            [sys.executable, "-B", str(server_script)],
            input="\n".join(json.dumps(r) for r in requests) + "\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=10, check=False,
        )
        if proc.returncode != 0:
            report.error(f"Dry-run MCP échoué (rc={proc.returncode}) : {proc.stderr or proc.stdout}")
            return
        lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        if len(lines) != 5:
            report.error(f"Dry-run MCP : 5 réponses attendues, obtenu {len(lines)}.")
            return
        try:
            resps = {obj["id"]: obj for obj in (json.loads(ln) for ln in lines)}
        except Exception as exc:
            report.error(f"Dry-run MCP : JSON-RPC invalide ({exc})")
            return
        for req_id in (1, 2, 3, 4, 5):
            if req_id not in resps or "error" in resps[req_id]:
                report.error(f"Dry-run MCP : réponse erreur/manquante pour id={req_id} : {resps.get(req_id)!r}")
                return

        tools = (resps[2].get("result") or {}).get("tools") or []
        tool_names = {t.get("name") for t in tools if isinstance(t, dict)}
        if tool_names != EXPECTED_MCP_TOOLS:
            report.error(f"MCP tools/list : outils attendus {sorted(EXPECTED_MCP_TOOLS)}, obtenu {sorted(tool_names)}")
        open_tool = next((t for t in tools if t.get("name") == "open_gravity_dashboard"), None)
        if not open_tool:
            report.error("MCP tools/list : 'open_gravity_dashboard' manquant.")
        else:
            meta = open_tool.get("_meta") or {}
            ui_meta = meta.get("ui") or {}
            if ui_meta.get("resourceUri") != MCP_APP_URI:
                report.error(f"MCP resourceUri invalide : {ui_meta.get('resourceUri')!r}")
            if not {"model", "app"}.issubset(set(ui_meta.get("visibility") or [])):
                report.error(f"MCP open_gravity_dashboard visibility invalide : {ui_meta.get('visibility')!r}")
            ep_types = {e.get("type") for e in ((meta.get("com.google.antigravity/ui") or {}).get("entrypoints") or []) if isinstance(e, dict)}
            if not {"aux_pane", "global"}.issubset(ep_types):
                report.error(f"MCP entrypoints incomplets : {ep_types!r}")
        for tool in tools:
            tname = str(tool.get("name") or "")
            if tname.startswith("gravity_get_"):
                vis = ((tool.get("_meta") or {}).get("ui") or {}).get("visibility")
                if vis != ["app"]:
                    report.error(f"MCP outil {tname!r} : visibility doit être ['app'], obtenu {vis!r}")

        resources = (resps[3].get("result") or {}).get("resources") or []
        if not resources or resources[0].get("uri") != MCP_APP_URI:
            report.error(f"MCP resources/list invalide : {resources!r}")
        elif ((resources[0].get("_meta") or {}).get("ui") or {}).get("prefersBorder") is not False:
            report.error("MCP resources/list : _meta.ui.prefersBorder doit être False.")

        contents = (resps[4].get("result") or {}).get("contents") or []
        if not contents:
            report.error("MCP resources/read : contenu vide.")
        else:
            c0 = contents[0]
            html_txt = str(c0.get("text") or "")
            if c0.get("mimeType") != MCP_APP_MIME:
                report.error(f"MCP mimeType invalide : {c0.get('mimeType')!r}")
            html_bytes = len(html_txt.encode("utf-8"))
            if not html_txt or html_bytes >= MCP_HTML_MAX_BYTES:
                report.error(f"MCP HTML vide ou >= {MCP_HTML_MAX_BYTES} o ({html_bytes}).")
            for forbidden in ("innerHTML", "http://", "https://", "window.confirm", "window.alert", "window.prompt"):
                if forbidden in html_txt:
                    report.error(f"MCP HTML : motif interdit {forbidden!r} détecté (CSP / anti-XSS).")

        call_res = resps[5].get("result") or {}
        call_bytes = len(json.dumps(call_res, ensure_ascii=False).encode("utf-8"))
        sc = call_res.get("structuredContent") or {}
        if call_res.get("isError") or not isinstance(sc.get("overview"), dict) or call_bytes > MCP_TRAJECTORY_MAX_BYTES:
            report.error(f"MCP open_gravity_dashboard résultat invalide (isError={call_res.get('isError')}, bytes={call_bytes}).")


def _validate_core_extras(root: Path, report: Report) -> None:
    if not (root / "README.md").is_file():
        report.error("README.md manquant à la racine du plugin.")
    if root.name == "plugin" and (root.parent / "AGENTS.md").is_file():
        _check_doc_hygiene(root.parent / "AGENTS.md", "AGENTS.md", report)
    _validate_core_skills(root, report)
    _validate_markdown_links(root, report)
    _run_e2e_dry_run(root, report)
    _run_mcp_dry_run(root, report)


def build_validator_config(plugin_root: Path, *, strict: bool = False, json_output: bool = False) -> ValidatorConfig:
    return ValidatorConfig(
        plugin_root=plugin_root,
        strict=strict,
        json_output=json_output,
        expected_plugin_name="gravity",
        expected_module_id="core",
        required_dirs=REQUIRED_DIRS,
        allowed_local_modules=CORE_ALLOWED_LOCAL_MODULES,
        extra_forbidden_patterns=(("référence legacy atelier", STUDIO_REF_RE),),
        require_module_contract=True,
        require_hooks_config=True,
        require_mcp_config=True,
        require_rules_agents=True,
        check_links=False,
        extra_check_fn=_validate_core_extras,
    )


def validate_plugin(root: Path, report: Optional[Report] = None) -> Report:
    """Validate the Gravity Core plugin tree and return the Report."""
    return validate_plugin_tree(build_validator_config(root), report)


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_cli(build_validator_config(PLUGIN_ROOT_DEFAULT), argv, description="Validateur strict Gravity Core")


if __name__ == "__main__":
    raise SystemExit(main())

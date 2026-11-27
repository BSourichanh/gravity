"""Read-only quick guide and consolidated overview rendering for Gravity Core."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable, Optional, Sequence

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.doctor import (  # noqa: E402
    _collect_doctor_warnings,
    _detect_antigravity_app_version,
    _inspect_module_health_ro,
    diagnose_mcp_dashboard,
    find_duplicate_ids,
)
from core.registry import (  # noqa: E402
    default_plugin_roots,
    detect_legacy_homes,
    discover_modules,
    enrich_module_homes,
    resolve_gravity_home,
)

MAX_GUIDE_LINES = 20

GUIDE_QUICKSTART: tuple[str, ...] = (
    "1. Initialiser : /gravity init (cree $GRAVITY_HOME/core/modules.json)",
    "2. Piloter     : /gravity dashboard (MCP App, 0 token) ou vos modules actifs",
    "3. Verifier    : /gravity doctor (sante & legacy lecture seule)",
)
GUIDE_CORE_COMMANDS: tuple[str, ...] = (
    "/gravity init",
    "/gravity status",
    "/gravity modules",
    "/gravity doctor",
    "/gravity dashboard",
    "/gravity update",
    "/gravity export",
    "/gravity import",
    "/gravity help",
)
GUIDE_DOCS: tuple[str, ...] = (
    "docs/getting-started.md",
    "docs/user-journey.md",
    "docs/command-cheatsheet.md",
    "docs/troubleshooting-and-lifecycle.md",
)


def run_guide_mode(
    *,
    gravity_home: Optional[Path] = None,
    plugins_dirs: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
) -> tuple[dict[str, Any], int]:
    """Return a strictly read-only interactive quick-guide payload based on discovered modules."""
    resolved_home = resolve_gravity_home(gravity_home, home_dir=home_dir)
    roots = [Path(p) for p in plugins_dirs] if plugins_dirs is not None else default_plugin_roots(home_dir=home_dir)
    modules = discover_modules(roots)

    installed_modules: list[dict[str, Any]] = []
    commands: dict[str, list[str]] = {"core": list(GUIDE_CORE_COMMANDS)}
    for mod in modules:
        mod_id = str(mod.get("id") or "")
        mod_cmds = [str(c) for c in (mod.get("commands") or []) if isinstance(c, str) and c.strip()]
        installed_modules.append(
            {
                "id": mod_id,
                "plugin_name": mod.get("plugin_name"),
                "version": mod.get("version"),
                "valid": bool(mod.get("valid")),
                "commands": mod_cmds,
            }
        )
        if mod.get("valid") and mod_id and mod_id != "core":
            commands[mod_id] = mod_cmds

    payload: dict[str, Any] = {
        "mode": "guide",
        "ok": True,
        "gravity_home": str(resolved_home),
        "installed_modules": installed_modules,
        "quickstart": list(GUIDE_QUICKSTART),
        "commands": commands,
        "docs": list(GUIDE_DOCS),
    }
    return payload, 0


def print_guide_report(payload: dict[str, Any]) -> None:
    """Print the untruncated read-only Gravity Core quick guide."""
    installed = payload.get("installed_modules") or []
    commands = payload.get("commands") or {}
    docs = payload.get("docs") or []

    lines: list[str] = [
        "Gravity Core — Guide rapide (lecture seule)",
        "Boucle en 3 temps :",
        *[f"  {step}" for step in (payload.get("quickstart") or [])],
        "Commandes Core : /gravity [init|status|modules|doctor|dashboard|update|export|import|help]",
    ]
    other_mods = [m for m in installed if m.get("id") != "core" and m.get("valid")]
    if other_mods:
        lines.append(f"Modules detectes ({len(installed)}) :")
        for mod in other_mods:
            mod_id = str(mod.get("id") or "")
            ver = mod.get("version") or "?"
            cmds = ", ".join(commands.get(mod_id) or mod.get("commands") or []) or "-"
            lines.append(f"  - {mod_id} (v{ver}) : {cmds}")
    elif installed:
        lines.append("Modules detectes : core uniquement (Paliers 2/3 : workflow, metrics, architect)")
    else:
        lines.append("Modules detectes : aucun dans --plugins-dir")

    lines.append("Guides docs/ :")
    for doc_path in docs:
        lines.append(f"  - {doc_path}")

    for line in lines:
        print(line)


def build_overview_help(modules: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the 5 structured help journeys for --overview (read-only)."""
    companions = [
        {
            "id": str(m.get("id") or ""),
            "version": str(m.get("version") or "?"),
            "commands": [str(c) for c in (m.get("commands") or []) if isinstance(c, str) and c.strip()],
        }
        for m in modules
        if m.get("valid") and m.get("id") != "core"
    ]
    comp_items = [
        f"{c['id']} (v{c['version']}) : {', '.join(c['commands']) or '-'}" for c in companions
    ] or ["Aucun module compagnon détecté (Paliers 2/3 : workflow, metrics, architect)"]
    return [
        {"id": "quickstart", "title": "Démarrage / Init", "items": ["/gravity init — Créer $GRAVITY_HOME/core/modules.json et dossiers modules"]},
        {"id": "diagnostic", "title": "Diagnostic / Santé", "items": ["/gravity status — État RO", "/gravity doctor — Audit contrats & legacy (--migration-plan)", "/gravity modules — Liste JSON"]},
        {"id": "dashboard", "title": "Dashboard (0 token)", "items": ["/gravity dashboard — open_gravity_dashboard (aux_pane, barre latérale Gravity ou menu +)"]},
        {"id": "companions", "title": "Modules compagnons", "items": comp_items},
        {"id": "docs", "title": "Guides docs/", "items": list(GUIDE_DOCS)},
    ]


def run_overview_mode(
    *,
    gravity_home: Optional[Path] = None,
    plugins_dirs: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
    app_version_detector: Optional[Callable[[], dict[str, Any]]] = None,
    plugin_root: Path = PLUGIN_ROOT,
) -> tuple[dict[str, Any], int]:
    """Build strictly read-only --overview payload combining environment, health, MCP, and 5-journey help."""
    resolved_home = resolve_gravity_home(gravity_home, home_dir=home_dir)
    roots = [Path(p) for p in plugins_dirs] if plugins_dirs is not None else default_plugin_roots(home_dir=home_dir)
    modules = enrich_module_homes(discover_modules(roots), resolved_home)
    legacy_homes = detect_legacy_homes(home_dir)
    core_dir = resolved_home / "core"
    registry_path = core_dir / "modules.json"
    initialized = core_dir.is_dir() and registry_path.is_file()

    duplicates = find_duplicate_ids(modules)
    invalid_count = sum(1 for m in modules if not m.get("valid"))
    valid_count = len(modules) - invalid_count
    health_items = [_inspect_module_health_ro(m, plugin_root=plugin_root) for m in modules]
    diag = diagnose_mcp_dashboard(plugin_root)
    detector = app_version_detector or _detect_antigravity_app_version
    app_info = detector()
    warnings = _collect_doctor_warnings(modules, app_version=app_info, plugin_root=plugin_root)
    ok = invalid_count == 0 and not duplicates and not diag["errors"]

    payload: dict[str, Any] = {
        "mode": "overview",
        "ok": ok,
        "gravity_home": str(resolved_home),
        "core_dir": str(core_dir),
        "registry_path": str(registry_path),
        "initialized": initialized,
        "registry_exists": registry_path.is_file(),
        "plugin_roots": [str(Path(p).expanduser().resolve()) for p in roots],
        "module_count": len(modules),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "duplicate_ids": duplicates,
        "modules": modules,
        "module_health": health_items,
        "warnings": warnings,
        "legacy_homes": legacy_homes,
        "dashboard": diag,
        "antigravity_app": app_info,
        "help": build_overview_help(modules),
    }
    return payload, (0 if ok else 1)


def format_overview_markdown(payload: dict[str, Any]) -> str:
    """Format a compact read-only Markdown overview shared by CLI --overview and PreInvocation hook."""
    init_lbl = "initialisé" if payload.get("initialized") else "non initialisé (RO)"
    legacy = payload.get("legacy_homes") or []
    diag = payload.get("dashboard") or {}
    app_info = payload.get("antigravity_app") or {}
    app_ver = app_info.get("version")
    if app_ver:
        app_lbl = f"v{app_ver} ({app_info.get('source', '?')}, {'OK' if app_info.get('meets_mcp_app_min') else '< 2.34.0'})"
    else:
        app_lbl = "non détectée"
    mcp_lbl = "[OK]" if not diag.get("errors") else "[ERR]"

    lines = [
        "### Gravity Core — Vue d'ensemble (lecture seule)",
        f"- **`$GRAVITY_HOME` :** `{payload.get('gravity_home')}` ({init_lbl} · registre `{payload.get('registry_path')}`)",
        f"- **MCP Dashboard :** {mcp_lbl} `open_gravity_dashboard` · **Antigravity App :** {app_lbl} · **Legacy :** {len(legacy)} dossier(s)",
        "",
        "**Santé des modules :**",
    ]
    health_items = payload.get("module_health") or []
    if health_items:
        for h in health_items:
            cmds = ", ".join(h.get("commands") or []) or "-"
            lines.append(f"- `[{h.get('status', 'OK')}]` **{h.get('id')}** (v{h.get('version') or '?'}) — {h.get('summary') or '-'} · `{cmds}`")
    else:
        lines.append("- Aucun module découvert dans `--plugins-dir`.")

    if payload.get("duplicate_ids"):
        lines.append(f"- `[ERR]` IDs dupliqués : {', '.join(payload['duplicate_ids'])}")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.extend(["", "**Avertissements (non bloquants) :**"])
        lines.extend(f"- `[WARN]` {w}" for w in warnings)

    lines.extend(["", "**Parcours & Commandes (`/gravity`) :**"])
    for idx, sec in enumerate(payload.get("help") or [], start=1):
        lines.append(f"{idx}. **{sec.get('title')} :** {' · '.join(sec.get('items') or [])}")
    return "\n".join(lines)


_run_guide_mode = run_guide_mode
_print_guide_report = print_guide_report
_build_overview_help = build_overview_help
_run_overview_mode = run_overview_mode

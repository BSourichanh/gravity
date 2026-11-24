#!/usr/bin/env python3
"""Non-interactive CLI to initialize, inspect, and diagnose Gravity Core environment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any, Optional, Sequence

MAX_SCAN_FILES = 10_000
MAX_SCAN_DEPTH = 32
MAX_COLLISIONS_SHOWN = 50
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
    "/gravity help",
)
GUIDE_DOCS: tuple[str, ...] = (
    "docs/getting-started.md",
    "docs/user-journey.md",
    "docs/command-cheatsheet.md",
    "docs/troubleshooting-and-lifecycle.md",
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core.registry import (  # noqa: E402
    default_plugin_roots,
    detect_legacy_homes,
    discover_modules,
    resolve_gravity_home,
    resolve_module_home,
    write_modules_registry,
)


def _configure_stdio() -> None:
    """Force UTF-8 stdout/stderr so Windows cp1252 consoles never crash."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _enrich_module_homes(
    modules: list[dict[str, Any]],
    gravity_home: Path,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for mod in modules:
        item = dict(mod)
        storage = mod.get("storage") or {}
        subdir = storage.get("subdir")
        env_override = storage.get("env_override")
        if mod.get("valid") and isinstance(subdir, str) and subdir:
            try:
                resolved = resolve_module_home(
                    subdir,
                    env_override=env_override if isinstance(env_override, str) else None,
                    gravity_home=gravity_home,
                )
                item["resolved_home"] = str(resolved)
            except ValueError as exc:
                item["valid"] = False
                item["errors"] = [*item.get("errors", []), str(exc)]
                item["resolved_home"] = None
        else:
            item["resolved_home"] = None
        enriched.append(item)
    return enriched


def _resolve_shell(shell: str) -> str:
    """Resolve target shell ('powershell' or 'bash') from CLI selection."""
    if shell == "auto":
        return "powershell" if os.name == "nt" else "bash"
    return shell


def _resolve_base_home(home_dir: Optional[Path]) -> Path:
    base = Path.home() if home_dir is None else Path(home_dir)
    return base.expanduser().resolve()


def _ps_quote(value: str) -> str:
    return value.replace("`", "``").replace('"', '`"')


def _scan_legacy_directory(source_path: Path, target_path: Path) -> dict[str, Any]:
    """Read-only scan of a legacy path counting files/bytes and collisions without following symlinks."""
    if source_path.is_symlink():
        return {
            "file_count": 0,
            "total_bytes": 0,
            "truncated": False,
            "skipped_symlink": True,
            "conflict": False,
            "collision_count": 0,
            "collisions": [],
        }

    if not source_path.is_dir():
        size = 0
        try:
            size = source_path.lstat().st_size
        except OSError:
            pass
        dest = target_path / source_path.name
        has_collision = dest.exists() or dest.is_symlink()
        return {
            "file_count": 1,
            "total_bytes": size,
            "truncated": False,
            "skipped_symlink": False,
            "conflict": has_collision,
            "collision_count": 1 if has_collision else 0,
            "collisions": [source_path.name] if has_collision else [],
        }

    file_count = 0
    total_bytes = 0
    truncated = False
    collision_count = 0
    collisions: list[str] = []
    seen_dirs: set[tuple[int, int]] = set()

    try:
        root_stat = source_path.lstat()
        if root_stat.st_ino:
            seen_dirs.add((root_stat.st_dev, root_stat.st_ino))
    except OSError:
        pass

    stack: list[tuple[Path, int]] = [(source_path, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as entries:
                sorted_entries = sorted(entries, key=lambda e: e.name)
        except OSError:
            continue

        for entry in sorted_entries:
            if entry.is_symlink():
                continue
            entry_path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > MAX_SCAN_DEPTH:
                        truncated = True
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if st.st_ino:
                        dir_key = (st.st_dev, st.st_ino)
                        if dir_key in seen_dirs:
                            continue
                        seen_dirs.add(dir_key)
                    stack.append((entry_path, depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    if file_count >= MAX_SCAN_FILES:
                        truncated = True
                        return {
                            "file_count": file_count,
                            "total_bytes": total_bytes,
                            "truncated": truncated,
                            "skipped_symlink": False,
                            "conflict": collision_count > 0,
                            "collision_count": collision_count,
                            "collisions": collisions,
                        }
                    st = entry.stat(follow_symlinks=False)
                    file_count += 1
                    total_bytes += st.st_size
                    rel = entry_path.relative_to(source_path).as_posix()
                    dest = target_path / rel
                    if dest.exists() or dest.is_symlink():
                        collision_count += 1
                        if len(collisions) < MAX_COLLISIONS_SHOWN:
                            collisions.append(rel)
            except OSError:
                continue

    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "truncated": truncated,
        "skipped_symlink": False,
        "conflict": collision_count > 0,
        "collision_count": collision_count,
        "collisions": collisions,
    }


def _build_shell_steps(
    *,
    source_path: Path,
    target_path: Path,
    backup_path: Path,
    shell: str,
    is_dir: bool,
    conflict: bool,
) -> list[dict[str, Any]]:
    """Build 4 non-destructive manual migration steps for powershell or bash."""
    src_str = str(source_path)
    dst_str = str(target_path)
    bkp_str = str(backup_path)
    bkp_parent_str = str(backup_path.parent)

    if shell == "powershell":
        q_src = _ps_quote(src_str)
        q_dst = _ps_quote(dst_str)
        q_bkp = _ps_quote(bkp_str)
        q_bkp_parent = _ps_quote(bkp_parent_str)
        step1_cmd = (
            f'New-Item -ItemType Directory -Force -Path "{q_bkp_parent}" | Out-Null; '
            f'Copy-Item -Path "{q_src}" -Destination "{q_bkp}" -Recurse'
        )
        if is_dir:
            step2_cmd = (
                f'New-Item -ItemType Directory -Force -Path "{q_dst}" | Out-Null; '
                f'Get-ChildItem -Path "{q_src}" -Recurse -File | ForEach-Object {{ '
                f'$rel = $_.FullName.Substring("{q_src}".Length).TrimStart("\\","/"); '
                f'$out = Join-Path "{q_dst}" $rel; '
                f'if (-not (Test-Path $out)) {{ '
                f'New-Item -ItemType Directory -Force -Path (Split-Path $out -Parent) | Out-Null; '
                f'Copy-Item -Path $_.FullName -Destination $out }} }}'
            )
        else:
            q_name = _ps_quote(source_path.name)
            step2_cmd = (
                f'New-Item -ItemType Directory -Force -Path "{q_dst}" | Out-Null; '
                f'$out = Join-Path "{q_dst}" "{q_name}"; '
                f'if (-not (Test-Path $out)) {{ Copy-Item -Path "{q_src}" -Destination $out }}'
            )
        step4_cmd = f'# Remove-Item -Recurse -Force "{q_src}"'
    else:
        q_src = shlex.quote(src_str)
        q_dst = shlex.quote(dst_str)
        q_bkp = shlex.quote(bkp_str)
        q_bkp_parent = shlex.quote(bkp_parent_str)
        step1_cmd = f"mkdir -p {q_bkp_parent} && cp -a {q_src} {q_bkp}"
        if is_dir:
            q_src_dot = shlex.quote(f"{src_str}/.")
            q_dst_slash = shlex.quote(f"{dst_str}/")
            step2_cmd = f"mkdir -p {q_dst} && cp -n -r {q_src_dot} {q_dst_slash}"
        else:
            q_dst_slash = shlex.quote(f"{dst_str}/")
            step2_cmd = f"mkdir -p {q_dst} && cp -n {q_src} {q_dst_slash}"
        step4_cmd = f"# rm -rf {q_src}"

    copy_note = (
        "Conflicts detected: existing target files will be skipped; compare and merge manually."
        if conflict
        else "No collisions detected; existing target files will never be overwritten."
    )
    return [
        {
            "step": 1,
            "kind": "backup",
            "description": "Create a timestamped backup before any migration.",
            "command": step1_cmd,
        },
        {
            "step": 2,
            "kind": "copy",
            "description": copy_note,
            "command": step2_cmd,
        },
        {
            "step": 3,
            "kind": "verify",
            "description": "Verify module contracts and environment health (read-only).",
            "command": "python scripts/init_env.py --check",
        },
        {
            "step": 4,
            "kind": "cleanup",
            "description": "Manual cleanup only after verifying migrated data (commented out by default).",
            "command": step4_cmd,
        },
    ]


def _resolve_target_for_legacy(
    target_module: str,
    modules: Sequence[dict[str, Any]],
    gravity_home: Path,
) -> Path:
    env_override: Optional[str] = None
    for mod in modules:
        if mod.get("id") == target_module and mod.get("valid"):
            storage = mod.get("storage") or {}
            candidate_env = storage.get("env_override")
            if isinstance(candidate_env, str) and candidate_env.strip():
                env_override = candidate_env
                break
    return resolve_module_home(target_module, env_override=env_override, gravity_home=gravity_home)


def build_migration_plan(
    *,
    legacy_homes: Sequence[dict[str, Any]],
    modules: Sequence[dict[str, Any]],
    gravity_home: Path,
    home_dir: Optional[Path] = None,
    shell: str = "auto",
    date_stamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build a strictly read-only, 4-step manual migration plan for detected legacy homes."""
    resolved_shell = _resolve_shell(shell)
    base_home = _resolve_base_home(home_dir)
    stamp = date_stamp or datetime.now(timezone.utc).strftime("%Y%m%d")
    backup_root = base_home / "gravity-legacy-backup"

    plans: list[dict[str, Any]] = []
    for item in legacy_homes:
        source_path = Path(item["path"])
        target_module = str(item["target_module"])
        target_path = _resolve_target_for_legacy(target_module, modules, gravity_home)
        backup_path = backup_root / f"{item['name']}-{stamp}"
        scan = _scan_legacy_directory(source_path, target_path)
        steps = _build_shell_steps(
            source_path=source_path,
            target_path=target_path,
            backup_path=backup_path,
            shell=resolved_shell,
            is_dir=bool(item.get("is_dir", True)),
            conflict=bool(scan["conflict"]),
        )
        plans.append(
            {
                "name": item["name"],
                "target_module": target_module,
                "source_path": str(source_path),
                "target_path": str(target_path),
                "backup_path": str(backup_path),
                "is_dir": bool(item.get("is_dir", True)),
                "file_count": scan["file_count"],
                "total_bytes": scan["total_bytes"],
                "truncated": scan["truncated"],
                "skipped_symlink": scan["skipped_symlink"],
                "conflict": scan["conflict"],
                "collision_count": scan["collision_count"],
                "collisions": scan["collisions"],
                "steps": steps,
            }
        )

    return {
        "shell": resolved_shell,
        "backup_root": str(backup_root),
        "plan_count": len(plans),
        "has_conflicts": any(p["conflict"] for p in plans),
        "plans": plans,
    }


def _find_duplicate_ids(modules: Sequence[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for mod in modules:
        mod_id = str(mod.get("id") or "")
        if mod_id:
            counts[mod_id] = counts.get(mod_id, 0) + 1
    return sorted(mod_id for mod_id, count in counts.items() if count > 1)


def _is_valid_atelier_dir(candidate: Path) -> bool:
    try:
        return (
            not candidate.is_symlink()
            and candidate.is_dir()
            and (candidate / "ECOSYSTEM.md").is_file()
            and (candidate / "projects.json").is_file()
        )
    except OSError:
        return False


def _inspect_architect_registry_ro(ateliers_path: Path) -> tuple[bool, bool]:
    """Inspect <architect_home>/ateliers.json strictly read-only without following symlinks."""
    try:
        if ateliers_path.parent.is_symlink() or ateliers_path.is_symlink() or not ateliers_path.is_file():
            return False, False
        raw = ateliers_path.read_bytes()
    except OSError:
        return False, False

    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return True, False

    if not isinstance(data, dict) or not isinstance(data.get("ateliers"), list):
        return True, False

    for entry in data["ateliers"]:
        if not isinstance(entry, dict):
            continue
        raw_ws = str(entry.get("workspace_path") or "").strip()
        if not raw_ws:
            continue
        if _is_valid_atelier_dir(Path(raw_ws).expanduser()):
            return True, True
    return True, False


def _collect_doctor_warnings(modules: Sequence[dict[str, Any]]) -> list[str]:
    """Collect non-blocking read-only warnings for valid discovered modules."""
    warnings: list[str] = []
    for mod in modules:
        if not mod.get("valid"):
            continue
        mod_id = str(mod.get("id") or "")
        plugin_name = str(mod.get("plugin_name") or "")
        raw_home = mod.get("resolved_home")
        if not isinstance(raw_home, str) or not raw_home:
            continue
        mod_home = Path(raw_home)

        if mod_id == "architect" or plugin_name == "gravity-architect":
            ateliers_path = mod_home / "ateliers.json"
            reg_exists, has_valid = _inspect_architect_registry_ro(ateliers_path)
            if not reg_exists:
                warnings.append(
                    f"Module 'architect' actif mais {ateliers_path} absent : "
                    "lancez /gravity-architect init ou /gravity-architect sync dans votre atelier."
                )
            elif not has_valid:
                warnings.append(
                    f"Module 'architect' actif mais {ateliers_path} ne contient aucun atelier valide : "
                    "lancez /gravity-architect init ou /gravity-architect sync."
                )
        elif mod_id == "bridge" or plugin_name == "gravity-bridge":
            bridge_db = mod_home / "bridge.db"
            try:
                db_ok = (
                    not bridge_db.parent.is_symlink()
                    and not bridge_db.is_symlink()
                    and bridge_db.is_file()
                )
            except OSError:
                db_ok = False
            if not db_ok:
                warnings.append(
                    f"Module 'bridge' actif mais {bridge_db} absente : "
                    "exécutez /gravity-bridge pour initialiser la base SQLite."
                )
    return warnings


def _has_real_python3() -> bool:
    found = shutil.which("python3")
    if not found:
        return False
    if os.name == "nt" and "windowsapps" in found.lower():
        return False
    return True


def _diagnose_mcp_dashboard(plugin_root: Path) -> dict[str, Any]:
    """Inspect mcp_config.json, mcp/server.py, dashboard/api.py, and python3 availability."""
    mcp_config_path = plugin_root / "mcp_config.json"
    server_path = plugin_root / "mcp" / "server.py"
    api_path = plugin_root / "dashboard" / "api.py"
    errors: list[str] = []
    mcp_command = ""
    mcp_args: list[str] = []
    mcp_config_ok = False

    if not mcp_config_path.is_file():
        errors.append("mcp_config.json introuvable.")
    else:
        try:
            raw = mcp_config_path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                errors.append("mcp_config.json contient un BOM UTF-8.")
                raw = raw[3:]
            data = json.loads(raw.decode("utf-8"))
            servers = data.get("mcpServers") if isinstance(data, dict) else None
            dash = servers.get("dashboard") if isinstance(servers, dict) else None
            if not isinstance(dash, dict):
                errors.append("mcp_config.json : section mcpServers.dashboard manquante.")
            else:
                cmd = dash.get("command")
                args = dash.get("args")
                if isinstance(cmd, str) and cmd.strip():
                    mcp_command = cmd.strip()
                else:
                    errors.append("mcp_config.json : command manquant.")
                if isinstance(args, list) and all(isinstance(a, str) for a in args):
                    mcp_args = list(args)
                else:
                    errors.append("mcp_config.json : args invalide.")
                if not errors:
                    mcp_config_ok = True
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"mcp_config.json invalide : {exc}")

    server_exists = server_path.is_file()
    if not server_exists:
        errors.append("mcp/server.py introuvable.")
    api_exists = api_path.is_file()
    if not api_exists:
        errors.append("dashboard/api.py introuvable.")

    return {
        "mcp_config_path": str(mcp_config_path),
        "mcp_config_ok": mcp_config_ok,
        "mcp_command": mcp_command,
        "mcp_args": mcp_args,
        "server_path": str(server_path),
        "server_exists": server_exists,
        "api_path": str(api_path),
        "api_exists": api_exists,
        "real_python3": _has_real_python3(),
        "errors": errors,
    }


def _run_dashboard_diagnostic(
    *,
    gravity_home: Optional[Path] = None,
    plugins_dirs: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
) -> tuple[dict[str, Any], int]:
    """Run strictly read-only diagnostics for the Gravity MCP App dashboard."""
    from dashboard import api as dashboard_api

    resolved_home = resolve_gravity_home(gravity_home)
    roots = list(plugins_dirs) if plugins_dirs else default_plugin_roots()
    diag = _diagnose_mcp_dashboard(PLUGIN_ROOT)
    overview = dashboard_api.get_overview(
        gravity_home=resolved_home,
        plugin_roots=roots,
        home_dir=home_dir,
    )
    ok = (
        bool(diag["mcp_config_ok"])
        and bool(diag["server_exists"])
        and bool(diag["api_exists"])
        and not diag["errors"]
    )
    payload: dict[str, Any] = {
        "mode": "dashboard",
        "ok": ok,
        "gravity_home": str(resolved_home),
        "registry_path": overview["registry_path"],
        "registry_exists": overview["registry_exists"],
        "registry_source": overview["registry_source"],
        "plugin_roots": [str(Path(p).expanduser().resolve()) for p in roots],
        "dashboard": diag,
        "doctor": overview["doctor"],
        "tabs": overview["tabs"],
        "modules": overview["modules"],
        "legacy_homes": overview["legacy_homes"],
    }
    return payload, (0 if ok else 1)


def _run_guide_mode(
    *,
    gravity_home: Optional[Path] = None,
    plugins_dirs: Optional[Sequence[Path]] = None,
) -> tuple[dict[str, Any], int]:
    """Return a strictly read-only interactive quick-guide payload based on discovered modules."""
    resolved_home = resolve_gravity_home(gravity_home)
    roots = list(plugins_dirs) if plugins_dirs else default_plugin_roots()
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


def run_environment(
    *,
    gravity_home: Optional[Path] = None,
    plugins_dirs: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
    status_only: bool = False,
    check_only: bool = False,
    migration_plan: bool = False,
    dashboard: bool = False,
    guide: bool = False,
    shell: str = "auto",
) -> tuple[dict[str, Any], int]:
    """Execute init, status, check, migration-plan, dashboard, or guide workflow and return (payload, exit_code)."""
    if guide:
        return _run_guide_mode(
            gravity_home=gravity_home,
            plugins_dirs=plugins_dirs,
        )
    if dashboard:
        return _run_dashboard_diagnostic(
            gravity_home=gravity_home,
            plugins_dirs=plugins_dirs,
            home_dir=home_dir,
        )

    resolved_home = resolve_gravity_home(gravity_home)
    roots = list(plugins_dirs) if plugins_dirs else default_plugin_roots()
    raw_modules = discover_modules(roots)
    modules = _enrich_module_homes(raw_modules, resolved_home)
    legacy_homes = detect_legacy_homes(home_dir)

    core_dir = resolved_home / "core"
    registry_path = core_dir / "modules.json"
    if migration_plan:
        mode = "migration-plan"
    elif status_only:
        mode = "status"
    elif check_only:
        mode = "check"
    else:
        mode = "init"

    if mode == "init":
        core_dir.mkdir(parents=True, exist_ok=True)
        for mod in modules:
            if mod.get("valid") and mod.get("resolved_home"):
                Path(mod["resolved_home"]).mkdir(parents=True, exist_ok=True)
        registry_path = write_modules_registry(resolved_home, modules)

    duplicates = _find_duplicate_ids(modules)
    invalid_count = sum(1 for mod in modules if not mod.get("valid"))
    valid_count = len(modules) - invalid_count
    initialized = core_dir.is_dir() and registry_path.is_file()

    ok = True
    if mode == "check" and (invalid_count > 0 or bool(duplicates)):
        ok = False
    warnings = _collect_doctor_warnings(modules) if mode == "check" else []

    payload: dict[str, Any] = {
        "mode": mode,
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
        "warnings": warnings,
        "modules": modules,
        "legacy_homes": legacy_homes,
    }

    if mode == "migration-plan":
        plan_data = build_migration_plan(
            legacy_homes=legacy_homes,
            modules=modules,
            gravity_home=resolved_home,
            home_dir=home_dir,
            shell=shell,
        )
        payload["shell"] = plan_data["shell"]
        payload["backup_root"] = plan_data["backup_root"]
        payload["plan_count"] = plan_data["plan_count"]
        payload["has_conflicts"] = plan_data["has_conflicts"]
        payload["plans"] = plan_data["plans"]

    return payload, (0 if ok else 1)


def _print_migration_plan_report(payload: dict[str, Any]) -> None:
    print(f"Gravity Core Legacy Migration Plan (read-only, shell={payload['shell']})")
    print(f"  Gravity Home : {payload['gravity_home']}")
    print(f"  Backup Root  : {payload['backup_root']}")
    plans = payload.get("plans") or []
    if not plans:
        print("\nLegacy directories: none detected (nothing to migrate).")
        return

    print(
        f"\nDetected {len(plans)} legacy directory(ies) "
        "(read-only plan; nothing modified on disk):"
    )
    for plan in plans:
        print(f"\n- {plan['name']} -> module '{plan['target_module']}'")
        print(f"  Source  : {plan['source_path']} ({plan['file_count']} file(s), {plan['total_bytes']} bytes)")
        if plan.get("skipped_symlink"):
            print("  Notice  : Source path is a symlink and was not traversed.")
        if plan.get("truncated"):
            print("  Notice  : Scan cap reached; totals are lower bounds.")
        print(f"  Target  : {plan['target_path']}")
        print(f"  Backup  : {plan['backup_path']}")
        if plan.get("conflict"):
            shown = plan.get("collisions") or []
            total_col = plan.get("collision_count", len(shown))
            print(
                f"  [CONFLICT] {total_col} file(s) already exist at target "
                "(manual review required; non-clobber copy will skip them):"
            )
            for rel in shown:
                print(f"    * {rel}")
            if total_col > len(shown):
                print(f"    * ... (+{total_col - len(shown)} more)")
        print("  Steps:")
        for step in plan.get("steps") or []:
            print(f"    {step['step']}. [{step['kind']}] {step['description']}")
            print(f"       {step['command']}")


def _print_dashboard_report(payload: dict[str, Any]) -> None:
    diag = payload.get("dashboard") or {}
    doctor = payload.get("doctor") or {}
    tabs = payload.get("tabs") or []
    print("Gravity Dashboard Diagnostics (read-only)")
    print(f"  Gravity Home  : {payload['gravity_home']}")
    print(
        f"  MCP Config    : {'OK' if diag.get('mcp_config_ok') else 'ERROR'} "
        f"({diag.get('mcp_command') or '-'})"
    )
    print(f"  MCP Server    : {'present' if diag.get('server_exists') else 'missing'} ({diag.get('server_path')})")
    print(f"  Dashboard API : {'present' if diag.get('api_exists') else 'missing'} ({diag.get('api_path')})")
    py3_lbl = "yes" if diag.get("real_python3") else "no (Windows copy adapts to python/py -3)"
    print(f"  Real python3  : {py3_lbl}")
    print(
        f"  Doctor        : {doctor.get('status', 'unknown')} "
        f"({doctor.get('valid_count', 0)}/{doctor.get('module_count', 0)} modules valid)"
    )
    tab_desc = ", ".join(f"{t.get('id')} ({t.get('label')})" for t in tabs) or "none"
    print(f"  Tabs          : {tab_desc}")
    print("  MCP Tool      : open_gravity_dashboard (aux_pane / global)")
    for err in diag.get("errors") or []:
        print(f"  [ERROR] {err}")


def _print_guide_report(payload: dict[str, Any]) -> None:
    installed = payload.get("installed_modules") or []
    commands = payload.get("commands") or {}
    docs = payload.get("docs") or []

    lines: list[str] = [
        "Gravity Core — Guide rapide (lecture seule)",
        "Boucle en 3 temps :",
        *[f"  {step}" for step in (payload.get("quickstart") or [])],
        "Commandes Core : /gravity [init|status|modules|doctor|dashboard|help]",
    ]
    other_mods = [m for m in installed if m.get("id") != "core" and m.get("valid")]
    if other_mods:
        lines.append(f"Modules detectes ({len(installed)}) :")
        max_listed = 5
        for mod in other_mods[:max_listed]:
            mod_id = str(mod.get("id") or "")
            ver = mod.get("version") or "?"
            cmds = ", ".join(commands.get(mod_id) or mod.get("commands") or []) or "-"
            lines.append(f"  - {mod_id} (v{ver}) : {cmds}")
        if len(other_mods) > max_listed:
            lines.append(f"  - ... (+{len(other_mods) - max_listed} autres via /gravity modules)")
    elif installed:
        lines.append("Modules detectes : core uniquement (Paliers 2/3 : metrics, architect, bridge)")
    else:
        lines.append("Modules detectes : aucun dans --plugins-dir")

    lines.append("Guides docs/ :")
    for doc_path in docs:
        lines.append(f"  - {doc_path}")

    for line in lines[:MAX_GUIDE_LINES]:
        print(line)


def _print_human_report(payload: dict[str, Any]) -> None:
    if payload.get("mode") == "guide":
        _print_guide_report(payload)
        return
    if payload.get("mode") == "migration-plan":
        _print_migration_plan_report(payload)
        return
    if payload.get("mode") == "dashboard":
        _print_dashboard_report(payload)
        return

    print(f"Gravity Core Environment ({payload['mode']})")
    print(f"  Gravity Home  : {payload['gravity_home']}")
    print(f"  Core Registry : {payload['registry_path']} ({'present' if payload['registry_exists'] else 'not initialized'})")
    print(f"  Plugin Roots  : {', '.join(payload['plugin_roots'])}")
    print(
        f"  Modules       : {payload['module_count']} total "
        f"({payload['valid_count']} valid, {payload['invalid_count']} invalid)"
    )

    if payload["modules"]:
        print("\nDiscovered modules:")
        for mod in payload["modules"]:
            state = "OK" if mod.get("valid") else "INVALID"
            ver = mod.get("version") or "unknown"
            cmds = ", ".join(mod.get("commands") or []) or "-"
            ui = mod.get("ui") or {}
            ui_desc = f"{ui.get('mode', '?')}->{ui.get('target', '?')}"
            print(
                f"  - [{state}] {mod['id']} ({mod['plugin_name']} v{ver}) "
                f"cmds=[{cmds}] ui={ui_desc} home={mod.get('resolved_home') or '-'}"
            )
            for err in mod.get("errors") or []:
                print(f"      error: {err}")
    else:
        print("\nDiscovered modules: none")

    if payload["duplicate_ids"]:
        print(f"\nDuplicate module IDs detected: {', '.join(payload['duplicate_ids'])}")

    warnings = payload.get("warnings") or []
    if warnings:
        print("\nWarnings (non-blocking):")
        for warn in warnings:
            print(f"  - [WARN] {warn}")

    legacy = payload["legacy_homes"]
    if legacy:
        print("\nLegacy directories detected (read-only notice; nothing modified or deleted):")
        for item in legacy:
            print(f"  - {item['name']} -> module '{item['target_module']}': {item['path']}")
    else:
        print("\nLegacy directories: none detected")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize, inspect, or diagnose the Gravity Core environment."
    )
    parser.add_argument(
        "--gravity-home",
        type=Path,
        default=None,
        help="Override Gravity home directory (default: $GRAVITY_HOME or ~/.gemini/gravity).",
    )
    parser.add_argument(
        "--plugins-dir",
        type=Path,
        action="append",
        default=None,
        help="Plugin root directory to scan for Gravity modules (repeatable).",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Read-only inspection of current environment and discovered modules.",
    )
    mode_group.add_argument(
        "--check",
        action="store_true",
        help="Read-only validation check of discovered module contracts and environment.",
    )
    mode_group.add_argument(
        "--migration-plan",
        action="store_true",
        help="Read-only 4-step manual migration plan for legacy directories.",
    )
    mode_group.add_argument(
        "--dashboard",
        action="store_true",
        help="Read-only diagnostics for the Gravity MCP App dashboard, config, and tabs.",
    )
    mode_group.add_argument(
        "--guide",
        action="store_true",
        help="Read-only quick guide, discovered module commands, and docs/ pointers.",
    )
    parser.add_argument(
        "--shell",
        choices=("auto", "powershell", "bash"),
        default="auto",
        help="Target shell syntax for --migration-plan commands (default: auto).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        payload, rc = run_environment(
            gravity_home=args.gravity_home,
            plugins_dirs=args.plugins_dir,
            status_only=args.status,
            check_only=args.check,
            migration_plan=args.migration_plan,
            dashboard=args.dashboard,
            guide=args.guide,
            shell=args.shell,
        )
    except OSError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_human_report(payload)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

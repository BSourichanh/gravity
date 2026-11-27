#!/usr/bin/env python3
"""Non-interactive CLI to initialize, inspect, and diagnose Gravity Core environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Optional, Sequence

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.hook_runtime import configure_utf8_stdio  # noqa: E402
from _shared.path_safety import is_symlink_or_junction  # noqa: E402
from core.doctor import (  # noqa: E402
    _collect_doctor_warnings,
    _detect_antigravity_app_version,
    _detect_windows_app_version,
    build_migration_plan,
    find_duplicate_ids,
    format_dashboard_report,
    format_migration_plan_report,
    run_dashboard_diagnostic,
)
from core.overview import (  # noqa: E402
    GUIDE_CORE_COMMANDS,
    GUIDE_DOCS,
    GUIDE_QUICKSTART,
    format_guide_report,
    format_overview_markdown,
    run_guide_mode,
    run_overview_mode,
)
from core.registry import (  # noqa: E402
    default_plugin_roots,
    detect_legacy_homes,
    discover_modules,
    enrich_module_homes,
    resolve_gravity_home_raw,
    write_modules_registry,
)

_enrich_module_homes = enrich_module_homes


def _print_dashboard_report(payload: dict[str, Any]) -> None:
    print(format_dashboard_report(payload))


def _print_guide_report(payload: dict[str, Any]) -> None:
    print(format_guide_report(payload))


def _print_migration_plan_report(payload: dict[str, Any]) -> None:
    print(format_migration_plan_report(payload))


def _invoke_health_provider(
    module_id: str,
    *,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
) -> dict[str, Any]:
    from dashboard.providers.spi import invoke_dashboard_provider

    return invoke_dashboard_provider(
        module_id,
        view="health",
        gravity_home=gravity_home,
        plugin_roots=plugin_roots,
        home_dir=home_dir,
        timeout_s=5.0,
    )


def _get_dashboard_overview(
    *,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
) -> dict[str, Any]:
    from dashboard import api as dashboard_api

    return dashboard_api.get_overview(
        gravity_home=gravity_home,
        plugin_roots=plugin_roots,
        home_dir=home_dir,
    )


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
    overview: bool = False,
    shell: str = "auto",
    app_version_detector: Optional[Callable[[], dict[str, Any]]] = None,
    overview_fn: Optional[Callable[..., dict[str, Any]]] = None,
    health_provider_fn: Optional[Callable[..., dict[str, Any]]] = None,
) -> tuple[dict[str, Any], int]:
    """Execute init, status, check, migration-plan, dashboard, guide, or overview workflow."""
    eff_health_fn = health_provider_fn or _invoke_health_provider
    eff_overview_fn = overview_fn or _get_dashboard_overview
    if overview:
        return run_overview_mode(
            gravity_home=gravity_home,
            plugins_dirs=plugins_dirs,
            home_dir=home_dir,
            app_version_detector=app_version_detector,
            health_provider_fn=eff_health_fn,
        )
    if guide:
        return run_guide_mode(
            gravity_home=gravity_home,
            plugins_dirs=plugins_dirs,
            home_dir=home_dir,
        )
    if dashboard:
        return run_dashboard_diagnostic(
            gravity_home=gravity_home,
            plugins_dirs=plugins_dirs,
            home_dir=home_dir,
            app_version_detector=app_version_detector,
            overview_fn=eff_overview_fn,
        )

    raw_home = resolve_gravity_home_raw(gravity_home, home_dir=home_dir)
    resolved_home = raw_home.resolve()
    roots = [Path(p) for p in plugins_dirs] if plugins_dirs is not None else default_plugin_roots(home_dir=home_dir)
    raw_modules = discover_modules(roots)
    modules = enrich_module_homes(raw_modules, resolved_home)
    legacy_homes = detect_legacy_homes(home_dir)

    raw_core_dir = raw_home / "core"
    raw_registry_path = raw_core_dir / "modules.json"
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
        symlink_err: Optional[str] = None
        if is_symlink_or_junction(raw_home):
            symlink_err = f"Refusing symlink or junction gravity_home: {raw_home}"
        elif is_symlink_or_junction(raw_core_dir) or is_symlink_or_junction(core_dir):
            symlink_err = f"Refusing symlink or junction core directory: {raw_core_dir}"
        elif is_symlink_or_junction(raw_registry_path) or is_symlink_or_junction(registry_path):
            symlink_err = f"Refusing symlink or junction registry file: {raw_registry_path}"
        if symlink_err is not None:
            return {
                "mode": mode,
                "ok": False,
                "error": symlink_err,
                "gravity_home": str(raw_home),
                "core_dir": str(raw_core_dir),
                "registry_path": str(raw_registry_path),
                "initialized": False,
                "registry_exists": False,
                "plugin_roots": [str(Path(p).expanduser().resolve()) for p in roots],
                "module_count": len(modules),
                "valid_count": sum(1 for mod in modules if mod.get("valid")),
                "invalid_count": sum(1 for mod in modules if not mod.get("valid")),
                "duplicate_ids": find_duplicate_ids(modules),
                "warnings": [],
                "modules": modules,
                "legacy_homes": legacy_homes,
            }, 1
        core_dir.mkdir(parents=True, exist_ok=True)
        for mod in modules:
            if mod.get("valid") and mod.get("resolved_home"):
                Path(mod["resolved_home"]).mkdir(parents=True, exist_ok=True)
        registry_path = write_modules_registry(raw_home, modules)

    duplicates = find_duplicate_ids(modules)
    invalid_count = sum(1 for mod in modules if not mod.get("valid"))
    valid_count = len(modules) - invalid_count
    initialized = core_dir.is_dir() and registry_path.is_file()

    ok = True
    if mode == "check" and (invalid_count > 0 or bool(duplicates)):
        ok = False
    if mode == "check":
        detector = app_version_detector or _detect_antigravity_app_version
        warnings = _collect_doctor_warnings(
            modules,
            app_version=detector(),
            gravity_home=resolved_home,
            plugin_roots=roots,
            home_dir=home_dir,
            health_provider_fn=eff_health_fn,
        )
    else:
        warnings = []

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


def _print_human_report(payload: dict[str, Any]) -> None:
    mode = payload.get("mode")
    if mode in ("set-drive-dir", "export", "import"):
        from core.bundle import format_bundle_report

        print(format_bundle_report(payload))
        return
    if mode in ("update", "check-updates"):
        from core.updater import format_update_report

        print(format_update_report(payload))
        return
    if mode == "overview":
        print(format_overview_markdown(payload))
        return
    if mode == "guide":
        _print_guide_report(payload)
        return
    if mode == "migration-plan":
        _print_migration_plan_report(payload)
        return
    if mode == "dashboard":
        _print_dashboard_report(payload)
        return

    if payload.get("error"):
        print(f"[ERROR] {payload['error']}", file=sys.stderr)
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
    parser = argparse.ArgumentParser(description="Initialize, inspect, or diagnose the Gravity Core environment.")
    parser.add_argument("--gravity-home", type=Path, default=None, help="Override Gravity home directory (default: $GRAVITY_HOME or ~/.gemini/gravity).")
    parser.add_argument("--plugins-dir", type=Path, action="append", default=None, help="Plugin root directory to scan for Gravity modules (repeatable).")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--status", action="store_true", help="Read-only inspection of current environment and discovered modules.")
    mode_group.add_argument("--check", action="store_true", help="Read-only validation check of discovered module contracts and environment.")
    mode_group.add_argument("--migration-plan", action="store_true", help="Read-only 4-step manual migration plan for legacy directories.")
    mode_group.add_argument("--dashboard", action="store_true", help="Read-only diagnostics for the Gravity MCP App dashboard, config, and tabs.")
    mode_group.add_argument("--guide", action="store_true", help="Read-only quick guide, discovered module commands, and docs/ pointers.")
    mode_group.add_argument("--overview", action="store_true", help="Read-only consolidated overview (home, modules health, MCP, app version, 5-journey help).")
    mode_group.add_argument("--export", action="store_true", help="Export portable Gravity state (and optional ateliers) to a verified ZIP bundle.")
    mode_group.add_argument("--import", dest="import_zip", type=Path, default=None, help="Verify and import a portable Gravity ZIP bundle into $GRAVITY_HOME.")
    mode_group.add_argument("--update", action="store_true", help="Fetch, pull (--ff-only), and reinstall updated Gravity modules.")
    mode_group.add_argument("--check-updates", action="store_true", help="Read-only check for available Git updates and local drift.")
    parser.add_argument("--out", type=Path, default=None, help="Output ZIP file or directory for --export (overrides sync.json drive_dir).")
    parser.add_argument("--include-atelier", type=Path, action="append", default=None, help="Include an Architect atelier workspace in --export (repeatable).")
    parser.add_argument("--set-drive-dir", type=Path, default=None, help="Persist default local Google Drive sync directory in <gravity_home>/core/sync.json.")
    parser.add_argument("--dry-run", action="store_true", help="Preview or verify operations without modifying files on disk.")
    parser.add_argument("--force", action="store_true", help="Force reinstallation of selected modules during --update.")
    parser.add_argument("--modules", type=str, default=None, help="Comma-separated module IDs or plugin names for --update/--check-updates.")
    parser.add_argument("--link", type=Path, action="append", default=None, help="Link a local repository clone to its module in sources.json (repeatable).")
    parser.add_argument("--repos-root", type=Path, default=None, help="Parent directory containing cloned Gravity repositories for --update/--check-updates.")
    parser.add_argument("--offline", action="store_true", help="Skip remote Git network calls during --update/--check-updates.")
    parser.add_argument("--shell", choices=("auto", "powershell", "bash"), default="auto", help="Target shell syntax for --migration-plan commands (default: auto).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    other_modes = (
        args.status, args.check, args.migration_plan, args.dashboard,
        args.guide, args.overview, args.import_zip is not None,
        args.update, args.check_updates,
    )
    if args.set_drive_dir is not None and any(other_modes):
        parser.error("--set-drive-dir cannot be combined with modes other than --export.")

    try:
        drive_res = None
        if args.set_drive_dir is not None:
            from core.bundle import set_drive_dir

            drive_res = set_drive_dir(args.set_drive_dir, gravity_home=args.gravity_home)

        if args.export:
            from core.bundle import export_bundle

            payload = export_bundle(
                args.gravity_home, out=args.out,
                include_ateliers=args.include_atelier or (), plugins_dirs=args.plugins_dir,
            )
            if drive_res is not None:
                payload["drive_config"] = drive_res
            rc = 0
        elif drive_res is not None:
            payload, rc = drive_res, 0
        elif args.import_zip is not None:
            from core.bundle import import_bundle

            payload, rc = import_bundle(args.import_zip, gravity_home=args.gravity_home, dry_run=args.dry_run), 0
        elif args.update or args.check_updates:
            from core.updater import run_update

            payload, rc = run_update(
                gravity_home=args.gravity_home, plugins_dirs=args.plugins_dir,
                check_only=args.check_updates, force=args.force, modules_csv=args.modules,
                link_paths=args.link or (), repos_root=args.repos_root,
                offline=args.offline, dry_run=args.dry_run,
            )
        else:
            payload, rc = run_environment(
                gravity_home=args.gravity_home, plugins_dirs=args.plugins_dir,
                status_only=args.status, check_only=args.check, migration_plan=args.migration_plan,
                dashboard=args.dashboard, guide=args.guide, overview=args.overview, shell=args.shell,
            )
    except (OSError, ValueError, ImportError) as exc:
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

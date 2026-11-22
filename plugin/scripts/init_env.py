#!/usr/bin/env python3
"""Non-interactive CLI to initialize, inspect, and diagnose Gravity Core environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional, Sequence

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


def _find_duplicate_ids(modules: Sequence[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for mod in modules:
        mod_id = str(mod.get("id") or "")
        if mod_id:
            counts[mod_id] = counts.get(mod_id, 0) + 1
    return sorted(mod_id for mod_id, count in counts.items() if count > 1)


def run_environment(
    *,
    gravity_home: Optional[Path] = None,
    plugins_dirs: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None,
    status_only: bool = False,
    check_only: bool = False,
) -> tuple[dict[str, Any], int]:
    """Execute init, status, or check workflow and return (payload, exit_code)."""
    resolved_home = resolve_gravity_home(gravity_home)
    roots = list(plugins_dirs) if plugins_dirs else default_plugin_roots()
    raw_modules = discover_modules(roots)
    modules = _enrich_module_homes(raw_modules, resolved_home)
    legacy_homes = detect_legacy_homes(home_dir)

    core_dir = resolved_home / "core"
    registry_path = core_dir / "modules.json"
    mode = "status" if status_only else ("check" if check_only else "init")

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
        "modules": modules,
        "legacy_homes": legacy_homes,
    }
    return payload, (0 if ok else 1)


def _print_human_report(payload: dict[str, Any]) -> None:
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

#!/usr/bin/env python3
"""Cross-platform installer and uninstaller for the Gravity Core Antigravity plugin (100% stdlib)."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent
PLUGIN_SOURCE = REPO_ROOT / "plugin"
PLUGIN_NAME = "gravity"
if str(PLUGIN_SOURCE) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SOURCE))

from _shared.installer_core import (  # noqa: E402
    InstallSpec,
    check_environment,
    has_real_python3,
    install_agy,
    install_copy,
    is_unsafe_target,
    read_module_contract,
    read_plugin_manifest,
    run_installer,
    uninstall_plugin,
)
from _shared.path_safety import safe_home_dir  # noqa: E402

EXEC_SCRIPTS: tuple[str, ...] = (
    "hooks/pre_invocation_gravity.py",
    "mcp/server.py",
    "scripts/init_env.py",
    "scripts/validate.py",
)


def is_gravity_core_dir(plugin_dir: Path) -> bool:
    """Return True when plugin_dir contains the Gravity Core plugin."""
    manifest = read_plugin_manifest(plugin_dir)
    if not manifest or manifest.get("name") != PLUGIN_NAME:
        return False
    mod = read_module_contract(plugin_dir)
    return bool(mod is not None and mod.get("id") == "core")


def is_legacy_gravity_harness(plugin_dir: Path) -> bool:
    """Return True when plugin_dir looks like an older legacy 'gravity' harness install."""
    if not plugin_dir.is_dir() or is_gravity_core_dir(plugin_dir):
        return False
    manifest = read_plugin_manifest(plugin_dir)
    if manifest is not None and manifest.get("name") == PLUGIN_NAME:
        return True
    if (plugin_dir / "hooks" / "pre_tool_guard.py").is_file():
        return True
    return (plugin_dir / "observability").is_dir() and (plugin_dir / "skills" / "gravity").is_dir()


def is_gravity_install_dir(plugin_dir: Path) -> bool:
    """Return True for either Gravity Core or an older legacy 'gravity' install."""
    return is_gravity_core_dir(plugin_dir) or is_legacy_gravity_harness(plugin_dir)


def print_next_steps(target_dir: Optional[Path], _args: object = None) -> None:
    """Print concise post-install instructions."""
    gravity_home = os.environ.get("GRAVITY_HOME", "").strip() or str(safe_home_dir() / ".gemini" / "gravity")
    print("\nNext steps:")
    if target_dir is not None:
        print(f"  - Installed plugin location : {target_dir}")
    print(f"  - Unified Gravity home      : {gravity_home}")
    print("  - Initialize environment    : python plugin/scripts/init_env.py (or /gravity init)")
    print("  - Open dashboard            : /gravity dashboard or Plugins -> Gravity (zero tokens)")
    print("  - Manage plugin in Antigravity : [Gravity](customization://gravity)")


CORE_INSTALL_SPEC = InstallSpec(
    plugin_name=PLUGIN_NAME,
    plugin_source=PLUGIN_SOURCE,
    display_name="Gravity Core",
    repo_root=REPO_ROOT,
    exec_scripts=EXEC_SCRIPTS,
    has_executable_manifest=True,
    description="Install, upgrade, validate, or uninstall the Gravity Core Antigravity plugin.",
    epilog="Examples:\n  python install.py --check\n  python install.py --force\n  python install.py --scope workspace --workspace /path/to/project",
    installed_check_fn=is_gravity_core_dir,
    legacy_check_fn=is_legacy_gravity_harness,
    next_steps_fn=print_next_steps,
    agy_strict_default=True,
    record_sources=True,
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_installer(CORE_INSTALL_SPEC, argv)


if __name__ == "__main__":
    raise SystemExit(main())

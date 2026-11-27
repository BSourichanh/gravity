"""Gravity Core package: unified environment resolution and module registry."""

from .registry import (
    detect_legacy_homes,
    discover_modules,
    resolve_gravity_home,
    resolve_gravity_home_raw,
    resolve_module_home,
    validate_module_contract,
    write_modules_registry,
)

__all__ = [
    "detect_legacy_homes",
    "discover_modules",
    "resolve_gravity_home",
    "resolve_gravity_home_raw",
    "resolve_module_home",
    "validate_module_contract",
    "write_modules_registry",
]

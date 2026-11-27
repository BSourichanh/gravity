#!/usr/bin/env python3
"""Deterministic SSOT synchronizer for gravity/shared/gravity_shared -> */plugin/_shared/ (100% stdlib)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional, Sequence, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_PARENT = REPO_ROOT / "shared"
if str(SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(SHARED_PARENT))

from gravity_shared.atomic_io import write_bytes_atomic  # noqa: E402
from gravity_shared.hook_runtime import configure_utf8_stdio  # noqa: E402
from gravity_shared.path_safety import ensure_safe_dir, is_symlink_or_junction  # noqa: E402

DEFAULT_SOURCE_DIR = SHARED_PARENT / "gravity_shared"
DEFAULT_REPOS_ROOT = REPO_ROOT.parent
DEFAULT_REPOS: tuple[str, ...] = ("gravity", "gravity-workflow", "gravity-metrics", "gravity-architect")
MANIFEST_FILENAME = ".shared_manifest.json"
SHARED_DIRNAME = "_shared"
SOURCE_REPO_NAME = "gravity"
SOURCE_REL_PATH = "shared/gravity_shared"
UTF8_BOM = b"\xef\xbb\xbf"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes_safe(path: str) -> Optional[bytes]:
    if not os.path.isfile(path) or is_symlink_or_junction(path):
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _normalize_py_bytes(raw: bytes, label: str) -> bytes:
    if raw.startswith(UTF8_BOM):
        raw = raw[len(UTF8_BOM) :]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Non-UTF-8 Python source in SSOT ({label}): {exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def collect_ssot_files(source_dir: Union[str, Path]) -> dict[str, tuple[bytes, str]]:
    """Read and normalize *.py files from source_dir, returning {filename: (bytes, sha256)}."""
    src_str = os.path.abspath(os.fspath(source_dir))
    if is_symlink_or_junction(src_str):
        raise ValueError(f"SSOT source directory must not be a symlink or junction: {src_str}")
    if not os.path.isdir(src_str):
        raise FileNotFoundError(f"SSOT source directory not found: {src_str}")

    collected: dict[str, tuple[bytes, str]] = {}
    for name in sorted(os.listdir(src_str)):
        if name == "__pycache__" or not name.endswith(".py"):
            continue
        entry_path = os.path.join(src_str, name)
        if is_symlink_or_junction(entry_path):
            raise ValueError(f"SSOT source file must not be a symlink or junction: {entry_path}")
        if os.path.isfile(entry_path):
            with open(entry_path, "rb") as fh:
                norm_bytes = _normalize_py_bytes(fh.read(), entry_path)
            collected[name] = (norm_bytes, _sha256_hex(norm_bytes))

    if not collected:
        raise ValueError(f"No .py files found in SSOT source directory: {src_str}")
    return collected


def parse_repos_arg(raw_repos: Optional[Sequence[str]]) -> tuple[str, ...]:
    """Parse --repos supporting single, comma-separated, or space-separated repo names."""
    if not raw_repos:
        return DEFAULT_REPOS
    selected: list[str] = []
    seen: set[str] = set()
    allowed = set(DEFAULT_REPOS)
    for token in raw_repos:
        for part in str(token).split(","):
            name = part.strip()
            if not name:
                continue
            if name not in allowed:
                raise ValueError(f"Unknown repository {name!r}; expected subset of {', '.join(DEFAULT_REPOS)}")
            if name not in seen:
                seen.add(name)
                selected.append(name)
    return tuple(selected) if selected else DEFAULT_REPOS


def _issue(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _read_existing_manifest(manifest_path: str) -> Optional[dict[str, Any]]:
    raw = _read_bytes_safe(manifest_path)
    if raw is None or raw.startswith(UTF8_BOM):
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except (UnicodeDecodeError, ValueError):
        return None


def _build_manifest_bytes(expected_hashes: dict[str, str], manifest_path: str) -> bytes:
    existing = _read_existing_manifest(manifest_path)
    if (
        existing is not None
        and existing.get("schema_version") == 1
        and existing.get("source_repo") == SOURCE_REPO_NAME
        and existing.get("source_path") == SOURCE_REL_PATH
        and existing.get("files") == expected_hashes
        and isinstance(existing.get("generated_at"), str)
        and existing["generated_at"].strip()
    ):
        generated_at = existing["generated_at"].strip()
    else:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "schema_version": 1, "source_repo": SOURCE_REPO_NAME, "source_path": SOURCE_REL_PATH,
        "generated_at": generated_at, "files": {k: expected_hashes[k] for k in sorted(expected_hashes)},
    }
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _collect_link_issues(repo_dir: str, plugin_dir: str, shared_dir: str, manifest_path: str) -> list[dict[str, str]]:
    issues = [
        _issue("SYMLINK_OR_JUNCTION", p, f"Refusing symlink or junction: {p}")
        for p in (repo_dir, plugin_dir, shared_dir, manifest_path)
        if is_symlink_or_junction(p)
    ]
    if os.path.isdir(shared_dir) and not is_symlink_or_junction(shared_dir):
        for entry_name in sorted(os.listdir(shared_dir)):
            entry_path = os.path.join(shared_dir, entry_name)
            if is_symlink_or_junction(entry_path):
                issues.append(_issue("SYMLINK_OR_JUNCTION", entry_path, f"Symlink/junction in _shared: {entry_path}"))
    return issues


def _check_repo(repo_name: str, repo_dir: str, expected: dict[str, tuple[bytes, str]]) -> dict[str, Any]:
    plugin_dir = os.path.join(repo_dir, "plugin")
    shared_dir, manifest_path = os.path.join(plugin_dir, SHARED_DIRNAME), os.path.join(plugin_dir, MANIFEST_FILENAME)
    issues = _collect_link_issues(repo_dir, plugin_dir, shared_dir, manifest_path)
    if not os.path.isdir(plugin_dir):
        issues.append(_issue("MISSING", plugin_dir, f"Plugin directory missing: {plugin_dir}"))
        return {"repo": repo_name, "ok": False, "status": "drift", "plugin_dir": plugin_dir, "manifest_path": manifest_path, "issues": issues}

    expected_hashes = {name: sha for name, (_, sha) in sorted(expected.items())}
    if not os.path.isdir(shared_dir):
        issues.append(_issue("MISSING", shared_dir, f"Shared directory missing: {shared_dir}"))
    else:
        for entry_name in sorted(os.listdir(shared_dir)):
            entry_path = os.path.join(shared_dir, entry_name)
            if not is_symlink_or_junction(entry_path) and entry_name.endswith(".py") and entry_name not in expected_hashes:
                issues.append(_issue("EXTRA_FILE", entry_path, f"Unexpected stale file in _shared: {entry_name}"))
        for name, (_, exp_sha) in sorted(expected.items()):
            dst_file = os.path.join(shared_dir, name)
            if is_symlink_or_junction(dst_file):
                continue
            raw = _read_bytes_safe(dst_file)
            if raw is None and not os.path.isfile(dst_file):
                issues.append(_issue("MISSING", dst_file, f"Missing projected file: {name}"))
            elif raw is None or _sha256_hex(raw) != exp_sha:
                issues.append(_issue("HASH_MISMATCH", dst_file, f"SHA-256 mismatch for {name}"))

    if not os.path.lexists(manifest_path):
        issues.append(_issue("MISSING", manifest_path, f"Manifest missing: {manifest_path}"))
    elif not is_symlink_or_junction(manifest_path):
        manifest = _read_existing_manifest(manifest_path)
        if manifest is None or any((
            manifest.get("schema_version") != 1, manifest.get("source_repo") != SOURCE_REPO_NAME,
            manifest.get("source_path") != SOURCE_REL_PATH, manifest.get("files") != expected_hashes,
        )):
            issues.append(_issue("MANIFEST_STALE", manifest_path, "Manifest invalid, missing BOM-free JSON, or stale"))
    return {"repo": repo_name, "ok": not issues, "status": "ok" if not issues else "drift", "plugin_dir": plugin_dir, "manifest_path": manifest_path, "issues": issues}


def _apply_repo(repo_name: str, repo_dir: str, expected: dict[str, tuple[bytes, str]]) -> dict[str, Any]:
    plugin_dir = os.path.join(repo_dir, "plugin")
    shared_dir, manifest_path = os.path.join(plugin_dir, SHARED_DIRNAME), os.path.join(plugin_dir, MANIFEST_FILENAME)
    issues = _collect_link_issues(repo_dir, plugin_dir, shared_dir, manifest_path)
    if not os.path.isdir(plugin_dir):
        issues.append(_issue("MISSING", plugin_dir, f"Plugin directory missing: {plugin_dir}"))
    if issues:
        return {"repo": repo_name, "ok": False, "status": "error", "plugin_dir": plugin_dir, "manifest_path": manifest_path, "issues": issues, "written": [], "removed": []}

    ensure_safe_dir(shared_dir)
    written: list[str] = []
    removed: list[str] = []
    for entry_name in sorted(os.listdir(shared_dir)):
        if entry_name.endswith(".py") and entry_name not in expected:
            stale_path = os.path.join(shared_dir, entry_name)
            if os.path.isfile(stale_path):
                os.unlink(stale_path)
                removed.append(entry_name)

    for name, (norm_bytes, _) in sorted(expected.items()):
        dst_file = os.path.join(shared_dir, name)
        if _read_bytes_safe(dst_file) != norm_bytes:
            write_bytes_atomic(dst_file, norm_bytes, reject_symlink=True)
            written.append(name)

    expected_hashes = {name: sha for name, (_, sha) in sorted(expected.items())}
    manifest_bytes = _build_manifest_bytes(expected_hashes, manifest_path)
    if _read_bytes_safe(manifest_path) != manifest_bytes:
        write_bytes_atomic(manifest_path, manifest_bytes, reject_symlink=True)
        written.append(MANIFEST_FILENAME)
    return {"repo": repo_name, "ok": True, "status": "synced", "plugin_dir": plugin_dir, "manifest_path": manifest_path, "issues": [], "written": written, "removed": removed}


def sync_shared_plugins(
    source_dir: Union[str, Path] = DEFAULT_SOURCE_DIR,
    repos_root: Union[str, Path] = DEFAULT_REPOS_ROOT,
    repos: Sequence[str] = DEFAULT_REPOS,
    *,
    apply: bool = False,
    check: bool = False,
) -> dict[str, Any]:
    """Project or verify gravity/shared/gravity_shared/*.py across Gravity plugin repositories."""
    if apply and check:
        raise ValueError("Cannot pass both apply=True and check=True")
    selected_repos = parse_repos_arg(repos)
    src_abs, root_abs = os.path.abspath(os.fspath(source_dir)), os.path.abspath(os.fspath(repos_root))
    expected = collect_ssot_files(src_abs)
    expected_hashes = {name: sha for name, (_, sha) in sorted(expected.items())}
    results = [(_apply_repo if apply else _check_repo)(repo_name, os.path.join(root_abs, repo_name), expected) for repo_name in selected_repos]
    return {
        "schema_version": 1, "mode": "apply" if apply else "check", "source_dir": src_abs,
        "repos_root": root_abs, "files": expected_hashes, "ok": all(item["ok"] for item in results), "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync or verify gravity_shared -> <repo>/plugin/_shared/ + .shared_manifest.json.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write _shared/*.py and .shared_manifest.json.")
    mode.add_argument("--check", action="store_true", help="Read-only verification (default).")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    parser.add_argument("--repos-root", type=Path, default=DEFAULT_REPOS_ROOT, help="Parent directory containing Gravity repos.")
    parser.add_argument("--repos", nargs="+", default=None, help=f"Repos subset (default: {', '.join(DEFAULT_REPOS)}).")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    configure_utf8_stdio()
    if sys.version_info < (3, 10):
        print("[ERROR] Python 3.10+ is required.", file=sys.stderr)
        return 1
    args = build_parser().parse_args(argv)
    try:
        report = sync_shared_plugins(DEFAULT_SOURCE_DIR, args.repos_root, parse_repos_arg(args.repos), apply=args.apply, check=args.check or not args.apply)
    except (ValueError, FileNotFoundError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False) if args.json else f"[ERROR] {exc}", file=sys.stdout if args.json else sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for item in report["results"]:
            print(f"[{'OK' if item['ok'] else 'FAIL'}] {item['repo']}: {item['status']}")
            for iss in item["issues"]:
                print(f"  - {iss['code']}: {iss['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

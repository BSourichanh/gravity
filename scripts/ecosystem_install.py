#!/usr/bin/env python3
"""Offline cross-repo orchestrator for installing, updating, checking, or uninstalling Gravity plugins (100% stdlib)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOS_ROOT = REPO_ROOT.parent

_PLUGIN_DIR = REPO_ROOT / "plugin"
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from core.updater import pull_git_repo_ff_only, run_subprocess_no_shell  # noqa: E402

TOPOLOGICAL_ORDER: tuple[str, ...] = (
    "gravity",
    "gravity-workflow",
    "gravity-metrics",
    "gravity-architect",
)

TIERS: dict[int, tuple[str, ...]] = {
    1: ("gravity", "gravity-workflow"),
    2: ("gravity", "gravity-workflow", "gravity-metrics"),
    3: TOPOLOGICAL_ORDER,
}


def _configure_stdio() -> None:
    """Force stdout/stderr to UTF-8 so Windows cp1252 consoles never crash."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def resolve_selected_repos(
    *,
    tier: Optional[int] = None,
    modules_csv: Optional[str] = None,
    uninstall: bool = False,
) -> list[str]:
    """Resolve and topologically order selected repositories (reversed for --uninstall)."""
    if tier is not None and modules_csv is not None:
        raise ValueError("--tier and --modules are mutually exclusive.")

    if modules_csv is not None:
        raw_tokens = [tok.strip() for tok in modules_csv.split(",") if tok.strip()]
        if not raw_tokens:
            raise ValueError("--modules requires at least one repository name.")
        unknown = [tok for tok in raw_tokens if tok not in TOPOLOGICAL_ORDER]
        if unknown:
            valid = ", ".join(TOPOLOGICAL_ORDER)
            raise ValueError(
                f"Unknown module(s) in --modules: {', '.join(unknown)}. Valid values: {valid}."
            )
        selected_set = set(raw_tokens)
        ordered = [name for name in TOPOLOGICAL_ORDER if name in selected_set]
    else:
        chosen_tier = 3 if tier is None else tier
        if chosen_tier not in TIERS:
            raise ValueError(f"Invalid --tier {chosen_tier!r}: expected 1, 2, or 3.")
        allowed = set(TIERS[chosen_tier])
        ordered = [name for name in TOPOLOGICAL_ORDER if name in allowed]

    if uninstall:
        ordered.reverse()
    return ordered


def _resolve_action(args: argparse.Namespace) -> str:
    if args.install:
        return "install"
    if args.update:
        return "update"
    if args.uninstall:
        return "uninstall"
    return "check"


def _build_installer_args(
    *,
    action: str,
    dry_run: bool,
    scope: Optional[str],
    workspace: Optional[Path],
    method: Optional[str],
    strict: bool,
    skip_validate: bool,
) -> list[str]:
    cmd_args: list[str] = []
    if action == "check":
        cmd_args.append("--check")
    elif action == "update":
        cmd_args.append("--force")
    elif action == "uninstall":
        cmd_args.append("--uninstall")

    if scope is not None:
        cmd_args.extend(["--scope", scope])
    if workspace is not None:
        cmd_args.extend(["--workspace", str(workspace)])
    if method is not None:
        cmd_args.extend(["--method", method])
    if strict:
        cmd_args.append("--strict")
    if skip_validate:
        cmd_args.append("--skip-validate")
    if dry_run:
        cmd_args.append("--dry-run")
    return cmd_args


def _validate_repos_layout(repos_root: Path, repos: Sequence[str]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    if not repos_root.is_dir():
        missing.append(
            {
                "repo": "<repos-root>",
                "path": str(repos_root),
                "reason": "repos-root directory does not exist",
            }
        )
        return missing

    for name in repos:
        repo_dir = repos_root / name
        installer = repo_dir / "install.py"
        if not repo_dir.is_dir():
            missing.append(
                {
                    "repo": name,
                    "path": str(repo_dir),
                    "reason": "repository directory not found",
                }
            )
        elif not installer.is_file():
            missing.append(
                {
                    "repo": name,
                    "path": str(installer),
                    "reason": "install.py not found in repository",
                }
            )
    return missing


def _locate_init_env(repos_root: Path) -> Optional[Path]:
    candidate = repos_root / "gravity" / "plugin" / "scripts" / "init_env.py"
    if candidate.is_file():
        return candidate
    fallback = REPO_ROOT / "plugin" / "scripts" / "init_env.py"
    if fallback.is_file():
        return fallback
    return None


def _locate_sync_shared(repos_root: Path) -> Optional[Path]:
    candidate = repos_root / "gravity" / "scripts" / "sync_shared.py"
    if candidate.is_file():
        return candidate
    fallback = REPO_ROOT / "scripts" / "sync_shared.py"
    if fallback.is_file():
        return fallback
    return None


def _run_sync_shared_preflight(
    repos_root: Path,
    ordered_repos: Sequence[str],
) -> tuple[Optional[dict[str, Any]], bool]:
    ssot_dir = repos_root / "gravity" / "shared" / "gravity_shared"
    if not ssot_dir.is_dir():
        return None, True

    sync_script = _locate_sync_shared(repos_root)
    if sync_script is None:
        return {"ok": False, "error": "scripts/sync_shared.py not found"}, False

    cmd = [
        sys.executable,
        "-B",
        str(sync_script),
        "--check",
        "--repos-root",
        str(repos_root),
        "--repos",
        ",".join(ordered_repos),
        "--json",
    ]
    proc = run_subprocess_no_shell(cmd, cwd=sync_script.parent.parent, timeout=None)
    parsed: Any = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except ValueError:
            parsed = None

    ok = proc.returncode == 0 and isinstance(parsed, dict) and parsed.get("ok") is True
    if isinstance(parsed, dict):
        return parsed, ok
    return {
        "ok": False,
        "returncode": proc.returncode,
        "stderr": proc.stderr.strip(),
        "stdout": proc.stdout.strip(),
    }, False


def _run_registry_post_step(
    *,
    repos_root: Path,
    action: str,
    dry_run: bool,
    effective_scope: str,
) -> tuple[dict[str, Any], bool]:
    if effective_scope != "global":
        return {"status": "skipped", "reason": "workspace scope does not update global modules.json"}, True
    if action == "uninstall":
        return {"status": "skipped", "reason": "uninstall preserves centralized $GRAVITY_HOME"}, True

    init_script = _locate_init_env(repos_root)
    if init_script is None:
        if action in ("install", "update") and not dry_run:
            return {"status": "error", "error": "plugin/scripts/init_env.py not found"}, False
        return {"status": "skipped", "reason": "init_env.py not found"}, True

    if action in ("install", "update") and not dry_run:
        cmd = [sys.executable, "-B", str(init_script), "--json"]
        mode = "refresh"
    else:
        cmd = [sys.executable, "-B", str(init_script), "--status", "--json"]
        mode = "status"

    proc = run_subprocess_no_shell(cmd, cwd=init_script.parent.parent, timeout=None)
    parsed: Any = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except ValueError:
            parsed = None

    ok = proc.returncode == 0
    result: dict[str, Any] = {
        "status": "ok" if ok else "error",
        "mode": mode,
        "script": str(init_script),
        "returncode": proc.returncode,
    }
    if isinstance(parsed, dict):
        result["registry_path"] = parsed.get("registry_path")
        result["module_count"] = parsed.get("module_count")
        result["valid_count"] = parsed.get("valid_count")
    if not ok:
        result["stderr"] = proc.stderr.strip()
        result["stdout"] = proc.stdout.strip()
    return result, ok


def orchestrate(
    *,
    action: str = "check",
    tier: Optional[int] = None,
    modules_csv: Optional[str] = None,
    repos_root: Optional[Path] = None,
    dry_run: bool = False,
    scope: Optional[str] = None,
    workspace: Optional[Path] = None,
    method: Optional[str] = None,
    strict: bool = False,
    skip_validate: bool = False,
    pull: bool = False,
) -> tuple[dict[str, Any], int]:
    """Orchestrate local Gravity installers in topological order and return (payload, exit_code)."""
    effective_scope = scope or "global"
    effective_method = method or "copy"
    resolved_root = (
        DEFAULT_REPOS_ROOT if repos_root is None else Path(repos_root)
    ).expanduser().resolve()

    if pull and action in ("check", "uninstall"):
        return (
            {
                "ok": False,
                "action": action,
                "error": "--pull cannot be combined with --check or --uninstall (requires --install or --update).",
            },
            2,
        )
    if effective_scope == "workspace" and workspace is None:
        return (
            {
                "ok": False,
                "action": action,
                "error": "--workspace PATH is required when --scope is 'workspace'.",
            },
            2,
        )
    if effective_method == "agy" and effective_scope == "workspace":
        return (
            {
                "ok": False,
                "action": action,
                "error": "--method agy only supports --scope global.",
            },
            2,
        )

    try:
        ordered_repos = resolve_selected_repos(
            tier=tier,
            modules_csv=modules_csv,
            uninstall=(action == "uninstall"),
        )
    except ValueError as exc:
        return (
            {
                "ok": False,
                "action": action,
                "repos_root": str(resolved_root),
                "error": str(exc),
            },
            2,
        )

    missing = _validate_repos_layout(resolved_root, ordered_repos)
    if missing:
        return (
            {
                "ok": False,
                "action": action,
                "repos_root": str(resolved_root),
                "ordered_repos": ordered_repos,
                "error": "Missing required repository or install.py (fail-closed).",
                "missing": missing,
                "results": [],
            },
            1,
        )

    pull_results: list[dict[str, Any]] = []
    if pull:
        for repo_name in ordered_repos:
            if dry_run:
                pull_results.append({"repo": repo_name, "status": "dry_run", "ok": True})
            else:
                pull_results.append(pull_git_repo_ff_only(resolved_root / repo_name, repo_name=repo_name))

    shared_sync_report: Optional[dict[str, Any]] = None
    if action in ("install", "update", "check"):
        shared_sync_report, sync_ok = _run_sync_shared_preflight(resolved_root, ordered_repos)
        if not sync_ok:
            fail_sync: dict[str, Any] = {
                "ok": False,
                "action": action,
                "dry_run": dry_run,
                "scope": effective_scope,
                "method": effective_method,
                "repos_root": str(resolved_root),
                "ordered_repos": ordered_repos,
                "error": "Shared SSOT drift detected (sync_shared.py --check failed).",
                "shared_sync": shared_sync_report,
                "results": [],
            }
            if pull:
                fail_sync["pull_results"] = pull_results
            return fail_sync, 1

    installer_args = _build_installer_args(
        action=action,
        dry_run=dry_run,
        scope=scope,
        workspace=workspace,
        method=method,
        strict=strict,
        skip_validate=skip_validate,
    )

    results: list[dict[str, Any]] = []
    for repo_name in ordered_repos:
        repo_dir = resolved_root / repo_name
        installer = repo_dir / "install.py"
        cmd = [sys.executable, "-B", str(installer), *installer_args]
        proc = run_subprocess_no_shell(cmd, cwd=repo_dir, timeout=None)
        entry = {
            "repo": repo_name,
            "installer": str(installer),
            "args": list(installer_args),
            "returncode": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
        results.append(entry)
        if proc.returncode != 0:
            fail_payload: dict[str, Any] = {
                "ok": False,
                "action": action,
                "dry_run": dry_run,
                "scope": effective_scope,
                "method": effective_method,
                "repos_root": str(resolved_root),
                "ordered_repos": ordered_repos,
                "failed_repo": repo_name,
                "error": f"Installer failed for '{repo_name}' (exit {proc.returncode}).",
                "results": results,
                "registry": {"status": "skipped", "reason": "aborted after installer failure"},
            }
            if shared_sync_report is not None:
                fail_payload["shared_sync"] = shared_sync_report
            if pull:
                fail_payload["pull_results"] = pull_results
            return fail_payload, 1

    registry_info, reg_ok = _run_registry_post_step(
        repos_root=resolved_root,
        action=action,
        dry_run=dry_run,
        effective_scope=effective_scope,
    )
    pull_errors = [item for item in pull_results if not item.get("ok")]
    overall_ok = reg_ok and not pull_errors
    payload: dict[str, Any] = {
        "ok": overall_ok,
        "action": action,
        "dry_run": dry_run,
        "scope": effective_scope,
        "method": effective_method,
        "repos_root": str(resolved_root),
        "ordered_repos": ordered_repos,
        "results": results,
        "registry": registry_info,
    }
    if shared_sync_report is not None:
        payload["shared_sync"] = shared_sync_report
    if pull:
        payload["pull_results"] = pull_results
    if not reg_ok:
        payload["error"] = registry_info.get("error") or "Failed to refresh core/modules.json."
    elif pull_errors:
        payload["error"] = "One or more repositories failed during --pull."
    return payload, (0 if overall_ok else 1)


def _print_human_report(payload: dict[str, Any]) -> None:
    print(f"Gravity Ecosystem Orchestrator (action={payload.get('action')})")
    if "repos_root" in payload:
        print(f"  Repos Root : {payload['repos_root']}")
    if "ordered_repos" in payload:
        print(f"  Order      : {' -> '.join(payload['ordered_repos'])}")

    if payload.get("missing"):
        print("\n[ERROR] Missing prerequisites (fail-closed):", file=sys.stderr)
        for item in payload["missing"]:
            print(f"  - {item['repo']}: {item['reason']} ({item['path']})", file=sys.stderr)
        return

    pull_results = payload.get("pull_results") or []
    if pull_results:
        print("\n[PULL] Git fast-forward results:")
        for item in pull_results:
            reason = item.get("reason") or item.get("error") or ""
            suffix = f" ({reason})" if reason else ""
            print(f"  - {item.get('repo')}: {item.get('status')}{suffix}")

    shared_sync = payload.get("shared_sync")
    if isinstance(shared_sync, dict):
        tag = "OK" if shared_sync.get("ok") else "FAIL"
        print(f"\n[{tag}] Shared SSOT check (sync_shared.py --check)")

    for res in payload.get("results") or []:
        tag = "OK" if res["ok"] else "FAIL"
        args_str = " ".join(res["args"]) if res["args"] else "(default install)"
        print(f"\n[{tag}] {res['repo']} ({args_str})")
        if res["stdout"]:
            print(res["stdout"])
        if res["stderr"]:
            print(res["stderr"], file=sys.stderr)

    registry = payload.get("registry")
    if isinstance(registry, dict):
        status = registry.get("status")
        if status == "ok":
            print(
                f"\n[OK] Registry ({registry.get('mode')}): {registry.get('registry_path')} "
                f"({registry.get('valid_count')}/{registry.get('module_count')} valid)"
            )
        elif status == "error":
            print(f"\n[ERROR] Registry {registry.get('mode')} failed: {registry.get('stderr')}", file=sys.stderr)
        elif status == "skipped":
            print(f"\n[INFO] Registry step skipped: {registry.get('reason')}")

    if not payload.get("ok") and payload.get("error"):
        print(f"\n[ERROR] {payload['error']}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline orchestrator for local Gravity ecosystem repositories.",
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--check",
        action="store_true",
        help="Read-only check across selected repositories (default action).",
    )
    action_group.add_argument(
        "--install",
        action="store_true",
        help="Install selected repositories in topological order.",
    )
    action_group.add_argument(
        "--update",
        action="store_true",
        help="Upgrade/reinstall selected repositories (passes --force).",
    )
    action_group.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall selected repositories in reverse topological order.",
    )

    select_group = parser.add_mutually_exclusive_group()
    select_group.add_argument(
        "--tier",
        type=int,
        choices=(1, 2, 3),
        default=None,
        help="Suite tier: 1 (core+workflow), 2 (+metrics), 3 (all 4 repos, default).",
    )
    select_group.add_argument(
        "--modules",
        type=str,
        default=None,
        help="Comma-separated list of repository names to process in topological order.",
    )

    parser.add_argument(
        "--repos-root",
        type=Path,
        default=None,
        help="Parent directory containing cloned Gravity repositories (default: parent of gravity repo).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Forward --dry-run to each repository installer without modifying disk.",
    )
    parser.add_argument(
        "--scope",
        choices=("global", "workspace"),
        default=None,
        help="Forward --scope {global,workspace} to each repository installer.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Forward --workspace PATH to each repository installer.",
    )
    parser.add_argument(
        "--method",
        choices=("copy", "agy"),
        default=None,
        help="Forward --method {copy,agy} to each repository installer.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Forward --strict to each repository installer.",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Forward --skip-validate to each repository installer.",
    )
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Opt-in: run git fetch + git pull --ff-only (fail-isolated) before install/update.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdio()
    if sys.version_info < (3, 10):
        print("[ERROR] Python 3.10+ is required.", file=sys.stderr)
        return 1

    parser = build_parser()
    args = parser.parse_args(argv)
    action = _resolve_action(args)

    payload, rc = orchestrate(
        action=action,
        tier=args.tier,
        modules_csv=args.modules,
        repos_root=args.repos_root,
        dry_run=args.dry_run,
        scope=args.scope,
        workspace=args.workspace,
        method=args.method,
        strict=args.strict,
        skip_validate=args.skip_validate,
        pull=args.pull,
    )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_human_report(payload)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

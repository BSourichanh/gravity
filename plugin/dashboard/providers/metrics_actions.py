"""Read-only DIP CLI dispatcher for Gravity Metrics session lifecycle actions."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Optional, Sequence

from core.registry import resolve_gravity_home
from dashboard.providers import load_modules_snapshot_ro

ALLOWED_METRICS_ACTIONS: tuple[str, ...] = (
    "record",
    "update",
    "update-meta",
    "ignore",
    "unignore",
    "remove",
)

CLI_TIMEOUT_S = 20
_SAFE_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _clean_text(value: Any, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Expected string parameter.")
    return _CONTROL_RE.sub(" ", value).strip()[:max_len]


def _validate_target(conversation_id: str, slug: str, target: str) -> str:
    for cand in (target, conversation_id, slug):
        clean = str(cand or "").strip()
        if clean:
            if not _SAFE_TARGET_RE.match(clean):
                raise ValueError(f"Invalid target identifier: {clean!r}.")
            return clean
    raise ValueError("A valid conversation_id, slug, or target is required.")


def resolve_metrics_cli_path(
    *,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
) -> tuple[Optional[Path], Optional[str]]:
    """Resolve `gravity-metrics/plugin/scripts/cli.py` via DIP `modules.json` or `discover_modules()`."""
    g_home = resolve_gravity_home(gravity_home)
    modules, _, _, _, _ = load_modules_snapshot_ro(g_home, plugin_roots=plugin_roots)
    metrics_mod = next(
        (m for m in modules if isinstance(m, dict) and str(m.get("id") or "").strip() == "metrics"),
        None,
    )
    if metrics_mod is None:
        return None, "Gravity Metrics module is not installed or registered in modules.json."

    raw_dir = str(metrics_mod.get("plugin_dir") or "").strip()
    if not raw_dir:
        return None, "Gravity Metrics module has no plugin_dir configured."

    plugin_dir = Path(raw_dir).expanduser().resolve()
    cli_path = (plugin_dir / "scripts" / "cli.py").resolve()
    if not cli_path.is_relative_to(plugin_dir) or cli_path.is_symlink() or not cli_path.is_file():
        return None, f"Metrics CLI script not found or unsafe: {cli_path}"
    return cli_path, None


def _build_cli_args(
    action: str,
    target: str,
    *,
    label: str,
    project: str,
    note: str,
    reason: str,
    workspace: str,
    full: bool,
    purge_reports: bool,
    metrics_home: Optional[Path],
    brain_dir: Optional[Path],
) -> list[str]:
    cmd: list[str] = []
    if action in ("record", "update"):
        cmd.extend(["record", target])
        if action == "update":
            cmd.append("--update-sealed")
        if full:
            cmd.append("--full")
        if label:
            cmd.extend(["--label", label])
        if note:
            cmd.extend(["--note", note])
        if workspace:
            cmd.extend(["--workspace", workspace])
        if brain_dir is not None:
            cmd.extend(["--brain-dir", str(Path(brain_dir).expanduser())])
    elif action == "update-meta":
        cmd.extend(["update-meta", target])
        for flag, val in (("--label", label), ("--project", project), ("--note", note)):
            if val:
                cmd.extend([flag, val])
    elif action == "ignore":
        cmd.extend(["ignore", target])
        if reason or note:
            cmd.extend(["--reason", reason or note])
    elif action == "unignore":
        cmd.extend(["unignore", target])
    elif action == "remove":
        cmd.extend(["remove", target])
        if purge_reports:
            cmd.append("--purge-reports")

    if metrics_home is not None:
        cmd.extend(["--store", str(Path(metrics_home).expanduser())])
    cmd.append("--json")
    return cmd


def _parse_cli_json(stdout: str) -> Optional[dict[str, Any]]:
    raw = (stdout or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except ValueError:
        return None


def run_metrics_cli_action(
    action: str,
    *,
    conversation_id: str = "",
    slug: str = "",
    target: str = "",
    label: str = "",
    project: str = "",
    note: str = "",
    reason: str = "",
    workspace: str = "",
    full: bool = False,
    purge_reports: bool = True,
    timeout_s: int = CLI_TIMEOUT_S,
    gravity_home: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None,
    metrics_home: Optional[Path] = None,
    brain_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Execute a validated `gravity-metrics` CLI action via subprocess without shell."""
    clean_action = str(action or "").strip().lower()
    if clean_action not in ALLOWED_METRICS_ACTIONS:
        return {"ok": False, "action": clean_action, "message": f"Unsupported action {clean_action!r}.", "result": None}

    try:
        resolved_target = _validate_target(conversation_id, slug, target)
        c_label = _clean_text(label, 120)
        c_project = _clean_text(project, 80)
        c_note = _clean_text(note, 500)
        c_reason = _clean_text(reason, 240)
        c_workspace = _clean_text(workspace, 400)
    except ValueError as exc:
        return {"ok": False, "action": clean_action, "message": str(exc), "result": None}

    cli_path, err = resolve_metrics_cli_path(gravity_home=gravity_home, plugin_roots=plugin_roots)
    if cli_path is None:
        return {"ok": False, "action": clean_action, "message": err or "Metrics CLI unavailable.", "result": None}

    args = _build_cli_args(
        clean_action, resolved_target,
        label=c_label, project=c_project, note=c_note, reason=c_reason, workspace=c_workspace,
        full=bool(full), purge_reports=bool(purge_reports), metrics_home=metrics_home, brain_dir=brain_dir,
    )
    bounded_timeout = max(1, min(60, int(timeout_s)))

    try:
        proc = subprocess.run(
            [sys.executable, str(cli_path), *args],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=bounded_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "action": clean_action, "message": f"Metrics CLI timed out after {bounded_timeout}s.", "result": None}
    except OSError as exc:
        return {"ok": False, "action": clean_action, "message": f"Failed to run Metrics CLI: {exc}", "result": None}

    parsed = _parse_cli_json(proc.stdout)
    ok = proc.returncode == 0 and (bool(parsed.get("ok")) if isinstance(parsed, dict) and "ok" in parsed else True)
    msg = str(parsed.get("message") or parsed.get("error") or "").strip() if isinstance(parsed, dict) else ""
    if not msg:
        msg = (proc.stderr or proc.stdout or "").strip() or (
            f"Action {clean_action} completed." if ok else f"Action {clean_action} failed (exit {proc.returncode})."
        )
    return {"ok": ok, "action": clean_action, "message": msg[:400], "result": parsed, "returncode": proc.returncode}

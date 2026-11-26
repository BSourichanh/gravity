"""Read-only diagnostics, legacy migration planning, and Antigravity version probes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any, Callable, Optional, Sequence

try:
    import winreg  # type: ignore[import-not-found]
except ImportError:
    winreg = None  # type: ignore[assignment]

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.path_safety import is_symlink_or_junction, safe_home_dir  # noqa: E402
from core.registry import default_plugin_roots, resolve_gravity_home, resolve_module_home  # noqa: E402

MAX_SCAN_FILES = 10_000
MAX_SCAN_DEPTH = 32
MAX_COLLISIONS_SHOWN = 50
MIN_ANTIGRAVITY_MCP_APP_VERSION: tuple[int, int, int] = (2, 34, 0)


def _resolve_shell(shell: str) -> str: return ("powershell" if os.name == "nt" else "bash") if shell == "auto" else shell
def _resolve_base_home(home_dir: Optional[Path]) -> Path: return (safe_home_dir() if home_dir is None else Path(home_dir)).expanduser().resolve()
def _ps_quote(value: str) -> str: return value.replace("`", "``").replace('"', '`"')


def _scan_result(
    file_count: int, total_bytes: int, *, truncated: bool = False,
    skipped_symlink: bool = False, collision_count: int = 0, collisions: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "file_count": file_count, "total_bytes": total_bytes, "truncated": truncated,
        "skipped_symlink": skipped_symlink, "conflict": collision_count > 0,
        "collision_count": collision_count, "collisions": collisions if collisions is not None else [],
    }


def _scan_legacy_directory(source_path: Path, target_path: Path) -> dict[str, Any]:
    """Read-only scan of a legacy path counting files/bytes and collisions without following symlinks."""
    if is_symlink_or_junction(source_path):
        return _scan_result(0, 0, skipped_symlink=True)
    if not source_path.is_dir():
        try:
            size = source_path.lstat().st_size
        except OSError:
            size = 0
        dest = target_path / source_path.name
        col = dest.exists() or is_symlink_or_junction(dest)
        return _scan_result(1, size, collision_count=1 if col else 0, collisions=[source_path.name] if col else [])

    file_count = total_bytes = collision_count = 0
    truncated, collisions, seen_dirs = False, [], set()
    try:
        if (rst := source_path.lstat()).st_ino:
            seen_dirs.add((rst.st_dev, rst.st_ino))
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
            ep = Path(entry.path)
            if entry.is_symlink() or is_symlink_or_junction(ep):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > MAX_SCAN_DEPTH:
                        truncated = True
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if st.st_ino:
                        if (st.st_dev, st.st_ino) in seen_dirs:
                            continue
                        seen_dirs.add((st.st_dev, st.st_ino))
                    stack.append((ep, depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    if file_count >= MAX_SCAN_FILES:
                        return _scan_result(file_count, total_bytes, truncated=True, collision_count=collision_count, collisions=collisions)
                    file_count += 1
                    total_bytes += entry.stat(follow_symlinks=False).st_size
                    rel = ep.relative_to(source_path).as_posix()
                    dest = target_path / rel
                    if dest.exists() or is_symlink_or_junction(dest):
                        collision_count += 1
                        if len(collisions) < MAX_COLLISIONS_SHOWN:
                            collisions.append(rel)
            except OSError:
                continue
    return _scan_result(file_count, total_bytes, truncated=truncated, collision_count=collision_count, collisions=collisions)


def _build_shell_steps(
    *, source_path: Path, target_path: Path, backup_path: Path, shell: str, is_dir: bool, conflict: bool,
) -> list[dict[str, Any]]:
    """Build 4 non-destructive manual migration steps for powershell or bash."""
    src_str, dst_str, bkp_str, bkp_par = str(source_path), str(target_path), str(backup_path), str(backup_path.parent)
    if shell == "powershell":
        q_src, q_dst, q_bkp, q_par = _ps_quote(src_str), _ps_quote(dst_str), _ps_quote(bkp_str), _ps_quote(bkp_par)
        s1 = f'New-Item -ItemType Directory -Force -Path "{q_par}" | Out-Null; Copy-Item -Path "{q_src}" -Destination "{q_bkp}" -Recurse'
        s2 = (
            f'New-Item -ItemType Directory -Force -Path "{q_dst}" | Out-Null; Get-ChildItem -Path "{q_src}" -Recurse -File | ForEach-Object {{ '
            f'$rel = $_.FullName.Substring("{q_src}".Length).TrimStart("\\","/"); $out = Join-Path "{q_dst}" $rel; '
            f'if (-not (Test-Path $out)) {{ New-Item -ItemType Directory -Force -Path (Split-Path $out -Parent) | Out-Null; Copy-Item -Path $_.FullName -Destination $out }} }}'
        ) if is_dir else f'New-Item -ItemType Directory -Force -Path "{q_dst}" | Out-Null; $out = Join-Path "{q_dst}" "{_ps_quote(source_path.name)}"; if (-not (Test-Path $out)) {{ Copy-Item -Path "{q_src}" -Destination $out }}'
        s4 = f'# Remove-Item -Recurse -Force "{q_src}"'
    else:
        q_src, q_dst, q_bkp, q_par, q_dst_sl = shlex.quote(src_str), shlex.quote(dst_str), shlex.quote(bkp_str), shlex.quote(bkp_par), shlex.quote(f"{dst_str}/")
        s1 = f"mkdir -p {q_par} && cp -a {q_src} {q_bkp}"
        s2 = f"mkdir -p {q_dst} && cp -n -r {shlex.quote(f'{src_str}/.')} {q_dst_sl}" if is_dir else f"mkdir -p {q_dst} && cp -n {q_src} {q_dst_sl}"
        s4 = f"# rm -rf {q_src}"
    copy_note = "Conflicts detected: existing target files will be skipped; compare and merge manually." if conflict else "No collisions detected; existing target files will never be overwritten."
    return [
        {"step": 1, "kind": "backup", "description": "Create a timestamped backup before any migration.", "command": s1},
        {"step": 2, "kind": "copy", "description": copy_note, "command": s2},
        {"step": 3, "kind": "verify", "description": "Verify module contracts and environment health (read-only).", "command": "python scripts/init_env.py --check"},
        {"step": 4, "kind": "cleanup", "description": "Manual cleanup only after verifying migrated data (commented out by default).", "command": s4},
    ]


def _resolve_target_for_legacy(target_module: str, modules: Sequence[dict[str, Any]], gravity_home: Path) -> Path:
    env_override: Optional[str] = None
    for mod in modules:
        if mod.get("id") == target_module and mod.get("valid"):
            cand = (mod.get("storage") or {}).get("env_override")
            if isinstance(cand, str) and cand.strip():
                env_override = cand
                break
    return resolve_module_home(target_module, env_override=env_override, gravity_home=gravity_home)


def build_migration_plan(
    *, legacy_homes: Sequence[dict[str, Any]], modules: Sequence[dict[str, Any]],
    gravity_home: Path, home_dir: Optional[Path] = None, shell: str = "auto", date_stamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build a strictly read-only, 4-step manual migration plan for detected legacy homes."""
    resolved_shell = _resolve_shell(shell)
    backup_root = _resolve_base_home(home_dir) / "gravity-legacy-backup"
    stamp = date_stamp or datetime.now(timezone.utc).strftime("%Y%m%d")
    plans: list[dict[str, Any]] = []
    for item in legacy_homes:
        source_path, target_module = Path(item["path"]), str(item["target_module"])
        target_path = _resolve_target_for_legacy(target_module, modules, gravity_home)
        backup_path = backup_root / f"{item['name']}-{stamp}"
        scan = _scan_legacy_directory(source_path, target_path)
        is_dir = bool(item.get("is_dir", True))
        steps = _build_shell_steps(
            source_path=source_path, target_path=target_path, backup_path=backup_path,
            shell=resolved_shell, is_dir=is_dir, conflict=bool(scan["conflict"]),
        )
        plans.append({
            "name": item["name"], "target_module": target_module, "source_path": str(source_path),
            "target_path": str(target_path), "backup_path": str(backup_path), "is_dir": is_dir, **scan, "steps": steps,
        })
    return {"shell": resolved_shell, "backup_root": str(backup_root), "plan_count": len(plans), "has_conflicts": any(p["conflict"] for p in plans), "plans": plans}


def print_migration_plan_report(payload: dict[str, Any]) -> None:
    print(f"Gravity Core Legacy Migration Plan (read-only, shell={payload['shell']})\n  Gravity Home : {payload['gravity_home']}\n  Backup Root  : {payload['backup_root']}")
    plans = payload.get("plans") or []
    if not plans:
        print("\nLegacy directories: none detected (nothing to migrate).")
        return
    print(f"\nDetected {len(plans)} legacy directory(ies) (read-only plan; nothing modified on disk):")
    for plan in plans:
        print(f"\n- {plan['name']} -> module '{plan['target_module']}'\n  Source  : {plan['source_path']} ({plan['file_count']} file(s), {plan['total_bytes']} bytes)")
        if plan.get("skipped_symlink"):
            print("  Notice  : Source path is a symlink and was not traversed.")
        if plan.get("truncated"):
            print("  Notice  : Scan cap reached; totals are lower bounds.")
        print(f"  Target  : {plan['target_path']}\n  Backup  : {plan['backup_path']}")
        if plan.get("conflict"):
            shown = plan.get("collisions") or []
            total_col = plan.get("collision_count", len(shown))
            print(f"  [CONFLICT] {total_col} file(s) already exist at target (manual review required; non-clobber copy will skip them):")
            for rel in shown:
                print(f"    * {rel}")
            if total_col > len(shown):
                print(f"    * ... (+{total_col - len(shown)} more)")
        print("  Steps:\n" + "\n".join(f"    {s['step']}. [{s['kind']}] {s['description']}\n       {s['command']}" for s in (plan.get("steps") or [])))


def find_duplicate_ids(modules: Sequence[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for mod in modules:
        mod_id = str(mod.get("id") or "")
        if mod_id:
            counts[mod_id] = counts.get(mod_id, 0) + 1
    return sorted(mod_id for mod_id, count in counts.items() if count > 1)


def _read_json_file_ro(path: Path) -> tuple[Any, Optional[str]]:
    if is_symlink_or_junction(path):
        return None, f"{path} est un symlink (refusé en lecture seule)."
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"{path} illisible ({exc})."
    bom_err = raw.startswith(b"\xef\xbb\xbf")
    if bom_err:
        raw = raw[3:]
    try:
        data = json.loads(raw.decode("utf-8"))
        return data, (f"{path.name} contient un BOM UTF-8." if bom_err else None)
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"{path} JSON invalide ({exc})."


def _is_valid_atelier_dir(candidate: Path) -> bool:
    try:
        return not is_symlink_or_junction(candidate) and candidate.is_dir() and (candidate / "ECOSYSTEM.md").is_file() and (candidate / "projects.json").is_file()
    except OSError:
        return False


def _inspect_architect_ateliers_ro(ateliers_path: Path) -> tuple[bool, int]:
    """Inspect <architect_home>/ateliers.json strictly RO; return (exists, valid_count)."""
    if is_symlink_or_junction(ateliers_path.parent) or is_symlink_or_junction(ateliers_path) or not ateliers_path.is_file():
        return False, 0
    data, err = _read_json_file_ro(ateliers_path)
    if err and data is None:
        return True, 0
    if not isinstance(data, dict) or not isinstance(data.get("ateliers"), list):
        return True, 0
    valid_count = sum(
        1 for e in data["ateliers"]
        if isinstance(e, dict) and str(e.get("workspace_path") or "").strip() and _is_valid_atelier_dir(Path(str(e["workspace_path"]).strip()).expanduser())
    )
    return True, valid_count


def _parse_semver_str(raw: str) -> Optional[tuple[int, int, int]]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", raw)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _app_version_payload(parsed: Optional[tuple[int, int, int]], source: str, hint: str) -> dict[str, Any]:
    min_req = ".".join(str(x) for x in MIN_ANTIGRAVITY_MCP_APP_VERSION)
    if parsed is None:
        return {"version": None, "source": "none", "meets_mcp_app_min": None, "min_required": min_req, "update_hint": ""}
    return {"version": f"{parsed[0]}.{parsed[1]}.{parsed[2]}", "source": source, "meets_mcp_app_min": parsed >= MIN_ANTIGRAVITY_MCP_APP_VERSION, "min_required": min_req, "update_hint": hint}


def _detect_windows_app_version() -> Optional[dict[str, Any]]:
    """Read-only probe of installed Antigravity App version via Windows Registry (winreg)."""
    if os.name != "nt" or winreg is None:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                with winreg.OpenKey(hive, subkey) as root_key:
                    idx = 0
                    while True:
                        try:
                            app_sub = winreg.EnumKey(root_key, idx)
                            idx += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(root_key, app_sub) as app_key:
                                disp_name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                if isinstance(disp_name, str) and "antigravity" in disp_name.lower():
                                    disp_ver, _ = winreg.QueryValueEx(app_key, "DisplayVersion")
                                    if isinstance(disp_ver, str) and (parsed := _parse_semver_str(disp_ver)) is not None:
                                        return _app_version_payload(parsed, "winreg", "mettez à jour Antigravity App (>= 2.34.0) depuis son installeur Windows")
                        except OSError:
                            continue
            except OSError:
                continue
    return None


def _detect_antigravity_app_version() -> dict[str, Any]:
    """Best-effort read-only probe of installed Antigravity App version (winreg, snap, or dpkg-query)."""
    if (win_info := _detect_windows_app_version()) is not None:
        return win_info
    for bin_name, args, hint in (
        ("snap", ["list", "antigravity"], "fermer Antigravity App puis exécuter : sudo snap refresh antigravity"),
        ("dpkg-query", ["-W", "-f=${Version}", "antigravity"], "sudo apt update && sudo apt upgrade antigravity"),
    ):
        if not (cmd_path := shutil.which(bin_name)):
            continue
        try:
            proc = subprocess.run([cmd_path, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2.0, shell=False, check=False)
            if proc.returncode == 0:
                raw_ver = next((c[1] for ln in proc.stdout.splitlines() if len(c := ln.split()) >= 2 and c[0] == "antigravity"), "") if bin_name == "snap" else proc.stdout.strip()
                if (parsed := _parse_semver_str(raw_ver)) is not None:
                    return _app_version_payload(parsed, "dpkg" if bin_name == "dpkg-query" else bin_name, hint)
        except Exception:
            pass
    return _app_version_payload(None, "none", "")


def _validate_jsonl_ro(path: Path) -> tuple[int, Optional[str]]:
    if is_symlink_or_junction(path):
        return 0, f"{path} est un symlink (refusé en lecture seule)."
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return 0, f"{path} illisible ({exc})."
    count = 0
    for idx, raw_ln in enumerate(text.splitlines(), start=1):
        line = raw_ln.lstrip("\ufeff").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            return count, f"{path} ligne {idx} corrompue ({exc})."
        if not isinstance(obj, dict):
            return count, f"{path} ligne {idx} n'est pas un objet JSON."
        count += 1
    return count, None


def _inspect_metrics_health_ro(mod_home: Path) -> tuple[str, str, list[str]]:
    history_path, metrics_md = mod_home / "data" / "history.jsonl", mod_home / "METRICS.md"
    try:
        paths_ok = not any(is_symlink_or_junction(p) for p in (mod_home, history_path.parent, history_path, metrics_md)) and history_path.is_file() and metrics_md.is_file()
    except OSError:
        paths_ok = False
    if not paths_ok:
        return ("WARN", "history.jsonl/METRICS.md absent(s)", [f"Module 'metrics' actif mais {history_path} ou {metrics_md} absent : exécutez /gravity-metrics pour initialiser la télémétrie."])
    sessions, jerr = _validate_jsonl_ro(history_path)
    if jerr:
        return "WARN", "history.jsonl invalide", [f"Module 'metrics' : {jerr}"]
    return "OK", f"{sessions} session(s)", []


def _check_json_dict_ro(path: Path, warns: list[str], err_prefix: str) -> bool:
    if not is_symlink_or_junction(path) and not path.is_file():
        return False
    data, err = _read_json_file_ro(path)
    if err or not isinstance(data, dict):
        warns.append(f"{err_prefix} : {path} invalide ({err or 'objet JSON attendu'}).")
        return False
    return True


def _inspect_workflow_health_ro(mod: dict[str, Any], mod_home: Path) -> tuple[str, str, list[str]]:
    warns: list[str] = []
    pdir = str(mod.get("plugin_dir") or "").strip()
    hooks_path = Path(pdir) / "hooks.json" if pdir else None
    if hooks_path is None or is_symlink_or_junction(hooks_path) or not hooks_path.is_file():
        warns.append(f"Module 'workflow' : hooks.json absent ou symlink ({hooks_path}).")
    else:
        _check_json_dict_ro(hooks_path, warns, "Module 'workflow'")

    live_count = 0
    if is_symlink_or_junction(mod_home):
        warns.append(f"Module 'workflow' : {mod_home} est un symlink.")
    elif mod_home.is_dir():
        _check_json_dict_ro(mod_home / "live_workspaces.json", warns, "Module 'workflow'")
        ws_dir = mod_home / "workspaces"
        if is_symlink_or_junction(ws_dir):
            warns.append(f"Module 'workflow' : {ws_dir} est un symlink.")
        elif ws_dir.is_dir():
            for sub in sorted(ws_dir.iterdir(), key=lambda p: p.name):
                if is_symlink_or_junction(sub):
                    warns.append(f"Module 'workflow' : sous-dossier symlink refusé ({sub}).")
                elif sub.is_dir():
                    if _check_json_dict_ro(sub / "live_state.json", warns, "Module 'workflow'"):
                        live_count += 1
                    rj = sub / "runs.jsonl"
                    if is_symlink_or_junction(rj) or rj.is_file():
                        _, rerr = _validate_jsonl_ro(rj)
                        if rerr:
                            warns.append(f"Module 'workflow' : {rerr}")
    return ("WARN", "état ou hooks invalide(s)", warns) if warns else ("OK", f"hooks.json OK · {live_count} état(s) live", [])


def _inspect_module_health_ro(mod: dict[str, Any], *, plugin_root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    """Inspect a single discovered module strictly read-only without symlinks or disk writes."""
    mod_id, plugin_name = str(mod.get("id") or ""), str(mod.get("plugin_name") or "")
    commands = [str(c) for c in (mod.get("commands") or []) if isinstance(c, str) and c.strip()]
    base = {"id": mod_id, "plugin_name": plugin_name, "version": str(mod.get("version") or "?"), "commands": commands}
    if not mod.get("valid"):
        return {**base, "status": "ERR", "summary": "contrat invalide", "warnings": [], "errors": [str(e) for e in (mod.get("errors") or ["Contrat module invalide."])]}
    raw_home = mod.get("resolved_home")
    if not isinstance(raw_home, str) or not raw_home:
        return {**base, "status": "OK", "summary": "actif", "warnings": [], "errors": []}

    mod_home = Path(raw_home)
    if mod_id == "architect" or plugin_name == "gravity-architect":
        ap = mod_home / "ateliers.json"
        reg_exists, valid_count = _inspect_architect_ateliers_ro(ap)
        if not reg_exists:
            status, summary, warns = "WARN", "ateliers.json absent", [f"Module 'architect' actif mais {ap} absent : lancez /gravity-architect init ou /gravity-architect sync dans votre atelier."]
        elif valid_count == 0:
            status, summary, warns = "WARN", "0 atelier valide", [f"Module 'architect' actif mais {ap} ne contient aucun atelier valide : lancez /gravity-architect init ou /gravity-architect sync."]
        else:
            status, summary, warns = "OK", f"{valid_count} atelier(s) valide(s)", []
    elif mod_id == "metrics" or plugin_name == "gravity-metrics":
        status, summary, warns = _inspect_metrics_health_ro(mod_home)
    elif mod_id == "workflow" or plugin_name == "gravity-workflow":
        status, summary, warns = _inspect_workflow_health_ro(mod, mod_home)
    elif mod_id == "core" or plugin_name == "gravity":
        diag = diagnose_mcp_dashboard(Path(mod.get("plugin_dir") or plugin_root))
        status, summary, warns = ("WARN", "MCP dashboard incomplet", list(diag["errors"])) if diag["errors"] else ("OK", ("registre initialisé" if (mod_home / "modules.json").is_file() else "lecture seule (non initialisé)"), [])
    elif is_symlink_or_junction(mod_home):
        status, summary, warns = "WARN", "home symlink refusé", [f"Module '{mod_id}' : {mod_home} est un symlink."]
    else:
        status, summary, warns = "OK", ("home présent" if mod_home.is_dir() else "home non initialisé"), []
    return {**base, "status": status, "summary": summary, "warnings": warns, "errors": []}


def _collect_doctor_warnings(
    modules: Sequence[dict[str, Any]], *, app_version: Optional[dict[str, Any]] = None, plugin_root: Path = PLUGIN_ROOT,
) -> list[str]:
    """Collect non-blocking read-only warnings for valid discovered modules and MCP dashboard."""
    warnings: list[str] = []
    has_core = False
    for mod in modules:
        if not mod.get("valid"):
            continue
        if mod.get("id") == "core" or mod.get("plugin_name") == "gravity":
            has_core = True
        warnings.extend(_inspect_module_health_ro(mod, plugin_root=plugin_root)["warnings"])
    if not has_core:
        warnings.extend(diagnose_mcp_dashboard(plugin_root)["errors"])
    app_info = app_version if app_version is not None else _detect_antigravity_app_version()
    if app_info.get("meets_mcp_app_min") is False:
        hint = str(app_info.get("update_hint") or "").strip()
        warnings.append(
            f"Antigravity App v{app_info.get('version') or '?'} détectée (< {app_info.get('min_required') or '2.34.0'}) : "
            f"interface MCP Apps non supportée{f' ; {hint}' if hint else ''}."
        )
    return warnings


def _has_real_python3() -> bool:
    found = shutil.which("python3")
    return bool(found) and not (os.name == "nt" and "windowsapps" in found.lower())


def diagnose_mcp_dashboard(plugin_root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    """Inspect mcp_config.json, mcp/server.py, dashboard/api.py, and python3 availability."""
    mcp_config_path, server_path, api_path = plugin_root / "mcp_config.json", plugin_root / "mcp" / "server.py", plugin_root / "dashboard" / "api.py"
    errors, mcp_command, mcp_args, mcp_config_ok = [], "", [], False
    if not mcp_config_path.is_file():
        errors.append("mcp_config.json introuvable.")
    else:
        data, read_err = _read_json_file_ro(mcp_config_path)
        if read_err:
            errors.append(read_err)
        dash = (data.get("mcpServers") or {}).get("dashboard") if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict) else None
        if data is not None and not isinstance(dash, dict):
            errors.append("mcp_config.json : section mcpServers.dashboard manquante.")
        elif isinstance(dash, dict):
            cmd, args = dash.get("command"), dash.get("args")
            mcp_command = cmd.strip() if (isinstance(cmd, str) and cmd.strip()) else ""
            if not mcp_command:
                errors.append("mcp_config.json : command manquant.")
            if isinstance(args, list) and all(isinstance(a, str) for a in args):
                mcp_args = list(args)
            else:
                errors.append("mcp_config.json : args invalide.")
            mcp_config_ok = not errors
    server_exists, api_exists = server_path.is_file(), api_path.is_file()
    if not server_exists:
        errors.append("mcp/server.py introuvable.")
    if not api_exists:
        errors.append("dashboard/api.py introuvable.")
    return {
        "mcp_config_path": str(mcp_config_path), "mcp_config_ok": mcp_config_ok, "mcp_command": mcp_command,
        "mcp_args": mcp_args, "server_path": str(server_path), "server_exists": server_exists,
        "api_path": str(api_path), "api_exists": api_exists, "real_python3": _has_real_python3(), "errors": errors,
    }


def run_dashboard_diagnostic(
    *, gravity_home: Optional[Path] = None, plugins_dirs: Optional[Sequence[Path]] = None,
    home_dir: Optional[Path] = None, app_version_detector: Optional[Callable[[], dict[str, Any]]] = None,
    plugin_root: Path = PLUGIN_ROOT,
) -> tuple[dict[str, Any], int]:
    """Run strictly read-only diagnostics for the Gravity MCP App dashboard."""
    from dashboard import api as dashboard_api

    resolved_home = resolve_gravity_home(gravity_home)
    roots = list(plugins_dirs) if plugins_dirs else default_plugin_roots()
    diag, app_info = diagnose_mcp_dashboard(plugin_root), (app_version_detector or _detect_antigravity_app_version)()
    overview = dashboard_api.get_overview(gravity_home=resolved_home, plugin_roots=roots, home_dir=home_dir)
    ok = bool(diag["mcp_config_ok"]) and bool(diag["server_exists"]) and bool(diag["api_exists"]) and not diag["errors"]
    return {
        "mode": "dashboard", "ok": ok, "gravity_home": str(resolved_home),
        "registry_path": overview["registry_path"], "registry_exists": overview["registry_exists"],
        "registry_source": overview["registry_source"], "plugin_roots": [str(Path(p).expanduser().resolve()) for p in roots],
        "dashboard": diag, "antigravity_app": app_info, "doctor": overview["doctor"],
        "tabs": overview["tabs"], "modules": overview["modules"], "legacy_homes": overview["legacy_homes"],
    }, (0 if ok else 1)


def print_dashboard_report(payload: dict[str, Any]) -> None:
    diag, doctor, tabs, app_info = payload.get("dashboard") or {}, payload.get("doctor") or {}, payload.get("tabs") or [], payload.get("antigravity_app") or {}
    meets = app_info.get("meets_mcp_app_min")
    if meets is True:
        app_lbl = f"OK (v{app_info.get('version') or '?'} via {app_info.get('source') or '?'}, >= {app_info.get('min_required') or '2.34.0'})"
    elif meets is False:
        hint = str(app_info.get("update_hint") or "").strip()
        app_lbl = f"[WARN] v{app_info.get('version') or '?'} via {app_info.get('source') or '?'} (< {app_info.get('min_required') or '2.34.0'}{f' ; {hint}' if hint else ''})"
    else:
        app_lbl = "unknown (non détecté)"
    tab_desc = ", ".join(f"{t.get('id')} ({t.get('label')})" for t in tabs) or "none"
    print(
        f"Gravity Dashboard Diagnostics (read-only)\n  Gravity Home  : {payload['gravity_home']}\n"
        f"  MCP Config    : {'OK' if diag.get('mcp_config_ok') else 'ERROR'} ({diag.get('mcp_command') or '-'})\n"
        f"  MCP Server    : {'present' if diag.get('server_exists') else 'missing'} ({diag.get('server_path')})\n"
        f"  Dashboard API : {'present' if diag.get('api_exists') else 'missing'} ({diag.get('api_path')})\n"
        f"  Real python3  : {'yes' if diag.get('real_python3') else 'no (Windows copy adapts to python/py -3)'}\n"
        f"  Antigravity   : {app_lbl}\n"
        f"  Doctor        : {doctor.get('status', 'unknown')} ({doctor.get('valid_count', 0)}/{doctor.get('module_count', 0)} modules valid)\n"
        f"  Tabs          : {tab_desc}\n  MCP Tool      : open_gravity_dashboard (aux_pane / global)"
    )
    for err in diag.get("errors") or []:
        print(f"  [ERROR] {err}")


_diagnose_mcp_dashboard = diagnose_mcp_dashboard
_find_duplicate_ids = find_duplicate_ids

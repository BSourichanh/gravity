"""Data-driven Git updater and source provenance registry for Gravity Core (100% stdlib)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Optional, Sequence

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.atomic_io import write_json_atomic  # noqa: E402
from _shared.file_lock import exclusive_file_lock  # noqa: E402
from _shared.path_safety import ensure_safe_dir, is_symlink_or_junction, safe_home_dir  # noqa: E402
from core.registry import default_plugin_roots, discover_modules, resolve_gravity_home  # noqa: E402

SOURCES_SCHEMA_VERSION = 1
CORE_MODULE_ID = "core"
GIT_TIMEOUT_S = 30
INSTALL_TIMEOUT_S = 120
_SKIPPED_GIT_STATUSES = frozenset({
    "unlinked", "missing_repo", "not_git_repo", "dirty",
    "detached", "no_upstream", "diverged", "error_fetch", "error_pull",
})
_HARD_ERROR_STATUSES = frozenset({"error_fetch", "error_pull", "error_install"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_repo_url(url: str) -> str:
    """Normalize HTTPS/SSH Git repository URLs for case-insensitive comparison."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    for pattern in (r"^git@([^:]+):(.+)$", r"^https?://([^/]+)/(.+)$"):
        m = re.match(pattern, cleaned, re.IGNORECASE)
        if m:
            return f"{m.group(1)}/{m.group(2)}".lower()
    return cleaned.lower()


def _read_json_dict(path: Path) -> Optional[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sources_path(gravity_home: Optional[Path] = None) -> Path:
    base = resolve_gravity_home(gravity_home)
    core_dir = base / "core"
    sources_path = core_dir / "sources.json"
    for p, lbl in ((base, "gravity_home"), (core_dir, "core_dir"), (sources_path, "sources.json")):
        if is_symlink_or_junction(p):
            raise ValueError(f"{lbl} must not be a symlink or junction: {p}")
    return sources_path


def _parse_sources_file(sources_path: Path) -> dict[str, Any]:
    if not sources_path.exists():
        return {"schema_version": SOURCES_SCHEMA_VERSION, "updated_at": None, "sources": {}}
    data = _read_json_dict(sources_path)
    if data is None:
        raise ValueError(f"Invalid JSON in sources registry: {sources_path}")
    raw_sources = {} if data.get("sources") is None else data.get("sources")
    if not isinstance(raw_sources, dict):
        raise ValueError(f"Invalid 'sources' object in {sources_path}")
    normalized = {k.strip(): dict(v) for k, v in raw_sources.items() if isinstance(k, str) and k.strip() and isinstance(v, dict)}
    return {"schema_version": SOURCES_SCHEMA_VERSION, "updated_at": data.get("updated_at"), "sources": normalized}


def load_sources_registry(gravity_home: Optional[Path] = None) -> tuple[Path, dict[str, Any]]:
    """Load <gravity_home>/core/sources.json safely (returns normalized structure if missing)."""
    sources_path = _sources_path(gravity_home)
    return sources_path, _parse_sources_file(sources_path)


def _write_sources_locked(sources_path: Path, registry: dict[str, Any]) -> Path:
    ensure_safe_dir(sources_path.parent)
    payload = {"schema_version": SOURCES_SCHEMA_VERSION, "updated_at": _utc_now_iso(), "sources": dict(registry.get("sources") or {})}
    return write_json_atomic(sources_path, payload, indent=2, ensure_ascii=False)


def write_sources_registry(gravity_home: Path, registry: dict[str, Any]) -> Path:
    """Atomically write <gravity_home>/core/sources.json under sources.lock."""
    sources_path = _sources_path(gravity_home)
    with exclusive_file_lock(sources_path.with_suffix(".lock")):
        return _write_sources_locked(sources_path, registry)


def run_subprocess_no_shell(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    extra_env: Optional[dict[str, str]] = None,
    timeout: Optional[int] = GIT_TIMEOUT_S,
) -> subprocess.CompletedProcess[str]:
    """Run a command with shell=False, PYTHONDONTWRITEBYTECODE=1, UTF-8 capture, and timeout handling."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        env.update(extra_env)
    try:
        return subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=list(cmd), returncode=124, stdout="", stderr=f"Command timed out after {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(args=list(cmd), returncode=127, stdout="", stderr=str(exc))


def _run_git(repo_dir: Path, args: Sequence[str], *, timeout: int = GIT_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    return run_subprocess_no_shell(
        ["git", "-C", str(repo_dir), *args],
        extra_env={"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
        timeout=timeout,
    )


def _git_head_and_branch(repo_dir: Path) -> tuple[Optional[str], Optional[str]]:
    sha_proc = _run_git(repo_dir, ["rev-parse", "HEAD"])
    sha = sha_proc.stdout.strip() if sha_proc.returncode == 0 and sha_proc.stdout.strip() else None
    br_proc = _run_git(repo_dir, ["symbolic-ref", "--short", "-q", "HEAD"])
    branch = br_proc.stdout.strip() if br_proc.returncode == 0 and br_proc.stdout.strip() else None
    return sha, branch


def _validate_candidate_repo(
    repo_dir: Path,
    *,
    expected_plugin: Optional[str] = None,
    expected_repository: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    resolved = repo_dir.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Repository directory not found: {resolved}")

    manifest_path = resolved / "plugin" / "plugin.json"
    if not manifest_path.is_file():
        raise ValueError(f"Missing plugin/plugin.json in repository: {resolved}")

    manifest = _read_json_dict(manifest_path)
    if manifest is None or not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        raise ValueError(f"Invalid plugin/plugin.json in repository: {manifest_path}")

    plugin_name = manifest["name"].strip()
    if expected_plugin and plugin_name != expected_plugin:
        raise ValueError(f"Repository plugin name {plugin_name!r} does not match expected {expected_plugin!r} ({resolved}).")

    repo_url = manifest.get("repository")
    if (
        isinstance(expected_repository, str)
        and expected_repository.strip()
        and isinstance(repo_url, str)
        and repo_url.strip()
        and _normalize_repo_url(expected_repository) != _normalize_repo_url(repo_url)
    ):
        raise ValueError(f"Repository URL mismatch for {plugin_name}: expected {expected_repository!r}, got {repo_url!r}.")

    return plugin_name, manifest


def _apply_link_overrides(
    modules: Sequence[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    *,
    link_paths: Sequence[Path] = (),
    repos_root: Optional[Path] = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Validate and merge --link and --repos-root mappings into sources dict in memory."""
    by_plugin = {str(mod["plugin_name"]).strip(): mod for mod in modules if str(mod.get("plugin_name") or "").strip()}
    linked_events: list[dict[str, Any]] = []
    changed = False

    def _upsert_link(plugin_name: str, repo_dir: Path, manifest: dict[str, Any], method: str) -> None:
        nonlocal changed
        mod = by_plugin[plugin_name]
        existing = dict(sources.get(plugin_name) or {})
        resolved_repo = str(repo_dir.resolve())
        entry = {
            **existing,
            "plugin_name": plugin_name,
            "repo_dir": resolved_repo,
            "repository": manifest.get("repository") or existing.get("repository"),
            "target_dir": existing.get("target_dir") or mod.get("plugin_dir"),
            "installed_version": existing.get("installed_version") or mod.get("version"),
        }
        if entry != sources.get(plugin_name):
            sources[plugin_name] = entry
            changed = True
        linked_events.append({"plugin_name": plugin_name, "repo_dir": resolved_repo, "via": method})

    def _expected_url_for(mod: dict[str, Any]) -> Optional[str]:
        installed = _read_json_dict(Path(mod["plugin_dir"]) / "plugin.json") or {}
        url = installed.get("repository")
        return url if isinstance(url, str) else None

    if repos_root is not None:
        root_dir = Path(repos_root).expanduser().resolve()
        if not root_dir.is_dir():
            raise ValueError(f"--repos-root directory does not exist: {root_dir}")
        manifest_index: dict[str, Path] = {}
        for child in sorted(root_dir.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or is_symlink_or_junction(child):
                continue
            cand_manifest = child / "plugin" / "plugin.json"
            parsed = _read_json_dict(cand_manifest) if cand_manifest.is_file() else None
            if parsed and isinstance(parsed.get("name"), str) and parsed["name"].strip():
                manifest_index.setdefault(parsed["name"].strip(), child)
        for plugin_name, mod in sorted(by_plugin.items()):
            cand_dir = root_dir / plugin_name
            target = cand_dir if cand_dir.is_dir() else manifest_index.get(plugin_name)
            if target is not None:
                matched_name, manifest = _validate_candidate_repo(target, expected_plugin=plugin_name, expected_repository=_expected_url_for(mod))
                _upsert_link(matched_name, target, manifest, "repos-root")

    for raw_link in link_paths:
        link_dir = Path(raw_link).expanduser().resolve()
        plugin_name, manifest = _validate_candidate_repo(link_dir)
        if plugin_name not in by_plugin:
            raise ValueError(f"Linked repository {link_dir} provides plugin {plugin_name!r}, which is not installed in plugins_dir.")
        _validate_candidate_repo(link_dir, expected_plugin=plugin_name, expected_repository=_expected_url_for(by_plugin[plugin_name]))
        _upsert_link(plugin_name, link_dir, manifest, "link")

    return linked_events, changed


def _filter_and_order_modules(modules: Sequence[dict[str, Any]], modules_csv: Optional[str]) -> list[dict[str, Any]]:
    """Filter modules by id or plugin_name (fail-closed) and order companions before core."""
    selected = list(modules)
    if modules_csv is not None:
        tokens = [tok.strip() for tok in modules_csv.split(",") if tok.strip()]
        if not tokens:
            raise ValueError("--modules requires at least one module id or plugin name.")
        by_token: dict[str, dict[str, Any]] = {}
        for mod in modules:
            for key in (str(mod.get("id") or "").strip(), str(mod.get("plugin_name") or "").strip()):
                if key:
                    by_token[key] = mod
        unknown = [tok for tok in tokens if tok not in by_token]
        if unknown:
            known = sorted({str(m.get("plugin_name") or m.get("id")) for m in modules})
            raise ValueError(f"Unknown module(s) in --modules: {', '.join(unknown)}. Installed: {', '.join(known) or 'none'}.")
        chosen_dirs: set[str] = set()
        filtered: list[dict[str, Any]] = []
        for tok in tokens:
            mod = by_token[tok]
            key = str(mod.get("plugin_dir") or mod.get("id"))
            if key not in chosen_dirs:
                chosen_dirs.add(key)
                filtered.append(mod)
        selected = filtered

    selected.sort(key=lambda m: (1 if m.get("id") == CORE_MODULE_ID else 0, str(m.get("id") or ""), str(m.get("plugin_name") or "")))
    return selected


def inspect_git_repo(repo_dir: Path, *, offline: bool = False) -> dict[str, Any]:
    """Inspect a local Git clone read-only (with optional git fetch) and classify its sync status."""
    info: dict[str, Any] = {
        "branch": None, "upstream": None, "ahead": 0, "behind": 0,
        "head_sha": None, "status": "not_git_repo", "ok": True, "error": None,
    }
    wt_proc = _run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"])
    if wt_proc.returncode != 0 or wt_proc.stdout.strip() != "true":
        return info

    head_sha, branch = _git_head_and_branch(repo_dir)
    info["head_sha"], info["branch"] = head_sha, branch

    st_proc = _run_git(repo_dir, ["status", "--porcelain"])
    if st_proc.returncode != 0:
        info["error"] = st_proc.stderr.strip() or None
        return info
    if st_proc.stdout.strip():
        info["status"] = "dirty"
        return info
    if not branch:
        info["status"] = "detached"
        return info

    up_proc = _run_git(repo_dir, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if up_proc.returncode != 0 or not up_proc.stdout.strip():
        info["status"] = "no_upstream"
        return info
    info["upstream"] = up_proc.stdout.strip()

    if not offline:
        fetch_proc = _run_git(repo_dir, ["fetch", "--quiet"])
        if fetch_proc.returncode != 0:
            info.update({"status": "error_fetch", "ok": False, "error": fetch_proc.stderr.strip() or f"git fetch failed (exit {fetch_proc.returncode})"})
            return info

    cnt_proc = _run_git(repo_dir, ["rev-list", "--left-right", "--count", "HEAD...@{u}"])
    if cnt_proc.returncode != 0:
        info.update({"status": "error_fetch", "ok": False, "error": cnt_proc.stderr.strip() or "Failed to compare HEAD with upstream."})
        return info

    parts = cnt_proc.stdout.strip().split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        info.update({"status": "error_fetch", "ok": False, "error": f"Unexpected rev-list output: {cnt_proc.stdout.strip()!r}"})
        return info

    ahead, behind = int(parts[0]), int(parts[1])
    info["ahead"], info["behind"] = ahead, behind
    if ahead > 0 and behind > 0:
        info["status"] = "diverged"
    elif behind > 0:
        info["status"] = "update_available"
    elif ahead > 0:
        info["status"] = "ahead"
    else:
        info["status"] = "up_to_date"
    return info


def pull_git_repo_ff_only(
    repo_dir: Path,
    *,
    repo_name: Optional[str] = None,
    offline: bool = False,
    inspected: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Fail-isolated fast-forward pull for a clean tracked Git repository."""
    state = dict(inspected) if inspected is not None else inspect_git_repo(repo_dir, offline=offline)
    status = state.get("status")
    out: dict[str, Any] = {
        "status": status, "branch": state.get("branch"), "head_sha": state.get("head_sha"),
        "ahead": state.get("ahead", 0), "behind": state.get("behind", 0), "ok": bool(state.get("ok", True)),
    }
    if repo_name is not None:
        out["repo"] = repo_name
    if state.get("error"):
        out["error"] = state["error"]

    if status in ("not_git_repo", "dirty", "detached", "no_upstream", "diverged"):
        out.update({"status": "skipped", "reason": status, "ok": True})
        return out

    if status == "update_available" and not offline:
        pull_proc = _run_git(repo_dir, ["pull", "--ff-only"])
        if pull_proc.returncode != 0:
            out.update({"status": "error_pull", "ok": False, "error": pull_proc.stderr.strip() or f"git pull --ff-only failed (exit {pull_proc.returncode})"})
            return out
        new_sha, new_branch = _git_head_and_branch(repo_dir)
        out.update({"head_sha": new_sha or out.get("head_sha"), "branch": new_branch or out.get("branch"), "status": "pulled", "ok": True})
    return out


def _inspect_module_git(mod: dict[str, Any], source_entry: Optional[dict[str, Any]], *, offline: bool) -> dict[str, Any]:
    mod_id = str(mod.get("id") or "")
    plugin_name = str(mod.get("plugin_name") or mod_id)
    installed_version = mod.get("version")
    installed_sha = source_entry.get("git_sha") if isinstance(source_entry, dict) else None
    raw_repo = source_entry.get("repo_dir") if isinstance(source_entry, dict) else None

    result: dict[str, Any] = {
        "id": mod_id, "plugin_name": plugin_name, "plugin_dir": mod.get("plugin_dir"),
        "installed_version": installed_version, "source_version": None, "repo_dir": str(raw_repo) if raw_repo else None,
        "branch": None, "upstream": None, "ahead": 0, "behind": 0,
        "installed_sha": installed_sha, "head_sha": None, "status": "unlinked",
        "action": "none", "reinstalled": False, "shared_sync_ok": None, "ok": True, "error": None,
    }
    if not raw_repo or not isinstance(raw_repo, str):
        return result

    repo_dir = Path(raw_repo).expanduser()
    result["repo_dir"] = str(repo_dir)
    if not repo_dir.is_dir():
        result["status"] = "missing_repo"
        return result

    src_manifest = _read_json_dict(repo_dir / "plugin" / "plugin.json")
    if src_manifest and isinstance(src_manifest.get("version"), str):
        result["source_version"] = src_manifest["version"]

    result.update(inspect_git_repo(repo_dir, offline=offline))
    if result["status"] == "up_to_date":
        sha_drift = bool(installed_sha and result["head_sha"] and installed_sha != result["head_sha"])
        ver_drift = bool(result["source_version"] and installed_version and result["source_version"] != installed_version)
        if sha_drift or ver_drift:
            result["status"] = "local_drift"
    return result


def _verify_shared_sync_for_repo(repo_dir: Path, plugin_dir: Path) -> tuple[bool, Optional[str]]:
    """Fail-closed verification of _shared/*.py and .shared_manifest.json parity after reinstall."""
    repo_shared, repo_manifest = repo_dir / "plugin" / "_shared", repo_dir / "plugin" / ".shared_manifest.json"
    sync_script, ssot_dir = repo_dir / "scripts" / "sync_shared.py", repo_dir / "shared" / "gravity_shared"
    inst_shared, inst_manifest = plugin_dir / "_shared", plugin_dir / ".shared_manifest.json"
    if not any(p.exists() or is_symlink_or_junction(p) for p in (repo_shared, repo_manifest, sync_script, inst_shared, inst_manifest)):
        return True, None

    if sync_script.is_file() and ssot_dir.is_dir() and repo_dir.name == "gravity":
        proc = run_subprocess_no_shell([sys.executable, "-B", str(sync_script), "--check", "--repos-root", str(repo_dir.parent), "--repos", "gravity", "--json"], cwd=repo_dir, timeout=GIT_TIMEOUT_S)
        try:
            chk = json.loads(proc.stdout) if proc.stdout.strip() else None
        except ValueError:
            chk = None
        if proc.returncode != 0 or not isinstance(chk, dict) or not chk.get("ok"):
            detail = proc.stderr.strip() or proc.stdout.strip() or f"sync_shared.py --check exited {proc.returncode}"
            return False, f"Shared SSOT drift detected via sync_shared.py --check: {detail}"

    if is_symlink_or_junction(inst_manifest) or not inst_manifest.is_file():
        return False, f"Missing or unsafe .shared_manifest.json in {plugin_dir}"
    raw_man = inst_manifest.read_bytes()
    if raw_man.startswith(b"\xef\xbb\xbf"):
        return False, f"UTF-8 BOM rejected in {inst_manifest}"
    manifest = _read_json_dict(inst_manifest)
    files = manifest.get("files") if manifest and manifest.get("schema_version") == 1 else None
    if not isinstance(files, dict) or not files:
        return False, f"Invalid .shared_manifest.json schema in {plugin_dir}"

    if is_symlink_or_junction(inst_shared) or not inst_shared.is_dir():
        return False, f"Missing or unsafe _shared directory in {plugin_dir}"
    actual_py = set()
    for entry in sorted(inst_shared.iterdir(), key=lambda p: p.name):
        if is_symlink_or_junction(entry):
            return False, f"Symlink or junction rejected in _shared: {entry}"
        if entry.is_file() and entry.suffix == ".py":
            actual_py.add(entry.name)
    if actual_py != set(files.keys()):
        return False, f"_shared file set mismatch in {plugin_dir}: expected {sorted(files)}, got {sorted(actual_py)}"
    for name, exp_sha in sorted(files.items()):
        if not isinstance(exp_sha, str) or hashlib.sha256((inst_shared / name).read_bytes()).hexdigest() != exp_sha:
            return False, f"_shared SHA-256 mismatch for {name} in {plugin_dir}"

    if repo_manifest.is_file() and not is_symlink_or_junction(repo_manifest):
        repo_man_data = _read_json_dict(repo_manifest)
        if not repo_man_data or repo_man_data.get("files") != files:
            return False, f"Installed .shared_manifest.json does not match source repo {repo_dir}"
    return True, None


def _run_installer_for_module(entry: dict[str, Any], *, gravity_home: Path) -> tuple[bool, Optional[str], Path]:
    repo_dir = Path(str(entry["repo_dir"]))
    plugin_name = str(entry["plugin_name"])
    default_target = (safe_home_dir() / ".gemini" / "config" / "plugins" / plugin_name).resolve()
    installed_target = Path(str(entry["plugin_dir"])).resolve() if entry.get("plugin_dir") else default_target
    installer = repo_dir / "install.py"
    if not installer.is_file():
        return False, f"install.py not found in {repo_dir}", installed_target

    cmd = [sys.executable, "-B", str(installer), "--force", "--strict"]
    if installed_target != default_target:
        cmd.extend(["--target", str(installed_target)])

    proc = run_subprocess_no_shell(cmd, cwd=repo_dir, extra_env={"GRAVITY_HOME": str(gravity_home)}, timeout=INSTALL_TIMEOUT_S)
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip() or f"install.py exited with {proc.returncode}", installed_target
    return True, None, installed_target


def _refresh_modules_registry_subprocess(
    *,
    gravity_home: Path,
    plugins_dirs: Sequence[Path],
    core_plugin_dir: Optional[Path],
) -> tuple[dict[str, Any], bool]:
    candidates = [core_plugin_dir / "scripts" / "init_env.py"] if core_plugin_dir is not None else []
    candidates.append(PLUGIN_ROOT / "scripts" / "init_env.py")
    init_script = next((p for p in candidates if p.is_file()), None)
    if init_script is None:
        return {"status": "error", "error": "scripts/init_env.py not found for registry refresh"}, False

    cmd = [sys.executable, "-B", str(init_script), "--gravity-home", str(gravity_home), "--json"]
    for pdir in plugins_dirs:
        cmd.extend(["--plugins-dir", str(pdir)])

    proc = run_subprocess_no_shell(cmd, cwd=init_script.parent.parent, timeout=GIT_TIMEOUT_S)
    ok = proc.returncode == 0
    info: dict[str, Any] = {"status": "ok" if ok else "error", "script": str(init_script), "returncode": proc.returncode}
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                for key in ("registry_path", "module_count", "valid_count"):
                    info[key] = parsed.get(key)
        except ValueError:
            pass
    if not ok:
        info["error"] = proc.stderr.strip() or proc.stdout.strip() or f"init_env.py exited with {proc.returncode}"
    return info, ok


def run_update(
    *,
    gravity_home: Optional[Path] = None,
    plugins_dirs: Optional[Sequence[Path]] = None,
    check_only: bool = False,
    force: bool = False,
    modules_csv: Optional[str] = None,
    link_paths: Sequence[Path] = (),
    repos_root: Optional[Path] = None,
    offline: bool = False,
    dry_run: bool = False,
) -> tuple[dict[str, Any], int]:
    """Inspect linked Git repos, pull fast-forward updates fail-isolated, and reinstall targets."""
    resolved_home = resolve_gravity_home(gravity_home)
    roots = [Path(p).expanduser().resolve() for p in (plugins_dirs if plugins_dirs else default_plugin_roots())]
    discovered = discover_modules(roots)

    sources_path, sources_reg = load_sources_registry(resolved_home)
    sources_map: dict[str, dict[str, Any]] = dict(sources_reg.get("sources") or {})
    linked_events, links_changed = _apply_link_overrides(discovered, sources_map, link_paths=link_paths, repos_root=repos_root)
    if links_changed and not check_only and not dry_run:
        sources_reg["sources"] = sources_map
        write_sources_registry(resolved_home, sources_reg)

    ordered_modules = _filter_and_order_modules(discovered, modules_csv)
    results = [
        _inspect_module_git(mod, sources_map.get(str(mod.get("plugin_name") or mod.get("id") or "")), offline=offline)
        for mod in ordered_modules
    ]
    core_plugin_dir = next(
        (Path(str(mod["plugin_dir"])) for mod in ordered_modules if mod.get("id") == CORE_MODULE_ID and mod.get("plugin_dir")),
        None,
    )

    any_reinstalled = False
    core_updated = False
    warnings: list[str] = []

    if not check_only and not dry_run:
        for entry in results:
            pulled = False
            if entry["status"] == "update_available" and not offline:
                repo_dir = Path(str(entry["repo_dir"]))
                pull_res = pull_git_repo_ff_only(repo_dir, offline=False, inspected=entry)
                if not pull_res.get("ok"):
                    entry.update({"status": pull_res["status"], "ok": False, "error": pull_res.get("error")})
                    continue
                pulled = True
                entry["action"] = "pulled"
                entry["head_sha"] = pull_res.get("head_sha") or entry["head_sha"]
                entry["branch"] = pull_res.get("branch") or entry["branch"]
                src_manifest = _read_json_dict(repo_dir / "plugin" / "plugin.json")
                if src_manifest and isinstance(src_manifest.get("version"), str):
                    entry["source_version"] = src_manifest["version"]

            if not (pulled or entry["status"] == "local_drift" or (force and entry["status"] not in _SKIPPED_GIT_STATUSES)):
                continue

            inst_ok, inst_err, installed_target = _run_installer_for_module(entry, gravity_home=resolved_home)
            if not inst_ok:
                entry.update({"status": "error_install", "ok": False, "error": inst_err})
                continue

            sync_ok, sync_err = _verify_shared_sync_for_repo(Path(str(entry["repo_dir"])), installed_target)
            entry["shared_sync_ok"] = sync_ok
            if not sync_ok:
                entry.update({"status": "error_install", "ok": False, "error": sync_err})
                continue

            entry.update({"reinstalled": True, "status": "updated" if pulled else "reinstalled", "action": "pulled+reinstalled" if pulled else "reinstalled"})
            any_reinstalled = True
            if entry["id"] == CORE_MODULE_ID:
                core_updated = True

            pname = str(entry["plugin_name"])
            base_src = dict(sources_map.get(pname) or {})
            base_src.update({
                "plugin_name": pname, "repo_dir": entry["repo_dir"], "git_sha": entry["head_sha"], "git_branch": entry["branch"],
                "installed_version": entry["source_version"] or entry["installed_version"], "installed_at": _utc_now_iso(),
            })
            sources_map[pname] = base_src
            links_changed = True

        if links_changed:
            with exclusive_file_lock(sources_path.with_suffix(".lock")):
                latest_reg = _parse_sources_file(sources_path)
                merged_sources = dict(latest_reg.get("sources") or {})
                for pname, sdata in sources_map.items():
                    combined = dict(merged_sources.get(pname) or {})
                    combined.update(sdata)
                    merged_sources[pname] = combined
                latest_reg["sources"] = merged_sources
                _write_sources_locked(sources_path, latest_reg)

    registry_info: dict[str, Any] = {"status": "skipped", "reason": "no module reinstalled"}
    reg_ok = True
    if any_reinstalled:
        registry_info, reg_ok = _refresh_modules_registry_subprocess(gravity_home=resolved_home, plugins_dirs=roots, core_plugin_dir=core_plugin_dir)

    if core_updated:
        warnings.append("Gravity Core ('gravity') a été mis à jour : redémarrez le serveur MCP 'gravity_dashboard' (ou Antigravity) pour recharger les modules Python en mémoire.")
    for entry in results:
        if entry["status"] in ("dirty", "detached", "no_upstream", "diverged"):
            warnings.append(f"{entry['plugin_name']}: dépôt ignoré ({entry['status']}).")
        elif entry["status"] == "unlinked":
            warnings.append(f"{entry['plugin_name']}: non lié dans sources.json (utilisez --link ou --repos-root).")

    error_count = sum(1 for r in results if r["status"] in _HARD_ERROR_STATUSES)
    skipped_count = sum(1 for r in results if r["status"] in _SKIPPED_GIT_STATUSES and r["status"] not in _HARD_ERROR_STATUSES)
    ok = (error_count == 0) and reg_ok
    payload: dict[str, Any] = {
        "mode": "check-updates" if check_only else "update", "ok": ok, "dry_run": dry_run, "offline": offline, "force": force,
        "check_only": check_only, "gravity_home": str(resolved_home), "sources_path": str(sources_path),
        "plugin_roots": [str(r) for r in roots], "linked": linked_events, "module_count": len(results),
        "updated_count": sum(1 for r in results if r["status"] == "updated"),
        "reinstalled_count": sum(1 for r in results if r["reinstalled"]),
        "up_to_date_count": sum(1 for r in results if r["status"] == "up_to_date"),
        "updates_available_count": sum(1 for r in results if r["status"] == "update_available"),
        "skipped_count": skipped_count, "error_count": error_count, "restart_mcp_recommended": core_updated,
        "warnings": warnings, "results": results, "registry_refresh": registry_info,
    }
    return payload, (0 if ok else 1)


def format_update_report(payload: dict[str, Any]) -> str:
    """Format compact human-readable report for --update and --check-updates."""
    title = "Gravity Core — Check Updates (read-only)" if payload.get("check_only") else "Gravity Core — Update"
    lines = [
        title,
        f"  Gravity Home : {payload.get('gravity_home')}",
        f"  Sources File : {payload.get('sources_path')}",
        f"  Options      : offline={bool(payload.get('offline'))} force={bool(payload.get('force'))} dry_run={bool(payload.get('dry_run'))}",
    ]
    for item in payload.get("results") or []:
        line = f"  - [{item.get('status')}] {item.get('plugin_name')} (id={item.get('id')}, branch={item.get('branch') or '-'}, ver={item.get('source_version') or item.get('installed_version') or '?'})"
        if item.get("behind"):
            line += f" behind={item['behind']}"
        if item.get("ahead"):
            line += f" ahead={item['ahead']}"
        if item.get("error"):
            line += f" :: {item['error']}"
        lines.append(line)

    reg = payload.get("registry_refresh") or {}
    if reg.get("status") == "ok":
        lines.append(f"  Registry     : refreshed ({reg.get('valid_count')}/{reg.get('module_count')} valid)")
    elif reg.get("status") == "error":
        lines.append(f"  Registry ERR : {reg.get('error')}")
    for warn in payload.get("warnings") or []:
        lines.append(f"  [WARN] {warn}")
    return "\n".join(lines)

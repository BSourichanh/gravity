"""Portable ZIP bundle export, verified import with path remapping, and Drive sync config."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import sys
import tempfile
from typing import Any, Optional, Sequence
import zipfile

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.atomic_io import write_bytes_atomic, write_json_atomic  # noqa: E402
from _shared.path_safety import (  # noqa: E402
    ensure_no_symlink_or_junction_under,
    ensure_safe_dir,
    is_symlink_or_junction,
    is_within_root,
    safe_home_dir,
    validate_rel_member_path,
)
from core.registry import default_plugin_roots, resolve_gravity_home  # noqa: E402

SYNC_CONFIG_SCHEMA_VERSION = 1
BUNDLE_SCHEMA_VERSION = 1
_EXCLUDED_DIR_NAMES = frozenset({".git", "__pycache__", ".venv", "venv", "node_modules"})
_STRICT_EXCLUDED_EXACT = frozenset(
    {
        "core/modules.json",
        "core/sources.json",
        "workflow/live_workspaces.json",
        "metrics/session_meta.json",
    }
)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _reject_link(path: Path, label: str) -> None:
    if is_symlink_or_junction(path):
        raise ValueError(f"{label} must not be a symlink or junction: {path}")


def _is_strictly_excluded(rel_posix: str) -> bool:
    norm = rel_posix.replace("\\", "/").lstrip("/")
    lower = norm.lower()
    if lower in _STRICT_EXCLUDED_EXACT:
        return True
    name = PurePosixPath(lower).name
    return name.endswith((".lock", ".db-wal", ".db-shm"))


def set_drive_dir(drive_dir: str | Path, gravity_home: Optional[Path] = None) -> dict[str, Any]:
    """Validate and atomically save <gravity_home>/core/sync.json."""
    if isinstance(drive_dir, str) and not drive_dir.strip():
        raise ValueError("drive_dir must be a non-empty path.")
    raw_drive = Path(drive_dir).expanduser()
    _reject_link(raw_drive, "drive_dir")
    _reject_link(raw_drive.parent, "drive_dir parent")
    if raw_drive.exists() and not raw_drive.is_dir():
        raise ValueError(f"drive_dir must be a directory: {raw_drive}")
    resolved_drive = raw_drive.resolve()

    if gravity_home is not None:
        _reject_link(Path(gravity_home).expanduser(), "gravity_home")
    base = resolve_gravity_home(gravity_home)
    _reject_link(base, "gravity_home")
    core_dir = base / "core"
    _reject_link(core_dir, "core_dir")
    sync_path = core_dir / "sync.json"
    _reject_link(sync_path, "sync.json")

    updated_at = _utc_now_iso()
    payload = {
        "schema_version": SYNC_CONFIG_SCHEMA_VERSION,
        "drive_dir": str(resolved_drive),
        "updated_at": updated_at,
    }
    write_json_atomic(sync_path, payload, indent=2, ensure_ascii=False)
    return {
        "mode": "set-drive-dir",
        "ok": True,
        "gravity_home": str(base),
        "sync_config_path": str(sync_path),
        "drive_dir": str(resolved_drive),
        "updated_at": updated_at,
    }


def _read_sync_drive_dir(base: Path) -> Optional[str]:
    sync_path = base / "core" / "sync.json"
    if is_symlink_or_junction(sync_path) or not sync_path.is_file():
        return None
    try:
        data = json.loads(sync_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    val = data.get("drive_dir")
    return val.strip() if isinstance(val, str) and val.strip() else None


def _detect_gdrive_plugin(plugins_dirs: Optional[Sequence[Path]] = None) -> bool:
    roots = [Path(p) for p in plugins_dirs] if plugins_dirs is not None else default_plugin_roots()
    for root in roots:
        try:
            resolved_root = root.expanduser().resolve()
        except OSError:
            continue
        gdrive_dir = resolved_root / "gdrive"
        if not gdrive_dir.is_dir() or is_symlink_or_junction(gdrive_dir):
            continue
        if (gdrive_dir / "plugin.json").is_file() or (gdrive_dir / "skills" / "gdrive" / "SKILL.md").is_file():
            return True
    return False


def _unique_slug(raw_name: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-") or "atelier"
    candidate = base
    idx = 2
    while candidate in used:
        candidate = f"{base}-{idx}"
        idx += 1
    used.add(candidate)
    return candidate


def _collect_dir_items(
    root_dir: Path,
    rel_prefix: str,
    kind: str,
    collected: list[tuple[str, bytes, str]],
    skipped: list[str],
    seen_targets: set[str],
) -> None:
    if is_symlink_or_junction(root_dir) or not root_dir.is_dir():
        if is_symlink_or_junction(root_dir):
            skipped.append(f"symlink:{root_dir}")
        return

    stack = [root_dir]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if is_symlink_or_junction(entry):
                skipped.append(f"symlink:{entry}")
                continue
            if entry.is_dir():
                if entry.name in _EXCLUDED_DIR_NAMES:
                    continue
                stack.append(entry)
                continue
            if not entry.is_file() or entry.suffix.lower() in (".pyc", ".pyo"):
                continue
            rel_sub = entry.relative_to(root_dir).as_posix()
            target_rel = f"{rel_prefix}/{rel_sub}" if rel_prefix else rel_sub
            if _is_strictly_excluded(target_rel):
                skipped.append(f"excluded:{target_rel}")
                continue
            if target_rel in seen_targets:
                continue
            seen_targets.add(target_rel)
            collected.append((target_rel, entry.read_bytes(), kind))


def _collect_single_file(
    file_path: Path,
    target_rel: str,
    kind: str,
    collected: list[tuple[str, bytes, str]],
    skipped: list[str],
    seen_targets: set[str],
) -> None:
    if is_symlink_or_junction(file_path):
        skipped.append(f"symlink:{file_path}")
        return
    if not file_path.is_file():
        return
    if _is_strictly_excluded(target_rel):
        skipped.append(f"excluded:{target_rel}")
        return
    if target_rel in seen_targets:
        return
    seen_targets.add(target_rel)
    collected.append((target_rel, file_path.read_bytes(), kind))


def _resolve_export_zip_path(out: Optional[str | Path], drive_dir: Optional[str], stamp: str) -> Path:
    filename = f"gravity-backup-{stamp}.zip"
    if out is not None:
        out_path = Path(out).expanduser()
        _reject_link(out_path, "out")
        if out_path.suffix.lower() == ".zip" or (out_path.exists() and out_path.is_file()):
            return out_path.resolve()
        if out_path.exists() and not out_path.is_dir():
            raise ValueError(f"--out path is neither a directory nor a .zip file: {out_path}")
        return (out_path / filename).resolve()
    if drive_dir:
        drive_path = Path(drive_dir).expanduser()
        _reject_link(drive_path, "drive_dir")
        return (drive_path / filename).resolve()
    return (Path.cwd() / filename).resolve()


def export_bundle(
    gravity_home: Optional[Path] = None,
    *,
    out: Optional[str | Path] = None,
    include_ateliers: Sequence[str | Path] = (),
    plugins_dirs: Optional[Sequence[Path]] = None,
) -> dict[str, Any]:
    """Export portable Gravity state and optional ateliers into an atomic verified ZIP bundle."""
    if gravity_home is not None:
        _reject_link(Path(gravity_home).expanduser(), "gravity_home")
    base = resolve_gravity_home(gravity_home)
    _reject_link(base, "gravity_home")

    stamp = _utc_stamp()
    drive_dir = _read_sync_drive_dir(base)
    target_zip = _resolve_export_zip_path(out, drive_dir, stamp)
    _reject_link(target_zip, "target_zip")
    ensure_safe_dir(target_zip.parent)

    collected: list[tuple[str, bytes, str]] = []
    skipped: list[str] = []
    seen_targets: set[str] = set()

    for rel_dir in ("metrics/data", "metrics/reports"):
        _collect_dir_items(base / rel_dir, rel_dir, "gravity_home", collected, skipped, seen_targets)

    for rel_file in (
        "metrics/METRICS.md",
        "METRICS.md",
        "metrics/ignored.json",
        "ignored.json",
        "architect/ateliers.json",
    ):
        _collect_single_file(base / rel_file, rel_file, "gravity_home", collected, skipped, seen_targets)

    wf_root = base / "workflow" / "workspaces"
    if wf_root.is_dir() and not is_symlink_or_junction(wf_root):
        for ws_dir in sorted(wf_root.iterdir(), key=lambda p: p.name):
            if is_symlink_or_junction(ws_dir) or not ws_dir.is_dir():
                continue
            _collect_single_file(
                ws_dir / "profile.json",
                f"workflow/workspaces/{ws_dir.name}/profile.json",
                "gravity_home",
                collected,
                skipped,
                seen_targets,
            )

    ateliers_meta: list[dict[str, str]] = []
    used_slugs: set[str] = set()
    for raw_atelier in include_ateliers:
        ap_raw = Path(raw_atelier).expanduser()
        _reject_link(ap_raw, "atelier")
        ap = ap_raw.resolve()
        if not ap.is_dir():
            raise ValueError(f"Atelier directory not found: {ap}")
        slug = _unique_slug(ap.name, used_slugs)
        ateliers_meta.append({"slug": slug, "source_path": str(ap)})
        _collect_single_file(ap / "ECOSYSTEM.md", f"ateliers/{slug}/ECOSYSTEM.md", "atelier", collected, skipped, seen_targets)
        _collect_single_file(ap / "projects.json", f"ateliers/{slug}/projects.json", "atelier", collected, skipped, seen_targets)
        for sub in ("specs", "tasks", "audits/code", "tracking"):
            _collect_dir_items(ap / sub, f"ateliers/{slug}/{sub}", "atelier", collected, skipped, seen_targets)

    collected.sort(key=lambda item: item[0])
    manifest_entries = [
        {
            "arcname": target_rel,
            "target_rel": target_rel,
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for target_rel, data, kind in collected
    ]
    gdrive_detected = _detect_gdrive_plugin(plugins_dirs)
    manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": _utc_now_iso(),
        "source_gravity_home": str(base),
        "source_user_home": str(safe_home_dir().resolve()),
        "platform": platform.system().lower(),
        "drive_dir": drive_dir,
        "gdrive_plugin_detected": gdrive_detected,
        "ateliers": ateliers_meta,
        "entries": manifest_entries,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    tmp_zip: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(target_zip.parent),
            prefix=f".{target_zip.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_zip = Path(handle.name)
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            for target_rel, data, _ in collected:
                zf.writestr(target_rel, data)
        os.replace(str(tmp_zip), str(target_zip))
        tmp_zip = None
    finally:
        if tmp_zip is not None and tmp_zip.exists():
            tmp_zip.unlink(missing_ok=True)

    return {
        "mode": "export",
        "ok": True,
        "gravity_home": str(base),
        "bundle_path": str(target_zip),
        "drive_dir": drive_dir,
        "gdrive_plugin_detected": gdrive_detected,
        "file_count": len(manifest_entries),
        "total_bytes": sum(e["size"] for e in manifest_entries),
        "ateliers": ateliers_meta,
        "skipped": skipped,
    }


def _normalize_prefix(raw_path: str) -> str:
    norm = raw_path.replace("\\", "/")
    if len(norm) > 1 and norm.endswith("/") and not re.match(r"^[A-Za-z]:/$", norm):
        norm = norm.rstrip("/")
    return norm


def _match_prefix(norm_val: str, norm_prefix: str) -> Optional[str]:
    if not norm_prefix:
        return None
    case_fold = bool(_WINDOWS_DRIVE_RE.match(norm_prefix))
    val_cmp = norm_val.lower() if case_fold else norm_val
    pre_cmp = norm_prefix.lower() if case_fold else norm_prefix
    if val_cmp == pre_cmp:
        return ""
    sep_prefix = pre_cmp if pre_cmp.endswith("/") else pre_cmp + "/"
    if val_cmp.startswith(sep_prefix):
        return norm_val[len(sep_prefix) :]
    return None


def _remap_path_value(
    raw_path: str,
    *,
    target_rel: str,
    field_name: str,
    src_gravity: str,
    dst_gravity: Path,
    src_user: str,
    dst_user: Path,
    atelier_restored_roots: dict[str, Path],
    remapped_paths: list[dict[str, str]],
    warnings: list[str],
) -> str:
    norm_val = _normalize_prefix(raw_path)
    new_path: Optional[str] = None
    for src_prefix, dst_base in ((src_gravity, dst_gravity), (src_user, dst_user)):
        suffix = _match_prefix(_normalize_prefix(norm_val), _normalize_prefix(src_prefix))
        if suffix is not None:
            joined = (dst_base / Path(*[p for p in suffix.split("/") if p])) if suffix else dst_base
            new_path = str(joined)
            break

    if new_path is None:
        warnings.append(f"Path outside source homes left unchanged ({target_rel} {field_name}): {raw_path}")
        return raw_path

    remapped_paths.append({"file": target_rel, "field": field_name, "old": raw_path, "new": new_path})
    if not Path(new_path).exists():
        restored = atelier_restored_roots.get(norm_val.lower() if _WINDOWS_DRIVE_RE.match(norm_val) else norm_val)
        hint = f" (restored archive copy at {restored})" if restored else ""
        warnings.append(f"Remapped path does not exist on disk ({target_rel} {field_name}): {new_path}{hint}")
    return new_path


def _remap_json_payload(
    target_rel: str,
    raw_bytes: bytes,
    *,
    manifest: dict[str, Any],
    target_home: Path,
    target_user: Path,
    atelier_restored_roots: dict[str, Path],
    remapped_paths: list[dict[str, str]],
    warnings: list[str],
) -> bytes:
    is_ateliers_reg = target_rel == "architect/ateliers.json"
    is_projects = target_rel == "projects.json" or (
        target_rel.startswith("ateliers/") and target_rel.endswith("/projects.json") and target_rel.count("/") == 2
    )
    if not (is_ateliers_reg or is_projects):
        return raw_bytes

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return raw_bytes
    if not isinstance(data, dict):
        return raw_bytes

    src_gravity = str(manifest.get("source_gravity_home") or "")
    src_user = str(manifest.get("source_user_home") or "")
    changed = False

    if is_ateliers_reg and isinstance(data.get("ateliers"), list):
        for idx, entry in enumerate(data["ateliers"]):
            if isinstance(entry, dict) and isinstance(entry.get("workspace_path"), str) and entry["workspace_path"].strip():
                old_ws = entry["workspace_path"]
                new_ws = _remap_path_value(
                    old_ws,
                    target_rel=target_rel,
                    field_name=f"ateliers[{idx}].workspace_path",
                    src_gravity=src_gravity,
                    dst_gravity=target_home,
                    src_user=src_user,
                    dst_user=target_user,
                    atelier_restored_roots=atelier_restored_roots,
                    remapped_paths=remapped_paths,
                    warnings=warnings,
                )
                if new_ws != old_ws:
                    entry["workspace_path"] = new_ws
                    changed = True

    if is_projects and isinstance(data.get("projects"), list):
        for idx, proj in enumerate(data["projects"]):
            if isinstance(proj, dict) and isinstance(proj.get("path"), str) and proj["path"].strip():
                old_p = proj["path"]
                new_p = _remap_path_value(
                    old_p,
                    target_rel=target_rel,
                    field_name=f"projects[{idx}].path",
                    src_gravity=src_gravity,
                    dst_gravity=target_home,
                    src_user=src_user,
                    dst_user=target_user,
                    atelier_restored_roots=atelier_restored_roots,
                    remapped_paths=remapped_paths,
                    warnings=warnings,
                )
                if new_p != old_p:
                    proj["path"] = new_p
                    changed = True

    if not changed:
        return raw_bytes
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def import_bundle(
    zip_path: str | Path,
    *,
    gravity_home: Optional[Path] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Verify ZIP integrity and safety in memory, remap paths, and restore under target gravity_home."""
    raw_zip = Path(zip_path).expanduser()
    _reject_link(raw_zip, "zip_path")
    resolved_zip = raw_zip.resolve()
    if not resolved_zip.is_file():
        raise FileNotFoundError(f"Bundle ZIP not found: {resolved_zip}")

    if gravity_home is not None:
        _reject_link(Path(gravity_home).expanduser(), "gravity_home")
    target_home = resolve_gravity_home(gravity_home)
    _reject_link(target_home, "gravity_home")
    target_user = safe_home_dir().resolve()

    staged: list[tuple[str, bytes]] = []
    ignored_excluded: list[str] = []
    remapped_paths: list[dict[str, str]] = []
    warnings: list[str] = []

    try:
        zf_ctx = zipfile.ZipFile(resolved_zip, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid ZIP bundle ({resolved_zip}): {exc}") from exc

    with zf_ctx as zf:
        for info in zf.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symlink entry rejected in ZIP: {info.filename!r}")
            validate_rel_member_path(info.filename, label="ZIP member", allow_dir=info.is_dir())

        try:
            manifest_raw = zf.read("manifest.json")
        except KeyError as exc:
            raise ValueError("Missing manifest.json in bundle ZIP.") from exc

        try:
            manifest = json.loads(manifest_raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid manifest.json in bundle ZIP: {exc}") from exc

        if not isinstance(manifest, dict) or manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
            raise ValueError("Unsupported or invalid manifest schema_version in bundle ZIP.")
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise ValueError("Invalid manifest.json: 'entries' must be a list.")

        atelier_restored_roots: dict[str, Path] = {}
        for item in manifest.get("ateliers") or []:
            if isinstance(item, dict) and isinstance(item.get("slug"), str) and isinstance(item.get("source_path"), str):
                norm_src = _normalize_prefix(item["source_path"])
                key = norm_src.lower() if _WINDOWS_DRIVE_RE.match(norm_src) else norm_src
                atelier_restored_roots[key] = target_home / "ateliers" / item["slug"]

        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"Invalid manifest entry at index {idx}.")
            arcname = validate_rel_member_path(str(entry.get("arcname") or ""), label=f"entries[{idx}].arcname")
            target_rel = validate_rel_member_path(str(entry.get("target_rel") or ""), label=f"entries[{idx}].target_rel")
            if target_rel == "manifest.json":
                raise ValueError("Refusing to overwrite manifest.json as target entry.")
            if _is_strictly_excluded(target_rel) or _is_strictly_excluded(arcname):
                ignored_excluded.append(target_rel)
                continue

            expected_size = entry.get("size")
            expected_sha = entry.get("sha256")
            if type(expected_size) is not int or expected_size < 0 or not isinstance(expected_sha, str):
                raise ValueError(f"Invalid size/sha256 metadata for entry {target_rel!r}.")

            try:
                data = zf.read(arcname)
            except KeyError as exc:
                raise ValueError(f"Missing ZIP member referenced by manifest: {arcname!r}") from exc

            if len(data) != expected_size:
                raise ValueError(f"Size mismatch for {arcname!r}: expected {expected_size}, got {len(data)}.")
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != expected_sha:
                raise ValueError(f"SHA-256 mismatch for {arcname!r}: expected {expected_sha}, got {actual_sha}.")
            staged.append((target_rel, data))

    prepared: list[tuple[str, bytes]] = []
    for target_rel, data in staged:
        remapped_bytes = _remap_json_payload(
            target_rel,
            data,
            manifest=manifest,
            target_home=target_home,
            target_user=target_user,
            atelier_restored_roots=atelier_restored_roots,
            remapped_paths=remapped_paths,
            warnings=warnings,
        )
        prepared.append((target_rel, remapped_bytes))

    written_files: list[str] = []
    if not dry_run:
        ensure_safe_dir(target_home)
        for target_rel, payload_bytes in prepared:
            dest_raw = target_home / target_rel
            ensure_no_symlink_or_junction_under(target_home, dest_raw)
            dest = dest_raw.resolve()
            if not is_within_root(target_home, dest):
                raise ValueError(f"Target path escapes gravity_home: {dest}")
            write_bytes_atomic(dest, payload_bytes)
            written_files.append(str(dest))

    return {
        "mode": "import",
        "ok": True,
        "dry_run": dry_run,
        "bundle_path": str(resolved_zip),
        "gravity_home": str(target_home),
        "file_count": len(prepared),
        "written_files": written_files,
        "ignored_excluded": ignored_excluded,
        "remapped_paths": remapped_paths,
        "warnings": warnings,
    }


def format_bundle_report(payload: dict[str, Any]) -> str:
    """Format compact human-readable output for set-drive-dir, export, and import."""
    mode = payload.get("mode")
    if mode == "set-drive-dir":
        return "\n".join(
            [
                "Gravity Core — Drive Sync Config",
                f"  Gravity Home : {payload.get('gravity_home')}",
                f"  Sync Config  : {payload.get('sync_config_path')}",
                f"  Drive Dir    : {payload.get('drive_dir')}",
            ]
        )
    if mode == "export":
        lines = [
            "Gravity Core — Bundle Export",
            f"  Gravity Home : {payload.get('gravity_home')}",
            f"  Bundle ZIP   : {payload.get('bundle_path')}",
            f"  Files / Size : {payload.get('file_count', 0)} file(s), {payload.get('total_bytes', 0)} bytes",
            f"  Drive Dir    : {payload.get('drive_dir') or 'not configured'}",
            f"  gdrive Plugin: {'detected' if payload.get('gdrive_plugin_detected') else 'not detected'}",
        ]
        ateliers = payload.get("ateliers") or []
        if ateliers:
            lines.append("  Ateliers     : " + ", ".join(a.get("slug", "?") for a in ateliers))
        return "\n".join(lines)
    if mode == "import":
        dry = bool(payload.get("dry_run"))
        lines = [
            f"Gravity Core — Bundle Import ({'dry-run' if dry else 'applied'})",
            f"  Bundle ZIP   : {payload.get('bundle_path')}",
            f"  Gravity Home : {payload.get('gravity_home')}",
            f"  Verified     : {payload.get('file_count', 0)} file(s)",
            f"  Written      : {len(payload.get('written_files') or [])} file(s)",
            f"  Remapped     : {len(payload.get('remapped_paths') or [])} path(s)",
        ]
        for warn in payload.get("warnings") or []:
            lines.append(f"  [WARN] {warn}")
        return "\n".join(lines)
    return json.dumps(payload, indent=2, ensure_ascii=False)

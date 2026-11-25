"""Read-only confined discovery and content reader for `audits/agents/` Markdown files."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Optional, Sequence

from core.registry import resolve_module_home
from dashboard.providers import (
    extract_md_excerpt,
    extract_md_title,
    extract_md_verdict,
    read_json_ro,
)

MAX_AUDIT_HEAD_BYTES = 32_768
MAX_AUDIT_CONTENT_BYTES = 262_144
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")


def is_code_audit_path(root_resolved: Path, file_path: Path, resolved_file: Path) -> bool:
    """Return True if an audit file path sits inside `code/` or `audits/code/`."""
    for candidate in (file_path, resolved_file):
        try:
            rel_parts = candidate.relative_to(root_resolved).parts
        except ValueError:
            return True
        if any(part.lower() == "code" for part in rel_parts[:-1]):
            return True
    dir_parts = [part.lower() for part in resolved_file.parts[:-1]]
    return any(
        dir_parts[idx] == "audits" and dir_parts[idx + 1] == "code"
        for idx in range(len(dir_parts) - 1)
    )


def is_audits_code_dir(path: Path, *, is_direct: bool = False) -> bool:
    """Return True if `path` points to an `audits/code` directory."""
    low_name = path.name.lower()
    if is_direct and low_name == "code":
        return True
    if low_name == "code" and path.parent.name.lower() == "audits":
        return True
    return any(
        path.parts[idx].lower() == "audits" and path.parts[idx + 1].lower() == "code"
        for idx in range(len(path.parts) - 1)
    )


def discover_audit_roots_ro(
    *,
    audits_dirs: Optional[Sequence[Path]],
    session_meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Discover non-symlinked `audits/agents/` directories (excluding `audits/code/`)."""
    candidates: list[tuple[str, Path, bool]] = []
    if audits_dirs is not None:
        for p in audits_dirs:
            candidates.append(("", Path(p).expanduser(), True))
    else:
        env_raw = os.environ.get("GRAVITY_AUDITS_DIR", "").strip()
        if env_raw:
            for part in env_raw.split(os.pathsep):
                clean = part.strip()
                if clean:
                    candidates.append(("", Path(clean).expanduser(), True))
        else:
            seen_cwds: set[str] = set()
            for meta in session_meta.values():
                cwd = str(meta.get("cwd") or "").strip()
                if not cwd:
                    continue
                cwd_key = os.path.normcase(cwd)
                if cwd_key in seen_cwds:
                    continue
                seen_cwds.add(cwd_key)
                ws_path = Path(cwd).expanduser()
                candidates.append((ws_path.name or "workspace", ws_path / "audits" / "agents", False))

    roots: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    used_ids: set[str] = set()

    for ws_hint, raw_root, is_direct in candidates:
        try:
            abs_raw = Path(os.path.abspath(str(raw_root)))
            if is_audits_code_dir(abs_raw, is_direct=is_direct):
                continue
            if raw_root.is_symlink() or not raw_root.is_dir():
                continue
            resolved = raw_root.resolve()
            if is_audits_code_dir(resolved, is_direct=is_direct):
                continue
            if is_direct:
                agents_sub = resolved / "agents"
                if agents_sub.is_dir() and not agents_sub.is_symlink():
                    agents_res = agents_sub.resolve()
                    if is_audits_code_dir(agents_sub) or is_audits_code_dir(agents_res):
                        continue
                    resolved = agents_res
                if resolved.name.lower() == "agents" and resolved.parent.name.lower() == "audits":
                    ws_label = resolved.parent.parent.name or resolved.parent.name or "audits"
                else:
                    ws_label = resolved.parent.name or resolved.name or "audits"
            else:
                ws_label = ws_hint or resolved.parent.parent.name or "workspace"
            key = os.path.normcase(str(resolved))
        except OSError:
            continue

        if key in seen_paths:
            continue
        seen_paths.add(key)

        base_id = re.sub(r"[^a-z0-9._-]+", "-", ws_label.lower()).strip("-") or "audits"
        root_id = base_id
        suffix = 2
        while root_id in used_ids:
            root_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(root_id)

        roots.append({"root_id": root_id, "workspace": ws_label, "path": resolved})
    return roots


def collect_audit_files_ro(roots: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], Path, str]]:
    """Collect regular `.md` files (excluding `_*` and `code/`) under discovered audit roots."""
    discovered: list[tuple[dict[str, Any], Path, str]] = []
    for root in roots:
        root_resolved = root["path"].resolve()
        try:
            candidates = sorted(root_resolved.rglob("*"))
        except OSError:
            continue
        for fpath in candidates:
            try:
                if fpath.is_symlink() or not fpath.is_file() or fpath.suffix.lower() != ".md":
                    continue
                if fpath.name.startswith("_"):
                    continue
                resolved_file = fpath.resolve()
                if resolved_file.name.startswith("_") or not resolved_file.is_relative_to(root_resolved):
                    continue
                if is_code_audit_path(root_resolved, fpath, resolved_file):
                    continue
                rel_posix = resolved_file.relative_to(root_resolved).as_posix()
                discovered.append((root, resolved_file, rel_posix))
            except OSError:
                continue
    return discovered


def build_audits_bundle_ro(
    audit_files: Sequence[tuple[dict[str, Any], Path, str]],
) -> dict[str, Any]:
    """Build compact audit summaries separated into regular audits and `README.md` indexes."""
    regular: list[dict[str, Any]] = []
    index_audits: list[dict[str, Any]] = []

    for root, resolved_file, rel_posix in audit_files:
        try:
            st = resolved_file.stat()
            with resolved_file.open("rb") as fh:
                raw = fh.read(MAX_AUDIT_HEAD_BYTES)
        except OSError:
            continue
        text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
        updated_at = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_m = _DATE_PREFIX_RE.match(resolved_file.name)
        date_str = date_m.group(1) if date_m else updated_at[:10]
        verdict, verdict_tone = extract_md_verdict(text)

        entry = {
            "audit_id": f"{root['root_id']}:{rel_posix}",
            "workspace": root["workspace"],
            "rel_path": rel_posix,
            "title": extract_md_title(text, resolved_file.stem),
            "verdict": verdict,
            "verdict_tone": verdict_tone,
            "date": date_str,
            "updated_at": updated_at,
            "size_bytes": int(st.st_size),
            "excerpt": extract_md_excerpt(text),
            "uri": resolved_file.as_uri(),
        }
        if rel_posix.lower() == "readme.md":
            index_audits.append(entry)
        else:
            regular.append(entry)

    index_audits.sort(
        key=lambda a: (str(a.get("workspace") or "").casefold(), str(a.get("rel_path") or "").casefold())
    )
    regular.sort(
        key=lambda a: (str(a.get("date") or ""), str(a.get("updated_at") or ""), str(a.get("rel_path") or "")),
        reverse=True,
    )
    return {
        "audits": regular,
        "index_audit": index_audits[0] if index_audits else None,
        "index_audits": index_audits,
    }


def read_audit_content_ro(
    target: str,
    *,
    gravity_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    audits_dirs: Optional[Sequence[Path]] = None,
    session_meta: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Read full Markdown content of an `audits/agents/` file with strict path confinement."""
    clean = str(target or "").strip()
    if not clean or "\x00" in clean:
        return {"found": False, "error": "Audit path or ID is required."}

    norm_clean = clean.replace("\\", "/")
    if ".." in norm_clean.split("/"):
        return {"found": False, "error": "Path traversal is forbidden."}

    if session_meta is None:
        m_home = (
            Path(metrics_home).expanduser().resolve()
            if metrics_home is not None
            else resolve_module_home("metrics", env_override="GRAVITY_METRICS_HOME", gravity_home=gravity_home)
        )
        raw_meta, _ = read_json_ro(m_home / "session_meta.json")
        bucket = raw_meta.get("sessions") if isinstance(raw_meta, dict) else None
        session_meta = {
            str(k): dict(v)
            for k, v in (bucket or {}).items()
            if isinstance(k, str) and isinstance(v, dict)
        }

    roots = discover_audit_roots_ro(audits_dirs=audits_dirs, session_meta=session_meta)
    if not roots:
        return {"found": False, "error": "No audits/agents directories discovered."}

    audit_files = collect_audit_files_ro(roots)
    matched: Optional[tuple[dict[str, Any], Path, str]] = None

    for item in audit_files:
        root, resolved_file, rel_posix = item
        aid = f"{root['root_id']}:{rel_posix}"
        if clean == aid or norm_clean == rel_posix:
            matched = item
            break
        try:
            if Path(clean).expanduser().resolve() == resolved_file:
                matched = item
                break
        except OSError:
            continue

    if matched is None:
        return {"found": False, "target": clean, "error": "Audit file not found or outside confined roots."}

    root, resolved_file, rel_posix = matched
    try:
        st = resolved_file.stat()
        with resolved_file.open("rb") as fh:
            raw = fh.read(MAX_AUDIT_CONTENT_BYTES + 1)
    except OSError as exc:
        return {"found": False, "target": clean, "error": f"Failed to read audit file: {exc}"}

    truncated = len(raw) > MAX_AUDIT_CONTENT_BYTES
    if truncated:
        raw = raw[:MAX_AUDIT_CONTENT_BYTES]
    text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
    verdict, verdict_tone = extract_md_verdict(text)
    updated_at = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_m = _DATE_PREFIX_RE.match(resolved_file.name)

    return {
        "found": True,
        "audit_id": f"{root['root_id']}:{rel_posix}",
        "workspace": root["workspace"],
        "rel_path": rel_posix,
        "title": extract_md_title(text, resolved_file.stem),
        "verdict": verdict,
        "verdict_tone": verdict_tone,
        "date": date_m.group(1) if date_m else updated_at[:10],
        "updated_at": updated_at,
        "size_bytes": int(st.st_size),
        "truncated": truncated,
        "content": text,
        "uri": resolved_file.as_uri(),
    }

"""Read-only Gravity Metrics & Audits Agents provider for the Gravity dashboard."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Optional, Sequence

from core.registry import resolve_module_home
from dashboard.providers import (
    enforce_payload_budget,
    extract_md_excerpt,
    extract_md_title,
    extract_md_verdict,
    file_uri_if_exists,
    open_sqlite_ro,
    read_json_ro,
    short_digest,
    stat_token,
    unchanged_response,
)

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_PAYLOAD_BYTES = 450_000
MAX_AUDIT_HEAD_BYTES = 32_768
MAX_AGENTS_IN_DETAIL = 200

_HEX_PREFIX_RE = re.compile(r"^[0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{0,4}){0,4}$")
_SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
_TRAJECTORY_KEYS = frozenset(
    {
        "trajectory",
        "raw_trajectory",
        "steps",
        "transcript",
        "raw_transcript",
        "messages",
        "events_raw",
    }
)


def _clamp_limit(limit: int) -> int:
    try:
        val = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, val))


def _slugify_fallback(label: str, cid: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", label.strip().lower()).strip("-")
    if base:
        return base[:80]
    return f"session-{cid[:8]}" if cid else "session"


def _load_history_ro(history_path: Path, warnings: list[str]) -> list[dict[str, Any]]:
    if not history_path.is_file() or history_path.is_symlink():
        return []
    try:
        text = history_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"Failed to read history.jsonl: {exc}")
        return []

    records: list[dict[str, Any]] = []
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.lstrip("\ufeff").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            warnings.append(f"Ignored corrupted JSONL line {idx} in history.jsonl.")
            continue
        if not isinstance(obj, dict) or not obj.get("conversation_id"):
            warnings.append(f"Ignored invalid history.jsonl record at line {idx}.")
            continue
        rec = dict(obj)
        if not rec.get("status"):
            rec["status"] = "archived"
        if rec.get("bridge_children_count") is None:
            rec["bridge_children_count"] = 0
        if not rec.get("detail_slug"):
            rec["detail_slug"] = _slugify_fallback(
                str(rec.get("label") or ""),
                str(rec.get("conversation_id") or ""),
            )
        records.append(rec)
    return records


def _load_state_map_ro(
    path: Path,
    top_key: str,
    warnings: list[str],
) -> dict[str, dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        return {}
    data, read_warn = read_json_ro(path)
    if read_warn:
        warnings.append(read_warn)
    if not isinstance(data, dict):
        if data is not None:
            warnings.append(f"Invalid structure in {path.name}: expected JSON object.")
        return {}
    bucket = data.get(top_key)
    if not isinstance(bucket, dict):
        return {}
    return {
        str(k): dict(v)
        for k, v in bucket.items()
        if isinstance(k, str) and k.strip() and isinstance(v, dict)
    }


def _canonical_projects_map(records: Sequence[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for rec in records:
        proj = str(rec.get("project") or "").strip()
        if proj:
            grouped[proj.casefold()][proj] += 1
    return {
        cf: min(counts.items(), key=lambda kv: (-kv[1], kv[0] != kv[0].lower(), kv[0]))[0]
        for cf, counts in grouped.items()
    }


def _collect_projects(records: Sequence[dict[str, Any]]) -> list[str]:
    return sorted(_canonical_projects_map(records).values(), key=lambda s: (s.casefold(), s))


def _aggregate_by_project(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    proj_map = _canonical_projects_map(records)
    buckets: dict[str, dict[str, Any]] = {}
    total_2026 = 0.0
    total_2027 = 0.0

    for rec in records:
        raw_p = str(rec.get("project") or "").strip()
        canon_p = proj_map.get(raw_p.casefold(), raw_p) if raw_p else "(sans projet)"
        key = canon_p.casefold()
        if key not in buckets:
            buckets[key] = {
                "project": canon_p,
                "sessions": 0,
                "cost_usd": 0.0,
                "cost_2027_usd": 0.0,
                "cache_sum": 0.0,
                "llm_calls": 0,
                "agents": 0,
                "wall_clock_s": 0.0,
                "bridge_sessions": 0,
            }
        b = buckets[key]
        c26 = float(rec.get("cost_usd") or 0.0)
        raw_27 = rec.get("cost_2027_usd")
        c27 = float(raw_27) if raw_27 is not None else c26
        b["sessions"] += 1
        b["cost_usd"] += c26
        b["cost_2027_usd"] += c27
        b["cache_sum"] += float(rec.get("cache_hit_rate_pct") or 0.0)
        b["llm_calls"] += int(rec.get("llm_calls") or 0)
        b["agents"] += int(rec.get("agents") or 0)
        b["wall_clock_s"] += float(rec.get("wall_clock_s") or 0.0)
        if int(rec.get("bridge_children_count") or 0) > 0:
            b["bridge_sessions"] += 1
        total_2026 += c26
        total_2027 += c27

    out: list[dict[str, Any]] = []
    for b in buckets.values():
        sess = b["sessions"]
        out.append(
            {
                "project": b["project"],
                "sessions": sess,
                "cost_usd": round(b["cost_usd"], 6),
                "cost_2027_usd": round(b["cost_2027_usd"], 6),
                "share_pct": round((b["cost_usd"] / total_2026) * 100.0, 2) if total_2026 > 0 else 0.0,
                "share_2027_pct": round((b["cost_2027_usd"] / total_2027) * 100.0, 2) if total_2027 > 0 else 0.0,
                "avg_cache_hit_rate_pct": round(b["cache_sum"] / sess, 2) if sess > 0 else 0.0,
                "llm_calls": b["llm_calls"],
                "agents": b["agents"],
                "wall_clock_s": round(b["wall_clock_s"], 2),
                "bridge_sessions": b["bridge_sessions"],
            }
        )
    out.sort(key=lambda item: (-item["cost_usd"], -item["sessions"], item["project"].casefold()))
    return out


def _compute_kpis(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    sessions_count = len(records)
    archived_count = sum(
        1 for r in records if str(r.get("status") or "archived").strip().lower() == "archived"
    )
    active_count = sum(
        1 for r in records if str(r.get("status") or "").strip().lower() == "active"
    )
    cost_usd = sum(float(r.get("cost_usd") or 0.0) for r in records)
    cost_2027_usd = sum(
        float(r["cost_2027_usd"]) if r.get("cost_2027_usd") is not None else float(r.get("cost_usd") or 0.0)
        for r in records
    )
    cache_savings_usd = sum(float(r.get("cache_savings_usd") or 0.0) for r in records)
    cache_sum = sum(float(r.get("cache_hit_rate_pct") or 0.0) for r in records)
    total_tokens = sum(int(r.get("total_tokens") or 0) for r in records)
    total_llm_calls = sum(int(r.get("llm_calls") or 0) for r in records)
    bridge_sessions_count = sum(1 for r in records if int(r.get("bridge_children_count") or 0) > 0)
    bridge_children_total = sum(int(r.get("bridge_children_count") or 0) for r in records)

    return {
        "sessions_count": sessions_count,
        "archived_count": archived_count,
        "active_count": active_count,
        "cost_usd": round(cost_usd, 6),
        "cost_2027_usd": round(cost_2027_usd, 6),
        "cache_savings_usd": round(cache_savings_usd, 6),
        "avg_cache_hit_rate_pct": round(cache_sum / sessions_count, 2) if sessions_count > 0 else 0.0,
        "total_tokens": total_tokens,
        "total_llm_calls": total_llm_calls,
        "bridge_sessions_count": bridge_sessions_count,
        "bridge_children_total": bridge_children_total,
    }


def _matches_query(rec: dict[str, Any], q_cf: str) -> bool:
    if not q_cf:
        return True
    for field in (
        "label",
        "project",
        "conversation_id",
        "note",
        "primary_model",
        "execution_mode",
        "current_phase",
    ):
        val = rec.get(field)
        if isinstance(val, str) and q_cf in val.casefold():
            return True
    return False


def _resolve_bridge_db_path(
    *,
    gravity_home: Optional[Path] = None,
    bridge_home: Optional[Path] = None,
) -> Path:
    """Resolve `bridge.db` (`$GRAVITY_BRIDGE_HOME` > `$GRAVITY_HOME/bridge` > `~/.gemini/gravity/bridge`)."""
    b_home = (
        Path(bridge_home).expanduser().resolve()
        if bridge_home is not None
        else resolve_module_home("bridge", env_override="GRAVITY_BRIDGE_HOME", gravity_home=gravity_home)
    )
    return (b_home / "bridge.db").resolve()


def _load_bridge_roles_ro(
    bridge_db_path: Path,
    warnings: list[str],
) -> tuple[set[str], set[str]]:
    """Load `(caller_ids, target_ids)` strictly read-only from `bridge.db`."""
    caller_ids: set[str] = set()
    target_ids: set[str] = set()
    conn = open_sqlite_ro(bridge_db_path, warnings)
    if conn is None:
        return caller_ids, target_ids
    try:
        t_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
        t_sel = [c for c in ("caller_conversation_id", "target_conversation_id") if c in t_cols]
        if t_sel:
            for row in conn.execute(f"SELECT {', '.join(t_sel)} FROM threads").fetchall():
                if "caller_conversation_id" in t_cols:
                    val = str(row["caller_conversation_id"] or "").strip()
                    if val:
                        caller_ids.add(val)
                if "target_conversation_id" in t_cols:
                    val = str(row["target_conversation_id"] or "").strip()
                    if val:
                        target_ids.add(val)

        j_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        j_sel = [c for c in ("target_conversation_id", "caller_conversation_id") if c in j_cols]
        if j_sel:
            clauses = []
            if "direction" in j_cols:
                clauses.append("LOWER(COALESCE(direction, '')) != 'callback'")
            if "action" in j_cols:
                clauses.append("LOWER(COALESCE(action, '')) != 'send_message'")
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            for row in conn.execute(f"SELECT {', '.join(j_sel)} FROM jobs{where}").fetchall():
                if "target_conversation_id" in j_cols:
                    val = str(row["target_conversation_id"] or "").strip()
                    if val:
                        target_ids.add(val)
                if "caller_conversation_id" in j_cols:
                    val = str(row["caller_conversation_id"] or "").strip()
                    if val:
                        caller_ids.add(val)
    except sqlite3.Error as exc:
        warnings.append(f"Bridge SQLite read-only query failed in {bridge_db_path.name}: {exc}")
    finally:
        conn.close()
    return caller_ids, target_ids


def _is_worktree_cwd(cwd: Any) -> bool:
    """Return True if `cwd` points inside an Antigravity worktree directory."""
    if not isinstance(cwd, str) or not cwd.strip():
        return False
    low = cwd.strip().casefold()
    norm = low.replace("\\", "/")
    return (
        "/.gemini/antigravity/worktrees/" in norm
        or norm.endswith("/.gemini/antigravity/worktrees")
        or "\\worktrees\\" in low
        or low.endswith("\\worktrees")
    )


def _derive_pending_states_ro(
    *,
    records: Sequence[dict[str, Any]],
    active_captures: dict[str, dict[str, Any]],
    ignored_map: dict[str, dict[str, Any]],
    session_meta: dict[str, dict[str, Any]],
    bridge_callers: Optional[set[str]] = None,
    bridge_targets: Optional[set[str]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive pending and ignored lifecycle entries strictly from metrics/Bridge state (no brain scan)."""
    archived_cids = {
        str(r.get("conversation_id") or "").strip()
        for r in records
        if str(r.get("status") or "archived").strip().lower() == "archived"
    }
    active_history_by_cid: dict[str, dict[str, Any]] = {}
    for rec in records:
        cid = str(rec.get("conversation_id") or "").strip()
        if cid and str(rec.get("status") or "").strip().lower() == "active":
            active_history_by_cid[cid] = rec

    callers = {str(c).strip() for c in (bridge_callers or set()) if str(c).strip()}
    targets = {str(c).strip() for c in (bridge_targets or set()) if str(c).strip()}

    candidate_cids = (
        set(active_captures.keys())
        | set(ignored_map.keys())
        | set(active_history_by_cid.keys())
        | (callers - targets)
    ) - archived_cids - targets

    pending: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []

    for cid in sorted(candidate_cids):
        if not cid:
            continue
        cap = active_captures.get(cid)
        ign = ignored_map.get(cid)
        meta = session_meta.get(cid) or {}
        if cid not in active_captures and _is_worktree_cwd(meta.get("cwd")):
            continue
        hist_active = active_history_by_cid.get(cid) or {}

        item = {
            "conversation_id": cid,
            "label": str(
                (cap or {}).get("label") or hist_active.get("label") or f"session-{cid[:8]}"
            ),
            "project": str(
                (cap or {}).get("project") or meta.get("project") or hist_active.get("project") or ""
            ),
            "cwd": str(meta.get("cwd") or ""),
            "started_at": str(
                (cap or {}).get("started_at")
                or meta.get("started_at")
                or hist_active.get("started_at")
                or ""
            ),
            "updated_at": str(
                (cap or {}).get("updated_at")
                or meta.get("updated_at")
                or hist_active.get("ended_at")
                or ""
            ),
            "active_capture": cap is not None,
            "start_step": (cap or {}).get("start_step")
            if isinstance((cap or {}).get("start_step"), int)
            else None,
            "ignored": ign is not None,
            "ignored_reason": str((ign or {}).get("reason") or ""),
            "ignored_at": str((ign or {}).get("ignored_at") or ""),
            "current_phase": str(hist_active.get("current_phase") or ""),
            "llm_calls": int(hist_active.get("llm_calls") or 0),
            "bridge_children_count": int(hist_active.get("bridge_children_count") or 0),
        }
        if item["ignored"]:
            ignored.append(item)
        else:
            pending.append(item)

    sort_key = lambda entry: (str(entry.get("updated_at") or ""), str(entry.get("conversation_id") or ""))
    pending.sort(key=sort_key, reverse=True)
    ignored.sort(key=sort_key, reverse=True)
    return pending, ignored


def _is_code_audit_path(root_resolved: Path, file_path: Path, resolved_file: Path) -> bool:
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


def _is_audits_code_dir(path: Path, *, is_direct: bool = False) -> bool:
    low_name = path.name.lower()
    if is_direct and low_name == "code":
        return True
    if low_name == "code" and path.parent.name.lower() == "audits":
        return True
    return any(
        path.parts[idx].lower() == "audits" and path.parts[idx + 1].lower() == "code"
        for idx in range(len(path.parts) - 1)
    )


def _discover_audit_roots_ro(
    *,
    audits_dirs: Optional[Sequence[Path]],
    session_meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
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
            if _is_audits_code_dir(abs_raw, is_direct=is_direct):
                continue
            if raw_root.is_symlink() or not raw_root.is_dir():
                continue
            resolved = raw_root.resolve()
            if _is_audits_code_dir(resolved, is_direct=is_direct):
                continue
            if is_direct:
                agents_sub = resolved / "agents"
                if agents_sub.is_dir() and not agents_sub.is_symlink():
                    agents_res = agents_sub.resolve()
                    if _is_audits_code_dir(agents_sub) or _is_audits_code_dir(agents_res):
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


def _collect_audit_files_ro(roots: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], Path, str]]:
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
                if _is_code_audit_path(root_resolved, fpath, resolved_file):
                    continue
                rel_posix = resolved_file.relative_to(root_resolved).as_posix()
                discovered.append((root, resolved_file, rel_posix))
            except OSError:
                continue
    return discovered


def _build_audits_bundle_ro(
    audit_files: Sequence[tuple[dict[str, Any], Path, str]],
) -> dict[str, Any]:
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


def get_metrics_state(
    project: str = "",
    limit: int = DEFAULT_LIMIT,
    q: str = "",
    since_signature: str = "",
    *,
    gravity_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
    bridge_home: Optional[Path] = None,
    audits_dirs: Optional[Sequence[Path]] = None,
) -> dict[str, Any]:
    """Return read-only Gravity Metrics KPIs, filtered history, lifecycle state, and agents audits."""
    m_home = (
        Path(metrics_home).expanduser().resolve()
        if metrics_home is not None
        else resolve_module_home("metrics", env_override="GRAVITY_METRICS_HOME", gravity_home=gravity_home)
    )
    eff_limit = _clamp_limit(limit)
    project_clean = project.strip()
    q_clean = q.strip()

    history_path = m_home / "data" / "history.jsonl"
    active_captures_path = m_home / "active_captures.json"
    ignored_path = m_home / "ignored.json"
    session_meta_path = m_home / "session_meta.json"
    metrics_md_path = m_home / "METRICS.md"
    bridge_db_path = _resolve_bridge_db_path(gravity_home=gravity_home, bridge_home=bridge_home)
    bridge_wal_path = Path(f"{bridge_db_path}-wal")
    bridge_shm_path = Path(f"{bridge_db_path}-shm")

    warnings: list[str] = []
    session_meta = _load_state_map_ro(session_meta_path, "sessions", warnings)
    audit_roots = _discover_audit_roots_ro(audits_dirs=audits_dirs, session_meta=session_meta)
    audit_files = _collect_audit_files_ro(audit_roots)

    def _compute_sig() -> str:
        return short_digest(
            [
                str(m_home),
                str(bridge_db_path),
                project_clean.casefold(),
                eff_limit,
                q_clean.casefold(),
                stat_token(history_path),
                stat_token(active_captures_path),
                stat_token(ignored_path),
                stat_token(session_meta_path),
                stat_token(metrics_md_path),
                stat_token(bridge_db_path),
                stat_token(bridge_wal_path),
                stat_token(bridge_shm_path),
                *[(f"{r['root_id']}:{rel}", stat_token(fpath)) for r, fpath, rel in audit_files],
            ]
        )

    pre_sig = _compute_sig()
    if since_signature and since_signature == pre_sig:
        return unchanged_response(pre_sig)

    all_records = _load_history_ro(history_path, warnings)
    active_captures = _load_state_map_ro(active_captures_path, "captures", warnings)
    ignored_map = _load_state_map_ro(ignored_path, "ignored", warnings)
    bridge_callers, bridge_targets = _load_bridge_roles_ro(bridge_db_path, warnings)
    # Recompute after closing SQLite so WAL/SHM attachment on initial RO read is reflected in `signature`.
    sig = _compute_sig()

    proj_cf = project_clean.casefold()
    q_cf = q_clean.casefold()
    filtered = [
        rec
        for rec in all_records
        if (not proj_cf or str(rec.get("project") or "").strip().casefold() == proj_cf)
        and _matches_query(rec, q_cf)
    ]

    kpis = _compute_kpis(filtered)
    projects = _collect_projects(all_records)
    by_project = _aggregate_by_project(filtered)
    pending_sessions, ignored_sessions = _derive_pending_states_ro(
        records=all_records,
        active_captures=active_captures,
        ignored_map=ignored_map,
        session_meta=session_meta,
        bridge_callers=bridge_callers,
        bridge_targets=bridge_targets,
    )
    audits_bundle = _build_audits_bundle_ro(audit_files)
    records_page = list(reversed(filtered))[:eff_limit]

    payload: dict[str, Any] = {
        "changed": True,
        "unchanged": False,
        "signature": sig,
        "metrics_home": str(m_home),
        "metrics_md_uri": file_uri_if_exists(metrics_md_path),
        "filters": {"project": project_clean, "limit": eff_limit, "q": q_clean},
        "total_records": len(all_records),
        "total_matching": len(filtered),
        "truncated": False,
        "kpis": kpis,
        "projects": projects,
        "by_project": by_project,
        "records": records_page,
        "active_captures": active_captures,
        "pending_sessions": pending_sessions,
        "ignored_sessions": ignored_sessions,
        "audits": audits_bundle["audits"],
        "index_audit": audits_bundle["index_audit"],
        "index_audits": audits_bundle["index_audits"],
        "warnings": warnings,
    }
    return enforce_payload_budget(
        payload,
        ("records", "audits", "pending_sessions", "ignored_sessions"),
        max_bytes=MAX_PAYLOAD_BYTES,
    )


def _resolve_target_record(
    records: Sequence[dict[str, Any]],
    target: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    clean = target.strip()
    if not clean:
        return None, "Target is required."

    for rec in records:
        if str(rec.get("detail_slug") or "") == clean:
            return rec, None

    for rec in records:
        if str(rec.get("label") or "").strip() == clean:
            return rec, None
    cf = clean.casefold()
    label_hits = [rec for rec in records if str(rec.get("label") or "").strip().casefold() == cf]
    if len(label_hits) == 1:
        return label_hits[0], None
    if len(label_hits) > 1:
        return label_hits[-1], None

    low = clean.lower()
    for rec in records:
        if str(rec.get("conversation_id") or "").strip().lower() == low:
            return rec, None

    if len(clean) >= 8 and _HEX_PREFIX_RE.match(clean):
        cid_matches: dict[str, dict[str, Any]] = {}
        for rec in records:
            cid = str(rec.get("conversation_id") or "").strip()
            if cid.lower().startswith(low):
                cid_matches[cid] = rec
        if len(cid_matches) == 1:
            return next(iter(cid_matches.values())), None
        if len(cid_matches) > 1:
            return None, f"Ambiguous conversation_id prefix {target!r}."

    return None, f"Session not found: {target!r}."


def _strip_raw_trajectories(data: Any) -> Any:
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            if k in _TRAJECTORY_KEYS:
                continue
            if k == "agents" and isinstance(v, list):
                cleaned[k] = [
                    {ak: av for ak, av in ag.items() if ak not in _TRAJECTORY_KEYS}
                    if isinstance(ag, dict)
                    else ag
                    for ag in v[:MAX_AGENTS_IN_DETAIL]
                ]
            else:
                cleaned[k] = v
        return cleaned
    return data


def _confined_report_file(reports_dir: Path, filename: str) -> Optional[Path]:
    if "/" in filename or "\\" in filename or "\x00" in filename or ".." in filename:
        return None
    candidate = reports_dir / filename
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(reports_dir) or resolved.parent != reports_dir:
        return None
    return resolved


def get_session_detail(
    target: str,
    *,
    gravity_home: Optional[Path] = None,
    metrics_home: Optional[Path] = None,
) -> dict[str, Any]:
    """Return read-only session detail from `reports/<slug>.json` (no raw trajectories) or `history.jsonl`."""
    clean_target = str(target or "").strip()
    if not clean_target:
        return {"found": False, "error": "Target is required."}

    m_home = (
        Path(metrics_home).expanduser().resolve()
        if metrics_home is not None
        else resolve_module_home("metrics", env_override="GRAVITY_METRICS_HOME", gravity_home=gravity_home)
    )
    warnings: list[str] = []
    records = _load_history_ro(m_home / "data" / "history.jsonl", warnings)
    rec, err = _resolve_target_record(records, clean_target)
    if rec is None:
        return {"found": False, "target": clean_target, "error": err or "Session not found.", "warnings": warnings}

    cid = str(rec.get("conversation_id") or "")
    label = str(rec.get("label") or cid[:8])
    slug = str(rec.get("detail_slug") or _slugify_fallback(label, cid)).strip()

    reports_dir = (m_home / "reports").resolve()
    detail_data: dict[str, Any] = dict(rec)
    source = "history_fallback"
    report_md_uri = ""

    if not _SAFE_SLUG_RE.match(slug):
        warnings.append(f"Unsafe detail_slug {slug!r} ignored; using history fallback.")
    elif reports_dir.is_dir():
        json_path = _confined_report_file(reports_dir, f"{slug}.json")
        if json_path is None:
            warnings.append(f"Confined report path check failed for {slug!r}; using history fallback.")
        elif json_path.is_file():
            loaded, read_warn = read_json_ro(json_path)
            if read_warn:
                warnings.append(read_warn)
            if isinstance(loaded, dict):
                detail_data = _strip_raw_trajectories(loaded)
                source = "report_json"
            elif loaded is not None:
                warnings.append(f"Invalid structure in {json_path.name}; using history fallback.")

        md_path = _confined_report_file(reports_dir, f"{slug}.md")
        if md_path is not None:
            report_md_uri = file_uri_if_exists(md_path)

    result: dict[str, Any] = {
        "found": True,
        "source": source,
        "target": clean_target,
        "slug": slug,
        "conversation_id": cid,
        "label": label,
        "report_md_uri": report_md_uri,
        "detail": detail_data,
        "record": rec,
        "warnings": warnings,
    }
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) >= MAX_PAYLOAD_BYTES:
        if isinstance(detail_data.get("agents"), list):
            detail_data["agents"] = detail_data["agents"][:20]
    return result

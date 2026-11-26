"""Read-only incremental live session provider scanning Antigravity brain/ and workflow state."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Optional, Sequence

from _shared.path_safety import is_symlink_or_junction
from _shared.signal_bus import list_topic_signals
from _shared.transcript_reader import (
    extract_shell_nonzero_code, is_worktree_path, normalize_worktree_path,
    parse_iso_ts, read_jsonl_incremental, strip_file_uri,
)
from core.registry import resolve_module_home
from dashboard.providers import (
    enforce_payload_budget, read_json_ro, short_digest, stat_token, truncate_preview, unchanged_response,
)
from dashboard.providers.live_progress import (
    build_live_progress, collect_descendant_sig_tokens, collect_wf_refs_from_obj,
    discover_live_tree, find_cycle_root_overrides, parse_wf_agent_refs,
    read_workflow_live_c8_ro, update_termination_acc,
)
from dashboard.providers.spi import invoke_dashboard_provider, resolve_dashboard_provider

MAX_ROOT_SESSIONS, MAX_AGENT_EVENTS, MAX_BOARD_EVENTS, MAX_RECENT_EVENTS = 25, 25, 30, 80
MAX_PAYLOAD_BYTES, MAX_CACHE_ENTRIES = 450_000, 256
LIVE_RECENT_WINDOW_S = 6 * 3600

_WORKTREE_SUFFIX_RE = re.compile(r"-w\d+$", re.IGNORECASE)
_REPO_MARKER_RE = re.compile(
    r"/([^/]+)/(?:plugin|src|tests|specs|tasks|docs|scripts|config|audits|assets|tracking|dashboard|templates|archives|README\.md|AGENTS\.md|CHANGELOG\.md)(?:/|$)"
)
_CMD_CD_RE = re.compile(r"(?:^|[;&|]\s*)(?:cd|git\s+-C)\s+[\"']?([^\s\"';&|]+)", re.IGNORECASE)
_UUID_LIKE_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{12,}$|^[A-Za-z0-9._-]{4,80}$")

_TRANSCRIPT_CACHE: dict[str, dict[str, Any]] = {}
_BOARD_CACHE: dict[str, dict[str, Any]] = {}
_JSON_CACHE: dict[str, dict[str, Any]] = {}
_WF_CHILD_CACHE: dict[str, tuple[Any, ...]] = {}
_CACHE_STATS: dict[str, int] = {"bytes_read": 0, "incremental_reads": 0, "full_reads": 0, "cache_hits": 0}


def reset_live_cache() -> None:
    """Clear in-memory incremental caches and counters."""
    for cache in (_TRANSCRIPT_CACHE, _BOARD_CACHE, _JSON_CACHE, _WF_CHILD_CACHE):
        cache.clear()
    for k in _CACHE_STATS:
        _CACHE_STATS[k] = 0


def get_live_cache_stats() -> dict[str, int]:
    """Return a copy of incremental read counters."""
    return dict(_CACHE_STATS)


def _cache_put(cache: dict[Any, Any], key: Any, val: Any) -> None:
    while len(cache) >= MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)), None)
    cache[key] = val


def _normalize_repo_name(raw_path: str, root_parent: Optional[Path] = None) -> str:
    cleaned = strip_file_uri(raw_path).replace("\\", "/").strip()
    if not cleaned:
        return ""
    if is_worktree_path(cleaned):
        wt_repo = normalize_worktree_path(cleaned, root_workspace_path=root_parent)
        if wt_repo:
            return wt_repo
    if root_parent is not None:
        parent_posix = str(root_parent).replace("\\", "/").rstrip("/")
        prefix = parent_posix + "/"
        if parent_posix and cleaned[: len(prefix)].casefold() == prefix.casefold():
            rest = cleaned[len(prefix) :].split("/", 1)[0]
            if rest:
                return _WORKTREE_SUFFIX_RE.sub("", rest) if "worktree" in parent_posix.lower() else rest
    shared_repo = normalize_worktree_path(cleaned, root_workspace_path=root_parent)
    if shared_repo:
        return shared_repo
    marker_m = _REPO_MARKER_RE.search(cleaned)
    if marker_m:
        return marker_m.group(1)
    p = Path(cleaned.rstrip("/"))
    return p.parent.name if (p.suffix and p.parent.name) else p.name


def _classify_workspace_kind(ws_name: str, ws_path: str = "", root_ws: str = "") -> str:
    low = ws_name.strip().lower()
    if low == "gravity-workshop" or low.endswith("-workshop"):
        return "atelier"
    if ws_path:
        p = Path(strip_file_uri(ws_path))
        if p.is_dir() and not is_symlink_or_junction(p) and ((p / "projects.json").is_file() or (p / "specs").is_dir()):
            return "atelier"
    return "code"


def _read_json_cached(path: Path) -> Any:
    try:
        if is_symlink_or_junction(path) or not path.is_file():
            return None
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    cached = _JSON_CACHE.get(key)
    if cached and cached["inode"] == st.st_ino and cached["size"] == st.st_size and cached["mtime_ns"] == st.st_mtime_ns:
        _CACHE_STATS["cache_hits"] += 1
        return cached["data"]
    data, _ = read_json_ro(path)
    _CACHE_STATS["bytes_read"] += int(st.st_size)
    _CACHE_STATS["full_reads"] += 1
    _cache_put(_JSON_CACHE, key, {"inode": st.st_ino, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "data": data})
    return data


def _read_jsonl_incremental(
    path: Path, cache: dict[str, dict[str, Any]], make_state: Callable[[], Any], apply_line: Callable[[Any, dict[str, Any]], None]
) -> Any:
    return read_jsonl_incremental(path, cache, make_state, apply_line, max_cache_entries=MAX_CACHE_ENTRIES, stats=_CACHE_STATS)


def _new_transcript_acc() -> dict[str, Any]:
    return {
        "first_ts": "", "last_ts": "", "last_step_index": -1, "model": "",
        "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0, "context_tokens": 0,
        "max_context_tokens": 0, "thinking_chars": 0, "llm_calls": 0, "tool_calls": 0, "error_count": 0,
        "last_tool": "", "last_status": "", "write_paths": Counter(), "read_paths": Counter(), "recent_events": [],
        "last_non_sys_type": "", "last_non_sys_status": "", "last_non_sys_shell_nonzero": False,
        "last_planner_status": "", "last_planner_has_tools": False, "last_planner_terminal_tool": "",
        "trailing_after_planner_count": 0, "trailing_after_planner_all_clean_generic": False, "wf_child_refs": {},
    }


def _extract_tool_paths(name: str, args: Any, acc: dict[str, Any]) -> None:
    if not isinstance(args, dict):
        return
    lname = name.lower()
    if lname in ("edit_file", "write_file", "replace_file_content", "multi_replace_file_content", "write_to_file"):
        keys, bucket = ("Path", "path", "TargetFile", "file_path"), "write_paths"
    elif lname in ("run_command", "execute_command"):
        for m in _CMD_CD_RE.finditer(str(args.get("CommandLine") or args.get("command") or "")):
            acc["write_paths"][m.group(1)] += 1
        keys, bucket = ("Cwd", "cwd"), "write_paths"
    elif lname in ("read_file", "view_file", "grep_search", "find_by_name", "list_dir"):
        keys, bucket = ("Path", "path", "AbsolutePath", "SearchPath", "DirectoryPath", "SearchDirectory"), "read_paths"
    else:
        return
    for k in keys:
        if isinstance(args.get(k), str) and args[k].strip():
            acc[bucket][args[k].strip().strip("\"'")] += 1
            return


def _apply_transcript_obj(acc: dict[str, Any], obj: dict[str, Any], agent_id: str, *, parent_cid: str = "") -> None:
    ts = str(obj.get("created_at") or "").strip()
    if ts:
        acc["first_ts"], acc["last_ts"] = acc["first_ts"] or ts, ts
    step_idx = obj.get("step_index")
    clean_step = step_idx if (isinstance(step_idx, int) and not isinstance(step_idx, bool)) else None
    if clean_step is not None:
        acc["last_step_index"] = max(acc["last_step_index"], clean_step)
    step_type, status = str(obj.get("type") or "").strip(), str(obj.get("status") or "").strip()
    status_up = status.upper()
    if status:
        acc["last_status"] = status
    if status_up in ("ERROR", "INVALID", "FAILED"):
        acc["error_count"] += 1
        acc["recent_events"].append({"ts": ts, "agent_id": agent_id, "kind": "error", "name": step_type or "STEP", "detail": status})
    shell_nonzero = False
    if step_type == "GENERIC" and status_up not in ("ERROR", "INVALID", "FAILED"):
        shell_code = extract_shell_nonzero_code(obj.get("content"))
        if shell_code is not None:
            shell_nonzero = True
            acc["error_count"] += 1
            acc["recent_events"].append({"ts": ts, "agent_id": agent_id, "kind": "error", "name": "GENERIC", "detail": f"shell exit={shell_code}"})
    update_termination_acc(acc, obj, step_type, status, shell_nonzero)
    collect_wf_refs_from_obj(obj, parent_cid, clean_step, acc["wf_child_refs"])
    if step_type == "PLANNER_RESPONSE":
        acc["llm_calls"] += 1
        if str(obj.get("model") or "").strip():
            acc["model"] = str(obj.get("model")).strip()
        in_t, cache_t, out_t = max(0, int(obj.get("input_tokens") or 0)), max(0, int(obj.get("cache_read_tokens") or 0)), max(0, int(obj.get("output_tokens") or 0))
        acc["input_tokens"] += in_t; acc["cache_read_tokens"] += cache_t; acc["output_tokens"] += out_t
        if (in_t + cache_t) > 0:
            acc["context_tokens"], acc["max_context_tokens"] = in_t + cache_t, max(acc["max_context_tokens"], in_t + cache_t)
        if isinstance(obj.get("thinking"), str):
            acc["thinking_chars"] += len(obj["thinking"])
        for tc in (obj.get("tool_calls") if isinstance(obj.get("tool_calls"), list) else []):
            if isinstance(tc, dict) and str(tc.get("name") or "").strip():
                tname = str(tc["name"]).strip()
                acc["tool_calls"] += 1; acc["last_tool"] = tname
                _extract_tool_paths(tname, tc.get("args"), acc)
                acc["recent_events"].append({"ts": ts, "agent_id": agent_id, "kind": "tool", "name": tname, "detail": truncate_preview(json.dumps(tc.get("args") or {}, ensure_ascii=False), 120)})
    if len(acc["recent_events"]) > MAX_AGENT_EVENTS:
        acc["recent_events"] = acc["recent_events"][-MAX_AGENT_EVENTS:]


def _read_board_events(board_jsonl: Path, board_json: Path) -> list[dict[str, Any]]:
    _to_ev = lambda o: {"ts": str(o.get("time") or ""), "agent_id": str(o.get("agent") or "board"), "kind": "board", "name": str(o.get("kind") or "post"), "detail": truncate_preview(str(o.get("text") or ""), 140), "seq": o.get("seq")}
    if board_jsonl.is_file() and not is_symlink_or_junction(board_jsonl):
        def _append_board(events: list[dict[str, Any]], obj: dict[str, Any]) -> None:
            events.append(_to_ev(obj))
            if len(events) > MAX_BOARD_EVENTS:
                del events[:-MAX_BOARD_EVENTS]
        return list(_read_jsonl_incremental(board_jsonl, _BOARD_CACHE, list, _append_board))
    data = _read_json_cached(board_json)
    raw = data.get("messages") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    return [_to_ev(o) for o in (raw[-MAX_BOARD_EVENTS:] if isinstance(raw, list) else []) if isinstance(o, dict)]


def _resolve_agent_workspace(
    acc: dict[str, Any], *, uris: Sequence[str], meta_cwd: str, root_ws: str, root_parent: Optional[Path]
) -> tuple[str, str]:
    root_cf = root_ws.casefold()
    for bucket, skip_root in ((acc["write_paths"], False), (acc["read_paths"], True)):
        repos: Counter[str] = Counter()
        for p, cnt in bucket.items():
            norm_cf = p.replace("\\", "/").casefold()
            if skip_root and root_cf and (f"/{root_cf}/specs/" in norm_cf or f"/{root_cf}/tasks/" in norm_cf):
                continue
            repo = _normalize_repo_name(p, root_parent=root_parent)
            if repo and (not skip_root or repo.casefold() != root_cf):
                repos[repo] += cnt
        if repos:
            ws = repos.most_common(1)[0][0]
            ws_path = meta_cwd if (meta_cwd and root_cf and ws.casefold() == root_cf) else ""
            if not ws_path and root_parent is not None and (root_parent / ws).is_dir():
                ws_path = str(root_parent / ws)
            return ws, _classify_workspace_kind(ws, ws_path, root_ws=root_ws)
    for uri in uris:
        repo = _normalize_repo_name(uri, root_parent=root_parent)
        if repo and (not root_cf or repo.casefold() != root_cf):
            return repo, _classify_workspace_kind(repo, uri, root_ws=root_ws)
    if meta_cwd:
        repo = _normalize_repo_name(meta_cwd, root_parent=root_parent)
        if repo:
            return repo, _classify_workspace_kind(repo, meta_cwd, root_ws=root_ws)
    return root_ws or "workspace", _classify_workspace_kind(root_ws, meta_cwd if (meta_cwd and root_ws) else "", root_ws=root_ws)


def _build_agent_entry(
    *, agent_id: str, cid: str, role: str, type_name: str, status: str,
    acc: dict[str, Any], model_hint: str, workspace: str, workspace_kind: str, task_title: str,
    parent_id: Optional[str] = None, parent_name: Optional[str] = None, depth: int = 0,
    source: str = "root", spawn_step: Optional[int] = None, clean_termination: bool = False, children_count: int = 0,
) -> dict[str, Any]:
    in_t, cache_t, out_t = acc["input_tokens"], acc["cache_read_tokens"], acc["output_tokens"]
    prompt_t, t0, t1 = in_t + cache_t, parse_iso_ts(acc["first_ts"]), parse_iso_ts(acc["last_ts"])
    return {
        "id": agent_id, "conversation_id": cid, "role": role, "type_name": type_name, "status": status,
        "parent_id": parent_id, "parent_name": parent_name, "depth": depth, "source": source,
        "spawn_step": spawn_step, "clean_termination": clean_termination, "children_count": children_count,
        "model": acc["model"] or model_hint or "unknown", "workspace": workspace, "workspace_kind": workspace_kind,
        "task_title": task_title, "last_tool": acc["last_tool"], "context_tokens": acc["context_tokens"],
        "max_context_tokens": acc["max_context_tokens"], "useful_tokens": in_t + out_t, "cache_read_tokens": cache_t,
        "thinking_est_tokens": acc["thinking_chars"] // 4,
        "cache_hit_pct": round((cache_t / prompt_t) * 100.0, 2) if prompt_t > 0 else 0.0,
        "llm_calls": acc["llm_calls"], "tool_calls": acc["tool_calls"],
        "duration_s": round(max(0.0, (t1 - t0).total_seconds()), 1) if t0 and t1 else 0.0,
        "error_count": acc["error_count"], "error_steps": acc["error_count"],
        "started_at": acc["first_ts"], "last_ts": acc["last_ts"],
    }


def _collect_wf_children_from_file(path: Path, parent_cid: str, *, is_msg_json: bool) -> dict[str, dict[str, Any]]:
    try:
        if is_symlink_or_junction(path) or not path.is_file():
            return {}
        st = path.stat()
    except OSError:
        return {}
    key, fp = str(path), (int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))
    cached = _WF_CHILD_CACHE.get(key)
    if cached and cached[:3] == fp:
        return cached[3]
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    found: dict[str, dict[str, Any]] = {}
    if not (is_msg_json and "run_workflow" not in raw and "[agent:" not in raw):
        for ref in parse_wf_agent_refs(raw, parent_cid=parent_cid):
            found[ref["cid"]] = ref
    _cache_put(_WF_CHILD_CACHE, key, (*fp, found))
    return found


def _collect_wf_children_from_transcript(path: Path, parent_cid: str) -> frozenset[str]:
    try:
        if is_symlink_or_junction(path) or not path.is_file():
            return frozenset()
        st = path.stat()
    except OSError:
        return frozenset()
    key, fp = f"tr::{path}", (int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))
    cached = _WF_CHILD_CACHE.get(key)
    if cached and cached[:3] == fp:
        return cached[3]
    is_inc = bool(cached and cached[0] == int(st.st_ino) and int(st.st_size) >= int(cached[4]))
    offset, partial, found_set = (int(cached[4]), bytes(cached[5]), set(cached[3])) if (is_inc and cached) else (0, b"", set())
    try:
        with path.open("rb") as fh:
            if offset > 0:
                fh.seek(offset)
            chunk = fh.read()
    except OSError:
        return frozenset(found_set)
    lines = (partial + chunk).splitlines(keepends=True)
    new_partial = lines.pop() if lines and not lines[-1].endswith((b"\n", b"\r")) else b""
    if b"[agent:" in (partial + chunk):
        refs: dict[str, dict[str, Any]] = {}
        for raw_line in lines:
            if b"[agent:" not in raw_line:
                continue
            try:
                obj = json.loads(raw_line.decode("utf-8", errors="replace").lstrip("\ufeff").strip() or "null")
            except ValueError:
                obj = None
            if isinstance(obj, dict):
                collect_wf_refs_from_obj(obj, parent_cid, None, refs)
        found_set.update(refs.keys())
    frozen = frozenset(found_set)
    _cache_put(_WF_CHILD_CACHE, key, (*fp, frozen, offset + len(chunk), new_partial))
    return frozen


def _ingest_archived_item(out: dict[str, tuple[str, Optional[float]]], item: Any, fallback_ts: str = "") -> None:
    if isinstance(item, str) and item.strip():
        dt = parse_iso_ts(fallback_ts)
        out[item.strip()] = ("archived", dt.timestamp() if dt is not None else None)
    elif isinstance(item, dict):
        cid = str(item.get("conversation_id") or item.get("cid") or "").strip()
        if cid:
            dt = parse_iso_ts(item.get("ended_at") or item.get("updated_at") or fallback_ts)
            out[cid] = (str(item.get("status") or "archived").strip().lower(), dt.timestamp() if dt is not None else None)


def _load_archived_status_ro(
    *, gravity_home: Optional[Path], metrics_home: Optional[Path], plugin_roots: Optional[Sequence[Path]] = None
) -> tuple[dict[str, tuple[str, Optional[float]]], list[Any]]:
    """Load archived session status from `_shared.signal_bus` (`session-metrics`) and optional metrics SPI-1."""
    out: dict[str, tuple[str, Optional[float]]] = {}
    sig_tokens: list[Any] = []
    try:
        envelopes = list_topic_signals("session-metrics", gravity_home=gravity_home)
    except (ValueError, OSError):
        envelopes = []
    for env in envelopes:
        payload = env.get("payload") if isinstance(env, dict) else None
        emitted = str(env.get("emitted_at") or "") if isinstance(env, dict) else ""
        sig_tokens.append((emitted, env.get("sample_count") if isinstance(env, dict) else 0))
        if not isinstance(payload, dict):
            continue
        arch_map = payload.get("archived_cids")
        if isinstance(arch_map, dict):
            for cid, meta in arch_map.items():
                _ingest_archived_item(out, {"conversation_id": cid, **(meta if isinstance(meta, dict) else {"ended_at": meta if isinstance(meta, str) else emitted})}, emitted)
        for items in (arch_map, payload.get("records"), payload.get("sessions")):
            if isinstance(items, list):
                for entry in items:
                    _ingest_archived_item(out, entry, emitted)
        if payload.get("conversation_id"):
            _ingest_archived_item(out, payload, emitted)

    if resolve_dashboard_provider("metrics", gravity_home=gravity_home, plugin_roots=plugin_roots).get("ok"):
        spi_res = invoke_dashboard_provider("metrics", view="metrics", params={"limit": 100}, ctx={"metrics_home": metrics_home}, gravity_home=gravity_home, plugin_roots=plugin_roots)
        if not spi_res.get("spi_fallback") and isinstance(spi_res.get("records"), list):
            sig_tokens.append(("spi", spi_res.get("signature", ""), len(spi_res["records"])))
            for rec in spi_res["records"]:
                _ingest_archived_item(out, rec)
    return out, sig_tokens


def _is_candidate_archived(rcid: str, mtime_ns: int, active_captures: dict[str, Any], archived_map: dict[str, tuple[str, Optional[float]]]) -> bool:
    if rcid in active_captures:
        return False
    hist = archived_map.get(rcid)
    if hist is None or hist[0] != "archived":
        return False
    return True if hist[1] is None else ((mtime_ns / 1e9) <= (hist[1] + 60.0))


def _read_first_transcript_ts(brain_root: Path, cid: str) -> str:
    tpath = brain_root / cid / ".system_generated" / "logs" / "transcript.jsonl"
    if is_symlink_or_junction(tpath) or not tpath.is_file():
        return ""
    try:
        with tpath.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.lstrip("\ufeff").strip()
                if line:
                    obj = json.loads(line)
                    return str(obj.get("created_at") or "").strip() if isinstance(obj, dict) else ""
    except (OSError, ValueError):
        pass
    return ""


def _discover_brain_sessions(
    brain_root: Path, active_captures: dict[str, Any], session_meta: dict[str, Any],
    archived_map: dict[str, tuple[str, Optional[float]]], *, explicit_cid: str = "",
) -> list[dict[str, Any]]:
    if is_symlink_or_junction(brain_root) or not brain_root.is_dir():
        return []
    child_cids: set[str] = set()
    strong_child_cids: set[str] = set()
    edges: dict[str, set[str]] = {}
    candidates: list[dict[str, Any]] = []
    try:
        entries = list(brain_root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if is_symlink_or_junction(entry) or not entry.is_dir() or not _UUID_LIKE_RE.match(entry.name):
            continue
        cid, sg = entry.name, entry / ".system_generated"
        if is_symlink_or_junction(sg) or not sg.is_dir():
            continue
        node_edges = edges.setdefault(cid, set())
        if (sg / "subagents").is_dir() and not is_symlink_or_junction(sg / "subagents"):
            for sf in (sg / "subagents").iterdir():
                if sf.suffix == ".json" and not is_symlink_or_junction(sf):
                    sdata = _read_json_cached(sf)
                    scid = str((sdata or {}).get("conversationId") or sf.stem).strip() if isinstance(sdata, dict) else ""
                    if scid and scid != cid:
                        child_cids.add(scid); strong_child_cids.add(scid); node_edges.add(scid)
        members_file = sg / "swarm" / "members.json"
        mdata = _read_json_cached(members_file) if members_file.is_file() and not is_symlink_or_junction(members_file) else None
        for m_info in (mdata.get("members") if isinstance(mdata, dict) and isinstance(mdata.get("members"), dict) else {}).values():
            if isinstance(m_info, dict) and str(m_info.get("conversation_id") or "").strip() not in ("", cid):
                mcid = str(m_info["conversation_id"]).strip()
                child_cids.add(mcid); strong_child_cids.add(mcid); node_edges.add(mcid)
        for sub_name, is_msg, pred in (
            ("tasks", False, lambda p: p.name.lower().startswith("task-") and p.suffix.lower() == ".log"),
            ("messages", True, lambda p: p.suffix.lower() == ".json" and p.name.lower() != "read.json"),
        ):
            sub_dir = sg / sub_name
            if sub_dir.is_dir() and not is_symlink_or_junction(sub_dir):
                try:
                    for fp in sub_dir.iterdir():
                        if not is_symlink_or_junction(fp) and pred(fp):
                            wf_ids = _collect_wf_children_from_file(fp, cid, is_msg_json=is_msg).keys()
                            child_cids.update(wf_ids); node_edges.update(wf_ids)
                except OSError:
                    pass
        tpath = sg / "logs" / "transcript.jsonl"
        has_transcript = tpath.is_file() and not is_symlink_or_junction(tpath)
        if has_transcript:
            tr_ids = _collect_wf_children_from_transcript(tpath, cid)
            child_cids.update(tr_ids); node_edges.update(tr_ids)
        if has_transcript or cid in active_captures:
            mtime_ns = max((p.stat().st_mtime_ns for p in (tpath, members_file, sg / "swarm" / "board.jsonl", entry) if p.exists()), default=0)
            candidates.append({"cid": cid, "dir": entry, "sg": sg, "mtime_ns": mtime_ns})

    q_cid = explicit_cid.strip().lower()
    if q_cid:
        match = next((r for r in candidates if r["cid"].lower() == q_cid), None) or next(
            (r for r in sorted(candidates, key=lambda c: (-int(c["mtime_ns"]), c["cid"])) if r["cid"].lower().startswith(q_cid)), None
        )
        if match is None:
            return []
        match["archived"] = _is_candidate_archived(match["cid"], int(match["mtime_ns"]), active_captures, archived_map)
        return [match]
    if any(c in edges for cs in edges.values() for c in cs):
        child_cids -= find_cycle_root_overrides(edges, strong_child_cids, lambda c: _read_first_transcript_ts(brain_root, c))
    roots = sorted([
        it for it in candidates
        if it["cid"] not in child_cids and not (
            it["cid"] not in active_captures and is_worktree_path((session_meta.get(it["cid"]) or {}).get("cwd"))
            and not (it["sg"] / "swarm").is_dir() and not (it["sg"] / "subagents").is_dir()
        )
    ], key=lambda r: (-int(r["mtime_ns"]), r["cid"]))
    now_s = datetime.now(timezone.utc).timestamp()
    for r in roots:
        r["archived"] = _is_candidate_archived(r["cid"], int(r["mtime_ns"]), active_captures, archived_map)
    return (
        [r for r in roots if not r["archived"] and r["cid"] in active_captures]
        + [r for r in roots if not r["archived"] and r["cid"] not in active_captures and r["mtime_ns"] > 0 and (now_s - (r["mtime_ns"] / 1e9)) <= LIVE_RECENT_WINDOW_S]
    )[:MAX_ROOT_SESSIONS]


def get_live_session_state(
    session_id: str = "", since_signature: str = "", include_events: bool = True, *,
    ws: str = "", gravity_home: Optional[Path] = None, brain_dir: Optional[Path] = None,
    metrics_home: Optional[Path] = None, workflow_home: Optional[Path] = None,
    registry_path: Optional[Path] = None, home_dir: Optional[Path] = None,
    plugin_roots: Optional[Sequence[Path]] = None, **_: Any,
) -> dict[str, Any]:
    """Return incremental read-only live session state from brain/ and Gravity Workflow."""
    if brain_dir is not None:
        b_dir = Path(brain_dir).expanduser().resolve()
    elif home_dir is not None:
        b_dir = (Path(home_dir).expanduser() / ".gemini" / "antigravity" / "brain").resolve()
    else:
        env_b = os.environ.get("GRAVITY_BRAIN_DIR", "").strip()
        b_dir = Path(env_b).expanduser().resolve() if env_b else (Path.home() / ".gemini" / "antigravity" / "brain").resolve()
    m_home = Path(metrics_home).expanduser().resolve() if metrics_home is not None else resolve_module_home("metrics", env_override="GRAVITY_METRICS_HOME", gravity_home=gravity_home)
    cap_path, meta_path = m_home / "active_captures.json", m_home / "session_meta.json"
    cap_raw, meta_raw = _read_json_cached(cap_path), _read_json_cached(meta_path)
    active_captures = cap_raw.get("captures") if isinstance(cap_raw, dict) and isinstance(cap_raw.get("captures"), dict) else {}
    session_meta = meta_raw.get("sessions") if isinstance(meta_raw, dict) and isinstance(meta_raw.get("sessions"), dict) else {}
    archived_map, archived_sig_tokens = _load_archived_status_ro(gravity_home=gravity_home, metrics_home=m_home, plugin_roots=plugin_roots)
    q_cid = session_id.strip().lower()
    roots = _discover_brain_sessions(b_dir, active_captures, session_meta, archived_map, explicit_cid=q_cid)
    selected = roots[0] if roots else None
    sel_meta: dict[str, Any] = (session_meta.get(selected["cid"]) or {}) if selected is not None else {}
    sel_cap: Optional[dict[str, Any]] = active_captures.get(selected["cid"]) if selected is not None else None
    root_cwd = str(sel_meta.get("cwd") or "").strip() if selected is not None else ""
    root_ws = str((sel_cap or {}).get("project") or sel_meta.get("project") or _normalize_repo_name(root_cwd) or "workspace") if selected is not None else ""
    effective_ws = ws.strip() or (root_cwd or (root_ws if root_ws and root_ws != "workspace" else ""))

    wf_state: Optional[dict[str, Any]] = None
    if resolve_dashboard_provider("workflow", gravity_home=gravity_home, plugin_roots=plugin_roots).get("ok"):
        cand_wf = invoke_dashboard_provider("workflow", view="workflow", params={"ws": effective_ws}, ctx={"workflow_home": workflow_home}, gravity_home=gravity_home, plugin_roots=plugin_roots)
        if not cand_wf.get("spi_fallback"):
            wf_state = cand_wf
    if wf_state is None:
        wf_state = read_workflow_live_c8_ro(ws=effective_ws, gravity_home=gravity_home, workflow_home=workflow_home, registry_path=registry_path)

    progress_info = build_live_progress(wf_state)
    wf_slim = {k: wf_state.get(k) for k in ("available", "stage", "progress", "mode", "level", "preset_profile", "suggested_profile", "guard_status", "nodes", "selected_workspace")}
    wf_slim["progress"], wf_slim["progress_detail"] = progress_info["label"], progress_info
    wf_slim["is_active"] = str(wf_slim.get("stage") or "").strip().lower() not in ("", "idle")

    sig_parts: list[Any] = [str(b_dir), q_cid, bool(include_events), stat_token(cap_path), stat_token(meta_path), archived_sig_tokens, wf_state.get("signature", ""), [(r["cid"], r["mtime_ns"], bool(r.get("archived"))) for r in roots]]
    root_task_logs_count = 0
    if selected is not None:
        desc_tokens, root_task_logs_count = collect_descendant_sig_tokens(
            b_dir, selected["cid"], read_json_fn=_read_json_cached,
            collect_wf_file_fn=lambda p, pcid, is_msg: _collect_wf_children_from_file(p, pcid, is_msg_json=is_msg),
            collect_transcript_wf_fn=_collect_wf_children_from_transcript, stat_token_fn=stat_token,
        )
        sig_parts.extend(desc_tokens)

    sig = short_digest(sig_parts)
    if since_signature and since_signature == sig:
        return unchanged_response(sig)

    sessions_list = [{"conversation_id": r["cid"], "label": str((active_captures.get(r["cid"]) or {}).get("label") or f"session-{r['cid'][:8]}"), "project": str((active_captures.get(r["cid"]) or {}).get("project") or (session_meta.get(r["cid"]) or {}).get("project") or _normalize_repo_name(str((session_meta.get(r["cid"]) or {}).get("cwd") or ""))), "captured": r["cid"] in active_captures, "archived": bool(r.get("archived")), "updated_at": str((active_captures.get(r["cid"]) or {}).get("updated_at") or (session_meta.get(r["cid"]) or {}).get("updated_at") or (datetime.fromtimestamp(r["mtime_ns"] / 1e9, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if r["mtime_ns"] else ""))} for r in roots]
    if selected is None:
        return {"changed": True, "unchanged": False, "signature": sig, "available": False, "brain_dir": str(b_dir), "sessions": sessions_list, "selected_session": None, "session_started_at": "", "session_last_ts": "", "agents": [], "recent_events": [], "summary": {"total_agents": 0, "active_agents": 0, "waiting_agents": 0, "done_agents": 0, "error_agents": 0, "session_started_at": "", "session_last_ts": ""}, "workflow": wf_slim}

    sel_cid, sg = selected["cid"], selected["sg"]
    root_parent = Path(strip_file_uri(root_cwd)).parent if root_cwd else None
    members_raw, plan_raw = _read_json_cached(sg / "swarm" / "members.json"), _read_json_cached(sg / "swarm" / "plan.json")
    swarm_title = str(members_raw.get("title") or "").strip() if isinstance(members_raw, dict) else ""
    members_map = {str(k): v for k, v in members_raw["members"].items() if isinstance(v, dict)} if isinstance(members_raw, dict) and isinstance(members_raw.get("members"), dict) else {}
    plan_tasks = plan_raw.get("tasks") if isinstance(plan_raw, dict) and isinstance(plan_raw.get("tasks"), dict) else {}
    goal_title = str((plan_raw.get("goal") or {}).get("title") or "").strip() if isinstance(plan_raw, dict) and isinstance(plan_raw.get("goal"), dict) else ""

    coord_member = members_map.get("coordinator")
    root_aid = "coordinator" if coord_member is not None else f"root-{sel_cid[:8]}"
    root_acc = _read_jsonl_incremental(sg / "logs" / "transcript.jsonl", _TRANSCRIPT_CACHE, _new_transcript_acc, lambda a, o: _apply_transcript_obj(a, o, root_aid, parent_cid=sel_cid))
    r_ws, r_kind = _resolve_agent_workspace(root_acc, uris=[], meta_cwd=root_cwd, root_ws=root_ws, root_parent=root_parent)

    agents, all_events = discover_live_tree(
        b_dir, sel_cid, root_aid=root_aid, root_role="Coordinator" if coord_member else "Session racine",
        root_type="coordinator" if coord_member else "root", root_acc=root_acc, coord_member=coord_member,
        root_model_hint=str((coord_member or {}).get("applied_model") or (coord_member or {}).get("model") or ""),
        root_ws=r_ws, root_ws_kind=r_kind, root_task_title=goal_title or swarm_title, root_parent=root_parent,
        plan_tasks=plan_tasks, session_meta=session_meta, is_archived=bool(selected.get("archived")),
        read_json_fn=_read_json_cached, collect_wf_file_fn=lambda p, pcid, is_msg: _collect_wf_children_from_file(p, pcid, is_msg_json=is_msg),
        read_transcript_fn=lambda c_cid, c_aid: _read_jsonl_incremental(b_dir / c_cid / ".system_generated" / "logs" / "transcript.jsonl", _TRANSCRIPT_CACHE, _new_transcript_acc, lambda a, o, _id=c_aid, _cid=c_cid: _apply_transcript_obj(a, o, _id, parent_cid=_cid)),
        resolve_ws_fn=_resolve_agent_workspace, build_entry_fn=_build_agent_entry, include_events=include_events,
    )
    if include_events:
        all_events = sorted([*all_events, *_read_board_events(sg / "swarm" / "board.jsonl", sg / "swarm" / "board.json")], key=lambda ev: str(ev.get("ts") or ""), reverse=True)[:MAX_RECENT_EVENTS]

    sc, tot_in, tot_cache = Counter(a["status"] for a in agents), sum(a["useful_tokens"] for a in agents), sum(a["cache_read_tokens"] for a in agents)
    start_ts_list = [str(a["started_at"]) for a in agents if a.get("started_at")]
    last_ts_list = [str(a["last_ts"]) for a in agents if a.get("last_ts")]
    session_started_at = min(start_ts_list, key=lambda s: (parse_iso_ts(s) or datetime.max.replace(tzinfo=timezone.utc), s)) if start_ts_list else root_acc["first_ts"]
    session_last_ts = max(last_ts_list, key=lambda s: (parse_iso_ts(s) or datetime.min.replace(tzinfo=timezone.utc), s)) if last_ts_list else root_acc["last_ts"]
    payload: dict[str, Any] = {
        "changed": True, "unchanged": False, "signature": sig, "available": True, "brain_dir": str(b_dir), "sessions": sessions_list,
        "session_started_at": session_started_at, "session_last_ts": session_last_ts,
        "selected_session": {"conversation_id": sel_cid, "label": str((sel_cap or {}).get("label") or swarm_title or goal_title or f"session-{sel_cid[:8]}"), "project": root_ws, "workspace_kind": r_kind, "captured": sel_cap is not None, "start_step": (sel_cap or {}).get("start_step"), "swarm_title": swarm_title, "goal_title": goal_title, "last_step_index": root_acc["last_step_index"], "started_at": session_started_at, "session_started_at": session_started_at, "session_last_ts": session_last_ts, "last_ts": root_acc["last_ts"]},
        "agents": agents, "recent_events": all_events if include_events else [],
        "summary": {"total_agents": len(agents), "active_agents": sc["active"], "waiting_agents": sc["waiting"], "done_agents": sc["done"], "error_agents": sc["error"], "useful_tokens": tot_in, "cache_read_tokens": tot_cache, "cache_hit_pct": round((tot_cache / (tot_in + tot_cache)) * 100.0, 2) if (tot_in + tot_cache) > 0 else 0.0, "max_context_tokens": max((a["max_context_tokens"] for a in agents), default=0), "context_tokens": agents[0]["context_tokens"], "thinking_est_tokens": sum(a["thinking_est_tokens"] for a in agents), "llm_calls": sum(a["llm_calls"] for a in agents), "tool_calls": sum(a["tool_calls"] for a in agents), "error_count": sum(a["error_count"] for a in agents), "duration_s": max((a["duration_s"] for a in agents), default=0.0), "session_started_at": session_started_at, "session_last_ts": session_last_ts, "background_tasks": root_task_logs_count},
        "workflow": wf_slim,
    }
    return enforce_payload_budget(payload, ("recent_events", "agents", "sessions"), max_bytes=MAX_PAYLOAD_BYTES)


__all__ = [
    "LIVE_RECENT_WINDOW_S", "MAX_AGENT_EVENTS", "MAX_BOARD_EVENTS", "MAX_CACHE_ENTRIES",
    "MAX_PAYLOAD_BYTES", "MAX_RECENT_EVENTS", "MAX_ROOT_SESSIONS",
    "get_live_cache_stats", "get_live_session_state", "reset_live_cache",
]

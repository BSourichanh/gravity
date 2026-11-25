"""Read-only incremental live session provider scanning Antigravity brain/ and workflow state."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Optional, Sequence

from core.registry import resolve_module_home
from dashboard.providers import (
    enforce_payload_budget,
    read_json_ro,
    short_digest,
    stat_token,
    truncate_preview,
    unchanged_response,
)
from dashboard.providers.live_tree import (
    collect_descendant_sig_tokens,
    collect_wf_refs_from_obj,
    derive_agent_status,
    discover_live_tree,
    extract_shell_nonzero_code,
    find_cycle_root_overrides,
    parse_iso_ts,
    parse_wf_agent_refs,
    update_termination_acc,
)
from dashboard.providers.workflow_provider import get_workflow_state

MAX_ROOT_SESSIONS, MAX_AGENT_EVENTS, MAX_BOARD_EVENTS, MAX_RECENT_EVENTS = 25, 25, 30, 80
MAX_PAYLOAD_BYTES, MAX_CACHE_ENTRIES = 450_000, 256
LIVE_RECENT_WINDOW_S = 6 * 3600

_WORKTREE_RE = re.compile(r"/(?:gravity-worktrees|\.gemini/antigravity/worktrees|\.worktrees)/([^/]+)(?:/|$)", re.IGNORECASE)
_WORKTREE_SUFFIX_RE = re.compile(r"-w\d+$", re.IGNORECASE)
_REPO_MARKER_RE = re.compile(
    r"/([^/]+)/(?:plugin|src|tests|specs|tasks|docs|scripts|config|audits|assets|tracking|dashboard|templates|archives|README\.md|AGENTS\.md|CHANGELOG\.md)(?:/|$)"
)
_CMD_CD_RE = re.compile(r"(?:^|[;&|]\s*)(?:cd|git\s+-C)\s+[\"']?([^\s\"';&|]+)", re.IGNORECASE)
_UUID_LIKE_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{12,}$|^[A-Za-z0-9._-]{4,80}$")

_TRANSCRIPT_CACHE: dict[str, dict[str, Any]] = {}
_BOARD_CACHE: dict[str, dict[str, Any]] = {}
_JSON_CACHE: dict[str, dict[str, Any]] = {}
_BRIDGE_SNIFF_CACHE: dict[tuple[str, int], bool] = {}
_WF_CHILD_CACHE: dict[str, tuple[Any, ...]] = {}
_HISTORY_ARCHIVE_CACHE: dict[str, tuple[int, int, int, dict[str, tuple[str, Optional[float]]]]] = {}
_CACHE_STATS: dict[str, int] = {"bytes_read": 0, "incremental_reads": 0, "full_reads": 0, "cache_hits": 0}


def reset_live_cache() -> None:
    """Clear in-memory incremental caches and counters."""
    for cache in (_TRANSCRIPT_CACHE, _BOARD_CACHE, _JSON_CACHE, _BRIDGE_SNIFF_CACHE, _WF_CHILD_CACHE, _HISTORY_ARCHIVE_CACHE):
        cache.clear()
    for k in _CACHE_STATS:
        _CACHE_STATS[k] = 0


def get_live_cache_stats() -> dict[str, int]:
    """Return a copy of incremental read counters."""
    return dict(_CACHE_STATS)


_parse_iso_ts = parse_iso_ts


def _strip_file_uri(raw: str) -> str:
    txt = raw.strip().strip("\"'")
    if txt.startswith("file://"):
        txt = txt[7:]
        if len(txt) >= 3 and txt[0] == "/" and txt[2] == ":":
            txt = txt[1:]
    return txt


def _normalize_repo_name(raw_path: str, root_parent: Optional[Path] = None) -> str:
    cleaned = _strip_file_uri(raw_path).replace("\\", "/").strip()
    if not cleaned:
        return ""
    m = _WORKTREE_RE.search(cleaned)
    if m:
        return _WORKTREE_SUFFIX_RE.sub("", m.group(1)) if "/gravity-worktrees/" in cleaned.lower() else m.group(1)
    if root_parent is not None:
        parent_posix = str(root_parent).replace("\\", "/").rstrip("/")
        prefix = parent_posix + "/"
        if parent_posix and cleaned[: len(prefix)].casefold() == prefix.casefold():
            rest = cleaned[len(prefix) :].split("/", 1)[0]
            if rest:
                return _WORKTREE_SUFFIX_RE.sub("", rest) if "worktree" in parent_posix.lower() else rest
    marker_m = _REPO_MARKER_RE.search(cleaned)
    if marker_m:
        return marker_m.group(1)
    p = Path(cleaned.rstrip("/"))
    return p.parent.name if (p.suffix and p.parent.name) else p.name


def _is_worktree_cwd(cwd: Any) -> bool:
    if not isinstance(cwd, str) or not cwd.strip():
        return False
    norm = cwd.strip().replace("\\", "/").lower()
    return any(tok in norm for tok in ("/.gemini/antigravity/worktrees/", "/gravity-worktrees/", "/.worktrees/", "/worktrees/"))


def _classify_workspace_kind(ws_name: str, ws_path: str = "", root_ws: str = "") -> str:
    low = ws_name.strip().lower()
    if low == "gravity-studio" or low.endswith("-studio"):
        return "atelier"
    if ws_path:
        p = Path(_strip_file_uri(ws_path))
        if p.is_dir() and ((p / "projects.json").is_file() or (p / "specs").is_dir()):
            return "atelier"
    return "code"


def _read_json_cached(path: Path) -> Any:
    try:
        if path.is_symlink() or not path.is_file():
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
    while len(_JSON_CACHE) >= MAX_CACHE_ENTRIES:
        _JSON_CACHE.pop(next(iter(_JSON_CACHE)), None)
    _JSON_CACHE[key] = {"inode": st.st_ino, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "data": data}
    return data


def _read_jsonl_incremental(
    path: Path, cache: dict[str, dict[str, Any]], make_state: Callable[[], Any], apply_line: Callable[[Any, dict[str, Any]], None]
) -> Any:
    """Read only newly appended lines using `(path, inode, size)` and `seek(offset)`."""
    try:
        if path.is_symlink() or not path.is_file():
            return make_state()
        st = path.stat()
    except OSError:
        return make_state()
    key = str(path)
    cached = cache.get(key)
    if cached and cached["inode"] == st.st_ino and cached["size"] == st.st_size and cached["mtime_ns"] == st.st_mtime_ns:
        _CACHE_STATS["cache_hits"] += 1
        return cached["state"]
    if cached and cached["inode"] == st.st_ino and st.st_size >= cached["offset"]:
        offset, partial, state, is_inc = cached["offset"], cached["partial"], cached["state"], True
    else:
        offset, partial, state, is_inc = 0, b"", make_state(), False
    try:
        with path.open("rb") as fh:
            if offset > 0:
                fh.seek(offset)
            chunk = fh.read()
    except OSError:
        return state
    _CACHE_STATS["bytes_read"] += len(chunk)
    _CACHE_STATS["incremental_reads" if is_inc else "full_reads"] += 1
    lines = (partial + chunk).splitlines(keepends=True)
    new_partial = lines.pop() if lines and not lines[-1].endswith((b"\n", b"\r")) else b""
    for raw_line in lines:
        txt = raw_line.decode("utf-8", errors="replace").lstrip("\ufeff").strip()
        if txt:
            try:
                obj = json.loads(txt)
                if isinstance(obj, dict):
                    apply_line(state, obj)
            except ValueError:
                pass
    while len(cache) >= MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)), None)
    cache[key] = {"inode": st.st_ino, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "offset": offset + len(chunk), "partial": new_partial, "state": state}
    return state


def _new_transcript_acc() -> dict[str, Any]:
    return {
        "first_ts": "", "last_ts": "", "last_step_index": -1, "model": "",
        "input_tokens": 0, "cache_read_tokens": 0, "output_tokens": 0,
        "context_tokens": 0, "max_context_tokens": 0, "thinking_chars": 0,
        "llm_calls": 0, "tool_calls": 0, "error_count": 0,
        "last_tool": "", "last_status": "", "write_paths": Counter(), "read_paths": Counter(), "recent_events": [],
        "last_non_sys_type": "", "last_non_sys_status": "", "last_non_sys_shell_nonzero": False,
        "last_planner_status": "", "last_planner_has_tools": False, "last_planner_terminal_tool": "",
        "trailing_after_planner_count": 0, "trailing_after_planner_all_clean_generic": False,
        "wf_child_refs": {},
    }


def _extract_tool_paths(name: str, args: Any, acc: dict[str, Any]) -> None:
    if not isinstance(args, dict):
        return
    lname = name.lower()
    if lname in ("edit_file", "write_file", "replace_file_content", "multi_replace_file_content", "write_to_file"):
        for k in ("Path", "path", "TargetFile", "file_path"):
            if isinstance(args.get(k), str) and args[k].strip():
                acc["write_paths"][args[k].strip().strip("\"'")] += 1
                return
    elif lname in ("run_command", "execute_command"):
        for m in _CMD_CD_RE.finditer(str(args.get("CommandLine") or args.get("command") or "")):
            acc["write_paths"][m.group(1)] += 1
        cwd_val = args.get("Cwd") or args.get("cwd")
        if isinstance(cwd_val, str) and cwd_val.strip():
            acc["write_paths"][cwd_val.strip().strip("\"'")] += 1
    elif lname in ("read_file", "view_file", "grep_search", "find_by_name", "list_dir"):
        for k in ("Path", "path", "AbsolutePath", "SearchPath", "DirectoryPath", "SearchDirectory"):
            if isinstance(args.get(k), str) and args[k].strip():
                acc["read_paths"][args[k].strip().strip("\"'")] += 1
                return


def _apply_transcript_obj(acc: dict[str, Any], obj: dict[str, Any], agent_id: str, *, parent_cid: str = "") -> None:
    ts = str(obj.get("created_at") or "").strip()
    if ts:
        acc["first_ts"] = acc["first_ts"] or ts
        acc["last_ts"] = ts
    step_idx = obj.get("step_index")
    clean_step_idx = step_idx if (isinstance(step_idx, int) and not isinstance(step_idx, bool)) else None
    if clean_step_idx is not None:
        acc["last_step_index"] = max(acc["last_step_index"], clean_step_idx)
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
    collect_wf_refs_from_obj(obj, parent_cid, clean_step_idx, acc["wf_child_refs"])
    if step_type == "PLANNER_RESPONSE":
        acc["llm_calls"] += 1
        if str(obj.get("model") or "").strip():
            acc["model"] = str(obj["model"]).strip()
        in_t, cache_t, out_t = max(0, int(obj.get("input_tokens") or 0)), max(0, int(obj.get("cache_read_tokens") or 0)), max(0, int(obj.get("output_tokens") or 0))
        acc["input_tokens"] += in_t
        acc["cache_read_tokens"] += cache_t
        acc["output_tokens"] += out_t
        ctx = in_t + cache_t
        if ctx > 0:
            acc["context_tokens"], acc["max_context_tokens"] = ctx, max(acc["max_context_tokens"], ctx)
        if isinstance(obj.get("thinking"), str):
            acc["thinking_chars"] += len(obj["thinking"])
        for tc in (obj.get("tool_calls") if isinstance(obj.get("tool_calls"), list) else []):
            if isinstance(tc, dict) and str(tc.get("name") or "").strip():
                tname = str(tc["name"]).strip()
                acc["tool_calls"] += 1
                acc["last_tool"] = tname
                _extract_tool_paths(tname, tc.get("args"), acc)
                acc["recent_events"].append({"ts": ts, "agent_id": agent_id, "kind": "tool", "name": tname, "detail": truncate_preview(json.dumps(tc.get("args") or {}, ensure_ascii=False), 120)})
    if len(acc["recent_events"]) > MAX_AGENT_EVENTS:
        acc["recent_events"] = acc["recent_events"][-MAX_AGENT_EVENTS:]


def _read_board_events(board_jsonl: Path, board_json: Path) -> list[dict[str, Any]]:
    _to_ev = lambda o: {"ts": str(o.get("time") or ""), "agent_id": str(o.get("agent") or "board"), "kind": "board", "name": str(o.get("kind") or "post"), "detail": truncate_preview(str(o.get("text") or ""), 140), "seq": o.get("seq")}
    if board_jsonl.is_file() and not board_jsonl.is_symlink():
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
            if not ws_path and root_parent is not None:
                cand = root_parent / ws
                if cand.is_dir():
                    ws_path = str(cand)
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


def _derive_agent_status(
    *,
    acc: dict[str, Any],
    member_info: Optional[dict[str, Any]],
    subagent_state: str,
    has_active_children: bool = False,
    is_coordinator: bool = False,
    all_workers_done: bool = False,
    is_archived: bool = False,
) -> str:
    status, _ = derive_agent_status(
        acc=acc,
        member_info=member_info,
        subagent_state=subagent_state,
        has_active_children=has_active_children,
        is_coordinator=is_coordinator,
        all_workers_done=all_workers_done,
        is_archived=is_archived,
    )
    return status


def _build_agent_entry(
    *, agent_id: str, cid: str, role: str, type_name: str, status: str,
    acc: dict[str, Any], model_hint: str, workspace: str, workspace_kind: str, task_title: str,
    parent_id: Optional[str] = None, parent_name: Optional[str] = None, depth: int = 0,
    source: str = "root", spawn_step: Optional[int] = None, clean_termination: bool = False,
    children_count: int = 0,
) -> dict[str, Any]:
    in_t, cache_t, out_t = acc["input_tokens"], acc["cache_read_tokens"], acc["output_tokens"]
    prompt_t, t0, t1 = in_t + cache_t, _parse_iso_ts(acc["first_ts"]), _parse_iso_ts(acc["last_ts"])
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


def _cache_put(cache: dict[Any, Any], key: Any, val: Any) -> None:
    while len(cache) >= MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)), None)
    cache[key] = val


def _is_bridge_child_transcript(tpath: Path) -> bool:
    """Return True if first USER_INPUT within 20 lines is a [GRAVITY-BRIDGE prompt (no bytes_read)."""
    try:
        if tpath.is_symlink() or not tpath.is_file():
            return False
        st = tpath.stat()
    except OSError:
        return False
    if st.st_size <= 0:
        return False
    key = (str(tpath), int(st.st_ino))
    if key in _BRIDGE_SNIFF_CACHE:
        return _BRIDGE_SNIFF_CACHE[key]
    is_bridge = False
    try:
        with tpath.open("r", encoding="utf-8", errors="replace") as fh:
            for idx, raw_line in enumerate(fh):
                if idx >= 20:
                    break
                line = raw_line.lstrip("\ufeff").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "USER_INPUT":
                    is_bridge = "[GRAVITY-BRIDGE" in str(obj.get("content") or "")
                    break
    except OSError:
        return False
    _cache_put(_BRIDGE_SNIFF_CACHE, key, is_bridge)
    return is_bridge


def _collect_wf_children_from_file(path: Path, parent_cid: str, *, is_msg_json: bool) -> dict[str, dict[str, Any]]:
    """Extract run_workflow child refs from task-*.log or messages/*.json (no bytes_read)."""
    try:
        if path.is_symlink() or not path.is_file():
            return {}
        st = path.stat()
    except OSError:
        return {}
    key = str(path)
    cached = _WF_CHILD_CACHE.get(key)
    fp = (int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))
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
    """Incrementally extract `[agent:...]` child CIDs from transcript.jsonl without incrementing bytes_read."""
    try:
        if path.is_symlink() or not path.is_file():
            return frozenset()
        st = path.stat()
    except OSError:
        return frozenset()
    key = f"tr::{path}"
    cached = _WF_CHILD_CACHE.get(key)
    fp = (int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))
    if cached and cached[:3] == fp:
        return cached[3]
    if cached and cached[0] == int(st.st_ino) and int(st.st_size) >= int(cached[4]):
        offset, partial, found_set = int(cached[4]), bytes(cached[5]), set(cached[3])
    else:
        offset, partial, found_set = 0, b"", set()
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
            txt = raw_line.decode("utf-8", errors="replace").lstrip("\ufeff").strip()
            if not txt:
                continue
            try:
                obj = json.loads(txt)
            except ValueError:
                obj = None
            if isinstance(obj, dict):
                collect_wf_refs_from_obj(obj, parent_cid, None, refs)
        found_set.update(refs.keys())
    frozen = frozenset(found_set)
    _cache_put(_WF_CHILD_CACHE, key, (*fp, frozen, offset + len(chunk), new_partial))
    return frozen


def _load_history_status_ro(metrics_home: Optional[Path]) -> dict[str, tuple[str, Optional[float]]]:
    """Read lightweight (status, ended_at_ts) map from history.jsonl (no bytes_read)."""
    if metrics_home is None:
        return {}
    hpath = metrics_home / "data" / "history.jsonl"
    try:
        if hpath.is_symlink() or not hpath.is_file():
            return {}
        st = hpath.stat()
    except OSError:
        return {}
    key = str(hpath)
    cached = _HISTORY_ARCHIVE_CACHE.get(key)
    fp = (int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))
    if cached and cached[:3] == fp:
        return cached[3]
    out: dict[str, tuple[str, Optional[float]]] = {}
    try:
        with hpath.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.lstrip("\ufeff").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                cid = str(obj.get("conversation_id") or "").strip()
                if not cid:
                    continue
                status = str(obj.get("status") or "archived").strip().lower()
                dt = _parse_iso_ts(obj.get("ended_at") or obj.get("updated_at"))
                out[cid] = (status, dt.timestamp() if dt is not None else None)
    except OSError:
        return {}
    _cache_put(_HISTORY_ARCHIVE_CACHE, key, (*fp, out))
    return out


def _is_candidate_archived(
    rcid: str,
    mtime_ns: int,
    active_captures: dict[str, Any],
    history_map: dict[str, tuple[str, Optional[float]]],
) -> bool:
    if rcid in active_captures:
        return False
    hist = history_map.get(rcid)
    if hist is None or hist[0] != "archived":
        return False
    ended_ts = hist[1]
    return True if ended_ts is None else ((mtime_ns / 1e9) <= (ended_ts + 60.0))


def _read_first_transcript_ts(brain_root: Path, cid: str) -> str:
    tpath = brain_root / cid / ".system_generated" / "logs" / "transcript.jsonl"
    try:
        if tpath.is_symlink() or not tpath.is_file():
            return ""
        with tpath.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.lstrip("\ufeff").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        return str(obj.get("created_at") or "").strip()
                except ValueError:
                    pass
                break
    except OSError:
        pass
    return ""


def _discover_brain_sessions(
    brain_root: Path,
    active_captures: dict[str, Any],
    session_meta: dict[str, Any],
    *,
    metrics_home: Optional[Path] = None,
    explicit_cid: str = "",
) -> list[dict[str, Any]]:
    if not brain_root.is_dir():
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
        if entry.is_symlink() or not entry.is_dir() or not _UUID_LIKE_RE.match(entry.name):
            continue
        cid, sg = entry.name, entry / ".system_generated"
        if not sg.is_dir():
            continue
        node_edges = edges.setdefault(cid, set())
        if (sg / "subagents").is_dir():
            for sf in (sg / "subagents").iterdir():
                if sf.suffix == ".json" and not sf.is_symlink():
                    sdata = _read_json_cached(sf)
                    scid = str((sdata or {}).get("conversationId") or sf.stem).strip() if isinstance(sdata, dict) else ""
                    if scid and scid != cid:
                        child_cids.add(scid)
                        strong_child_cids.add(scid)
                        node_edges.add(scid)
        members_file = sg / "swarm" / "members.json"
        if members_file.is_file():
            mdata = _read_json_cached(members_file)
            for m_info in (mdata.get("members") if isinstance(mdata, dict) and isinstance(mdata.get("members"), dict) else {}).values():
                if isinstance(m_info, dict) and str(m_info.get("conversation_id") or "").strip() not in ("", cid):
                    mcid = str(m_info["conversation_id"]).strip()
                    child_cids.add(mcid)
                    strong_child_cids.add(mcid)
                    node_edges.add(mcid)
        if (sg / "tasks").is_dir():
            try:
                for tf in (sg / "tasks").iterdir():
                    if tf.name.lower().startswith("task-") and tf.suffix.lower() == ".log" and not tf.is_symlink():
                        wf_ids = _collect_wf_children_from_file(tf, cid, is_msg_json=False).keys()
                        child_cids.update(wf_ids)
                        node_edges.update(wf_ids)
            except OSError:
                pass
        if (sg / "messages").is_dir():
            try:
                for mf in (sg / "messages").iterdir():
                    if mf.suffix.lower() == ".json" and mf.name.lower() != "read.json" and not mf.is_symlink():
                        wf_ids = _collect_wf_children_from_file(mf, cid, is_msg_json=True).keys()
                        child_cids.update(wf_ids)
                        node_edges.update(wf_ids)
            except OSError:
                pass
        tpath = sg / "logs" / "transcript.jsonl"
        has_transcript = tpath.is_file() and not tpath.is_symlink()
        if has_transcript:
            tr_ids = _collect_wf_children_from_transcript(tpath, cid)
            child_cids.update(tr_ids)
            node_edges.update(tr_ids)
        if not has_transcript and cid not in active_captures:
            continue
        if has_transcript and _is_bridge_child_transcript(tpath):
            child_cids.add(cid)
            strong_child_cids.add(cid)
            continue
        mtime_ns = max((p.stat().st_mtime_ns for p in (tpath, members_file, sg / "swarm" / "board.jsonl", entry) if p.exists()), default=0)
        candidates.append({"cid": cid, "dir": entry, "sg": sg, "mtime_ns": mtime_ns})

    history_map = _load_history_status_ro(metrics_home)
    q_cid = explicit_cid.strip().lower()
    if q_cid:
        match = next((r for r in candidates if r["cid"].lower() == q_cid), None) or next(
            (r for r in sorted(candidates, key=lambda c: (-int(c["mtime_ns"]), c["cid"])) if r["cid"].lower().startswith(q_cid)),
            None,
        )
        if match is None:
            return []
        match["archived"] = _is_candidate_archived(match["cid"], int(match["mtime_ns"]), active_captures, history_map)
        return [match]

    if any(c in edges for cs in edges.values() for c in cs):
        child_cids -= find_cycle_root_overrides(
            edges, strong_child_cids, lambda c: _read_first_transcript_ts(brain_root, c)
        )

    roots = [
        it for it in candidates
        if it["cid"] not in child_cids and not (
            it["cid"] not in active_captures and _is_worktree_cwd((session_meta.get(it["cid"]) or {}).get("cwd"))
            and not (it["sg"] / "swarm").is_dir() and not (it["sg"] / "subagents").is_dir()
        )
    ]
    roots.sort(key=lambda r: (-int(r["mtime_ns"]), r["cid"]))
    now_s = datetime.now(timezone.utc).timestamp()

    for r in roots:
        r["archived"] = _is_candidate_archived(r["cid"], int(r["mtime_ns"]), active_captures, history_map)

    captured_roots = [r for r in roots if not r["archived"] and r["cid"] in active_captures]
    fresh_roots = [
        r for r in roots
        if not r["archived"]
        and r["cid"] not in active_captures
        and r["mtime_ns"] > 0
        and (now_s - (r["mtime_ns"] / 1e9)) <= LIVE_RECENT_WINDOW_S
    ]
    return (captured_roots + fresh_roots)[:MAX_ROOT_SESSIONS]


def get_live_session_state(
    session_id: str = "", since_signature: str = "", include_events: bool = True, *,
    ws: str = "", gravity_home: Optional[Path] = None, brain_dir: Optional[Path] = None,
    metrics_home: Optional[Path] = None, workflow_home: Optional[Path] = None,
    registry_path: Optional[Path] = None, home_dir: Optional[Path] = None,
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
    q_cid = session_id.strip().lower()
    roots = _discover_brain_sessions(b_dir, active_captures, session_meta, metrics_home=m_home, explicit_cid=q_cid)
    selected = roots[0] if roots else None
    sel_meta: dict[str, Any] = (session_meta.get(selected["cid"]) or {}) if selected is not None else {}
    sel_cap: Optional[dict[str, Any]] = active_captures.get(selected["cid"]) if selected is not None else None
    root_cwd = str(sel_meta.get("cwd") or "").strip() if selected is not None else ""
    root_ws = str((sel_cap or {}).get("project") or sel_meta.get("project") or _normalize_repo_name(root_cwd) or "workspace") if selected is not None else ""
    effective_ws = ws.strip() or (root_cwd or (root_ws if root_ws and root_ws != "workspace" else ""))
    wf_state = get_workflow_state(ws=effective_ws, gravity_home=gravity_home, workflow_home=workflow_home, registry_path=registry_path)
    wf_slim = {k: wf_state.get(k) for k in ("available", "stage", "progress", "mode", "level", "preset_profile", "suggested_profile", "guard_status", "nodes", "selected_workspace")}
    wf_slim["is_active"] = str(wf_slim.get("stage") or "").strip().lower() not in ("", "idle")
    sig_parts: list[Any] = [str(b_dir), q_cid, bool(include_events), stat_token(cap_path), stat_token(meta_path), stat_token(m_home / "data" / "history.jsonl"), wf_state.get("signature", ""), [(r["cid"], r["mtime_ns"], bool(r.get("archived"))) for r in roots]]
    root_task_logs_count = 0
    if selected is not None:
        desc_tokens, root_task_logs_count = collect_descendant_sig_tokens(
            b_dir,
            selected["cid"],
            read_json_fn=_read_json_cached,
            collect_wf_file_fn=lambda p, pcid, is_msg: _collect_wf_children_from_file(p, pcid, is_msg_json=is_msg),
            collect_transcript_wf_fn=_collect_wf_children_from_transcript,
            stat_token_fn=stat_token,
        )
        sig_parts.extend(desc_tokens)

    sig = short_digest(sig_parts)
    if since_signature and since_signature == sig:
        return unchanged_response(sig)
    sessions_list = [{"conversation_id": r["cid"], "label": str((active_captures.get(r["cid"]) or {}).get("label") or f"session-{r['cid'][:8]}"), "project": str((active_captures.get(r["cid"]) or {}).get("project") or (session_meta.get(r["cid"]) or {}).get("project") or _normalize_repo_name(str((session_meta.get(r["cid"]) or {}).get("cwd") or ""))), "captured": r["cid"] in active_captures, "archived": bool(r.get("archived")), "updated_at": str((active_captures.get(r["cid"]) or {}).get("updated_at") or (session_meta.get(r["cid"]) or {}).get("updated_at") or (datetime.fromtimestamp(r["mtime_ns"] / 1e9, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if r["mtime_ns"] else ""))} for r in roots]
    if selected is None:
        return {"changed": True, "unchanged": False, "signature": sig, "available": False, "brain_dir": str(b_dir), "sessions": sessions_list, "selected_session": None, "session_started_at": "", "session_last_ts": "", "agents": [], "recent_events": [], "summary": {"total_agents": 0, "active_agents": 0, "waiting_agents": 0, "done_agents": 0, "error_agents": 0, "session_started_at": "", "session_last_ts": ""}, "workflow": wf_slim}

    sel_cid, sg = selected["cid"], selected["sg"]
    root_parent = Path(_strip_file_uri(root_cwd)).parent if root_cwd else None

    members_raw, plan_raw = _read_json_cached(sg / "swarm" / "members.json"), _read_json_cached(sg / "swarm" / "plan.json")
    swarm_title = str(members_raw.get("title") or "").strip() if isinstance(members_raw, dict) else ""
    members_map = {str(k): v for k, v in members_raw["members"].items() if isinstance(v, dict)} if isinstance(members_raw, dict) and isinstance(members_raw.get("members"), dict) else {}
    plan_tasks = plan_raw.get("tasks") if isinstance(plan_raw, dict) and isinstance(plan_raw.get("tasks"), dict) else {}
    goal_title = str((plan_raw.get("goal") or {}).get("title") or "").strip() if isinstance(plan_raw, dict) and isinstance(plan_raw.get("goal"), dict) else ""

    coord_member = members_map.get("coordinator")
    root_aid = "coordinator" if coord_member is not None else f"root-{sel_cid[:8]}"
    root_acc = _read_jsonl_incremental(
        sg / "logs" / "transcript.jsonl",
        _TRANSCRIPT_CACHE,
        _new_transcript_acc,
        lambda a, o: _apply_transcript_obj(a, o, root_aid, parent_cid=sel_cid),
    )
    r_ws, r_kind = _resolve_agent_workspace(root_acc, uris=[], meta_cwd=root_cwd, root_ws=root_ws, root_parent=root_parent)

    def _read_child_transcript(c_cid: str, c_aid: str) -> dict[str, Any]:
        return _read_jsonl_incremental(
            b_dir / c_cid / ".system_generated" / "logs" / "transcript.jsonl",
            _TRANSCRIPT_CACHE,
            _new_transcript_acc,
            lambda a, o, _id=c_aid, _cid=c_cid: _apply_transcript_obj(a, o, _id, parent_cid=_cid),
        )

    agents, all_events = discover_live_tree(
        b_dir,
        sel_cid,
        root_aid=root_aid,
        root_role="Coordinator" if coord_member else "Session racine",
        root_type="coordinator" if coord_member else "root",
        root_acc=root_acc,
        coord_member=coord_member,
        root_model_hint=str((coord_member or {}).get("applied_model") or (coord_member or {}).get("model") or ""),
        root_ws=r_ws,
        root_ws_kind=r_kind,
        root_task_title=goal_title or swarm_title,
        root_parent=root_parent,
        plan_tasks=plan_tasks,
        session_meta=session_meta,
        is_archived=bool(selected.get("archived")),
        read_json_fn=_read_json_cached,
        collect_wf_file_fn=lambda p, pcid, is_msg: _collect_wf_children_from_file(p, pcid, is_msg_json=is_msg),
        read_transcript_fn=_read_child_transcript,
        resolve_ws_fn=_resolve_agent_workspace,
        build_entry_fn=_build_agent_entry,
        include_events=include_events,
    )
    root_agent = agents[0]
    if include_events:
        all_events = sorted([*all_events, *_read_board_events(sg / "swarm" / "board.jsonl", sg / "swarm" / "board.json")], key=lambda ev: str(ev.get("ts") or ""), reverse=True)[:MAX_RECENT_EVENTS]

    sc = Counter(a["status"] for a in agents)
    tot_in, tot_cache = sum(a["useful_tokens"] for a in agents), sum(a["cache_read_tokens"] for a in agents)
    start_ts_list = [str(a["started_at"]) for a in agents if a.get("started_at")]
    last_ts_list = [str(a["last_ts"]) for a in agents if a.get("last_ts")]
    session_started_at = min(start_ts_list, key=lambda s: (_parse_iso_ts(s) or datetime.max.replace(tzinfo=timezone.utc), s)) if start_ts_list else root_acc["first_ts"]
    session_last_ts = max(last_ts_list, key=lambda s: (_parse_iso_ts(s) or datetime.min.replace(tzinfo=timezone.utc), s)) if last_ts_list else root_acc["last_ts"]
    payload: dict[str, Any] = {
        "changed": True, "unchanged": False, "signature": sig, "available": True, "brain_dir": str(b_dir), "sessions": sessions_list,
        "session_started_at": session_started_at, "session_last_ts": session_last_ts,
        "selected_session": {"conversation_id": sel_cid, "label": str((sel_cap or {}).get("label") or swarm_title or goal_title or f"session-{sel_cid[:8]}"), "project": root_ws, "workspace_kind": r_kind, "captured": sel_cap is not None, "start_step": (sel_cap or {}).get("start_step"), "swarm_title": swarm_title, "goal_title": goal_title, "last_step_index": root_acc["last_step_index"], "started_at": session_started_at, "session_started_at": session_started_at, "session_last_ts": session_last_ts, "last_ts": root_acc["last_ts"]},
        "agents": agents, "recent_events": all_events if include_events else [],
        "summary": {"total_agents": len(agents), "active_agents": sc["active"], "waiting_agents": sc["waiting"], "done_agents": sc["done"], "error_agents": sc["error"], "useful_tokens": tot_in, "cache_read_tokens": tot_cache, "cache_hit_pct": round((tot_cache / (tot_in + tot_cache)) * 100.0, 2) if (tot_in + tot_cache) > 0 else 0.0, "max_context_tokens": max((a["max_context_tokens"] for a in agents), default=0), "context_tokens": root_agent["context_tokens"], "thinking_est_tokens": sum(a["thinking_est_tokens"] for a in agents), "llm_calls": sum(a["llm_calls"] for a in agents), "tool_calls": sum(a["tool_calls"] for a in agents), "error_count": sum(a["error_count"] for a in agents), "duration_s": max((a["duration_s"] for a in agents), default=0.0), "session_started_at": session_started_at, "session_last_ts": session_last_ts, "background_tasks": root_task_logs_count},
        "workflow": wf_slim,
    }
    return enforce_payload_budget(payload, ("recent_events", "agents", "sessions"), max_bytes=MAX_PAYLOAD_BYTES)

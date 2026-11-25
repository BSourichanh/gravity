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
from dashboard.providers.workflow_provider import get_workflow_state

MAX_ROOT_SESSIONS, MAX_AGENT_EVENTS, MAX_BOARD_EVENTS, MAX_RECENT_EVENTS = 25, 25, 30, 40
MAX_PAYLOAD_BYTES, MAX_CACHE_ENTRIES = 450_000, 256

_WORKTREE_RE = re.compile(r"/(?:gravity-worktrees|\.gemini/antigravity/worktrees|\.worktrees)/([^/]+)(?:/|$)", re.IGNORECASE)
_WORKTREE_SUFFIX_RE = re.compile(r"-w\d+$", re.IGNORECASE)
_REPO_MARKER_RE = re.compile(r"/([^/]+)/(?:plugin|src|tests|specs|tasks|docs|scripts|config|audits|assets|README\.md|AGENTS\.md|CHANGELOG\.md)(?:/|$)")
_CMD_CD_RE = re.compile(r"(?:^|[;&|]\s*)(?:cd|git\s+-C)\s+[\"']?([^\s\"';&|]+)", re.IGNORECASE)
_UUID_LIKE_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{12,}$|^[A-Za-z0-9._-]{4,80}$")

_TRANSCRIPT_CACHE: dict[str, dict[str, Any]] = {}
_BOARD_CACHE: dict[str, dict[str, Any]] = {}
_JSON_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_STATS: dict[str, int] = {"bytes_read": 0, "incremental_reads": 0, "full_reads": 0, "cache_hits": 0}


def reset_live_cache() -> None:
    """Clear in-memory incremental caches and counters."""
    for cache in (_TRANSCRIPT_CACHE, _BOARD_CACHE, _JSON_CACHE):
        cache.clear()
    for k in _CACHE_STATS:
        _CACHE_STATS[k] = 0


def get_live_cache_stats() -> dict[str, int]:
    """Return a copy of incremental read counters."""
    return dict(_CACHE_STATS)


def _parse_iso_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()[:-1] + "+00:00" if raw.strip().endswith("Z") else raw.strip()
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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
        if parent_posix and cleaned.startswith(parent_posix + "/"):
            rest = cleaned[len(parent_posix) + 1 :].split("/", 1)[0]
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
    return "atelier" if (root_ws and ws_name and ws_name.casefold() == root_ws.casefold()) else "code"


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


def _apply_transcript_obj(acc: dict[str, Any], obj: dict[str, Any], agent_id: str) -> None:
    ts = str(obj.get("created_at") or "").strip()
    if ts:
        acc["first_ts"] = acc["first_ts"] or ts
        acc["last_ts"] = ts
    step_idx = obj.get("step_index")
    if isinstance(step_idx, int) and not isinstance(step_idx, bool):
        acc["last_step_index"] = max(acc["last_step_index"], step_idx)
    step_type, status = str(obj.get("type") or "").strip(), str(obj.get("status") or "").strip()
    if status:
        acc["last_status"] = status
    if status.upper() in ("ERROR", "INVALID", "FAILED"):
        acc["error_count"] += 1
        acc["recent_events"].append({"ts": ts, "agent_id": agent_id, "kind": "error", "name": step_type or "STEP", "detail": status})
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
    for bucket, skip_root in ((acc["write_paths"], False), (acc["read_paths"], True)):
        repos: Counter[str] = Counter()
        for p, cnt in bucket.items():
            norm_p = p.replace("\\", "/")
            if skip_root and root_ws and (f"/{root_ws}/specs/" in norm_p or f"/{root_ws}/tasks/" in norm_p):
                continue
            repo = _normalize_repo_name(p, root_parent=root_parent)
            if repo and (not skip_root or repo.casefold() != root_ws.casefold()):
                repos[repo] += cnt
        if repos:
            ws = repos.most_common(1)[0][0]
            return ws, _classify_workspace_kind(ws, root_ws=root_ws)
    for uri in uris:
        repo = _normalize_repo_name(uri, root_parent=root_parent)
        if repo and (not root_ws or repo.casefold() != root_ws.casefold()):
            return repo, _classify_workspace_kind(repo, uri, root_ws=root_ws)
    if meta_cwd:
        repo = _normalize_repo_name(meta_cwd, root_parent=root_parent)
        if repo:
            return repo, _classify_workspace_kind(repo, meta_cwd, root_ws=root_ws)
    return root_ws or "workspace", _classify_workspace_kind(root_ws, root_ws=root_ws)


def _derive_agent_status(*, acc: dict[str, Any], member_info: Optional[dict[str, Any]], subagent_state: str, has_active_children: bool = False) -> str:
    if member_info:
        if member_info.get("killed"):
            return "error" if acc["error_count"] > 0 and acc["last_status"].upper() in ("ERROR", "FAILED") else "done"
        wake, phase, desired = str(member_info.get("wake_mode") or "").lower(), str(member_info.get("phase") or "").upper(), str(member_info.get("desired_state") or "").upper()
        if desired == "STOPPED" or phase in ("STOPPED", "DONE", "COMPLETED"):
            return "done"
        if wake == "working" or phase == "WORKING" or (phase == "RUNNING" and wake != "mentions"):
            return "active"
        if wake == "mentions" or phase == "WAITING":
            return "waiting"
    st_up = subagent_state.upper()
    if any(tok in st_up for tok in ("ERROR", "FAIL")) or acc["last_status"].upper() in ("ERROR", "INVALID", "FAILED"):
        return "error"
    if any(tok in st_up for tok in ("COMPLETE", "DONE", "KILL", "STOP")):
        return "done"
    if "ALIVE" in st_up or "RUN" in st_up or has_active_children:
        return "active"
    dt = _parse_iso_ts(acc["last_ts"])
    if dt is not None and (datetime.now(timezone.utc) - dt).total_seconds() <= 300:
        return "active"
    return "waiting" if acc["llm_calls"] > 0 else "done"


def _build_agent_entry(
    *, agent_id: str, cid: str, role: str, type_name: str, status: str,
    acc: dict[str, Any], model_hint: str, workspace: str, workspace_kind: str, task_title: str,
) -> dict[str, Any]:
    in_t, cache_t, out_t = acc["input_tokens"], acc["cache_read_tokens"], acc["output_tokens"]
    prompt_t, t0, t1 = in_t + cache_t, _parse_iso_ts(acc["first_ts"]), _parse_iso_ts(acc["last_ts"])
    return {
        "id": agent_id, "conversation_id": cid, "role": role, "type_name": type_name, "status": status,
        "model": acc["model"] or model_hint or "unknown", "workspace": workspace, "workspace_kind": workspace_kind,
        "task_title": task_title, "last_tool": acc["last_tool"], "context_tokens": acc["context_tokens"],
        "max_context_tokens": acc["max_context_tokens"], "useful_tokens": in_t + out_t, "cache_read_tokens": cache_t,
        "thinking_est_tokens": acc["thinking_chars"] // 4,
        "cache_hit_pct": round((cache_t / prompt_t) * 100.0, 2) if prompt_t > 0 else 0.0,
        "llm_calls": acc["llm_calls"], "tool_calls": acc["tool_calls"],
        "duration_s": round(max(0.0, (t1 - t0).total_seconds()), 1) if t0 and t1 else 0.0,
        "error_count": acc["error_count"], "last_ts": acc["last_ts"],
    }


def _discover_brain_sessions(brain_root: Path, active_captures: dict[str, Any], session_meta: dict[str, Any]) -> list[dict[str, Any]]:
    if not brain_root.is_dir():
        return []
    child_cids: set[str] = set()
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
        if (sg / "subagents").is_dir():
            for sf in (sg / "subagents").iterdir():
                if sf.suffix == ".json" and not sf.is_symlink():
                    sdata = _read_json_cached(sf)
                    scid = str((sdata or {}).get("conversationId") or sf.stem).strip() if isinstance(sdata, dict) else ""
                    if scid and scid != cid:
                        child_cids.add(scid)
        members_file = sg / "swarm" / "members.json"
        if members_file.is_file():
            mdata = _read_json_cached(members_file)
            for m_info in (mdata.get("members") if isinstance(mdata, dict) and isinstance(mdata.get("members"), dict) else {}).values():
                if isinstance(m_info, dict) and str(m_info.get("conversation_id") or "").strip() not in ("", cid):
                    child_cids.add(str(m_info["conversation_id"]).strip())
        tpath = sg / "logs" / "transcript.jsonl"
        if not (tpath.is_file() and not tpath.is_symlink()) and cid not in active_captures:
            continue
        mtime_ns = max((p.stat().st_mtime_ns for p in (tpath, members_file, sg / "swarm" / "board.jsonl", entry) if p.exists()), default=0)
        candidates.append({"cid": cid, "dir": entry, "sg": sg, "mtime_ns": mtime_ns})
    roots = [
        it for it in candidates
        if it["cid"] not in child_cids and not (
            it["cid"] not in active_captures and _is_worktree_cwd((session_meta.get(it["cid"]) or {}).get("cwd"))
            and not (it["sg"] / "swarm").is_dir() and not (it["sg"] / "subagents").is_dir()
        )
    ]
    roots.sort(key=lambda r: (-int(r["mtime_ns"]), r["cid"]))
    return roots[:MAX_ROOT_SESSIONS]


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
    roots = _discover_brain_sessions(b_dir, active_captures, session_meta)
    q_cid = session_id.strip().lower()
    selected = (next((r for r in roots if r["cid"].lower() == q_cid), None) or next((r for r in roots if r["cid"].lower().startswith(q_cid)), None) or roots[0]) if (roots and q_cid) else (roots[0] if roots else None)
    wf_state = get_workflow_state(ws=ws, gravity_home=gravity_home, workflow_home=workflow_home, registry_path=registry_path)
    wf_slim = {k: wf_state.get(k) for k in ("available", "stage", "progress", "mode", "level", "preset_profile", "suggested_profile", "guard_status", "nodes", "selected_workspace")}
    sig_parts: list[Any] = [str(b_dir), q_cid, bool(include_events), stat_token(cap_path), stat_token(meta_path), wf_state.get("signature", ""), [(r["cid"], r["mtime_ns"]) for r in roots[:10]]]
    subagent_files, task_logs = [], []
    if selected is not None:
        sg = selected["sg"]
        subagent_files = sorted((p for p in (sg / "subagents").iterdir() if p.suffix == ".json" and not p.is_symlink()), key=lambda p: p.name) if (sg / "subagents").is_dir() else []
        task_logs = sorted((p for p in (sg / "tasks").iterdir() if p.name.startswith("task-") and p.suffix == ".log" and not p.is_symlink()), key=lambda p: p.name) if (sg / "tasks").is_dir() else []
        sig_parts.extend([selected["cid"], stat_token(sg / "logs" / "transcript.jsonl"), stat_token(sg / "swarm" / "members.json"), stat_token(sg / "swarm" / "plan.json"), stat_token(sg / "swarm" / "board.jsonl"), stat_token(sg / "swarm" / "board.json"), [(p.name, stat_token(p)) for p in subagent_files], [(p.name, stat_token(p)) for p in task_logs]])
        for sf in subagent_files:
            sdata = _read_json_cached(sf)
            scid = str((sdata or {}).get("conversationId") or sf.stem).strip() if isinstance(sdata, dict) else sf.stem
            sig_parts.append((scid, stat_token(b_dir / scid / ".system_generated" / "logs" / "transcript.jsonl")))

    sig = short_digest(sig_parts)
    if since_signature and since_signature == sig:
        return unchanged_response(sig)
    sessions_list = [{"conversation_id": r["cid"], "label": str((active_captures.get(r["cid"]) or {}).get("label") or f"session-{r['cid'][:8]}"), "project": str((active_captures.get(r["cid"]) or {}).get("project") or (session_meta.get(r["cid"]) or {}).get("project") or _normalize_repo_name(str((session_meta.get(r["cid"]) or {}).get("cwd") or ""))), "captured": r["cid"] in active_captures, "updated_at": str((active_captures.get(r["cid"]) or {}).get("updated_at") or (session_meta.get(r["cid"]) or {}).get("updated_at") or (datetime.fromtimestamp(r["mtime_ns"] / 1e9, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if r["mtime_ns"] else ""))} for r in roots]
    if selected is None:
        return {"changed": True, "unchanged": False, "signature": sig, "available": False, "brain_dir": str(b_dir), "sessions": sessions_list, "selected_session": None, "agents": [], "recent_events": [], "summary": {"total_agents": 0, "active_agents": 0, "waiting_agents": 0, "done_agents": 0, "error_agents": 0}, "workflow": wf_slim}

    sel_cid, sg = selected["cid"], selected["sg"]
    sel_meta, sel_cap = session_meta.get(sel_cid) or {}, active_captures.get(sel_cid)
    root_cwd = str(sel_meta.get("cwd") or "").strip()
    root_ws = str((sel_cap or {}).get("project") or sel_meta.get("project") or _normalize_repo_name(root_cwd) or "workspace")
    root_parent = Path(_strip_file_uri(root_cwd)).parent if root_cwd else None

    members_raw, plan_raw = _read_json_cached(sg / "swarm" / "members.json"), _read_json_cached(sg / "swarm" / "plan.json")
    swarm_title = str(members_raw.get("title") or "").strip() if isinstance(members_raw, dict) else ""
    members_map = {str(k): v for k, v in members_raw["members"].items() if isinstance(v, dict)} if isinstance(members_raw, dict) and isinstance(members_raw.get("members"), dict) else {}
    plan_tasks = plan_raw.get("tasks") if isinstance(plan_raw, dict) and isinstance(plan_raw.get("tasks"), dict) else {}
    goal_title = str((plan_raw.get("goal") or {}).get("title") or "").strip() if isinstance(plan_raw, dict) and isinstance(plan_raw.get("goal"), dict) else ""

    subagents_by_cid = {
        str(sd.get("conversationId") or sf.stem).strip(): sd
        for sf in subagent_files for sd in [_read_json_cached(sf)]
        if isinstance(sd, dict) and str(sd.get("conversationId") or sf.stem).strip()
    }
    root_aid = "coordinator" if "coordinator" in members_map else f"root-{sel_cid[:8]}"
    root_acc = _read_jsonl_incremental(sg / "logs" / "transcript.jsonl", _TRANSCRIPT_CACHE, _new_transcript_acc, lambda a, o: _apply_transcript_obj(a, o, root_aid))
    all_events: list[dict[str, Any]] = list(root_acc["recent_events"]) if include_events else []
    seen_cids = {sel_cid}
    child_entries: list[tuple[str, str, Optional[dict[str, Any]], Optional[dict[str, Any]]]] = []
    for m_name, m_info in members_map.items():
        mcid = str(m_info.get("conversation_id") or "").strip()
        if mcid and mcid != sel_cid and m_name != "coordinator":
            seen_cids.add(mcid)
            child_entries.append((m_name, mcid, m_info, subagents_by_cid.get(mcid)))
    for scid, sdata in subagents_by_cid.items():
        if scid not in seen_cids:
            seen_cids.add(scid)
            child_entries.append((f"sub-{scid[:8]}", scid, None, sdata))

    any_child_active, child_agents = False, []
    for aid, c_cid, m_info, sdata in child_entries:
        c_acc = _read_jsonl_incremental(b_dir / c_cid / ".system_generated" / "logs" / "transcript.jsonl", _TRANSCRIPT_CACHE, _new_transcript_acc, lambda a, o, _id=aid: _apply_transcript_obj(a, o, _id))
        desc = (sdata or {}).get("subagentDescriptor") if isinstance((sdata or {}).get("subagentDescriptor"), dict) else {}
        uris = [str(u) for u in (sdata or {}).get("workspaceUris", [])] if isinstance((sdata or {}).get("workspaceUris"), list) else []
        ws_name, ws_kind = _resolve_agent_workspace(c_acc, uris=uris, meta_cwd=str((session_meta.get(c_cid) or {}).get("cwd") or ""), root_ws=root_ws, root_parent=root_parent)
        c_status = _derive_agent_status(acc=c_acc, member_info=m_info, subagent_state=str((sdata or {}).get("state") or ""))
        any_child_active = any_child_active or c_status == "active"
        child_agents.append(_build_agent_entry(
            agent_id=aid, cid=c_cid, role=str(desc.get("role") or (m_info or {}).get("role") or aid),
            type_name=str(desc.get("typeName") or (m_info or {}).get("role") or "worker"), status=c_status, acc=c_acc,
            model_hint=str((m_info or {}).get("applied_model") or (m_info or {}).get("model") or ""),
            workspace=ws_name, workspace_kind=ws_kind, task_title=str(plan_tasks.get(aid) or ""),
        ))
        if include_events:
            all_events.extend(c_acc["recent_events"])

    coord_member = members_map.get("coordinator")
    r_ws, r_kind = _resolve_agent_workspace(root_acc, uris=[], meta_cwd=root_cwd, root_ws=root_ws, root_parent=root_parent)
    root_agent = _build_agent_entry(
        agent_id=root_aid, cid=sel_cid, role="Coordinator" if coord_member else "Session racine",
        type_name="coordinator" if coord_member else "root",
        status=_derive_agent_status(acc=root_acc, member_info=coord_member, subagent_state="", has_active_children=any_child_active),
        acc=root_acc, model_hint=str((coord_member or {}).get("applied_model") or (coord_member or {}).get("model") or ""),
        workspace=r_ws, workspace_kind=r_kind, task_title=goal_title or swarm_title,
    )
    agents = [root_agent, *child_agents]
    if include_events:
        all_events = sorted([*all_events, *_read_board_events(sg / "swarm" / "board.jsonl", sg / "swarm" / "board.json")], key=lambda ev: str(ev.get("ts") or ""), reverse=True)[:MAX_RECENT_EVENTS]

    sc = Counter(a["status"] for a in agents)
    tot_in, tot_cache = sum(a["useful_tokens"] for a in agents), sum(a["cache_read_tokens"] for a in agents)
    payload: dict[str, Any] = {
        "changed": True, "unchanged": False, "signature": sig, "available": True, "brain_dir": str(b_dir), "sessions": sessions_list,
        "selected_session": {"conversation_id": sel_cid, "label": str((sel_cap or {}).get("label") or swarm_title or goal_title or f"session-{sel_cid[:8]}"), "project": root_ws, "workspace_kind": r_kind, "captured": sel_cap is not None, "start_step": (sel_cap or {}).get("start_step"), "swarm_title": swarm_title, "goal_title": goal_title, "last_step_index": root_acc["last_step_index"], "last_ts": root_acc["last_ts"]},
        "agents": agents, "recent_events": all_events if include_events else [],
        "summary": {"total_agents": len(agents), "active_agents": sc["active"], "waiting_agents": sc["waiting"], "done_agents": sc["done"], "error_agents": sc["error"], "useful_tokens": tot_in, "cache_read_tokens": tot_cache, "cache_hit_pct": round((tot_cache / (tot_in + tot_cache)) * 100.0, 2) if (tot_in + tot_cache) > 0 else 0.0, "max_context_tokens": max((a["max_context_tokens"] for a in agents), default=0), "context_tokens": root_agent["context_tokens"], "thinking_est_tokens": sum(a["thinking_est_tokens"] for a in agents), "llm_calls": sum(a["llm_calls"] for a in agents), "tool_calls": sum(a["tool_calls"] for a in agents), "error_count": sum(a["error_count"] for a in agents), "duration_s": max((a["duration_s"] for a in agents), default=0.0), "background_tasks": len(task_logs)},
        "workflow": wf_slim,
    }
    return enforce_payload_budget(payload, ("recent_events", "agents", "sessions"), max_bytes=MAX_PAYLOAD_BYTES)

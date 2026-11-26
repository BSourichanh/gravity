"""Live agent tree, clean termination, C8 workflow reader, and progress aggregation (100% stdlib)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Callable, Optional

from _shared.path_safety import is_symlink_or_junction
from _shared.transcript_reader import extract_shell_nonzero_code, parse_iso_ts
from core.registry import resolve_module_home
from dashboard.providers import read_json_ro, short_digest, stat_token

TERMINAL_TOOLS: frozenset[str] = frozenset({"finish", "post_message", "swarm_wait", "send_message"})
TERMINAL_ERROR_STATUSES: frozenset[str] = frozenset({"ERROR", "INVALID", "FAILED"})
MAX_WORKFLOW_EVENTS = 50
WF_AGENT_REF_RE = re.compile(
    r"\[agent:([^\]]+)\]\s*([^\n]*?)\s*\(([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)"
)
_WF_STATUS_WORDS: frozenset[str] = frozenset(
    {
        "started", "start", "running", "run", "waiting", "wait", "done",
        "completed", "complete", "finished", "finish", "error", "failed",
        "fail", "killed", "stopped", "stop", "idle",
    }
)
_WF_ALLOWED_TRANSCRIPT_TYPES: frozenset[str] = frozenset({"SYSTEM_MESSAGE", "GENERIC"})
_WF_IGNORED_OUTPUT_MARKERS: tuple[str, ...] = ("Showing lines ", "Command output:", "Command exited with code ")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PROGRESS_RATIO_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_DONE_STATES: frozenset[str] = frozenset({"done", "completed", "complete", "passed", "ok", "closed", "finished"})


def parse_wf_agent_refs(text: str, parent_cid: str = "", step_idx: Optional[int] = None) -> list[dict[str, Any]]:
    """Extract `[agent:type] role: state (uuid)` references from text."""
    if not text or "[agent:" not in text:
        return []
    p_low = parent_cid.strip().lower()
    refs: list[dict[str, Any]] = []
    for m in WF_AGENT_REF_RE.finditer(text):
        type_name, rest, cid = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if not cid or cid.lower() == p_low:
            continue
        if ":" in rest:
            role_part, state_part = rest.rsplit(":", 1)
            role, state = role_part.strip(), state_part.strip()
        elif rest.lower() in _WF_STATUS_WORDS:
            role, state = "", rest
        else:
            role, state = rest, ""
        refs.append({"cid": cid, "type_name": type_name, "role": role, "state": state, "spawn_step": step_idx})
    return refs


def merge_wf_ref(target: dict[str, dict[str, Any]], ref: dict[str, Any]) -> None:
    """Merge a workflow agent reference preserving earliest spawn_step and latest state."""
    cid = ref["cid"]
    existing = target.get(cid)
    if existing is None:
        target[cid] = dict(ref)
        return
    for key in ("type_name", "role"):
        if ref.get(key) and not existing.get(key):
            existing[key] = ref[key]
    if ref.get("state"):
        existing["state"] = ref["state"]
    step = ref.get("spawn_step")
    if isinstance(step, int):
        prev = existing.get("spawn_step")
        existing["spawn_step"] = step if prev is None else min(prev, step)


def _is_ignored_generic_wf_text(text: str) -> bool:
    return any(marker in text for marker in _WF_IGNORED_OUTPUT_MARKERS)


def _scan_wf_refs_recursive(
    val: Any, parent_cid: str, step_idx: Optional[int], out: dict[str, dict[str, Any]], *, filter_output_markers: bool
) -> None:
    if isinstance(val, str):
        if "[agent:" in val and not (filter_output_markers and _is_ignored_generic_wf_text(val)):
            for ref in parse_wf_agent_refs(val, parent_cid=parent_cid, step_idx=step_idx):
                merge_wf_ref(out, ref)
        return
    children = val.values() if isinstance(val, dict) else (val if isinstance(val, list) else ())
    for item in children:
        if isinstance(item, (str, dict, list)):
            _scan_wf_refs_recursive(item, parent_cid, step_idx, out, filter_output_markers=filter_output_markers)


def collect_wf_refs_from_obj(
    val: Any, parent_cid: str, step_idx: Optional[int], out: dict[str, dict[str, Any]]
) -> None:
    """Scan a transcript step dict for `[agent:...]` child refs (SYSTEM_MESSAGE or GENERIC non-tool output)."""
    if not isinstance(val, dict):
        return
    step_type = str(val.get("type") or "").strip().upper()
    if step_type not in _WF_ALLOWED_TRANSCRIPT_TYPES:
        return
    is_generic = step_type == "GENERIC"
    if is_generic and isinstance(val.get("content"), str) and _is_ignored_generic_wf_text(val["content"]):
        return
    _scan_wf_refs_recursive(val, parent_cid, step_idx, out, filter_output_markers=is_generic)


def update_termination_acc(
    acc: dict[str, Any], obj: dict[str, Any], step_type: str, status: str, shell_nonzero: bool
) -> None:
    """Update incremental clean-termination and terminal-error tracking fields on `acc`."""
    if step_type == "SYSTEM_MESSAGE":
        return
    acc["last_non_sys_type"] = step_type
    acc["last_non_sys_status"] = status
    acc["last_non_sys_shell_nonzero"] = shell_nonzero
    if step_type == "PLANNER_RESPONSE":
        acc["last_planner_status"] = status
        raw_tcs = obj.get("tool_calls") if isinstance(obj.get("tool_calls"), list) else []
        tool_names = [str(tc.get("name") or "").strip() for tc in raw_tcs if isinstance(tc, dict) and str(tc.get("name") or "").strip()]
        acc["last_planner_has_tools"] = bool(tool_names)
        acc["last_planner_terminal_tool"] = next((tn for tn in tool_names if tn in TERMINAL_TOOLS), "")
        acc["trailing_after_planner_count"] = 0
        acc["trailing_after_planner_all_clean_generic"] = False
    elif acc.get("last_planner_status") or int(acc.get("llm_calls") or 0) > 0:
        is_clean = step_type == "GENERIC" and status.upper() == "DONE" and not shell_nonzero
        cnt = int(acc.get("trailing_after_planner_count") or 0)
        acc["trailing_after_planner_all_clean_generic"] = is_clean if cnt == 0 else (bool(acc.get("trailing_after_planner_all_clean_generic")) and is_clean)
        acc["trailing_after_planner_count"] = cnt + 1


def compute_termination_flags(acc: dict[str, Any], subagent_state: str = "") -> tuple[bool, bool]:
    """Return `(clean_termination, has_terminal_error)` from incremental transcript state and subagent state."""
    st_up = subagent_state.strip().upper()
    last_ns_type = str(acc.get("last_non_sys_type") or "").strip()
    last_ns_status_up = str(acc.get("last_non_sys_status") or acc.get("last_status") or "").strip().upper()
    has_err = any(tok in st_up for tok in ("ERROR", "FAIL")) or last_ns_status_up in TERMINAL_ERROR_STATUSES or (
        last_ns_type == "GENERIC" and bool(acc.get("last_non_sys_shell_nonzero"))
    )
    if has_err or not last_ns_type:
        return False, has_err

    lp_status = str(acc.get("last_planner_status") or "").strip().upper()
    lp_has_tools = bool(acc.get("last_planner_has_tools"))
    lp_term = str(acc.get("last_planner_terminal_tool") or "").strip()
    if last_ns_type == "PLANNER_RESPONSE":
        if last_ns_status_up == "RUNNING":
            return False, False
        return ((not lp_has_tools) or (lp_status == "DONE" and lp_term in TERMINAL_TOOLS)), False
    if last_ns_type == "GENERIC":
        clean = (
            lp_status == "DONE" and lp_term in TERMINAL_TOOLS
            and int(acc.get("trailing_after_planner_count") or 0) > 0
            and bool(acc.get("trailing_after_planner_all_clean_generic"))
        )
        return clean, False
    return False, False


def derive_agent_status(
    *, acc: dict[str, Any], member_info: Optional[dict[str, Any]], subagent_state: str,
    has_active_children: bool = False, is_coordinator: bool = False, all_workers_done: bool = False, is_archived: bool = False,
) -> tuple[str, bool]:
    """Derive `(status, clean_termination)` for a live agent node."""
    clean_term, has_terminal_error = compute_termination_flags(acc, subagent_state)
    if has_terminal_error:
        return "error", False
    if is_archived:
        return "done", clean_term

    st_up = subagent_state.strip().upper()
    last_ns_up = str(acc.get("last_non_sys_status") or acc.get("last_status") or "").strip().upper()
    done_tok = any(tok in st_up for tok in ("COMPLETE", "DONE", "KILL", "STOP"))

    if member_info:
        if member_info.get("killed") or done_tok:
            return "done", clean_term
        wake = str(member_info.get("wake_mode") or "").lower()
        phase = str(member_info.get("phase") or "").upper()
        if str(member_info.get("desired_state") or "").upper() == "STOPPED" or phase in ("STOPPED", "DONE", "COMPLETED"):
            return "done", clean_term
        if is_coordinator and all_workers_done and clean_term and not has_active_children and last_ns_up != "RUNNING":
            return "done", clean_term
        if wake == "working" or phase == "WORKING" or (phase == "RUNNING" and wake != "mentions"):
            if (
                not is_coordinator and clean_term and not has_active_children and last_ns_up != "RUNNING"
                and (not acc.get("last_planner_has_tools") or str(acc.get("last_planner_terminal_tool") or "") == "finish")
            ):
                return "done", clean_term
            return "active", clean_term
        if wake == "mentions" or phase == "WAITING":
            return "waiting", clean_term

    if done_tok:
        return "done", clean_term
    if any(tok in st_up for tok in ("ALIVE", "RUN", "START")):
        return ("done" if (clean_term and last_ns_up != "RUNNING" and not has_active_children) else "active"), clean_term
    if last_ns_up == "RUNNING" or has_active_children:
        return "active", clean_term
    if clean_term:
        return "done", clean_term
    dt = parse_iso_ts(acc.get("last_ts"))
    if dt is not None and (datetime.now(timezone.utc) - dt).total_seconds() <= 300:
        return "active", clean_term
    return ("waiting" if int(acc.get("llm_calls") or 0) > 0 else "done"), clean_term


def _iter_sorted_files(directory: Path, predicate: Callable[[Path], bool]) -> list[Path]:
    if is_symlink_or_junction(directory) or not directory.is_dir():
        return []
    try:
        return sorted((p for p in directory.iterdir() if not is_symlink_or_junction(p) and predicate(p)), key=lambda p: p.name)
    except OSError:
        return []


def _iter_sg_files(sg: Path) -> tuple[list[Path], list[Path], list[Path]]:
    if is_symlink_or_junction(sg):
        return [], [], []
    return (
        _iter_sorted_files(sg / "subagents", lambda p: p.suffix == ".json"),
        _iter_sorted_files(sg / "tasks", lambda p: p.name.lower().startswith("task-") and p.suffix.lower() == ".log"),
        _iter_sorted_files(sg / "messages", lambda p: p.suffix.lower() == ".json" and p.name.lower() != "read.json"),
    )


def collect_descendant_sig_tokens(
    brain_dir: Path, root_cid: str, *, read_json_fn: Callable[[Path], Any],
    collect_wf_file_fn: Callable[[Path, str, bool], dict[str, dict[str, Any]]],
    collect_transcript_wf_fn: Callable[[Path, str], frozenset[str]],
    stat_token_fn: Callable[[Optional[Path]], str],
) -> tuple[list[Any], int]:
    """Collect BFS signature tokens across all descendants (`messages/*.json`, `tasks/`, `subagents/`, `transcript.jsonl`)."""
    seen, queue, tokens, root_task_logs_count = {root_cid}, deque([root_cid]), [], 0
    while queue:
        cid = queue.popleft()
        sg = brain_dir / cid / ".system_generated"
        subagent_files, task_logs, msg_files = _iter_sg_files(sg)
        if cid == root_cid:
            root_task_logs_count = len(task_logs)
        tpath, members_path = sg / "logs" / "transcript.jsonl", sg / "swarm" / "members.json"
        tokens.append((
            cid, stat_token_fn(tpath), stat_token_fn(members_path), stat_token_fn(sg / "swarm" / "plan.json"),
            stat_token_fn(sg / "swarm" / "board.jsonl"), stat_token_fn(sg / "swarm" / "board.json"),
            [(p.name, stat_token_fn(p)) for p in subagent_files],
            [(p.name, stat_token_fn(p)) for p in task_logs],
            [(p.name, stat_token_fn(p)) for p in msg_files],
        ))
        child_cids: list[str] = []
        mdata = read_json_fn(members_path) if members_path.is_file() else None
        if isinstance(mdata, dict) and isinstance(mdata.get("members"), dict):
            for m_name, m_info in mdata["members"].items():
                if isinstance(m_info, dict) and str(m_name) != "coordinator":
                    mcid = str(m_info.get("conversation_id") or "").strip()
                    if mcid and mcid != cid:
                        child_cids.append(mcid)
        for sf in subagent_files:
            sdata = read_json_fn(sf)
            scid = str((sdata or {}).get("conversationId") or sf.stem).strip() if isinstance(sdata, dict) else ""
            if scid and scid != cid:
                child_cids.append(scid)
        for sub_files, is_msg in ((task_logs, False), (msg_files, True)):
            for fp in sub_files:
                child_cids.extend(collect_wf_file_fn(fp, cid, is_msg).keys())
        child_cids.extend(sorted(collect_transcript_wf_fn(tpath, cid)))
        for c_cid in child_cids:
            if c_cid and c_cid not in seen:
                seen.add(c_cid); queue.append(c_cid)
    return tokens, root_task_logs_count


def _discover_node_children(
    node: dict[str, Any], brain_dir: Path, seen_cids: set[str], *,
    read_json_fn: Callable[[Path], Any], collect_wf_file_fn: Callable[[Path, str, bool], dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    cid, acc = node["cid"], node["acc"]
    sg = brain_dir / cid / ".system_generated"
    members_file = sg / "swarm" / "members.json"
    members_raw = read_json_fn(members_file) if members_file.is_file() else None
    members_map = {str(k): v for k, v in members_raw["members"].items() if isinstance(v, dict)} if isinstance(members_raw, dict) and isinstance(members_raw.get("members"), dict) else {}
    subagent_files, task_logs, msg_files = _iter_sg_files(sg)
    subagents_by_cid = {
        str(sd.get("conversationId") or sf.stem).strip(): sd
        for sf in subagent_files for sd in [read_json_fn(sf)]
        if isinstance(sd, dict) and str(sd.get("conversationId") or sf.stem).strip()
    }
    wf_refs: dict[str, dict[str, Any]] = {}
    for files, is_msg in ((task_logs, False), (msg_files, True)):
        for fp in files:
            for ref in collect_wf_file_fn(fp, cid, is_msg).values():
                merge_wf_ref(wf_refs, ref)
    for ref in (acc.get("wf_child_refs") or {}).values():
        merge_wf_ref(wf_refs, ref)

    children: list[dict[str, Any]] = []
    for m_name, m_info in members_map.items():
        mcid = str(m_info.get("conversation_id") or "").strip()
        if mcid and mcid != cid and m_name != "coordinator" and mcid not in seen_cids:
            seen_cids.add(mcid)
            wf = wf_refs.get(mcid)
            children.append({"cid": mcid, "aid": m_name, "source": "swarm", "member_info": m_info, "subagent_data": subagents_by_cid.get(mcid), "wf_ref": wf, "spawn_step": wf.get("spawn_step") if wf else None})
    for scid, sdata in subagents_by_cid.items():
        if scid not in seen_cids:
            seen_cids.add(scid)
            wf = wf_refs.get(scid)
            children.append({"cid": scid, "aid": f"sub-{scid[:8]}", "source": "subagent", "member_info": None, "subagent_data": sdata, "wf_ref": wf, "spawn_step": wf.get("spawn_step") if wf else None})
    for wcid, wf in wf_refs.items():
        if wcid not in seen_cids:
            seen_cids.add(wcid)
            children.append({"cid": wcid, "aid": f"wf-{wcid[:8]}", "source": "workflow", "member_info": None, "subagent_data": None, "wf_ref": wf, "spawn_step": wf.get("spawn_step")})
    return children


def discover_live_tree(
    brain_dir: Path, root_cid: str, *, root_aid: str, root_role: str, root_type: str, root_acc: dict[str, Any],
    coord_member: Optional[dict[str, Any]], root_model_hint: str, root_ws: str, root_ws_kind: str,
    root_task_title: str, root_parent: Optional[Path], plan_tasks: dict[str, Any], session_meta: dict[str, Any],
    is_archived: bool, read_json_fn: Callable[[Path], Any], collect_wf_file_fn: Callable[[Path, str, bool], dict[str, dict[str, Any]]],
    read_transcript_fn: Callable[[str, str], dict[str, Any]], resolve_ws_fn: Callable[..., tuple[str, str]],
    build_entry_fn: Callable[..., dict[str, Any]], include_events: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recursively discover BFS live agent tree (`depth >= 0`) with anti-cycle and bottom-up status."""
    seen_cids: set[str] = {root_cid}
    nodes: list[dict[str, Any]] = [{
        "cid": root_cid, "aid": root_aid, "role": root_role, "type_name": root_type,
        "parent_id": None, "parent_name": None, "parent_cid": None, "depth": 0, "source": "root",
        "spawn_step": None, "acc": root_acc, "member_info": coord_member, "subagent_state": "",
        "model_hint": root_model_hint, "ws_name": root_ws, "ws_kind": root_ws_kind,
        "task_title": root_task_title, "is_coordinator": coord_member is not None, "child_indices": [],
    }]
    queue: deque[int] = deque([0])
    all_events: list[dict[str, Any]] = list(root_acc.get("recent_events") or []) if include_events else []

    while queue:
        idx = queue.popleft()
        parent = nodes[idx]
        for child_spec in _discover_node_children(parent, brain_dir, seen_cids, read_json_fn=read_json_fn, collect_wf_file_fn=collect_wf_file_fn):
            c_cid, c_aid = child_spec["cid"], child_spec["aid"]
            c_acc = read_transcript_fn(c_cid, c_aid)
            if include_events:
                all_events.extend(c_acc.get("recent_events") or [])
            sdata, m_info, wf_ref = child_spec["subagent_data"], child_spec["member_info"], child_spec["wf_ref"]
            desc = (sdata or {}).get("subagentDescriptor") if isinstance((sdata or {}).get("subagentDescriptor"), dict) else {}
            uris = [str(u) for u in (sdata or {}).get("workspaceUris", [])] if isinstance((sdata or {}).get("workspaceUris"), list) else []
            ws_name, ws_kind = resolve_ws_fn(c_acc, uris=uris, meta_cwd=str((session_meta.get(c_cid) or {}).get("cwd") or ""), root_ws=root_ws, root_parent=root_parent)
            child_idx = len(nodes)
            parent["child_indices"].append(child_idx)
            nodes.append({
                "cid": c_cid, "aid": c_aid,
                "role": str(desc.get("role") or (m_info or {}).get("role") or (wf_ref or {}).get("role") or (wf_ref or {}).get("type_name") or c_aid),
                "type_name": str(desc.get("typeName") or (m_info or {}).get("role") or (wf_ref or {}).get("type_name") or ("workflow" if child_spec["source"] == "workflow" else "worker")),
                "parent_id": parent["aid"], "parent_name": parent["role"], "parent_cid": parent["cid"],
                "depth": parent["depth"] + 1, "source": child_spec["source"], "spawn_step": child_spec["spawn_step"],
                "acc": c_acc, "member_info": m_info, "subagent_state": str((sdata or {}).get("state") or (wf_ref or {}).get("state") or ""),
                "model_hint": str((m_info or {}).get("applied_model") or (m_info or {}).get("model") or ""),
                "ws_name": ws_name, "ws_kind": ws_kind, "task_title": str(plan_tasks.get(c_aid) or ""),
                "is_coordinator": False, "child_indices": [],
            })
            queue.append(child_idx)

    for node in reversed(nodes):
        child_nodes = [nodes[ci] for ci in node["child_indices"]]
        swarm_workers = [cn for cn in child_nodes if cn["source"] == "swarm"] if node["is_coordinator"] else []
        node["status"], node["clean_termination"] = derive_agent_status(
            acc=node["acc"], member_info=node["member_info"], subagent_state=node["subagent_state"],
            has_active_children=any(cn["status"] == "active" for cn in child_nodes),
            is_coordinator=node["is_coordinator"],
            all_workers_done=bool(swarm_workers) and all(cn["status"] in ("done", "error") for cn in swarm_workers),
            is_archived=is_archived,
        )

    return [
        build_entry_fn(
            agent_id=n["aid"], cid=n["cid"], role=n["role"], type_name=n["type_name"], status=n["status"],
            acc=n["acc"], model_hint=n["model_hint"], workspace=n["ws_name"], workspace_kind=n["ws_kind"],
            task_title=n["task_title"], parent_id=n["parent_id"], parent_name=n["parent_name"],
            depth=n["depth"], source=n["source"], spawn_step=n["spawn_step"],
            clean_termination=n["clean_termination"], children_count=len(n["child_indices"]),
        )
        for n in nodes
    ], all_events


def find_cycle_root_overrides(
    edges: dict[str, set[str]], strong_child_cids: set[str], first_ts_fn: Callable[[str], str]
) -> set[str]:
    """Break top-level parent-child cycles by selecting the earliest root in each source SCC."""
    nodes = set(edges.keys()) | {dst for targets in edges.values() for dst in targets}
    if not nodes:
        return set()
    index_counter, indices, lowlink, on_stack, stack, sccs = 0, {}, {}, set(), [], []
    for start in sorted(nodes):
        if start in indices:
            continue
        call_stack: list[tuple[str, list[str], int]] = [(start, sorted(edges.get(start) or ()), 0)]
        indices[start] = lowlink[start] = index_counter
        index_counter += 1
        on_stack.add(start)
        stack.append(start)
        while call_stack:
            v, nbrs, pos = call_stack[-1]
            if pos < len(nbrs):
                w = nbrs[pos]
                call_stack[-1] = (v, nbrs, pos + 1)
                if w not in indices:
                    indices[w] = lowlink[w] = index_counter
                    index_counter += 1
                    on_stack.add(w)
                    stack.append(w)
                    call_stack.append((w, sorted(edges.get(w) or ()), 0))
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])
            else:
                call_stack.pop()
                if call_stack:
                    lowlink[call_stack[-1][0]] = min(lowlink[call_stack[-1][0]], lowlink[v])
                if lowlink[v] == indices[v]:
                    comp: list[str] = []
                    w = ""
                    while w != v:
                        w = stack.pop()
                        on_stack.remove(w)
                        comp.append(w)
                    sccs.append(comp)
    overrides: set[str] = set()
    for comp in sccs:
        if len(comp) > 1 and not any(dst in set(comp) for src, targets in edges.items() if src not in set(comp) for dst in targets):
            pool = [c for c in comp if c not in strong_child_cids] or comp
            overrides.add(min(pool, key=lambda c: (first_ts_fn(c) or "~", c)))
    return overrides


def _workspace_slug_hash(workspace_root: Path) -> str:
    resolved = workspace_root.resolve()
    slug = _SLUG_RE.sub("-", resolved.name.lower()).strip("-")[:32] or "workspace"
    return f"{slug}-{hashlib.sha256(os.path.normcase(str(resolved)).encode('utf-8')).hexdigest()[:8]}"


def _norm_ws_key(raw: str) -> str:
    try:
        return os.path.normcase(str(Path(raw).expanduser().resolve()))
    except OSError:
        return os.path.normcase(raw)


def _select_c8_workspace(ws: str, workspaces: list[dict[str, Any]], wf_home: Path) -> Optional[Path]:
    query = ws.strip()
    if not query:
        return Path(workspaces[0]["state_path"]) if workspaces else None
    if query.isdigit() and 0 <= int(query) < len(workspaces):
        return Path(workspaces[int(query)]["state_path"])
    norm_q = _norm_ws_key(query)
    for item in workspaces:
        ws_val, st_val = str(item.get("workspace_path") or ""), str(item.get("state_path") or "")
        if query in (ws_val, st_val) or (ws_val and _norm_ws_key(ws_val) == norm_q):
            return Path(st_val)
    for item in workspaces:
        ws_val = str(item.get("workspace_path") or "")
        if ws_val and Path(ws_val).name.casefold() == query.casefold():
            return Path(item["state_path"])
    ws_dir = Path(query).expanduser()
    if ws_dir.is_dir() and not is_symlink_or_junction(ws_dir):
        r_ws = ws_dir.resolve()
        for cand in (
            wf_home / "workspaces" / _workspace_slug_hash(r_ws) / "live_state.json",
            r_ws / ".agents" / "gravity-workflow" / "observability" / "live_state.json",
        ):
            if cand.is_file() and not is_symlink_or_junction(cand):
                return cand.resolve()
    return None


def read_workflow_live_c8_ro(
    ws: str = "", *, gravity_home: Optional[Path] = None,
    workflow_home: Optional[Path] = None, registry_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Read C8 (`live_workspaces.json` + `live_state.json`) read-only with `"0/0"` default."""
    wf_home = Path(workflow_home).expanduser().resolve() if workflow_home is not None else resolve_module_home("workflow", env_override="GRAVITY_WORKFLOW_HOME", gravity_home=gravity_home)
    reg_file = Path(registry_path).expanduser().resolve() if registry_path is not None else (wf_home / "live_workspaces.json").resolve()
    out: dict[str, Any] = {
        "available": False, "stage": "idle", "progress": "0/0", "mode": "evo", "level": "standard",
        "preset_profile": "standard", "suggested_profile": "standard", "guard_status": "ON",
        "nodes": {"planner": "", "builder": "", "reviewer": ""}, "events": [],
        "selected_workspace": None, "waves": [], "tasks": [], "warnings": [],
    }
    if is_symlink_or_junction(wf_home) or is_symlink_or_junction(reg_file):
        out["warnings"].append("Refused symlink or junction workflow path.")
        out["signature"] = short_digest([ws.strip(), str(wf_home), "symlink"])
        return out

    workspaces: list[dict[str, Any]] = []
    if reg_file.is_file():
        reg_data, reg_warn = read_json_ro(reg_file)
        if reg_warn:
            out["warnings"].append(reg_warn)
        entries = reg_data.get("workspaces") if isinstance(reg_data, dict) and isinstance(reg_data.get("workspaces"), list) else []
        for entry in entries:
            sp = Path(str(entry.get("state_path") or "").strip()).expanduser() if isinstance(entry, dict) and str(entry.get("state_path") or "").strip() else None
            if sp is not None and sp.name == "live_state.json" and not is_symlink_or_junction(sp):
                ws_p = str(entry.get("workspace_path") or entry.get("workspace") or str(sp.parent)).strip()
                workspaces.append({"workspace_path": ws_p, "state_path": str(sp), "updated_at": str(entry.get("updated_at") or "")})
        workspaces.sort(key=lambda item: item["updated_at"], reverse=True)
    if not workspaces and (wf_home / "workspaces").is_dir() and not is_symlink_or_junction(wf_home / "workspaces"):
        try:
            for sub in sorted((wf_home / "workspaces").iterdir(), key=lambda p: p.name):
                sf = sub / "live_state.json"
                if not is_symlink_or_junction(sub) and sub.is_dir() and not is_symlink_or_junction(sf) and sf.is_file():
                    workspaces.append({"workspace_path": sub.name, "state_path": str(sf.resolve()), "updated_at": ""})
        except OSError:
            pass

    selected_file = _select_c8_workspace(ws, workspaces, wf_home)
    if selected_file is not None and (selected_file.name != "live_state.json" or is_symlink_or_junction(selected_file)):
        selected_file = None
    out["signature"] = short_digest([ws.strip(), str(wf_home), stat_token(reg_file), stat_token(selected_file), len(workspaces)])
    if selected_file is not None and selected_file.is_file():
        raw_state, st_warn = read_json_ro(selected_file)
        if st_warn:
            out["warnings"].append(st_warn)
        if isinstance(raw_state, dict):
            out["available"] = True
            for key in ("stage", "progress", "mode", "level", "preset_profile", "suggested_profile", "guard_status"):
                if isinstance(raw_state.get(key), str) and raw_state[key].strip():
                    out[key] = raw_state[key].strip()
            if isinstance(raw_state.get("nodes"), dict):
                out["nodes"] = {str(k): str(v) for k, v in raw_state["nodes"].items() if isinstance(k, str) and isinstance(v, str)}
            if isinstance(raw_state.get("events"), list):
                out["events"] = [e for e in raw_state["events"][-MAX_WORKFLOW_EVENTS:] if isinstance(e, dict)]
            for k in ("waves", "tasks"):
                if isinstance(raw_state.get(k), (list, dict)):
                    out[k] = raw_state[k]
            out["selected_workspace"] = str(selected_file.parent)
    return out


def _is_item_done(item: Any) -> bool:
    if item is True:
        return True
    if isinstance(item, str):
        return item.strip().lower() in _DONE_STATES
    if isinstance(item, dict):
        return item.get("done") is True or str(item.get("status") or "").strip().lower() in _DONE_STATES
    return False


def build_live_progress(wf_state: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate structured `waves`/`tasks` progress or parse `progress` string, defaulting to `'0/0'`."""
    if not isinstance(wf_state, dict):
        return {"label": "0/0", "done": 0, "total": 0, "pct": 0, "waves": [], "tasks": []}
    done, total = 0, 0
    raw_tasks, raw_waves = wf_state.get("tasks"), wf_state.get("waves")
    if isinstance(raw_tasks, (list, dict)) and raw_tasks:
        items = raw_tasks if isinstance(raw_tasks, list) else list(raw_tasks.values())
        total, done = len(items), sum(1 for it in items if _is_item_done(it))
    elif isinstance(raw_waves, list) and raw_waves:
        for w in raw_waves:
            if not isinstance(w, dict):
                continue
            wt = w.get("tasks")
            if isinstance(wt, (list, dict)) and wt:
                items = wt if isinstance(wt, list) else list(wt.values())
                total += len(items)
                done += sum(1 for it in items if _is_item_done(it))
            elif isinstance(w.get("total"), int) and isinstance(w.get("done"), int) and w["total"] > 0:
                total += w["total"]
                done += max(0, min(w["done"], w["total"]))
            else:
                total += 1
                done += 1 if _is_item_done(w) else 0
    elif isinstance(raw_waves, dict) and raw_waves:
        total, done = len(raw_waves), sum(1 for it in raw_waves.values() if _is_item_done(it))
    if total == 0:
        m = _PROGRESS_RATIO_RE.match(str(wf_state.get("progress") or ""))
        if m:
            done, total = int(m.group(1)), int(m.group(2))
    return {
        "label": f"{done}/{total}", "done": done, "total": total,
        "pct": round((done / total) * 100) if total > 0 else 0,
        "waves": raw_waves if isinstance(raw_waves, (list, dict)) else [],
        "tasks": raw_tasks if isinstance(raw_tasks, (list, dict)) else [],
    }


__all__ = [
    "TERMINAL_ERROR_STATUSES", "TERMINAL_TOOLS", "WF_AGENT_REF_RE", "build_live_progress", "collect_descendant_sig_tokens",
    "collect_wf_refs_from_obj", "compute_termination_flags", "derive_agent_status", "discover_live_tree", "extract_shell_nonzero_code",
    "find_cycle_root_overrides", "merge_wf_ref", "parse_iso_ts", "parse_wf_agent_refs", "read_workflow_live_c8_ro", "update_termination_acc",
]

"""Live agent tree, clean termination, and workflow progress aggregation (100% stdlib)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable, Optional

from _shared.path_safety import is_symlink_or_junction
from _shared.transcript_reader import extract_shell_nonzero_code, parse_iso_ts

TERMINAL_TOOLS: frozenset[str] = frozenset({"finish", "post_message", "swarm_wait", "send_message"})
TERMINAL_ERROR_STATUSES: frozenset[str] = frozenset({"ERROR", "INVALID", "FAILED"})
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
_PROGRESS_RATIO_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_DONE_STATES: frozenset[str] = frozenset({"done", "completed", "complete", "passed", "ok", "closed", "finished"})

CYCLE_PHASES: tuple[tuple[str, str], ...] = (
    ("conception", "Conception"),
    ("planification", "Planification"),
    ("production", "Production"),
    ("validation", "Validation"),
)
PHASE_IDS: tuple[str, ...] = ("conception", "planification", "production", "validation")
_PHASE_INDEX: dict[str, int] = {pid: idx for idx, pid in enumerate(PHASE_IDS)}
_PHASE_ALIASES: dict[str, str] = {
    "conception": "conception", "concept": "conception", "spec": "conception", "specs": "conception",
    "design": "conception", "discovery": "conception", "research": "conception",
    "planification": "planification", "plan": "planification", "planning": "planification",
    "production": "production", "prod": "production", "build": "production", "building": "production",
    "validation": "validation", "val": "validation", "verify": "validation", "verif": "validation",
    "verification": "validation", "review": "validation", "cloture": "validation",
}
_CONCEPTION_TOKENS: frozenset[str] = frozenset({
    "research", "discovery", "discover", "explore", "explorer", "conception",
    "spec_miner", "teamwork_explorer", "teamwork_spec_miner",
})
_PLAN_TOKENS: frozenset[str] = frozenset({
    "planner", "plan", "planning", "planification", "interviewer", "teamwork_interviewer",
})
_VALIDATION_TOKENS: frozenset[str] = frozenset({
    "reviewer", "review", "verifier", "verify", "verification", "auditor", "audit",
    "validation", "validate", "challenger", "code_review", "qa", "tester",
    "teamwork_reviewer", "teamwork_challenger", "teamwork_auditor",
})
_PRODUCTION_TOKENS: frozenset[str] = frozenset({
    "builder", "build", "coder", "implementer", "developer", "producer", "production",
})
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9_]+")


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
            phase=classify_agent_phase(
                {
                    "id": n["aid"], "role": n["role"], "type_name": n["type_name"],
                    "source": n["source"], "depth": n["depth"],
                    "phase_signals": n["acc"].get("phase_signals"),
                },
                default="conception" if n["depth"] == 0 else "production",
            ),
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


def normalize_phase_id(raw: Any) -> str:
    """Normalize a phase name or alias into one of the 4 canonical phase IDs, or ''."""
    cleaned = str(raw or "").strip().lower()
    if not cleaned:
        return ""
    if cleaned in _PHASE_ALIASES:
        return _PHASE_ALIASES[cleaned]
    for tok in _TOKEN_SPLIT_RE.split(cleaned):
        if tok in _PHASE_ALIASES:
            return _PHASE_ALIASES[tok]
    return ""


def classify_agent_phase(agent_or_meta: Optional[dict[str, Any]] = None, *, default: str = "production") -> str:
    """Assign an agent to one of (`conception`, `planification`, `production`, `validation`)."""
    meta = agent_or_meta if isinstance(agent_or_meta, dict) else {}
    if explicit := normalize_phase_id(meta.get("phase")):
        return explicit

    raw_fields = (
        str(meta.get("type_name") or "").strip().lower(),
        str(meta.get("role") or "").strip().lower(),
        str(meta.get("id") or meta.get("agent_id") or "").strip().lower(),
    )
    tokens: set[str] = set()
    for field in raw_fields:
        if field:
            tokens.add(field)
            tokens.update(t for t in _TOKEN_SPLIT_RE.split(field) if t)

    for token_set, phase_id in (
        (_VALIDATION_TOKENS, "validation"),
        (_PLAN_TOKENS, "planification"),
        (_CONCEPTION_TOKENS, "conception"),
        (_PRODUCTION_TOKENS, "production"),
    ):
        if tokens & token_set:
            return phase_id

    sigs = meta.get("phase_signals")
    if isinstance(sigs, dict):
        if sigs.get("production"):
            return "production"
        if sigs.get("validation"):
            return "validation"
        if sigs.get("planification"):
            return "planification"
        if sigs.get("conception"):
            return "conception"

    return normalize_phase_id(default) or "production"


def _ingest_wf_phase_signals(
    wf_state: Optional[dict[str, Any]],
    reached: list[bool],
    active_hint: list[bool],
    done_hint: list[bool],
    error_hint: list[bool],
) -> bool:
    if not isinstance(wf_state, dict):
        return False
    stage = str(wf_state.get("stage") or "").strip().lower()
    wf_active = wf_state.get("is_active") if isinstance(wf_state.get("is_active"), bool) else (stage not in ("", "idle"))
    wf_all_done = False

    if stage not in ("", "idle"):
        if stage in ("done", "completed", "workflow:done"):
            wf_all_done = True
            for i in range(4):
                reached[i] = done_hint[i] = True
        elif any(tok in stage for tok in ("refused", "timeout", "escalated", "unsafe_done")) or stage in ("error", "failed"):
            reached[3] = error_hint[3] = True
        elif any(tok in stage for tok in ("review", "remediation", "verif", "validat")):
            reached[3] = active_hint[3] = True
        elif any(tok in stage for tok in ("build", "prod", "swarm", "execut")):
            reached[2] = active_hint[2] = True
        elif "plan" in stage:
            reached[1] = active_hint[1] = True
        elif any(tok in stage for tok in ("spec", "concept", "design", "quickstart")):
            reached[0] = active_hint[0] = True

    nodes = wf_state.get("nodes")
    if isinstance(nodes, dict):
        node_map = {"planner": 1, "builder": 2, "reviewer": 3, "verifier": 3}
        for n_name, n_state in nodes.items():
            idx = node_map.get(str(n_name).strip().lower())
            if idx is None:
                continue
            st = str(n_state or "").strip().lower()
            if st in ("running", "active", "in_progress"):
                reached[idx] = active_hint[idx] = True
            elif st in _DONE_STATES:
                reached[idx] = done_hint[idx] = True
            elif st in ("error", "failed"):
                reached[idx] = error_hint[idx] = True

    if wf_active and not any(reached):
        reached[0] = active_hint[0] = True
    return wf_all_done


def _ingest_architect_phase_signals(
    architect_state: Optional[dict[str, Any]],
    reached: list[bool],
    active_hint: list[bool],
    done_hint: list[bool],
    error_hint: list[bool],
) -> None:
    if not isinstance(architect_state, dict):
        return
    c_phases = architect_state.get("cycle_phases")
    if isinstance(c_phases, list):
        for item in c_phases:
            if not isinstance(item, dict):
                continue
            pid = normalize_phase_id(item.get("id"))
            if not pid:
                continue
            idx = _PHASE_INDEX[pid]
            st = str(item.get("status") or "").strip().lower()
            if st in ("", "pending"):
                continue
            reached[idx] = True
            if st == "active":
                active_hint[idx] = True
            elif st in _DONE_STATES:
                done_hint[idx] = True
            elif st in ("error", "failed"):
                error_hint[idx] = True
    if any(reached):
        cur_arch = normalize_phase_id(architect_state.get("current_phase"))
        if cur_arch:
            reached[_PHASE_INDEX[cur_arch]] = True


def build_live_phases(
    wf_state: Optional[dict[str, Any]] = None,
    *,
    architect_state: Optional[dict[str, Any]] = None,
    agents: Sequence[dict[str, Any]] = (),
    signals: Optional[dict[str, Any]] = None,
    is_archived: bool = False,
) -> dict[str, Any]:
    """Compute ordered 4-phase progress (`conception`, `planification`, `production`, `validation`)."""
    reached = [False, False, False, False]
    active_hint = [False, False, False, False]
    done_hint = [False, False, False, False]
    error_hint = [False, False, False, False]

    if isinstance(signals, dict):
        last_sig_phase = normalize_phase_id(signals.get("last_phase"))
        for pid, idx in _PHASE_INDEX.items():
            if not signals.get(pid):
                continue
            if pid == "validation" and last_sig_phase == "production":
                continue
            reached[idx] = True

    wf_all_done = _ingest_wf_phase_signals(wf_state, reached, active_hint, done_hint, error_hint)
    _ingest_architect_phase_signals(architect_state, reached, active_hint, done_hint, error_hint)

    root_error = False
    for ag in agents:
        if not isinstance(ag, dict):
            continue
        is_root = ag.get("depth") == 0 or str(ag.get("source") or "") == "root"
        ag_st = str(ag.get("status") or "").strip().lower()
        if is_root:
            if ag_st == "error":
                root_error = True
            continue
        ag_phase = normalize_phase_id(ag.get("phase")) or classify_agent_phase(ag)
        idx = _PHASE_INDEX[ag_phase]
        reached[idx] = True
        if ag_st in ("active", "waiting"):
            active_hint[idx] = True
        elif ag_st == "error":
            error_hint[idx] = True
        elif ag_st == "done":
            done_hint[idx] = True

    has_session = bool(agents) or bool((signals or {}).get("has_session"))
    if is_archived or (wf_all_done and not any(active_hint) and not any(error_hint)):
        cur_idx = 3
        statuses = ["done", "done", "done", "done"]
    elif any(reached):
        cur_idx = max(i for i, flag in enumerate(reached) if flag)
        statuses = []
        for i in range(4):
            if i < cur_idx:
                statuses.append("done")
            elif i == cur_idx:
                if (error_hint[i] or root_error) and not active_hint[i]:
                    statuses.append("error")
                elif wf_all_done and done_hint[i] and not active_hint[i]:
                    statuses.append("done")
                else:
                    statuses.append("active")
            else:
                statuses.append("pending")
    elif has_session:
        cur_idx = 0
        statuses = ["error" if root_error else "active", "pending", "pending", "pending"]
    else:
        cur_idx = 0
        statuses = ["pending", "pending", "pending", "pending"]

    current_phase = PHASE_IDS[cur_idx]
    buckets: list[dict[str, Any]] = [
        {
            "id": pid,
            "label": label,
            "status": statuses[idx],
            "tokens": 0,
            "useful_tokens": 0,
            "agents": 0,
            "duration_s": 0.0,
        }
        for idx, (pid, label) in enumerate(CYCLE_PHASES)
    ]

    for ag in agents:
        if not isinstance(ag, dict):
            continue
        is_root = ag.get("depth") == 0 or str(ag.get("source") or "") == "root"
        ag_phase = normalize_phase_id(ag.get("phase"))
        if not ag_phase:
            ag_phase = current_phase if is_root else classify_agent_phase(ag)
        bucket = buckets[_PHASE_INDEX[ag_phase]]
        useful = max(0, int(ag.get("useful_tokens") or 0))
        if ag.get("total_tokens") is not None:
            tot = max(0, int(ag.get("total_tokens") or 0))
        else:
            tot = useful + max(0, int(ag.get("cache_read_tokens") or 0))
        dur = max(0.0, float(ag.get("duration_s") or 0.0))
        bucket["agents"] += 1
        bucket["useful_tokens"] += useful
        bucket["tokens"] += tot
        bucket["duration_s"] = round(bucket["duration_s"] + dur, 1)

    return {"phases": buckets, "current_phase": current_phase}


__all__ = [
    "CYCLE_PHASES", "PHASE_IDS", "TERMINAL_ERROR_STATUSES", "TERMINAL_TOOLS", "WF_AGENT_REF_RE",
    "build_live_phases", "build_live_progress", "classify_agent_phase", "collect_descendant_sig_tokens",
    "collect_wf_refs_from_obj", "compute_termination_flags", "derive_agent_status", "discover_live_tree",
    "extract_shell_nonzero_code", "find_cycle_root_overrides", "merge_wf_ref", "normalize_phase_id",
    "parse_iso_ts", "parse_wf_agent_refs", "update_termination_acc",
]

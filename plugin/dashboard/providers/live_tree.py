"""Autonomous live agent tree, clean termination, and status derivation (100% stdlib)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable, Optional

TERMINAL_TOOLS: frozenset[str] = frozenset({"finish", "post_message", "swarm_wait", "send_message"})
TERMINAL_ERROR_STATUSES: frozenset[str] = frozenset({"ERROR", "INVALID", "FAILED"})

_SHELL_EXIT_RE = re.compile(r"^Command exited with code (-?\d+)\b", re.MULTILINE)
WF_AGENT_REF_RE = re.compile(
    r"\[agent:([^\]]+)\]\s*([^\n]*?)\s*\(([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)"
)
_WF_STATUS_WORDS: frozenset[str] = frozenset(
    {
        "started",
        "start",
        "running",
        "run",
        "waiting",
        "wait",
        "done",
        "completed",
        "complete",
        "finished",
        "finish",
        "error",
        "failed",
        "fail",
        "killed",
        "stopped",
        "stop",
        "idle",
    }
)


def parse_iso_ts(raw: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string into an aware UTC datetime, or return None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()[:-1] + "+00:00" if raw.strip().endswith("Z") else raw.strip()
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def extract_shell_nonzero_code(content: Any) -> Optional[int]:
    """Return nonzero shell exit code from a GENERIC step header (excluding output/preview bodies)."""
    if not isinstance(content, str) or "Command exited with code " not in content:
        return None
    header = content.split("\nCommand output:", 1)[0].split("\nShowing lines ", 1)[0]
    if header.lstrip().startswith("Showing lines "):
        return None
    for m in _SHELL_EXIT_RE.finditer(header):
        code = int(m.group(1))
        if code != 0:
            return code
    return None


def parse_wf_agent_refs(text: str, parent_cid: str = "", step_idx: Optional[int] = None) -> list[dict[str, Any]]:
    """Extract `[agent:type] role: state (uuid)` references from text."""
    if not text or "[agent:" not in text:
        return []
    p_low = parent_cid.strip().lower()
    refs: list[dict[str, Any]] = []
    for m in WF_AGENT_REF_RE.finditer(text):
        type_name = m.group(1).strip()
        rest = m.group(2).strip()
        cid = m.group(3).strip()
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
    """Merge a workflow agent reference into a `cid -> ref` map preserving earliest spawn_step and latest state."""
    cid = ref["cid"]
    existing = target.get(cid)
    if existing is None:
        target[cid] = dict(ref)
        return
    if ref.get("type_name") and not existing.get("type_name"):
        existing["type_name"] = ref["type_name"]
    if ref.get("role") and not existing.get("role"):
        existing["role"] = ref["role"]
    if ref.get("state"):
        existing["state"] = ref["state"]
    step = ref.get("spawn_step")
    if isinstance(step, int):
        prev_step = existing.get("spawn_step")
        existing["spawn_step"] = step if prev_step is None else min(prev_step, step)


_WF_ALLOWED_TRANSCRIPT_TYPES: frozenset[str] = frozenset({"SYSTEM_MESSAGE", "GENERIC"})
_WF_IGNORED_OUTPUT_MARKERS: tuple[str, ...] = (
    "Showing lines ",
    "Command output:",
    "Command exited with code ",
)


def _is_ignored_generic_wf_text(text: str) -> bool:
    return any(marker in text for marker in _WF_IGNORED_OUTPUT_MARKERS)


def _scan_wf_refs_recursive(
    val: Any,
    parent_cid: str,
    step_idx: Optional[int],
    out: dict[str, dict[str, Any]],
    *,
    filter_output_markers: bool,
) -> None:
    if isinstance(val, str):
        if "[agent:" in val and not (filter_output_markers and _is_ignored_generic_wf_text(val)):
            for ref in parse_wf_agent_refs(val, parent_cid=parent_cid, step_idx=step_idx):
                merge_wf_ref(out, ref)
    elif isinstance(val, dict):
        for v in val.values():
            if isinstance(v, (str, dict, list)):
                _scan_wf_refs_recursive(v, parent_cid, step_idx, out, filter_output_markers=filter_output_markers)
    elif isinstance(val, list):
        for item in val:
            if isinstance(item, (str, dict, list)):
                _scan_wf_refs_recursive(item, parent_cid, step_idx, out, filter_output_markers=filter_output_markers)


def collect_wf_refs_from_obj(
    val: Any,
    parent_cid: str,
    step_idx: Optional[int],
    out: dict[str, dict[str, Any]],
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
    acc: dict[str, Any],
    obj: dict[str, Any],
    step_type: str,
    status: str,
    shell_nonzero: bool,
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
        tool_names = [
            str(tc.get("name") or "").strip()
            for tc in raw_tcs
            if isinstance(tc, dict) and str(tc.get("name") or "").strip()
        ]
        acc["last_planner_has_tools"] = bool(tool_names)
        acc["last_planner_terminal_tool"] = next((tn for tn in tool_names if tn in TERMINAL_TOOLS), "")
        acc["trailing_after_planner_count"] = 0
        acc["trailing_after_planner_all_clean_generic"] = False
    elif acc.get("last_planner_status") or int(acc.get("llm_calls") or 0) > 0:
        is_clean_generic = step_type == "GENERIC" and status.upper() == "DONE" and not shell_nonzero
        cnt = int(acc.get("trailing_after_planner_count") or 0)
        acc["trailing_after_planner_all_clean_generic"] = (
            is_clean_generic if cnt == 0 else (bool(acc.get("trailing_after_planner_all_clean_generic")) and is_clean_generic)
        )
        acc["trailing_after_planner_count"] = cnt + 1


def compute_termination_flags(acc: dict[str, Any], subagent_state: str = "") -> tuple[bool, bool]:
    """Return `(clean_termination, has_terminal_error)` from incremental transcript state and subagent state."""
    st_up = subagent_state.strip().upper()
    last_ns_type = str(acc.get("last_non_sys_type") or "").strip()
    last_ns_status_up = str(acc.get("last_non_sys_status") or acc.get("last_status") or "").strip().upper()
    last_ns_shell_nonzero = bool(acc.get("last_non_sys_shell_nonzero"))

    sub_err = any(tok in st_up for tok in ("ERROR", "FAIL"))
    transcript_err = last_ns_status_up in TERMINAL_ERROR_STATUSES or (
        last_ns_type == "GENERIC" and last_ns_shell_nonzero
    )
    has_terminal_error = sub_err or transcript_err
    if has_terminal_error or not last_ns_type:
        return False, has_terminal_error

    last_planner_status_up = str(acc.get("last_planner_status") or "").strip().upper()
    last_planner_has_tools = bool(acc.get("last_planner_has_tools"))
    last_planner_terminal = str(acc.get("last_planner_terminal_tool") or "").strip()

    if last_ns_type == "PLANNER_RESPONSE":
        if last_ns_status_up == "RUNNING":
            return False, False
        clean = (not last_planner_has_tools) or (
            last_planner_status_up == "DONE" and last_planner_terminal in TERMINAL_TOOLS
        )
        return clean, False

    if last_ns_type == "GENERIC":
        clean = (
            last_planner_status_up == "DONE"
            and last_planner_terminal in TERMINAL_TOOLS
            and int(acc.get("trailing_after_planner_count") or 0) > 0
            and bool(acc.get("trailing_after_planner_all_clean_generic"))
        )
        return clean, False

    return False, False


def derive_agent_status(
    *,
    acc: dict[str, Any],
    member_info: Optional[dict[str, Any]],
    subagent_state: str,
    has_active_children: bool = False,
    is_coordinator: bool = False,
    all_workers_done: bool = False,
    is_archived: bool = False,
) -> tuple[str, bool]:
    """Derive `(status, clean_termination)` for a live agent node."""
    clean_term, has_terminal_error = compute_termination_flags(acc, subagent_state)
    if has_terminal_error:
        return "error", False
    if is_archived:
        return "done", clean_term

    st_up = subagent_state.strip().upper()
    last_ns_status_up = str(acc.get("last_non_sys_status") or acc.get("last_status") or "").strip().upper()

    if member_info:
        if member_info.get("killed"):
            return "done", clean_term
        wake = str(member_info.get("wake_mode") or "").lower()
        phase = str(member_info.get("phase") or "").upper()
        desired = str(member_info.get("desired_state") or "").upper()
        if desired == "STOPPED" or phase in ("STOPPED", "DONE", "COMPLETED"):
            return "done", clean_term
        if any(tok in st_up for tok in ("COMPLETE", "DONE", "KILL", "STOP")):
            return "done", clean_term
        if is_coordinator:
            if all_workers_done and clean_term and not has_active_children and last_ns_status_up != "RUNNING":
                return "done", clean_term
        if wake == "working" or phase == "WORKING" or (phase == "RUNNING" and wake != "mentions"):
            if (
                not is_coordinator
                and clean_term
                and not has_active_children
                and last_ns_status_up != "RUNNING"
                and (not acc.get("last_planner_has_tools") or str(acc.get("last_planner_terminal_tool") or "") == "finish")
            ):
                return "done", clean_term
            return "active", clean_term
        if wake == "mentions" or phase == "WAITING":
            return "waiting", clean_term

    if any(tok in st_up for tok in ("COMPLETE", "DONE", "KILL", "STOP")):
        return "done", clean_term
    if "ALIVE" in st_up or "RUN" in st_up or "START" in st_up:
        if clean_term and last_ns_status_up != "RUNNING" and not has_active_children:
            return "done", clean_term
        return "active", clean_term
    if last_ns_status_up == "RUNNING" or has_active_children:
        return "active", clean_term
    if clean_term:
        return "done", clean_term

    dt = parse_iso_ts(acc.get("last_ts"))
    if dt is not None and (datetime.now(timezone.utc) - dt).total_seconds() <= 300:
        return "active", clean_term
    return ("waiting" if int(acc.get("llm_calls") or 0) > 0 else "done"), clean_term


def _iter_sorted_files(directory: Path, predicate: Callable[[Path], bool]) -> list[Path]:
    if not directory.is_dir():
        return []
    try:
        return sorted((p for p in directory.iterdir() if not p.is_symlink() and predicate(p)), key=lambda p: p.name)
    except OSError:
        return []


def collect_descendant_sig_tokens(
    brain_dir: Path,
    root_cid: str,
    *,
    read_json_fn: Callable[[Path], Any],
    collect_wf_file_fn: Callable[[Path, str, bool], dict[str, dict[str, Any]]],
    collect_transcript_wf_fn: Callable[[Path, str], frozenset[str]],
    stat_token_fn: Callable[[Optional[Path]], str],
) -> tuple[list[Any], int]:
    """Collect BFS signature tokens across all descendants (`messages/*.json`, `tasks/`, `subagents/`, `transcript.jsonl`)."""
    seen: set[str] = {root_cid}
    queue: deque[str] = deque([root_cid])
    tokens: list[Any] = []
    root_task_logs_count = 0

    while queue:
        cid = queue.popleft()
        sg = brain_dir / cid / ".system_generated"
        subagent_files = _iter_sorted_files(sg / "subagents", lambda p: p.suffix == ".json")
        task_logs = _iter_sorted_files(
            sg / "tasks", lambda p: p.name.lower().startswith("task-") and p.suffix.lower() == ".log"
        )
        msg_files = _iter_sorted_files(
            sg / "messages", lambda p: p.suffix.lower() == ".json" and p.name.lower() != "read.json"
        )
        if cid == root_cid:
            root_task_logs_count = len(task_logs)

        tpath = sg / "logs" / "transcript.jsonl"
        members_path = sg / "swarm" / "members.json"
        tokens.append(
            (
                cid,
                stat_token_fn(tpath),
                stat_token_fn(members_path),
                stat_token_fn(sg / "swarm" / "plan.json"),
                stat_token_fn(sg / "swarm" / "board.jsonl"),
                stat_token_fn(sg / "swarm" / "board.json"),
                [(p.name, stat_token_fn(p)) for p in subagent_files],
                [(p.name, stat_token_fn(p)) for p in task_logs],
                [(p.name, stat_token_fn(p)) for p in msg_files],
            )
        )

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
        for tf in task_logs:
            child_cids.extend(collect_wf_file_fn(tf, cid, False).keys())
        for mf in msg_files:
            child_cids.extend(collect_wf_file_fn(mf, cid, True).keys())
        child_cids.extend(sorted(collect_transcript_wf_fn(tpath, cid)))

        for c_cid in child_cids:
            if c_cid and c_cid not in seen:
                seen.add(c_cid)
                queue.append(c_cid)

    return tokens, root_task_logs_count


def _discover_node_children(
    node: dict[str, Any],
    brain_dir: Path,
    seen_cids: set[str],
    *,
    read_json_fn: Callable[[Path], Any],
    collect_wf_file_fn: Callable[[Path, str, bool], dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    cid, acc = node["cid"], node["acc"]
    sg = brain_dir / cid / ".system_generated"
    members_raw = read_json_fn(sg / "swarm" / "members.json") if (sg / "swarm" / "members.json").is_file() else None
    members_map = (
        {str(k): v for k, v in members_raw["members"].items() if isinstance(v, dict)}
        if isinstance(members_raw, dict) and isinstance(members_raw.get("members"), dict)
        else {}
    )
    subagent_files = _iter_sorted_files(sg / "subagents", lambda p: p.suffix == ".json")
    subagents_by_cid = {
        str(sd.get("conversationId") or sf.stem).strip(): sd
        for sf in subagent_files
        for sd in [read_json_fn(sf)]
        if isinstance(sd, dict) and str(sd.get("conversationId") or sf.stem).strip()
    }

    wf_refs: dict[str, dict[str, Any]] = {}
    for tf in _iter_sorted_files(
        sg / "tasks", lambda p: p.name.lower().startswith("task-") and p.suffix.lower() == ".log"
    ):
        for ref in collect_wf_file_fn(tf, cid, False).values():
            merge_wf_ref(wf_refs, ref)
    for mf in _iter_sorted_files(
        sg / "messages", lambda p: p.suffix.lower() == ".json" and p.name.lower() != "read.json"
    ):
        for ref in collect_wf_file_fn(mf, cid, True).values():
            merge_wf_ref(wf_refs, ref)
    for ref in (acc.get("wf_child_refs") or {}).values():
        merge_wf_ref(wf_refs, ref)

    children: list[dict[str, Any]] = []
    for m_name, m_info in members_map.items():
        mcid = str(m_info.get("conversation_id") or "").strip()
        if mcid and mcid != cid and m_name != "coordinator" and mcid not in seen_cids:
            seen_cids.add(mcid)
            wf = wf_refs.get(mcid)
            children.append(
                {
                    "cid": mcid,
                    "aid": m_name,
                    "source": "swarm",
                    "member_info": m_info,
                    "subagent_data": subagents_by_cid.get(mcid),
                    "wf_ref": wf,
                    "spawn_step": wf.get("spawn_step") if wf else None,
                }
            )
    for scid, sdata in subagents_by_cid.items():
        if scid not in seen_cids:
            seen_cids.add(scid)
            wf = wf_refs.get(scid)
            children.append(
                {
                    "cid": scid,
                    "aid": f"sub-{scid[:8]}",
                    "source": "subagent",
                    "member_info": None,
                    "subagent_data": sdata,
                    "wf_ref": wf,
                    "spawn_step": wf.get("spawn_step") if wf else None,
                }
            )
    for wcid, wf in wf_refs.items():
        if wcid not in seen_cids:
            seen_cids.add(wcid)
            children.append(
                {
                    "cid": wcid,
                    "aid": f"wf-{wcid[:8]}",
                    "source": "workflow",
                    "member_info": None,
                    "subagent_data": None,
                    "wf_ref": wf,
                    "spawn_step": wf.get("spawn_step"),
                }
            )
    return children


def discover_live_tree(
    brain_dir: Path,
    root_cid: str,
    *,
    root_aid: str,
    root_role: str,
    root_type: str,
    root_acc: dict[str, Any],
    coord_member: Optional[dict[str, Any]],
    root_model_hint: str,
    root_ws: str,
    root_ws_kind: str,
    root_task_title: str,
    root_parent: Optional[Path],
    plan_tasks: dict[str, Any],
    session_meta: dict[str, Any],
    is_archived: bool,
    read_json_fn: Callable[[Path], Any],
    collect_wf_file_fn: Callable[[Path, str, bool], dict[str, dict[str, Any]]],
    read_transcript_fn: Callable[[str, str], dict[str, Any]],
    resolve_ws_fn: Callable[..., tuple[str, str]],
    build_entry_fn: Callable[..., dict[str, Any]],
    include_events: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recursively discover BFS live agent tree (`depth >= 0`) with anti-cycle and bottom-up status."""
    seen_cids: set[str] = {root_cid}
    root_node: dict[str, Any] = {
        "cid": root_cid,
        "aid": root_aid,
        "role": root_role,
        "type_name": root_type,
        "parent_id": None,
        "parent_name": None,
        "parent_cid": None,
        "depth": 0,
        "source": "root",
        "spawn_step": None,
        "acc": root_acc,
        "member_info": coord_member,
        "subagent_state": "",
        "model_hint": root_model_hint,
        "ws_name": root_ws,
        "ws_kind": root_ws_kind,
        "task_title": root_task_title,
        "is_coordinator": coord_member is not None,
        "child_indices": [],
    }
    nodes: list[dict[str, Any]] = [root_node]
    queue: deque[int] = deque([0])
    all_events: list[dict[str, Any]] = list(root_acc.get("recent_events") or []) if include_events else []

    while queue:
        idx = queue.popleft()
        parent = nodes[idx]
        for child_spec in _discover_node_children(
            parent, brain_dir, seen_cids, read_json_fn=read_json_fn, collect_wf_file_fn=collect_wf_file_fn
        ):
            c_cid, c_aid = child_spec["cid"], child_spec["aid"]
            c_acc = read_transcript_fn(c_cid, c_aid)
            if include_events:
                all_events.extend(c_acc.get("recent_events") or [])
            sdata = child_spec["subagent_data"]
            m_info = child_spec["member_info"]
            wf_ref = child_spec["wf_ref"]
            desc = (sdata or {}).get("subagentDescriptor") if isinstance((sdata or {}).get("subagentDescriptor"), dict) else {}
            uris = [str(u) for u in (sdata or {}).get("workspaceUris", [])] if isinstance((sdata or {}).get("workspaceUris"), list) else []
            ws_name, ws_kind = resolve_ws_fn(
                c_acc,
                uris=uris,
                meta_cwd=str((session_meta.get(c_cid) or {}).get("cwd") or ""),
                root_ws=root_ws,
                root_parent=root_parent,
            )
            c_role = str(
                desc.get("role")
                or (m_info or {}).get("role")
                or (wf_ref or {}).get("role")
                or (wf_ref or {}).get("type_name")
                or c_aid
            )
            c_type = str(
                desc.get("typeName")
                or (m_info or {}).get("role")
                or (wf_ref or {}).get("type_name")
                or ("workflow" if child_spec["source"] == "workflow" else "worker")
            )
            sub_state = str((sdata or {}).get("state") or (wf_ref or {}).get("state") or "")
            child_idx = len(nodes)
            parent["child_indices"].append(child_idx)
            nodes.append(
                {
                    "cid": c_cid,
                    "aid": c_aid,
                    "role": c_role,
                    "type_name": c_type,
                    "parent_id": parent["aid"],
                    "parent_name": parent["role"],
                    "parent_cid": parent["cid"],
                    "depth": parent["depth"] + 1,
                    "source": child_spec["source"],
                    "spawn_step": child_spec["spawn_step"],
                    "acc": c_acc,
                    "member_info": m_info,
                    "subagent_state": sub_state,
                    "model_hint": str((m_info or {}).get("applied_model") or (m_info or {}).get("model") or ""),
                    "ws_name": ws_name,
                    "ws_kind": ws_kind,
                    "task_title": str(plan_tasks.get(c_aid) or ""),
                    "is_coordinator": False,
                    "child_indices": [],
                }
            )
            queue.append(child_idx)

    for node in reversed(nodes):
        child_nodes = [nodes[ci] for ci in node["child_indices"]]
        has_active_children = any(cn["status"] == "active" for cn in child_nodes)
        all_workers_done = False
        if node["is_coordinator"]:
            swarm_workers = [cn for cn in child_nodes if cn["source"] == "swarm"]
            all_workers_done = bool(swarm_workers) and all(cn["status"] in ("done", "error") for cn in swarm_workers)
        status, clean_term = derive_agent_status(
            acc=node["acc"],
            member_info=node["member_info"],
            subagent_state=node["subagent_state"],
            has_active_children=has_active_children,
            is_coordinator=node["is_coordinator"],
            all_workers_done=all_workers_done,
            is_archived=is_archived,
        )
        node["status"] = status
        node["clean_termination"] = clean_term

    agents = [
        build_entry_fn(
            agent_id=n["aid"],
            cid=n["cid"],
            role=n["role"],
            type_name=n["type_name"],
            status=n["status"],
            acc=n["acc"],
            model_hint=n["model_hint"],
            workspace=n["ws_name"],
            workspace_kind=n["ws_kind"],
            task_title=n["task_title"],
            parent_id=n["parent_id"],
            parent_name=n["parent_name"],
            depth=n["depth"],
            source=n["source"],
            spawn_step=n["spawn_step"],
            clean_termination=n["clean_termination"],
            children_count=len(n["child_indices"]),
        )
        for n in nodes
    ]
    return agents, all_events


def find_cycle_root_overrides(
    edges: dict[str, set[str]],
    strong_child_cids: set[str],
    first_ts_fn: Callable[[str], str],
) -> set[str]:
    """Break top-level parent-child cycles by selecting the earliest root in each source SCC."""
    nodes = set(edges.keys())
    for targets in edges.values():
        nodes.update(targets)
    if not nodes:
        return set()

    index_counter = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []

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
                    parent = call_stack[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[v])
                if lowlink[v] == indices[v]:
                    comp: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.remove(w)
                        comp.append(w)
                        if w == v:
                            break
                    sccs.append(comp)

    overrides: set[str] = set()
    for comp in sccs:
        if len(comp) <= 1:
            continue
        comp_set = set(comp)
        has_external_parent = any(
            dst in comp_set for src, targets in edges.items() if src not in comp_set for dst in targets
        )
        if has_external_parent:
            continue
        pool = [c for c in comp if c not in strong_child_cids] or comp
        chosen = min(pool, key=lambda c: (first_ts_fn(c) or "~", c))
        overrides.add(chosen)
    return overrides

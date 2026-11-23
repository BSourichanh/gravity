"""Read-only Gravity Bridge SQLite WAL provider (`?mode=ro`) for the Gravity dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Optional

from core.registry import resolve_module_home
from dashboard.providers import (
    enforce_payload_budget,
    open_sqlite_ro,
    short_digest,
    stat_token,
    truncate_preview,
    unchanged_response,
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_WORKSPACES = 200
MAX_PAYLOAD_BYTES = 450_000
ONLINE_TTL_SECONDS = 45.0
PREVIEW_MAX_CHARS = 160
JOB_STATUSES: tuple[str, ...] = (
    "queued",
    "claimed",
    "dispatched",
    "completed",
    "failed",
    "cancelled",
)


def _clamp_limit(limit: Any) -> int:
    try:
        val = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, val))


def _parse_iso_utc(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_sidecar_status(
    sidecar_id: Any,
    sidecar_last_seen_at: Any,
    now_utc: datetime,
) -> str:
    if not isinstance(sidecar_id, str) or not sidecar_id.strip():
        return "unlinked"
    seen_dt = _parse_iso_utc(sidecar_last_seen_at)
    if seen_dt is None:
        return "offline"
    age = (now_utc - seen_dt).total_seconds()
    if age <= ONLINE_TTL_SECONDS:
        return "online"
    return "offline"


def _empty_kpis() -> dict[str, Any]:
    return {
        "workspaces_count": 0,
        "online_count": 0,
        "offline_count": 0,
        "unlinked_count": 0,
        "threads_total": 0,
        "threads_open": 0,
        "threads_done": 0,
        "notify_caller_threads": 0,
        "jobs_by_status": {s: 0 for s in JOB_STATUSES},
        "outbound_jobs": 0,
        "callback_jobs": 0,
    }


def _resolve_bridge_db(
    *,
    gravity_home: Optional[Path],
    bridge_home: Optional[Path],
    db_path: Optional[Path],
) -> tuple[Path, Path]:
    if db_path is not None:
        target_db = Path(db_path).expanduser().resolve()
        return target_db.parent, target_db
    if bridge_home is not None:
        b_home = Path(bridge_home).expanduser().resolve()
        return b_home, (b_home / "bridge.db").resolve()
    b_home = resolve_module_home(
        "bridge",
        env_override="GRAVITY_BRIDGE_HOME",
        gravity_home=gravity_home,
    )
    return b_home, (b_home / "bridge.db").resolve()


def _query_workspaces_ro(
    conn: sqlite3.Connection,
    now_utc: datetime,
) -> tuple[list[dict[str, Any]], int, int, int, int]:
    rows = conn.execute(
        """
        SELECT slug, canonical_path, display_name, sidecar_id, sidecar_pid,
               sidecar_last_seen_at, project_id, created_at, last_seen_at
        FROM workspaces
        ORDER BY last_seen_at DESC, slug ASC
        """
    ).fetchall()

    total = len(rows)
    online = 0
    offline = 0
    unlinked = 0
    items: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        sc_status = _compute_sidecar_status(
            row["sidecar_id"],
            row["sidecar_last_seen_at"],
            now_utc,
        )
        if sc_status == "online":
            online += 1
        elif sc_status == "offline":
            offline += 1
        else:
            unlinked += 1

        if idx < MAX_WORKSPACES:
            items.append(
                {
                    "slug": str(row["slug"] or ""),
                    "canonical_path": str(row["canonical_path"] or ""),
                    "display_name": str(row["display_name"] or row["slug"] or ""),
                    "project_id": row["project_id"],
                    "sidecar_id": row["sidecar_id"],
                    "sidecar_pid": row["sidecar_pid"],
                    "sidecar_last_seen_at": row["sidecar_last_seen_at"],
                    "sidecar_status": sc_status,
                    "created_at": str(row["created_at"] or ""),
                    "last_seen_at": str(row["last_seen_at"] or ""),
                }
            )
    return items, total, online, offline, unlinked


def _query_threads_ro(
    conn: sqlite3.Connection,
    status_filter: str,
    eff_limit: int,
) -> tuple[list[dict[str, Any]], int, int, int, int]:
    counts_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0) AS open_cnt,
            COALESCE(SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), 0) AS done_cnt,
            COALESCE(SUM(CASE WHEN notify_caller = 1 THEN 1 ELSE 0 END), 0) AS notify_cnt
        FROM threads
        """
    ).fetchone()
    total = int(counts_row["total"] or 0) if counts_row else 0
    open_cnt = int(counts_row["open_cnt"] or 0) if counts_row else 0
    done_cnt = int(counts_row["done_cnt"] or 0) if counts_row else 0
    notify_cnt = int(counts_row["notify_cnt"] or 0) if counts_row else 0

    if status_filter:
        t_rows = conn.execute(
            """
            SELECT id, from_workspace, to_workspace, msg_type, subject, status,
                   approved, target_conversation_id, caller_conversation_id,
                   notify_caller, callback_dispatched_at, created_at, updated_at
            FROM threads
            WHERE status = ?
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (status_filter, eff_limit),
        ).fetchall()
    else:
        t_rows = conn.execute(
            """
            SELECT id, from_workspace, to_workspace, msg_type, subject, status,
                   approved, target_conversation_id, caller_conversation_id,
                   notify_caller, callback_dispatched_at, created_at, updated_at
            FROM threads
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (eff_limit,),
        ).fetchall()

    if not t_rows:
        return [], total, open_cnt, done_cnt, notify_cnt

    thread_ids = [str(r["id"]) for r in t_rows]
    placeholders = ",".join("?" for _ in thread_ids)

    msg_stats: dict[str, tuple[int, int]] = {}
    stat_rows = conn.execute(
        f"""
        SELECT thread_id,
               COUNT(*) AS msg_count,
               COALESCE(SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END), 0) AS unread_count
        FROM messages
        WHERE thread_id IN ({placeholders})
        GROUP BY thread_id
        """,
        thread_ids,
    ).fetchall()
    for sr in stat_rows:
        msg_stats[str(sr["thread_id"])] = (
            int(sr["msg_count"] or 0),
            int(sr["unread_count"] or 0),
        )

    latest_msgs: dict[str, tuple[str, str, str]] = {}
    latest_rows = conn.execute(
        f"""
        SELECT m.thread_id, m.sender_workspace, SUBSTR(m.body, 1, 512) AS body_head, m.created_at
        FROM messages m
        INNER JOIN (
            SELECT thread_id, MAX(id) AS max_id
            FROM messages
            WHERE thread_id IN ({placeholders})
            GROUP BY thread_id
        ) latest ON m.id = latest.max_id
        """,
        thread_ids,
    ).fetchall()
    for lr in latest_rows:
        latest_msgs[str(lr["thread_id"])] = (
            truncate_preview(str(lr["body_head"] or ""), PREVIEW_MAX_CHARS),
            str(lr["sender_workspace"] or ""),
            str(lr["created_at"] or ""),
        )

    threads_out: list[dict[str, Any]] = []
    for tr in t_rows:
        tid = str(tr["id"] or "")
        msg_count, unread_count = msg_stats.get(tid, (0, 0))
        preview, last_sender, last_msg_at = latest_msgs.get(tid, ("", "", ""))
        threads_out.append(
            {
                "id": tid,
                "from_workspace": str(tr["from_workspace"] or ""),
                "to_workspace": str(tr["to_workspace"] or ""),
                "msg_type": str(tr["msg_type"] or ""),
                "subject": truncate_preview(str(tr["subject"] or ""), PREVIEW_MAX_CHARS),
                "status": str(tr["status"] or ""),
                "approved": bool(tr["approved"]),
                "notify_caller": bool(tr["notify_caller"]),
                "target_conversation_id": tr["target_conversation_id"],
                "caller_conversation_id": tr["caller_conversation_id"],
                "callback_dispatched_at": tr["callback_dispatched_at"],
                "created_at": str(tr["created_at"] or ""),
                "updated_at": str(tr["updated_at"] or ""),
                "message_count": msg_count,
                "unread_count": unread_count,
                "preview": preview,
                "last_sender_workspace": last_sender,
                "last_message_at": last_msg_at,
            }
        )

    return threads_out, total, open_cnt, done_cnt, notify_cnt


def _query_jobs_ro(
    conn: sqlite3.Connection,
    eff_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int], int, int]:
    by_status: dict[str, int] = {s: 0 for s in JOB_STATUSES}
    for sr in conn.execute("SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status").fetchall():
        st_key = str(sr["status"] or "")
        if st_key:
            by_status[st_key] = int(sr["cnt"] or 0)

    dir_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN direction = 'outbound' THEN 1 ELSE 0 END), 0) AS outbound_cnt,
            COALESCE(SUM(CASE WHEN direction = 'callback' THEN 1 ELSE 0 END), 0) AS callback_cnt
        FROM jobs
        """
    ).fetchone()
    outbound_cnt = int(dir_row["outbound_cnt"] or 0) if dir_row else 0
    callback_cnt = int(dir_row["callback_cnt"] or 0) if dir_row else 0

    j_rows = conn.execute(
        """
        SELECT id, thread_id, message_id, target_workspace, action, direction, model,
               sidecar_id, target_conversation_id, status, exit_code,
               SUBSTR(COALESCE(error_summary, ''), 1, 512) AS err_head,
               claimed_at, dispatched_at, finished_at, created_at
        FROM jobs
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (eff_limit,),
    ).fetchall()

    jobs_out: list[dict[str, Any]] = []
    for jr in j_rows:
        err_txt = truncate_preview(str(jr["err_head"] or ""), PREVIEW_MAX_CHARS)
        jobs_out.append(
            {
                "id": str(jr["id"] or ""),
                "thread_id": str(jr["thread_id"] or ""),
                "message_id": jr["message_id"],
                "target_workspace": str(jr["target_workspace"] or ""),
                "action": str(jr["action"] or ""),
                "direction": str(jr["direction"] or "outbound"),
                "model": jr["model"],
                "sidecar_id": jr["sidecar_id"],
                "target_conversation_id": jr["target_conversation_id"],
                "status": str(jr["status"] or ""),
                "exit_code": jr["exit_code"],
                "error_summary": err_txt or None,
                "claimed_at": jr["claimed_at"],
                "dispatched_at": jr["dispatched_at"],
                "finished_at": jr["finished_at"],
                "created_at": str(jr["created_at"] or ""),
            }
        )

    return jobs_out, by_status, outbound_cnt, callback_cnt


def _bridge_signature(
    target_db: Path,
    wal_path: Path,
    shm_path: Path,
    status_clean: str,
    eff_limit: int,
) -> str:
    return short_digest(
        [
            str(target_db),
            stat_token(target_db),
            stat_token(wal_path),
            stat_token(shm_path),
            status_clean,
            eff_limit,
        ]
    )


def get_bridge_state(
    since_signature: str = "",
    status: str = "",
    limit: int = DEFAULT_LIMIT,
    *,
    gravity_home: Optional[Path] = None,
    bridge_home: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return read-only Gravity Bridge workspaces, threads, jobs, and KPIs via `?mode=ro`."""
    b_home, target_db = _resolve_bridge_db(
        gravity_home=gravity_home,
        bridge_home=bridge_home,
        db_path=db_path,
    )
    wal_path = Path(f"{target_db}-wal")
    shm_path = Path(f"{target_db}-shm")
    status_clean = str(status or "").strip().lower()
    eff_limit = _clamp_limit(limit)

    pre_sig = _bridge_signature(target_db, wal_path, shm_path, status_clean, eff_limit)
    if since_signature and since_signature == pre_sig:
        return unchanged_response(pre_sig)

    warnings: list[str] = []
    kpis = _empty_kpis()
    workspaces: list[dict[str, Any]] = []
    threads: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    available = False

    conn = open_sqlite_ro(target_db, warnings) if target_db.is_file() else None
    if conn is not None:
        try:
            now_utc = datetime.now(timezone.utc)
            workspaces, ws_total, online, offline, unlinked = _query_workspaces_ro(conn, now_utc)
            threads, th_total, th_open, th_done, th_notify = _query_threads_ro(
                conn, status_clean, eff_limit
            )
            jobs, jobs_by_status, outbound_cnt, callback_cnt = _query_jobs_ro(conn, eff_limit)
            kpis = {
                "workspaces_count": ws_total,
                "online_count": online,
                "offline_count": offline,
                "unlinked_count": unlinked,
                "threads_total": th_total,
                "threads_open": th_open,
                "threads_done": th_done,
                "notify_caller_threads": th_notify,
                "jobs_by_status": jobs_by_status,
                "outbound_jobs": outbound_cnt,
                "callback_jobs": callback_cnt,
            }
            available = True
        except sqlite3.Error as exc:
            warnings.append(f"SQLite read-only query error in {target_db.name}: {exc}")
            workspaces = []
            threads = []
            jobs = []
            kpis = _empty_kpis()
        finally:
            conn.close()

    # Recompute after closing SQLite so WAL/SHM attachment on initial RO read is reflected in `signature`.
    sig = _bridge_signature(target_db, wal_path, shm_path, status_clean, eff_limit)

    payload: dict[str, Any] = {
        "changed": True,
        "unchanged": False,
        "signature": sig,
        "available": available,
        "bridge_home": str(b_home),
        "db_path": str(target_db),
        "filters": {"status": status_clean, "limit": eff_limit},
        "truncated": False,
        "kpis": kpis,
        "workspaces": workspaces,
        "threads": threads,
        "jobs": jobs,
        "warnings": warnings,
    }
    return enforce_payload_budget(
        payload,
        ("threads", "jobs", "workspaces"),
        max_bytes=MAX_PAYLOAD_BYTES,
    )

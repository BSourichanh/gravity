"""Read-only Gravity Architect Hot/Cold atelier & code audits provider for the Gravity dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Optional

from core.registry import resolve_gravity_home, resolve_module_home
from dashboard.providers import (
    clean_md_inline,
    enforce_payload_budget,
    extract_md_excerpt,
    extract_md_title,
    extract_md_verdict,
    file_uri_if_exists,
    read_json_ro,
    short_digest,
    stat_token,
    truncate_preview,
    unchanged_response,
)

MAX_PAYLOAD_BYTES = 450_000
MAX_HEAD_BYTES = 32_768
MAX_ECOSYSTEM_BYTES = 65_536
ATELIERS_REGISTRY_FILENAME = "ateliers.json"

_HYGIENE_BLOCK_RE = re.compile(
    r"<!--\s*AUTO:START:ecosystem-hygiene\s*-->(.*?)<!--\s*AUTO:END:ecosystem-hygiene\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_PROJECTS_BLOCK_RE = re.compile(
    r"<!--\s*AUTO:START:ecosystem-projects\s*-->(.*?)<!--\s*AUTO:END:ecosystem-projects\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_HYGIENE_HEADING_RE = re.compile(
    r"(?:^|\n)#{2,3}\s+Alertes\s+hygi[eè]ne[^\n]*\n(.*?)(?=\n#{1,3}\s+|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_DELTA_DATE_RE = re.compile(r"^\s*-\s*\*\*Date\s*:\*\*\s*`?([^`\n]+)`?", re.MULTILINE | re.IGNORECASE)
_DELTA_STATUS_RE = re.compile(
    r"^\s*-\s*\*\*Statut\s+[ée]ditorial\s*:\*\*\s*`?([^`\n]+)`?",
    re.MULTILINE | re.IGNORECASE,
)
_DELTA_WATCHES_RE = re.compile(r"^\s*-\s*\*\*Veilles\s*:\*\*\s*`?([^`\n]+)`?", re.MULTILINE | re.IGNORECASE)
_DELTA_TARGETS_RE = re.compile(
    r"^\s*-\s*\*\*Cibles\s+[ée]ditoriales\s+LLM\s*:\*\*\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_STATUS_LINE_RE = re.compile(
    r"^\s*-\s*\*\*(?:Date\s*/\s*)?Statut\s*:\*\*\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_TARGET_LINE_RE = re.compile(
    r"^\s*-\s*\*\*(?:D[ée]p[ôo]t\s+cible|Projets?\s+impact[ée]s?|Cible)\s*:\*\*\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_WAVE_LINE_RE = re.compile(r"^\s*-\s*\*\*Vague\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_DEPS_LINE_RE = re.compile(r"^\s*-\s*\*\*D[ée]pendances\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_PROFILE_LINE_RE = re.compile(r"^\s*-\s*\*\*Profil\s+workflow\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_SPEC_SOURCE_LINE_RE = re.compile(r"^\s*-\s*\*\*Spec\s+source\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_BRANCH_LINE_RE = re.compile(r"^\s*-\s*\*\*Branche\s+attendue\s*:\*\*\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
_NO_HYGIENE_ALERT_RE = re.compile(r"aucune alerte d'hygi[eè]ne", re.IGNORECASE)


def _has_atelier_markers(candidate: Path, *, require_both: bool = False) -> bool:
    try:
        if candidate.is_symlink() or not candidate.is_dir():
            return False
        has_eco = (candidate / "ECOSYSTEM.md").is_file()
        has_proj = (candidate / "projects.json").is_file()
        if require_both:
            return has_eco and has_proj
        return has_eco or has_proj
    except OSError:
        return False


def _norm_path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(str(path))


def _resolve_raw_architect_home(
    *,
    gravity_home: Optional[Path],
    architect_home: Optional[Path],
) -> Path:
    if architect_home is not None:
        return Path(architect_home).expanduser()
    env_arch = os.environ.get("GRAVITY_ARCHITECT_HOME", "").strip()
    if env_arch:
        return Path(env_arch).expanduser()
    return resolve_gravity_home(gravity_home) / "architect"


def _load_registered_ateliers_ro(
    reg_path: Path,
    warnings: list[str],
) -> list[dict[str, Any]]:
    try:
        if reg_path.parent.is_symlink() or reg_path.is_symlink():
            warnings.append(f"Ignored symlinked ateliers registry: {reg_path}.")
            return []
        if not reg_path.is_file():
            return []
    except OSError:
        return []

    data, read_warn = read_json_ro(reg_path)
    if read_warn:
        warnings.append(read_warn)
    if not isinstance(data, dict):
        if data is not None:
            warnings.append("Invalid structure in ateliers.json: expected JSON object.")
        return []

    entries = data.get("ateliers")
    if not isinstance(entries, list):
        warnings.append("Invalid 'ateliers' field in ateliers.json: expected list.")
        return []

    collected: list[dict[str, Any]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        raw_ws = str(raw.get("workspace_path") or "").strip()
        if not raw_ws:
            continue
        candidate = Path(raw_ws).expanduser()
        if not _has_atelier_markers(candidate, require_both=True):
            continue
        resolved = candidate.resolve()
        ws_name = str(raw.get("workspace_name") or "").strip() or resolved.name
        updated_at = str(raw.get("updated_at") or "").strip()
        collected.append(
            {
                "workspace_path": str(resolved),
                "workspace_name": ws_name,
                "updated_at": updated_at,
                "source": "architect_registry",
            }
        )

    collected.sort(
        key=lambda item: (str(item.get("updated_at") or ""), str(item.get("workspace_path") or "")),
        reverse=True,
    )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in collected:
        key = _norm_path_key(Path(item["workspace_path"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _discover_from_registry_ro(
    *,
    gravity_home: Optional[Path],
    architect_home: Optional[Path],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], Path]:
    raw_home = _resolve_raw_architect_home(
        gravity_home=gravity_home,
        architect_home=architect_home,
    )
    reg_path = raw_home / ATELIERS_REGISTRY_FILENAME
    return _load_registered_ateliers_ro(reg_path, warnings), reg_path


def _resolve_atelier_root(
    *,
    atelier: str,
    ws: str,
    gravity_home: Optional[Path],
    architect_home: Optional[Path],
    architect_workspace: Optional[Path],
    registry_ateliers: list[dict[str, Any]],
    warnings: list[str],
) -> tuple[Path, str, bool]:
    if architect_workspace is not None:
        return Path(architect_workspace).expanduser().resolve(), "arg_workspace", False

    selected = atelier.strip()
    if selected:
        cand = Path(selected).expanduser()
        if _has_atelier_markers(cand, require_both=True):
            return cand.resolve(), "selected_atelier", False
        cand_key = _norm_path_key(cand) if not cand.is_symlink() else ""
        if cand_key:
            for known in registry_ateliers:
                known_path = Path(str(known.get("workspace_path") or ""))
                if _norm_path_key(known_path) == cand_key and _has_atelier_markers(known_path, require_both=True):
                    return known_path.resolve(), "selected_atelier", False
        warnings.append(
            f"Atelier sélectionné invalide, symlink ou sans ECOSYSTEM.md + projects.json : {selected!r}."
        )
        return cand, "selected_atelier", True

    env_ws = os.environ.get("GRAVITY_ARCHITECT_WORKSPACE", "").strip()
    if env_ws:
        return Path(env_ws).expanduser().resolve(), "env_workspace", False

    if architect_home is not None:
        arch_arg = Path(architect_home).expanduser().resolve()
        if _has_atelier_markers(arch_arg, require_both=False):
            return arch_arg, "architect_home", False

    env_arch = os.environ.get("GRAVITY_ARCHITECT_HOME", "").strip()
    if env_arch:
        arch_env_path = Path(env_arch).expanduser().resolve()
        if _has_atelier_markers(arch_env_path, require_both=False):
            return arch_env_path, "env_architect_home", False

    ws_hint = ws.strip()
    if ws_hint:
        ws_cand = Path(ws_hint).expanduser()
        if _has_atelier_markers(ws_cand, require_both=True):
            return ws_cand.resolve(), "ws_hint", False

    if registry_ateliers:
        return Path(registry_ateliers[0]["workspace_path"]), "architect_registry", False

    if architect_home is not None:
        return Path(architect_home).expanduser().resolve(), "module_home", False

    fallback = resolve_module_home(
        "architect",
        env_override="GRAVITY_ARCHITECT_HOME",
        gravity_home=gravity_home,
    )
    return fallback, "module_home", False


def _read_head_text_ro(path: Path, max_bytes: int = MAX_HEAD_BYTES) -> Optional[tuple[str, int, str]]:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        st = path.stat()
        with path.open("rb") as fh:
            raw = fh.read(max_bytes)
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
    updated_at = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return text, int(st.st_size), updated_at


def _extract_bullet_alerts(block: str) -> list[str]:
    alerts: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line.startswith(("-", "*")):
            continue
        cleaned = clean_md_inline(line[1:].strip())
        if not cleaned or _NO_HYGIENE_ALERT_RE.search(cleaned):
            continue
        alerts.append(truncate_preview(cleaned, 200))
    return alerts


def _empty_ecosystem(budget_bytes: Optional[int] = None) -> dict[str, Any]:
    return {
        "exists": False,
        "size_bytes": 0,
        "budget_bytes": budget_bytes,
        "over_budget": False,
        "updated_at": "",
        "uri": "",
        "alerts": [],
        "projects_status": {},
    }


def _parse_ecosystem_projects_table(text: str) -> dict[str, dict[str, str]]:
    m_block = _PROJECTS_BLOCK_RE.search(text)
    if not m_block:
        return {}
    out: dict[str, dict[str, str]] = {}
    for raw_line in m_block.group(1).splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
            continue
        first_clean = clean_md_inline(cells[0])
        first_low = first_clean.lower()
        if first_low in ("projet", "project"):
            continue
        m_id = re.search(r"\(\s*(?:\.\./)?([A-Za-z0-9._-]+)\s*\)", first_clean)
        if m_id:
            pid = m_id.group(1).strip()
        elif len(cells) >= 6 and (m_card := re.search(r"([A-Za-z0-9._-]+)\.md", cells[5])):
            pid = m_card.group(1).strip()
        else:
            pid = re.sub(r"[^a-z0-9._-]+", "-", first_low).strip("-")
        if not pid:
            continue
        label = clean_md_inline(re.sub(r"\([^)]*\)", "", cells[0])).strip() or pid
        out[pid] = {
            "id": pid,
            "label": label,
            "release_main": clean_md_inline(cells[1]),
            "dev_status": clean_md_inline(cells[2]),
            "installed_version": clean_md_inline(cells[3]),
            "wip_status": clean_md_inline(cells[4]),
        }
    return out


def _empty_delta() -> dict[str, Any]:
    return {
        "exists": False,
        "date": "",
        "editorial_status": "",
        "watches_status": "",
        "editorial_targets": [],
        "hygiene_alerts": [],
        "uri": "",
    }


def _read_ecosystem_ro(eco_path: Path, budget_bytes: Optional[int]) -> dict[str, Any]:
    uri = file_uri_if_exists(eco_path)
    loaded = _read_head_text_ro(eco_path, MAX_ECOSYSTEM_BYTES)
    if loaded is None:
        return _empty_ecosystem(budget_bytes)
    text, size_bytes, updated_at = loaded
    m_block = _HYGIENE_BLOCK_RE.search(text)
    if not m_block:
        m_block = _HYGIENE_HEADING_RE.search(text)
    alerts = _extract_bullet_alerts(m_block.group(1)) if m_block else []
    projects_status = _parse_ecosystem_projects_table(text)
    over_budget = bool(budget_bytes and size_bytes > budget_bytes)
    return {
        "exists": True,
        "size_bytes": size_bytes,
        "budget_bytes": budget_bytes,
        "over_budget": over_budget,
        "updated_at": updated_at,
        "uri": uri,
        "alerts": alerts,
        "projects_status": projects_status,
    }


def _read_delta_ro(delta_path: Path) -> dict[str, Any]:
    uri = file_uri_if_exists(delta_path)
    loaded = _read_head_text_ro(delta_path, MAX_HEAD_BYTES)
    if loaded is None:
        return _empty_delta()
    text, _size_bytes, _updated_at = loaded
    date_m = _DELTA_DATE_RE.search(text)
    stat_m = _DELTA_STATUS_RE.search(text)
    watch_m = _DELTA_WATCHES_RE.search(text)
    tgt_m = _DELTA_TARGETS_RE.search(text)

    targets: list[str] = []
    if tgt_m:
        raw_t = clean_md_inline(tgt_m.group(1))
        if raw_t and raw_t.lower() != "aucune":
            targets = [item.strip() for item in raw_t.split(",") if item.strip()]

    hygiene_m = _HYGIENE_HEADING_RE.search(text)
    hygiene_alerts = _extract_bullet_alerts(hygiene_m.group(1)) if hygiene_m else []

    return {
        "exists": True,
        "date": date_m.group(1).strip() if date_m else "",
        "editorial_status": stat_m.group(1).strip() if stat_m else "",
        "watches_status": watch_m.group(1).strip() if watch_m else "",
        "editorial_targets": targets,
        "hygiene_alerts": hygiene_alerts,
        "uri": uri,
    }


def _read_projects_ro(
    projects_path: Path,
    atelier_root: Path,
    warnings: list[str],
) -> tuple[bool, str, bool, dict[str, int], int, list[dict[str, Any]]]:
    if projects_path.is_symlink() or not projects_path.is_file():
        return False, "", False, {}, 0, []

    data, read_warn = read_json_ro(projects_path)
    if read_warn:
        warnings.append(read_warn)
    if not isinstance(data, dict):
        if data is not None:
            warnings.append("Invalid structure in projects.json: expected JSON object.")
        return False, "", False, {}, 0, []

    workspace_name = str(data.get("workspace_name") or "").strip()
    privacy = data.get("privacy") if isinstance(data.get("privacy"), dict) else {}
    public_mode = bool(privacy.get("public_mode", False))

    raw_budgets = data.get("hot_budgets") if isinstance(data.get("hot_budgets"), dict) else {}
    hot_budgets: dict[str, int] = {}
    for k, v in raw_budgets.items():
        if isinstance(k, str) and isinstance(v, int):
            hot_budgets[k] = v

    card_budget = hot_budgets.get("project_card_max_bytes")
    watches_raw = data.get("watches")
    watches_count = len(watches_raw) if isinstance(watches_raw, list) else 0

    projects_out: list[dict[str, Any]] = []
    for raw in data.get("projects") or []:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "").strip()
        if not pid:
            continue
        card_path = atelier_root / "tracking" / "projects" / f"{pid}.md"
        card_uri = file_uri_if_exists(card_path)
        card_bytes = 0
        if card_path.is_file() and not card_path.is_symlink():
            try:
                card_bytes = int(card_path.stat().st_size)
            except OSError:
                card_bytes = 0
        dev_branch = str(raw.get("default_dev_branch") or raw.get("dev_branch") or "dev")
        projects_out.append(
            {
                "id": pid,
                "name": str(raw.get("name") or pid),
                "path": str(raw.get("path") or raw.get("repo_path") or ""),
                "role": str(raw.get("role") or ""),
                "main_branch": str(raw.get("main_branch") or raw.get("branch") or "main"),
                "default_dev_branch": dev_branch,
                "dev_branch": dev_branch,
                "card_uri": card_uri,
                "card_bytes": card_bytes,
                "over_budget": bool(card_budget and card_bytes > card_budget),
            }
        )

    return True, workspace_name, public_mode, hot_budgets, watches_count, projects_out


def _normalize_status_code(status_val: str) -> str:
    low = status_val.strip().lower()
    if not low or low == "unknown":
        return "unknown"
    tail = re.sub(r"^\d{4}-\d{2}-\d{2}\s*(?:[—–-]|/)?\s*", "", low).strip()
    candidate = tail or low
    for code in (
        "ready",
        "validated",
        "draft",
        "backlog",
        "in_progress",
        "in-progress",
        "running",
        "blocked",
        "done",
        "completed",
        "archived",
        "pending",
    ):
        if re.search(rf"\b{re.escape(code)}\b", candidate):
            return code.replace("-", "_")
    m = re.match(r"([a-z0-9_-]+)", candidate)
    return m.group(1) if m else "unknown"


def _parse_dependencies_list(raw: str) -> list[str]:
    cleaned = clean_md_inline(raw)
    if cleaned.lower() in ("", "aucune", "none", "n/a", "-"):
        return []
    return [
        tok.strip()
        for tok in re.split(r"[,|;]+", cleaned)
        if tok.strip() and tok.strip().lower() not in ("aucune", "none", "n/a", "-")
    ]


def _scan_flat_artifacts_ro(directory: Path, atelier_root: Path) -> list[dict[str, Any]]:
    if directory.is_symlink() or not directory.is_dir():
        return []
    try:
        candidates = sorted(directory.iterdir(), key=lambda p: p.name, reverse=True)
    except OSError:
        return []

    items: list[dict[str, Any]] = []
    for fpath in candidates:
        if fpath.is_symlink() or not fpath.is_file():
            continue
        if fpath.suffix.lower() != ".md" or fpath.name.startswith("_"):
            continue
        loaded = _read_head_text_ro(fpath, MAX_HEAD_BYTES)
        if loaded is None:
            continue
        text, size_bytes, updated_at = loaded
        date_m = _DATE_PREFIX_RE.match(fpath.name)
        status_m = _STATUS_LINE_RE.search(text)
        target_m = _TARGET_LINE_RE.search(text)
        wave_m = _WAVE_LINE_RE.search(text)
        deps_m = _DEPS_LINE_RE.search(text)
        profile_m = _PROFILE_LINE_RE.search(text)
        spec_src_m = _SPEC_SOURCE_LINE_RE.search(text)
        branch_m = _BRANCH_LINE_RE.search(text)

        status_val = clean_md_inline(status_m.group(1)) if status_m else "unknown"
        target_val = ""
        if target_m:
            raw_tgt = re.sub(r"\*?\([^)]*\)\*?", "", target_m.group(1)).strip()
            target_val = clean_md_inline(raw_tgt)
        wave_val: Optional[int] = None
        if wave_m:
            w_digits = re.search(r"\d+", clean_md_inline(wave_m.group(1)))
            if w_digits:
                wave_val = int(w_digits.group(0))
        spec_source = ""
        if spec_src_m:
            raw_spec = spec_src_m.group(1).strip()
            link_m = re.search(r"\[[^\]]*\]\(([^)]+)\)", raw_spec)
            spec_source = link_m.group(1).strip() if link_m else clean_md_inline(raw_spec)
        try:
            rel_path = fpath.resolve().relative_to(atelier_root.resolve()).as_posix()
        except (OSError, ValueError):
            rel_path = fpath.name
        items.append(
            {
                "filename": fpath.name,
                "rel_path": rel_path,
                "title": extract_md_title(text, fpath.stem),
                "date": date_m.group(1) if date_m else updated_at[:10],
                "status": status_val,
                "status_code": _normalize_status_code(status_val),
                "target_project": target_val,
                "wave": wave_val,
                "dependencies": _parse_dependencies_list(deps_m.group(1)) if deps_m else [],
                "workflow_profile": clean_md_inline(profile_m.group(1)) if profile_m else "",
                "spec_source": spec_source,
                "expected_branch": clean_md_inline(branch_m.group(1)) if branch_m else "",
                "size_bytes": size_bytes,
                "updated_at": updated_at,
                "uri": fpath.resolve().as_uri(),
            }
        )
    return items


def _count_archived_md_ro(archive_dir: Path) -> tuple[int, list[tuple[str, str]]]:
    if archive_dir.is_symlink() or not archive_dir.is_dir():
        return 0, []
    try:
        entries = sorted(archive_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return 0, []
    count = 0
    tokens: list[tuple[str, str]] = []
    for p in entries:
        if p.is_symlink() or not p.is_file():
            continue
        if p.suffix.lower() == ".md" and not p.name.startswith("_"):
            count += 1
            tokens.append((p.name, stat_token(p)))
    return count, tokens


def _is_agents_audit_path(code_dir_resolved: Path, file_path: Path, resolved_file: Path) -> bool:
    for candidate in (file_path, resolved_file):
        try:
            rel_parts = candidate.relative_to(code_dir_resolved).parts
        except ValueError:
            return True
        if any(part.lower() == "agents" for part in rel_parts[:-1]):
            return True
    dir_parts = [part.lower() for part in resolved_file.parts[:-1]]
    return any(
        dir_parts[idx] == "audits" and dir_parts[idx + 1] == "agents"
        for idx in range(len(dir_parts) - 1)
    )


def _scan_code_audits_ro(atelier_root: Path) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]], list[dict[str, Any]], list[tuple[str, str]]]:
    code_dir = atelier_root / "audits" / "code"
    if code_dir.is_symlink() or not code_dir.is_dir():
        return [], None, [], []

    code_resolved = code_dir.resolve()
    try:
        candidates = sorted(code_resolved.rglob("*"))
    except OSError:
        return [], None, [], []

    regular: list[dict[str, Any]] = []
    index_audits: list[dict[str, Any]] = []
    sig_tokens: list[tuple[str, str]] = []

    for fpath in candidates:
        try:
            if fpath.is_symlink() or not fpath.is_file() or fpath.suffix.lower() != ".md":
                continue
            if fpath.name.startswith("_"):
                continue
            resolved_file = fpath.resolve()
            if resolved_file.name.startswith("_") or not resolved_file.is_relative_to(code_resolved):
                continue
            if _is_agents_audit_path(code_resolved, fpath, resolved_file):
                continue
            rel_posix = resolved_file.relative_to(code_resolved).as_posix()
        except OSError:
            continue

        loaded = _read_head_text_ro(resolved_file, MAX_HEAD_BYTES)
        if loaded is None:
            continue
        text, size_bytes, updated_at = loaded
        sig_tokens.append((rel_posix, stat_token(resolved_file)))

        date_m = _DATE_PREFIX_RE.match(resolved_file.name)
        date_str = date_m.group(1) if date_m else updated_at[:10]
        verdict, verdict_tone = extract_md_verdict(text)
        target_m = _TARGET_LINE_RE.search(text)
        target_val = clean_md_inline(target_m.group(1)) if target_m else ""

        entry = {
            "audit_id": f"code:{rel_posix}",
            "rel_path": rel_posix,
            "title": extract_md_title(text, resolved_file.stem),
            "verdict": verdict,
            "verdict_tone": verdict_tone,
            "target": target_val,
            "date": date_str,
            "updated_at": updated_at,
            "size_bytes": size_bytes,
            "excerpt": extract_md_excerpt(text),
            "uri": resolved_file.as_uri(),
        }
        if rel_posix.lower() == "readme.md":
            index_audits.append(entry)
        else:
            regular.append(entry)

    index_audits.sort(key=lambda a: str(a.get("rel_path") or "").casefold())
    regular.sort(
        key=lambda a: (str(a.get("date") or ""), str(a.get("updated_at") or ""), str(a.get("rel_path") or "")),
        reverse=True,
    )
    index_audit = index_audits[0] if index_audits else None
    return regular, index_audit, index_audits, sig_tokens


def _dir_md_tokens(directory: Path) -> list[tuple[str, str]]:
    if directory.is_symlink() or not directory.is_dir():
        return []
    try:
        return [
            (p.name, stat_token(p))
            for p in sorted(directory.iterdir(), key=lambda item: item.name)
            if not p.is_symlink() and p.is_file() and p.suffix.lower() == ".md" and not p.name.startswith("_")
        ]
    except OSError:
        return []


def _merge_ateliers(
    registry_ateliers: list[dict[str, Any]],
    *,
    current_root: Path,
    current_available: bool,
    current_name: str,
    current_updated_at: str,
    current_source: str,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in registry_ateliers:
        raw_p = str(item.get("workspace_path") or "").strip()
        if not raw_p:
            continue
        key = _norm_path_key(Path(raw_p))
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
    if current_available:
        cur_key = _norm_path_key(current_root)
        if cur_key not in seen:
            merged.append(
                {
                    "workspace_path": str(current_root),
                    "workspace_name": current_name or current_root.name,
                    "updated_at": current_updated_at,
                    "source": current_source,
                }
            )
    return merged


def _target_mentions_project(target_str: str, pid: str, pname: str) -> bool:
    if not target_str:
        return False
    tokens = {tok.strip().casefold() for tok in re.split(r"[|,;/()]+", target_str) if tok.strip()}
    if pid and pid.casefold() in tokens:
        return True
    if pname and pname.casefold() in tokens:
        return True
    return False


def _enrich_projects_ro(
    projects: list[dict[str, Any]],
    ecosystem: dict[str, Any],
    specs: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> None:
    eco_map = ecosystem.get("projects_status") if isinstance(ecosystem.get("projects_status"), dict) else {}
    eco_by_cf = {str(k).casefold(): v for k, v in eco_map.items() if isinstance(v, dict)}
    for proj in projects:
        pid = str(proj.get("id") or "")
        pname = str(proj.get("name") or "")
        path_name = Path(str(proj.get("path") or "")).name if proj.get("path") else ""
        eco = eco_by_cf.get(pid.casefold()) or (eco_by_cf.get(path_name.casefold()) if path_name else None) or {}
        proj["release_main"] = str(eco.get("release_main") or "")
        proj["dev_status"] = str(eco.get("dev_status") or "")
        proj["installed_version"] = str(eco.get("installed_version") or "")
        proj["wip_status"] = str(eco.get("wip_status") or "")
        proj["specs_count"] = sum(1 for s in specs if _target_mentions_project(str(s.get("target_project") or ""), pid, pname))
        proj["tasks_count"] = sum(1 for t in tasks if _target_mentions_project(str(t.get("target_project") or ""), pid, pname))
        proj["audits_count"] = sum(1 for a in audits if _target_mentions_project(str(a.get("target") or ""), pid, pname))


def _build_waves_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    by_wave: dict[Optional[int], list[dict[str, Any]]] = {}
    for task in tasks:
        w = task.get("wave")
        by_wave.setdefault(w if isinstance(w, int) else None, []).append(task)
    ordered_keys = sorted(k for k in by_wave if k is not None) + ([None] if None in by_wave else [])
    waves: list[dict[str, Any]] = []
    for w_num in ordered_keys:
        w_tasks = by_wave[w_num]
        status_counts: dict[str, int] = {}
        projects_set: set[str] = set()
        for wt in w_tasks:
            sc = str(wt.get("status_code") or "unknown")
            status_counts[sc] = status_counts.get(sc, 0) + 1
            tgt = str(wt.get("target_project") or "").strip()
            if tgt:
                for tok in re.split(r"[|,;/]+", tgt):
                    if tok.strip():
                        projects_set.add(tok.strip())
        waves.append(
            {
                "wave": w_num,
                "tasks_count": len(w_tasks),
                "projects": sorted(projects_set),
                "status_counts": status_counts,
                "filenames": [str(wt.get("filename") or "") for wt in w_tasks],
            }
        )
    return {
        "total_tasks": len(tasks),
        "waves_count": len([k for k in ordered_keys if k is not None]),
        "waves": waves,
    }


def get_architect_state(
    since_signature: str = "",
    *,
    atelier: str = "",
    ws: str = "",
    gravity_home: Optional[Path] = None,
    architect_home: Optional[Path] = None,
    architect_workspace: Optional[Path] = None,
) -> dict[str, Any]:
    """Return read-only Gravity Architect atelier state, specs, tasks, and `audits/code/`."""
    warnings: list[str] = []
    registry_ateliers, ateliers_reg_path = _discover_from_registry_ro(
        gravity_home=gravity_home,
        architect_home=architect_home,
        warnings=warnings,
    )
    atelier_root, discovery_source, blocked_selection = _resolve_atelier_root(
        atelier=atelier,
        ws=ws,
        gravity_home=gravity_home,
        architect_home=architect_home,
        architect_workspace=architect_workspace,
        registry_ateliers=registry_ateliers,
        warnings=warnings,
    )

    reg_sig_token = (
        "symlink"
        if (ateliers_reg_path.parent.is_symlink() or ateliers_reg_path.is_symlink())
        else stat_token(ateliers_reg_path)
    )
    known_paths = [str(item.get("workspace_path") or "") for item in registry_ateliers]

    if blocked_selection:
        sig = short_digest(
            [
                atelier.strip(),
                ws.strip(),
                str(atelier_root),
                discovery_source,
                "blocked",
                reg_sig_token,
                *known_paths,
            ]
        )
        if since_signature and since_signature == sig:
            return unchanged_response(sig)

        ateliers_out = _merge_ateliers(
            registry_ateliers,
            current_root=atelier_root,
            current_available=False,
            current_name="",
            current_updated_at="",
            current_source=discovery_source,
        )
        blocked_payload: dict[str, Any] = {
            "changed": True,
            "unchanged": False,
            "signature": sig,
            "available": False,
            "atelier_root": str(atelier_root),
            "discovery_source": discovery_source,
            "workspace_name": atelier_root.name,
            "public_mode": False,
            "truncated": False,
            "ateliers": ateliers_out,
            "ecosystem": _empty_ecosystem(),
            "delta": _empty_delta(),
            "hot_budgets": {},
            "watches_count": 0,
            "projects": [],
            "specs": [],
            "tasks": [],
            "waves_summary": {"total_tasks": 0, "waves_count": 0, "waves": []},
            "archived_specs_count": 0,
            "archived_tasks_count": 0,
            "audits": [],
            "index_audit": None,
            "index_audits": [],
            "warnings": warnings,
        }
        return enforce_payload_budget(
            blocked_payload,
            ("audits", "tasks", "specs", "projects", "ateliers"),
            max_bytes=MAX_PAYLOAD_BYTES,
        )

    eco_path = atelier_root / "ECOSYSTEM.md"
    delta_path = atelier_root / "tracking" / "snapshots" / "delta.md"
    projects_path = atelier_root / "projects.json"
    specs_dir = atelier_root / "specs"
    tasks_dir = atelier_root / "tasks"
    # Priority to tasks/; read-only fallback to legacy handoffs/ only when tasks/ is absent.
    active_tasks_dir = (
        atelier_root / "handoffs"
        if not tasks_dir.exists() and not tasks_dir.is_symlink()
        else tasks_dir
    )

    audits, index_audit, index_audits, audit_sig_tokens = _scan_code_audits_ro(atelier_root)
    arch_specs_cnt, arch_specs_tokens = _count_archived_md_ro(specs_dir / "archive")
    arch_tasks_cnt, arch_tasks_tokens = _count_archived_md_ro(active_tasks_dir / "archive")

    sig = short_digest(
        [
            atelier.strip(),
            ws.strip(),
            str(atelier_root),
            discovery_source,
            reg_sig_token,
            *known_paths,
            stat_token(eco_path),
            stat_token(delta_path),
            stat_token(projects_path),
            *_dir_md_tokens(specs_dir),
            *_dir_md_tokens(active_tasks_dir),
            *arch_specs_tokens,
            *arch_tasks_tokens,
            *audit_sig_tokens,
        ]
    )
    if since_signature and since_signature == sig:
        return unchanged_response(sig)

    proj_exists, ws_name, public_mode, hot_budgets, watches_count, projects = _read_projects_ro(
        projects_path, atelier_root, warnings
    )
    ecosystem = _read_ecosystem_ro(eco_path, hot_budgets.get("ECOSYSTEM.md"))
    delta = _read_delta_ro(delta_path)
    specs = _scan_flat_artifacts_ro(specs_dir, atelier_root)
    tasks = _scan_flat_artifacts_ro(active_tasks_dir, atelier_root)
    _enrich_projects_ro(projects, ecosystem, specs, tasks, audits)
    waves_summary = _build_waves_summary(tasks)

    available = bool(
        atelier_root.is_dir()
        and (
            ecosystem["exists"]
            or proj_exists
            or delta["exists"]
            or specs
            or tasks
            or audits
            or index_audit is not None
        )
    )
    ateliers_out = _merge_ateliers(
        registry_ateliers,
        current_root=atelier_root,
        current_available=available,
        current_name=ws_name or atelier_root.name,
        current_updated_at=delta.get("date") or ecosystem.get("updated_at") or "",
        current_source=discovery_source,
    )

    payload: dict[str, Any] = {
        "changed": True,
        "unchanged": False,
        "signature": sig,
        "available": available,
        "atelier_root": str(atelier_root),
        "discovery_source": discovery_source,
        "workspace_name": ws_name or atelier_root.name,
        "public_mode": public_mode,
        "truncated": False,
        "ateliers": ateliers_out,
        "ecosystem": ecosystem,
        "delta": delta,
        "hot_budgets": hot_budgets,
        "watches_count": watches_count,
        "projects": projects,
        "specs": specs,
        "tasks": tasks,
        "waves_summary": waves_summary,
        "archived_specs_count": arch_specs_cnt,
        "archived_tasks_count": arch_tasks_cnt,
        "audits": audits,
        "index_audit": index_audit,
        "index_audits": index_audits,
        "warnings": warnings,
    }
    return enforce_payload_budget(
        payload,
        ("audits", "tasks", "specs", "projects", "ateliers"),
        max_bytes=MAX_PAYLOAD_BYTES,
    )

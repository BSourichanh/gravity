"""Shared helpers and provider registry for the read-only Gravity dashboard."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Optional, Sequence

DEDICATED_PROVIDERS: tuple[str, ...] = ("core", "workflow", "metrics", "bridge", "architect")

_DEFAULT_LABELS: dict[str, str] = {
    "core": "Overview",
    "workflow": "Workflow Live",
    "metrics": "Metrics",
    "bridge": "Bridge",
    "architect": "Architect",
}

_TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_VERDICT_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:[-*]\s+)?(?:\*\*|__)?(?:Verdict(?:\s+global)?|Statut(?:\s+global)?|Status|Conclusion|Résultat|Result)(?:\*\*|__)?\s*[:：]\s*(?:\*\*|__)?\s*(.+)",
    re.IGNORECASE,
)
_VERDICT_HEADING_RE = re.compile(
    r"(?:^|\n)\s*#{1,4}\s+(?:Verdict(?:\s+global)?|Conclusion|Statut(?:\s+global)?)\s*\n+([^\n#]+)",
    re.IGNORECASE,
)
_CANONICAL_VERDICT_RE = re.compile(
    r"\b(NON[\s-]+BLOQUANT|BLOQUANT|PASS|PARTIAL|PARTIEL|FAIL|UNTESTED|WARN(?:ING)?|OK|KO)\b",
    re.IGNORECASE,
)


def stat_token(path: Optional[Path]) -> str:
    """Return a lightweight read-only `<mtime_ns>:<size>` token for a filesystem path."""
    if path is None:
        return "missing"
    try:
        st = Path(path).stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "error"


def short_digest(parts: Sequence[Any], length: int = 12) -> str:
    """Return a deterministic truncated SHA-256 hex digest over stringified parts."""
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def unchanged_response(sig: str) -> dict[str, Any]:
    """Return the canonical fast-path payload when source signatures are unchanged."""
    return {"changed": False, "unchanged": True, "signature": sig}


def resolve_provider_kind(module_id: str) -> str:
    """Return the provider kind (`core`, `workflow`, `metrics`, `bridge`, `architect`, or `generic`)."""
    if module_id in DEDICATED_PROVIDERS:
        return module_id
    return "generic"


def build_dashboard_tabs(modules: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ordered dashboard tabs: `overview`, detected dedicated tabs, then generic OCP modules."""
    by_id: dict[str, dict[str, Any]] = {}
    ordered_others: list[dict[str, Any]] = []

    for raw in modules:
        if not isinstance(raw, dict):
            continue
        mod_id = str(raw.get("id") or "").strip()
        if not mod_id:
            continue
        if mod_id in by_id:
            if raw.get("valid") and not by_id[mod_id].get("valid"):
                by_id[mod_id] = raw
            continue
        by_id[mod_id] = raw
        if mod_id not in DEDICATED_PROVIDERS:
            ordered_others.append(raw)

    core_mod = by_id.get("core") or {}
    tabs: list[dict[str, Any]] = [
        {
            "id": "overview",
            "kind": "core",
            "module_id": "core",
            "label": _DEFAULT_LABELS["core"],
            "display_name": core_mod.get("display_name") or "Gravity Core",
            "plugin_name": core_mod.get("plugin_name") or "gravity",
            "version": core_mod.get("version"),
            "valid": bool(core_mod.get("valid", True)) if core_mod else True,
            "dedicated": True,
            "commands": list(core_mod.get("commands") or ["/gravity"]),
            "ui": dict(core_mod.get("ui") or {"mode": "core", "target": "gravity"}),
        }
    ]

    for mod_id in ("workflow", "metrics", "bridge", "architect"):
        mod = by_id.get(mod_id)
        if mod is None:
            continue
        tabs.append(
            {
                "id": mod_id,
                "kind": mod_id,
                "module_id": mod_id,
                "label": _DEFAULT_LABELS[mod_id],
                "display_name": mod.get("display_name") or mod.get("plugin_name") or mod_id.title(),
                "plugin_name": mod.get("plugin_name") or f"gravity-{mod_id}",
                "version": mod.get("version"),
                "valid": bool(mod.get("valid", False)),
                "dedicated": True,
                "commands": list(mod.get("commands") or []),
                "ui": dict(mod.get("ui") or {}),
            }
        )

    for mod in ordered_others:
        mod_id = str(mod["id"])
        label = str(mod.get("display_name") or mod.get("plugin_name") or mod_id.title())
        tabs.append(
            {
                "id": mod_id,
                "kind": "generic",
                "module_id": mod_id,
                "label": label,
                "display_name": label,
                "plugin_name": mod.get("plugin_name") or mod_id,
                "version": mod.get("version"),
                "role": mod.get("role") or "",
                "valid": bool(mod.get("valid", False)),
                "dedicated": False,
                "commands": list(mod.get("commands") or []),
                "ui": dict(mod.get("ui") or {}),
            }
        )

    return tabs


def read_json_ro(path: Path) -> tuple[Any, Optional[str]]:
    """Read and decode a JSON file read-only without raising exceptions."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"Failed to read {path.name}: {exc}"

    warning: Optional[str] = None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        warning = f"UTF-8 BOM detected in {path.name}."

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"Invalid JSON in {path.name}: {exc}"

    return data, warning


def file_uri_if_exists(path: Path) -> str:
    """Return a `file://` URI if `path` exists as a regular file, else empty string."""
    try:
        if path.is_file():
            return path.resolve().as_uri()
    except OSError:
        pass
    return ""


def load_modules_snapshot_ro(
    gravity_home: Path,
    plugin_roots: Optional[Sequence[Path]] = None,
) -> tuple[list[dict[str, Any]], str, bool, Optional[str], list[str]]:
    """Load modules from `<gravity_home>/core/modules.json` or fallback read-only to `discover_modules`."""
    from core.registry import discover_modules

    registry_path = gravity_home / "core" / "modules.json"
    warnings: list[str] = []
    registry_exists = registry_path.is_file()

    if registry_exists:
        data, read_warn = read_json_ro(registry_path)
        if read_warn:
            warnings.append(read_warn)
        if isinstance(data, dict) and isinstance(data.get("modules"), list):
            raw_modules = [dict(m) for m in data["modules"] if isinstance(m, dict)]
            generated_at = data.get("generated_at")
            gen_str = str(generated_at) if isinstance(generated_at, str) else None
            return raw_modules, "modules.json", True, gen_str, warnings
        if data is not None:
            warnings.append("Invalid structure in core/modules.json; falling back to live module discovery.")

    discovered = [dict(m) for m in discover_modules(plugin_roots)]
    return discovered, "discovered", registry_exists, None, warnings


def open_sqlite_ro(db_path: Path, warnings: list[str]) -> Optional[sqlite3.Connection]:
    """Open an existing SQLite database strictly read-only (`?mode=ro` + `PRAGMA query_only = ON`)."""
    try:
        if db_path.is_symlink() or not db_path.is_file():
            return None
        resolved = db_path.resolve()
        conn = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True, timeout=1.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn
    except (sqlite3.Error, OSError) as exc:
        warnings.append(f"SQLite read-only open failed for {db_path.name}: {exc}")
        return None


def truncate_preview(text: str, max_chars: int = 160) -> str:
    """Collapse whitespace and truncate a text preview cleanly to at most `max_chars`."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 3:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 3].rstrip() + "..."


def clean_md_inline(text: str) -> str:
    """Strip basic Markdown emphasis/code markers and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", text or "").strip())


def classify_verdict_tone(verdict_text: str) -> str:
    """Map an audit verdict string to a UI tone (`ok`, `warn`, `danger`, `neutral`)."""
    up = verdict_text.upper()
    if re.search(r"\bUNTESTED\b", up):
        return "neutral"
    if re.search(r"(?<!NON[\s-])\bBLOQUANT\b", up):
        return "danger"
    if any(tok in up for tok in ("FAIL", "REJECT", "REFUS", "CRITIQUE", "ERROR")):
        return "danger"
    if re.search(r"\bKO\b", up):
        return "danger"
    if any(tok in up for tok in ("PARTIAL", "PARTIEL", "WARN", "ATTENTION", "CORRIGER", "CONDITIONAL", "MITIG")):
        return "warn"
    if "NON BLOQUANT" in up or "NON-BLOQUANT" in up:
        return "ok"
    if any(tok in up for tok in ("PASS", "VALID", "APPROUV", "APPROVED", "CLEAN", "SUCC")):
        return "ok"
    if re.search(r"\bOK\b", up):
        return "ok"
    return "neutral"


def extract_md_verdict(text: str) -> tuple[str, str]:
    """Extract normalized verdict label and tone from the head of a Markdown audit."""
    chunk = text[:16_384]
    match = _VERDICT_LINE_RE.search(chunk)
    raw = match.group(1) if match else ""
    if not raw:
        h_match = _VERDICT_HEADING_RE.search(chunk)
        if h_match:
            raw = h_match.group(1)
    if not raw:
        return "", "neutral"
    cleaned = clean_md_inline(raw)
    prefix = re.split(r"\s*(?:\||—|–|\s-\s)\s*", cleaned, maxsplit=1)[0].strip() or cleaned
    canon_m = _CANONICAL_VERDICT_RE.search(prefix)
    if canon_m:
        token = re.sub(r"\s+", " ", canon_m.group(1).upper())
        val = "WARN" if token == "WARNING" else token
    else:
        val = prefix if len(prefix) <= 40 else prefix[:37].rstrip() + "..."
    return val, classify_verdict_tone(val) if val else "neutral"


def extract_md_title(text: str, fallback: str) -> str:
    """Extract first Markdown H1 heading from the head of a file."""
    match = _TITLE_RE.search(text[:8_192])
    if match:
        title = clean_md_inline(match.group(1))
        if title:
            return title
    return fallback


def extract_md_excerpt(text: str, max_chars: int = 160) -> str:
    """Extract a concise non-heading prose excerpt from the head of a Markdown file."""
    for line in text[:4_096].splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "---", "|", "<!--")):
            continue
        cleaned = clean_md_inline(s)
        if len(cleaned) >= 12:
            return truncate_preview(cleaned, max_chars=max_chars)
    return ""


def enforce_payload_budget(
    payload: dict[str, Any],
    list_keys: Sequence[str],
    max_bytes: int = 450_000,
) -> dict[str, Any]:
    """Halve configured list fields until serialized UTF-8 payload size is strictly `< max_bytes`."""
    def _encoded_len() -> int:
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    if _encoded_len() < max_bytes:
        return payload

    payload["truncated"] = True
    for list_key in list_keys:
        items = payload.get(list_key)
        while _encoded_len() >= max_bytes and isinstance(items, list) and items:
            keep = max(0, len(items) // 2)
            items = items[:keep]
            payload[list_key] = items
    return payload


__all__ = [
    "DEDICATED_PROVIDERS",
    "build_dashboard_tabs",
    "classify_verdict_tone",
    "clean_md_inline",
    "enforce_payload_budget",
    "extract_md_excerpt",
    "extract_md_title",
    "extract_md_verdict",
    "file_uri_if_exists",
    "load_modules_snapshot_ro",
    "open_sqlite_ro",
    "read_json_ro",
    "resolve_provider_kind",
    "short_digest",
    "stat_token",
    "truncate_preview",
    "unchanged_response",
]

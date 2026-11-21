#!/usr/bin/env python3
"""Générateur compact pour /statusline CLI (lit le JSON stdin d'Antigravity, exit 0 garanti)."""

import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CHECKED_STEP_RE = re.compile(r"^\s*-\s*\[x\]\s+(.*)$", re.IGNORECASE)


def _read_cli_payload() -> Dict[str, Any]:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    buf: List[str] = []

    def _reader() -> None:
        try:
            buf.append(sys.stdin.read())
        except Exception:
            pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()
    reader_thread.join(timeout=0.5)
    if not buf:
        return {}
    try:
        raw = buf[0].strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_project_dir(payload: Dict[str, Any]) -> Path:
    ws = payload.get("workspace")
    if isinstance(ws, dict):
        for key in ("project_dir", "current_dir"):
            val = ws.get(key)
            if isinstance(val, str) and val.strip():
                return Path(val.strip())
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return Path(cwd.strip())
    env_ws = os.environ.get("GRAVITY_WORKSPACE", "").strip()
    if env_ws:
        return Path(env_ws)
    return Path.cwd()


def _read_mode_badge(root: Path) -> str:
    try:
        obs_dir = str((PLUGIN_ROOT / "observability").resolve())
        if obs_dir not in sys.path:
            sys.path.insert(0, obs_dir)
        from profile_engine import format_mode_badge, load_profile  # type: ignore[import-not-found]

        return format_mode_badge(load_profile(root))
    except Exception:
        profile_path = root / ".agents/gravity/profile.json"
        if profile_path.is_file():
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    mode = str(data.get("mode", "evo"))
                    level = str(data.get("current_level", "medium"))
                    pace = str(data.get("pace", "slow"))
                    verif = str(data.get("verification", "safe"))
                    if mode == "evo":
                        return f"evo:{level}/{pace}/{verif}"
                    return f"{level}[lock]/{pace}/{verif}"
            except Exception:
                pass
        return "evo:medium/slow/safe"


def _read_caveman_badge(root: Path) -> str:
    try:
        obs_dir = str((PLUGIN_ROOT / "observability").resolve())
        if obs_dir not in sys.path:
            sys.path.insert(0, obs_dir)
        from profile_engine import format_caveman_badge, load_profile  # type: ignore[import-not-found]

        return format_caveman_badge(load_profile(root))
    except Exception:
        profile_path = root / ".agents/gravity/profile.json"
        if profile_path.is_file():
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cav = str(data.get("caveman", "lite")).strip().lower()
                    if cav not in ("off", "lite", "full", "ultra"):
                        cav = "lite"
                    if bool(data.get("caveman_locked", False)):
                        return f"caveman:{cav}[lock]"
                    return f"caveman:{cav}"
            except Exception:
                pass
        return "caveman:lite"


def main() -> int:
    try:
        payload = _read_cli_payload()
        root = _resolve_project_dir(payload)

        progress_file = root / ".agents/gravity/PROGRESS.md"
        done, total = 0, 8
        if progress_file.is_file():
            for line in progress_file.read_text(encoding="utf-8").splitlines():
                match = CHECKED_STEP_RE.match(line)
                if match and "(bonus)" not in match.group(1).lower():
                    done += 1
            done = min(done, total)

        mode_badge = _read_mode_badge(root)
        caveman_badge = _read_caveman_badge(root)

        plugin_guard_ok = (
            (PLUGIN_ROOT / "hooks/pre_tool_guard.py").is_file()
            and (PLUGIN_ROOT / "hooks.json").is_file()
        )
        ws_guard_ok = (root / ".agents/hooks.json").is_file()
        guard = "ON" if (plugin_guard_ok or ws_guard_ok) else "OFF"

        eval_str = "Evals N/A"
        report = root / ".agents/gravity/evals/report.json"
        if report.is_file():
            try:
                data = json.loads(report.read_text(encoding="utf-8"))
                p, t = data.get("passed", 0), data.get("total", 0)
                status = "PASS" if t > 0 and p == t else "FAIL"
                eval_str = f"Evals {p}/{t} {status}"
            except Exception:
                eval_str = "Evals ERR"

        parts: List[str] = [
            f"Gravity {done}/{total}",
            mode_badge,
            caveman_badge,
            f"Guard {guard}",
            eval_str,
        ]

        model = payload.get("model")
        if isinstance(model, dict):
            m_name = model.get("display_name") or model.get("id")
            if isinstance(m_name, str) and m_name.strip():
                parts.append(m_name.strip())

        ctx = payload.get("context_window")
        if isinstance(ctx, dict) and ctx.get("used_percentage") is not None:
            pct = float(ctx["used_percentage"])
            ctx_label = f"Ctx {pct:.0f}%"
            if payload.get("exceeds_200k_tokens"):
                ctx_label += " [>200K]"
            parts.append(ctx_label)

        sbx = payload.get("sandbox")
        if isinstance(sbx, dict) and "enabled" in sbx:
            parts.append("SBX ON" if sbx["enabled"] else "SBX OFF")

        cost = payload.get("cost")
        if isinstance(cost, dict) and cost.get("total_usd") is not None:
            parts.append(f"${float(cost['total_usd']):.2f}")

        print(" · ".join(parts))
    except Exception:
        print("Gravity ?/8 · Guard ? · Evals N/A")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

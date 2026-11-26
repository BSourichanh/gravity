#!/usr/bin/env python3
"""Read-only zero-token PreInvocation hook for bare '/gravity' command."""

from __future__ import annotations

from pathlib import Path
import sys

HOOKS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = HOOKS_DIR.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared.hook_runtime import (  # noqa: E402
    configure_utf8_stdio,
    emit_passthrough,
    emit_user_markdown,
    first_str_arg,
    is_initial_invocation,
    normalize_command,
    read_stdin_json,
)


def main() -> int:
    configure_utf8_stdio()
    payload = read_stdin_json()
    if not payload or not is_initial_invocation(payload):
        emit_passthrough()
        return 0

    cmd = normalize_command(first_str_arg(payload, "lastUserInput", "userInput", "prompt"))
    if cmd not in ("/gravity", "/gravity:gravity"):
        emit_passthrough()
        return 0

    try:
        from scripts import init_env  # noqa: E402

        overview_payload, _ = init_env.run_environment(overview=True)
        md = init_env.format_overview_markdown(overview_payload)
        emit_user_markdown(md, system_message="Gravity Core overview (read-only).")
    except Exception:
        emit_passthrough()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

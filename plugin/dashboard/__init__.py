"""Pure Python 3.10+ stdlib read-only dashboard package for Gravity Core."""

from __future__ import annotations

from dashboard import api
from dashboard.api import (
    build_initial_summary,
    get_architect_state,
    get_live_session_state,
    get_metrics_state,
    get_module_info,
    get_overview,
    get_session_detail,
    get_workflow_state,
    invoke_dashboard_provider,
    read_metrics_audit,
    run_metrics_cli_action,
)

__all__ = [
    "api",
    "build_initial_summary",
    "get_architect_state",
    "get_live_session_state",
    "get_metrics_state",
    "get_module_info",
    "get_overview",
    "get_session_detail",
    "get_workflow_state",
    "invoke_dashboard_provider",
    "read_metrics_audit",
    "run_metrics_cli_action",
]

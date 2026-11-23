"""Pure Python 3.10+ stdlib read-only dashboard package for Gravity Core."""

from __future__ import annotations

from dashboard import api
from dashboard.api import (
    build_initial_summary,
    get_metrics_state,
    get_module_info,
    get_overview,
    get_session_detail,
    get_workflow_state,
)

__all__ = [
    "api",
    "build_initial_summary",
    "get_metrics_state",
    "get_module_info",
    "get_overview",
    "get_session_detail",
    "get_workflow_state",
]

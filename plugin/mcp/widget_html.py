"""Autonomous SEP-1865 HTML5 generator for the Gravity unified MCP App (100% stdlib)."""

from __future__ import annotations

from mcp.ui import APP_JS, VIEWS_JS, WIDGET_CSS


def render_dashboard_html() -> str:
    """Return the self-contained SEP-1865 HTML5 dashboard document (< 200 KiB)."""
    script_body = "\n".join(
        [
            "(function () {",
            '  "use strict";',
            VIEWS_JS.strip(),
            APP_JS.strip(),
            "})();",
        ]
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr">\n'
        "<head>\n"
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        "<title>Gravity</title>\n"
        "<style>\n"
        f"{WIDGET_CSS.strip()}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        '<div id="root" class="app">\n'
        '  <div class="empty">Connexion à Gravity...</div>\n'
        "</div>\n"
        "<script>\n"
        f"{script_body}\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )


__all__ = ["render_dashboard_html"]

"""Autonomous SEP-1865 HTML5 generator for the Gravity unified MCP App (100% stdlib)."""

from __future__ import annotations

from mcp import ui as ui_pkg

_JS_FRAGMENT_NAMES = (
    "VIEWS_JS",
    "CHARTS_JS",
    "LIVE_VIEWS_JS",
    "METRICS_VIEWS_JS",
    "APP_JS",
)


def render_dashboard_html() -> str:
    """Return the self-contained SEP-1865 HTML5 dashboard document (< 150 KiB)."""
    css_text = str(getattr(ui_pkg, "WIDGET_CSS", "") or "").strip()
    js_fragments = [
        str(getattr(ui_pkg, name, "") or "").strip()
        for name in _JS_FRAGMENT_NAMES
    ]
    script_body = "\n".join(
        [
            "(function () {",
            '  "use strict";',
            *[frag for frag in js_fragments if frag],
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
        f"{css_text}\n"
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

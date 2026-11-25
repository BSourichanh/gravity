"""Stylesheet for the Gravity unified MCP App dashboard (100% stdlib)."""

from __future__ import annotations

WIDGET_CSS = r"""
  :root {
    color-scheme: dark light;
    --g-bg: var(--color-background-primary, #111317);
    --g-card: var(--color-background-secondary, #181b20);
    --g-muted: var(--color-background-tertiary, #22262e);
    --g-elev: var(--color-background-elevated, #1d2129);
    --g-fg: var(--color-text-primary, #eceef2);
    --g-fg-sec: var(--color-text-secondary, #a1a1aa);
    --g-fg-dim: var(--color-text-tertiary, #71717a);
    --g-border: var(--color-border-primary, #2c313c);
    --g-border-soft: var(--color-border-secondary, #232730);
    --g-accent: var(--color-text-info, #60a5fa);
    --g-accent-bg: var(--color-background-info, rgba(96, 165, 250, 0.14));
    --g-ok: var(--color-text-success, #34d399);
    --g-ok-bg: var(--color-background-success, rgba(52, 211, 153, 0.14));
    --g-warn: var(--color-text-warning, #f59e0b);
    --g-warn-bg: var(--color-background-warning, rgba(245, 158, 11, 0.14));
    --g-err: var(--color-text-danger, #ef4444);
    --g-err-bg: var(--color-background-danger, rgba(239, 68, 68, 0.14));
    --g-atelier: var(--color-text-accent, #a78bfa);
    --g-atelier-bg: rgba(167, 139, 250, 0.15);
    --g-code: #2dd4bf;
    --g-code-bg: rgba(45, 212, 191, 0.14);
    --g-font: var(--font-sans, system-ui, -apple-system, Segoe UI, sans-serif);
    --g-mono: var(--font-mono, ui-monospace, SFMono-Regular, Consolas, monospace);
    --g-radius: 10px;
    --g-radius-sm: 6px;
    --g-c1: var(--g-accent);
    --g-c2: #8b5cf6;
    --g-c3: #10b981;
    --g-c4: #f59e0b;
    --g-c5: #6366f1;
    --g-c6: #ec4899;
  }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
      color-scheme: light;
      --g-bg: var(--color-background-primary, #fafafa);
      --g-card: var(--color-background-secondary, #ffffff);
      --g-muted: var(--color-background-tertiary, #f4f4f5);
      --g-elev: var(--color-background-elevated, #f8fafc);
      --g-fg: var(--color-text-primary, #18181b);
      --g-fg-sec: var(--color-text-secondary, #52525b);
      --g-fg-dim: var(--color-text-tertiary, #71717a);
      --g-border: var(--color-border-primary, #e4e4e7);
      --g-border-soft: var(--color-border-secondary, #f0f0f2);
      --g-accent: var(--color-text-info, #2563eb);
      --g-accent-bg: var(--color-background-info, rgba(37, 99, 235, 0.10));
      --g-ok: var(--color-text-success, #059669);
      --g-ok-bg: var(--color-background-success, rgba(5, 150, 105, 0.11));
      --g-warn: var(--color-text-warning, #d97706);
      --g-warn-bg: var(--color-background-warning, rgba(217, 119, 6, 0.11));
      --g-err: var(--color-text-danger, #dc2626);
      --g-err-bg: var(--color-background-danger, rgba(220, 38, 38, 0.11));
      --g-atelier: var(--color-text-accent, #6d28d9);
      --g-atelier-bg: rgba(109, 40, 217, 0.10);
      --g-code: #0f766e;
      --g-code-bg: rgba(15, 118, 110, 0.10);
      --g-c2: #7c3aed;
      --g-c3: #059669;
      --g-c4: #d97706;
      --g-c5: #4f46e5;
      --g-c6: #db2777;
    }
  }
  :root[data-theme="light"] {
    color-scheme: light;
    --g-bg: var(--color-background-primary, #fafafa);
    --g-card: var(--color-background-secondary, #ffffff);
    --g-muted: var(--color-background-tertiary, #f4f4f5);
    --g-elev: var(--color-background-elevated, #f8fafc);
    --g-fg: var(--color-text-primary, #18181b);
    --g-fg-sec: var(--color-text-secondary, #52525b);
    --g-fg-dim: var(--color-text-tertiary, #71717a);
    --g-border: var(--color-border-primary, #e4e4e7);
    --g-border-soft: var(--color-border-secondary, #f0f0f2);
    --g-accent: var(--color-text-info, #2563eb);
    --g-accent-bg: var(--color-background-info, rgba(37, 99, 235, 0.10));
    --g-ok: var(--color-text-success, #059669);
    --g-ok-bg: var(--color-background-success, rgba(5, 150, 105, 0.11));
    --g-warn: var(--color-text-warning, #d97706);
    --g-warn-bg: var(--color-background-warning, rgba(217, 119, 6, 0.11));
    --g-err: var(--color-text-danger, #dc2626);
    --g-err-bg: var(--color-background-danger, rgba(220, 38, 38, 0.11));
    --g-atelier: var(--color-text-accent, #6d28d9);
    --g-atelier-bg: rgba(109, 40, 217, 0.10);
    --g-code: #0f766e;
    --g-code-bg: rgba(15, 118, 110, 0.10);
    --g-c2: #7c3aed;
    --g-c3: #059669;
    --g-c4: #d97706;
    --g-c5: #4f46e5;
    --g-c6: #db2777;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    background: var(--g-bg);
    color: var(--g-fg);
    font-family: var(--g-font);
    font-size: 13px;
    line-height: 1.45;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
  }
  .mono, .num, .kpi-val, .tab-count {
    font-variant-numeric: tabular-nums;
  }
  .mono {
    font-family: var(--g-mono);
    font-size: 11.5px;
    color: var(--g-fg-sec);
    overflow-wrap: anywhere;
  }
  .app {
    container-type: inline-size;
    container-name: app;
    width: 100%;
    max-width: 1380px;
    margin: 0 auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    overflow-x: hidden;
  }
  .shell-head {
    background: var(--g-card);
    border: 1px solid var(--g-border);
    border-radius: var(--g-radius);
    padding: 10px 12px 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .topbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .brand-dot, .live-dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: var(--g-ok);
    flex-shrink: 0;
  }
  .brand-dot.warn { background: var(--g-warn); }
  .brand-dot.error { background: var(--g-err); }
  .live-dot { box-shadow: 0 0 0 3px var(--g-ok-bg); }
  .live-dot.paused { background: var(--g-warn); box-shadow: 0 0 0 3px var(--g-warn-bg); }
  .live-dot.idle { background: var(--g-fg-dim); box-shadow: none; }
  .brand-title {
    font-size: 14px;
    font-weight: 600;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  .brand-sub {
    font-size: 11.5px;
    color: var(--g-fg-sec);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .actions-row, .live-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    border-top: 1px solid var(--g-border-soft);
    padding-top: 6px;
  }
  .tab-btn {
    appearance: none;
    background: transparent;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    color: var(--g-fg-sec);
    font: inherit;
    font-size: 12.5px;
    font-weight: 500;
    padding: 6px 10px;
    border-radius: 6px 6px 0 0;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: background-color .15s ease, color .15s ease;
  }
  .tab-btn:hover { color: var(--g-fg); background: var(--g-muted); }
  .tab-btn.active {
    color: var(--g-fg);
    border-bottom-color: var(--g-accent);
    background: var(--g-muted);
  }
  .tab-btn:focus-visible, .btn:focus-visible, .input:focus-visible, .select:focus-visible, summary:focus-visible {
    outline: 2px solid var(--g-accent);
    outline-offset: 1px;
  }
  .btn {
    appearance: none;
    background: var(--g-muted);
    color: var(--g-fg);
    border: 1px solid var(--g-border);
    border-radius: var(--g-radius-sm);
    padding: 5px 10px;
    font: inherit;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    transition: border-color .15s ease, background-color .15s ease;
  }
  .btn:hover { border-color: var(--g-accent); }
  .btn.active, .btn-primary {
    background: var(--g-accent-bg);
    color: var(--g-accent);
    border-color: var(--g-accent);
  }
  .btn-danger {
    background: var(--g-err-bg);
    color: var(--g-err);
    border-color: transparent;
  }
  .btn-danger:hover { border-color: var(--g-err); }
  .btn-sm { padding: 3px 8px; font-size: 11.5px; }
  .btn:disabled { opacity: 0.55; cursor: not-allowed; }
  .input, .select {
    background: var(--g-bg);
    color: var(--g-fg);
    border: 1px solid var(--g-border);
    border-radius: var(--g-radius-sm);
    padding: 5px 8px;
    font: inherit;
    font-size: 12px;
    min-width: 0;
    max-width: 100%;
  }
  .select { min-width: 140px; }
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 7px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    border: 1px solid var(--g-border);
    background: var(--g-muted);
    color: var(--g-fg-sec);
    white-space: nowrap;
    max-width: 100%;
  }
  .badge.ok { background: var(--g-ok-bg); color: var(--g-ok); border-color: transparent; }
  .badge.warn { background: var(--g-warn-bg); color: var(--g-warn); border-color: transparent; }
  .badge.danger, .badge.error, .badge.crit { background: var(--g-err-bg); color: var(--g-err); border-color: transparent; }
  .badge.info { background: var(--g-accent-bg); color: var(--g-accent); border-color: transparent; }
  .badge.atelier, .badge-atelier { background: var(--g-atelier-bg); color: var(--g-atelier); border-color: transparent; }
  .badge.code, .badge-code { background: var(--g-code-bg); color: var(--g-code); border-color: transparent; }
  .badge.src-root { background: var(--g-accent-bg); color: var(--g-accent); border-color: transparent; }
  .badge.src-swarm { background: var(--g-atelier-bg); color: var(--g-atelier); border-color: transparent; }
  .badge.src-subagent { background: var(--g-code-bg); color: var(--g-code); border-color: transparent; }
  .badge.src-workflow { background: var(--g-warn-bg); color: var(--g-warn); border-color: transparent; }
  .badge.src-other { background: var(--g-muted); color: var(--g-fg-sec); }
  .panel {
    background: var(--g-card);
    border: 1px solid var(--g-border);
    border-radius: var(--g-radius);
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
    max-width: 100%;
  }
  .panel-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-width: 0;
  }
  .panel-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--g-fg);
    min-width: 0;
  }
  .grid-kpi {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
    gap: 8px;
    min-width: 0;
  }
  .kpi-card {
    background: var(--g-muted);
    border: 1px solid var(--g-border-soft);
    border-radius: 8px;
    padding: 9px 10px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .kpi-card.warn { border-color: var(--g-warn); }
  .kpi-card.error, .kpi-card.danger { border-color: var(--g-err); }
  .kpi-card.ok { border-color: var(--g-ok); }
  .kpi-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
  }
  .kpi-lbl { font-size: 11px; color: var(--g-fg-sec); }
  .kpi-val { font-size: 16px; font-weight: 600; color: var(--g-fg); }
  .kpi-sub { font-size: 11px; color: var(--g-fg-dim); overflow-wrap: anywhere; }
  .grid-cards, .agent-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
    min-width: 0;
  }
  .mod-card, .agent-card {
    background: var(--g-muted);
    border: 1px solid var(--g-border);
    border-radius: 8px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 7px;
    min-width: 0;
    color: inherit;
    font: inherit;
  }
  .mod-card { cursor: pointer; text-align: left; }
  .mod-card:hover { border-color: var(--g-accent); }
  .agent-card.active { border-left: 3px solid var(--g-ok); }
  .agent-card.waiting { border-left: 3px solid var(--g-warn); }
  .agent-card.done { border-left: 3px solid var(--g-fg-dim); opacity: 0.92; }
  .agent-card.error { border-left: 3px solid var(--g-err); }
  .mod-top, .agent-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 6px;
    min-width: 0;
  }
  .mod-name, .agent-role {
    font-weight: 600;
    font-size: 13px;
    overflow-wrap: anywhere;
  }
  .agent-task {
    font-size: 12px;
    color: var(--g-fg-sec);
    overflow-wrap: anywhere;
  }
  .agent-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 10px;
    font-size: 11.5px;
    color: var(--g-fg-sec);
  }
  .agent-groups {
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-width: 0;
  }
  .agent-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .agent-group.has-error {
    border-left: 2px solid var(--g-err);
    padding-left: 8px;
  }
  .agent-group-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 12px;
    font-weight: 600;
    color: var(--g-fg-sec);
    min-width: 0;
  }
  .agent-filiation {
    font-size: 11px;
    color: var(--g-fg-sec);
    overflow-wrap: anywhere;
  }
  .agent-done-fold > .fold-summary {
    padding: 7px 10px;
    font-size: 12px;
    color: var(--g-fg-sec);
  }
  .agent-done-fold > .fold-body {
    padding: 8px;
  }
  .pill-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    min-width: 0;
  }
  .pill {
    font-family: var(--g-mono);
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 5px;
    background: var(--g-bg);
    border: 1px solid var(--g-border-soft);
    color: var(--g-fg-sec);
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ctx-gauge {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .ctx-gauge-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    font-size: 11px;
    color: var(--g-fg-sec);
  }
  .ctx-track, .wf-progress-track, .ws-bar-track {
    width: 100%;
    height: 6px;
    border-radius: 999px;
    background: var(--g-bg);
    border: 1px solid var(--g-border-soft);
    overflow: hidden;
  }
  .ctx-fill, .wf-progress-fill, .ws-bar-fill {
    height: 100%;
    border-radius: 999px;
    background: var(--g-accent);
    transition: width .2s ease;
  }
  .ctx-fill.ok { background: var(--g-ok); }
  .ctx-fill.warn { background: var(--g-warn); }
  .ctx-fill.crit { background: var(--g-err); }
  .stack-wrap {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  .stack-bar {
    display: flex;
    width: 100%;
    height: 10px;
    border-radius: 999px;
    overflow: hidden;
    background: var(--g-bg);
    border: 1px solid var(--g-border-soft);
  }
  .stack-seg { height: 100%; min-width: 2px; }
  .stack-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    font-size: 11.5px;
    color: var(--g-fg-sec);
  }
  .legend-item {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    flex-shrink: 0;
  }
  .ws-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .ws-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .ws-row-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    font-size: 12px;
    min-width: 0;
  }
  .ws-name-wrap {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .fold-panel {
    background: var(--g-card);
    border: 1px solid var(--g-border);
    border-radius: var(--g-radius);
    padding: 0;
    min-width: 0;
  }
  .fold-summary {
    list-style: none;
    cursor: pointer;
    padding: 10px 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 13px;
    font-weight: 600;
    user-select: none;
  }
  .fold-summary::-webkit-details-marker { display: none; }
  .fold-body {
    padding: 0 12px 12px;
    border-top: 1px solid var(--g-border-soft);
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding-top: 10px;
  }
  .session-bar {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--g-border-soft);
    border-radius: 8px;
    max-width: 100%;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  th, td {
    padding: 7px 9px;
    border-bottom: 1px solid var(--g-border-soft);
    text-align: left;
    vertical-align: top;
  }
  th {
    font-size: 11px;
    font-weight: 600;
    color: var(--g-fg-sec);
    background: var(--g-muted);
  }
  tr:last-child td { border-bottom: none; }
  tr.clickable { cursor: pointer; }
  tr.clickable:hover td { background: var(--g-muted); }
  tr.selected td { background: var(--g-accent-bg); }
  td.num, th.num { text-align: right; white-space: nowrap; }
  .split, .master-detail {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
    min-width: 0;
  }
  .drawer {
    background: var(--g-muted);
    border: 1px solid var(--g-border);
    border-radius: 8px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .notice {
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
    border: 1px solid var(--g-border);
    background: var(--g-muted);
    color: var(--g-fg-sec);
  }
  .notice.warn { background: var(--g-warn-bg); color: var(--g-warn); border-color: transparent; }
  .notice.info { background: var(--g-accent-bg); color: var(--g-accent); border-color: transparent; }
  .notice.ok { background: var(--g-ok-bg); color: var(--g-ok); border-color: transparent; }
  .toast {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 12px;
    background: var(--g-accent-bg);
    color: var(--g-accent);
    border: 1px solid var(--g-border);
  }
  .toast.ok { background: var(--g-ok-bg); color: var(--g-ok); }
  .toast.warn { background: var(--g-warn-bg); color: var(--g-warn); }
  .toast.error { background: var(--g-err-bg); color: var(--g-err); }
  .inline-confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--g-warn);
    background: var(--g-warn-bg);
    font-size: 12px;
  }
  .inline-confirm.danger {
    border-color: var(--g-err);
    background: var(--g-err-bg);
  }
  .inline-confirm-actions {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .empty {
    padding: 18px;
    text-align: center;
    color: var(--g-fg-sec);
    font-size: 12.5px;
    background: var(--g-muted);
    border-radius: 8px;
  }
  .subtabs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .svg-box { width: 100%; overflow-x: auto; }
  .svg-box svg { width: 100%; height: auto; display: block; }
  .sparkline { width: 76px; height: 22px; display: block; flex-shrink: 0; }
  .event-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 8px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--g-border-soft);
    font-size: 11.5px;
    min-width: 0;
  }
  .event-row:last-child { border-bottom: none; }
  .kv-grid {
    display: grid;
    grid-template-columns: minmax(96px, auto) minmax(0, 1fr);
    gap: 4px 10px;
    font-size: 12px;
  }
  .kv-k { color: var(--g-fg-sec); font-weight: 500; }
  .preview-text {
    max-width: 100%;
    color: var(--g-fg-sec);
    font-size: 11.5px;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }
  @container app (min-width: 620px) {
    .grid-cards, .agent-grid {
      grid-template-columns: repeat(auto-fill, minmax(265px, 1fr));
    }
  }
  @container app (min-width: 860px) {
    .app { padding: 14px; }
    .split.with-drawer, .master-detail {
      grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
      align-items: start;
    }
  }
  @media (min-width: 900px) {
    .grid-cards, .agent-grid {
      grid-template-columns: repeat(auto-fill, minmax(265px, 1fr));
    }
    .split.with-drawer, .master-detail {
      grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
      align-items: start;
    }
  }
"""

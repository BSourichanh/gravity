"""Stylesheet for the Gravity unified MCP App dashboard (100% stdlib)."""

WIDGET_CSS = r"""
  :root {
    color-scheme: dark light;
    --g-bg: var(--color-background-primary, #111317);
    --g-card: var(--color-background-secondary, #181b20);
    --g-muted: var(--color-background-tertiary, #22262e);
    --g-fg: var(--color-text-primary, #eceef2);
    --g-fg-sec: var(--color-text-secondary, #a1a1aa);
    --g-fg-dim: var(--color-text-tertiary, #71717a);
    --g-border: var(--color-border-primary, #2c313c);
    --g-border-soft: var(--color-border-secondary, #232730);
    --g-accent: var(--color-text-info, #60a5fa);
    --g-accent-bg: var(--color-background-info, rgba(96, 165, 250, 0.12));
    --g-ok: var(--color-text-success, #34d399);
    --g-ok-bg: var(--color-background-success, rgba(52, 211, 153, 0.12));
    --g-warn: var(--color-text-warning, #f59e0b);
    --g-warn-bg: var(--color-background-warning, rgba(245, 158, 11, 0.12));
    --g-err: var(--color-text-danger, #ef4444);
    --g-err-bg: var(--color-background-danger, rgba(239, 68, 68, 0.12));
    --g-font: var(--font-sans, system-ui, -apple-system, Segoe UI, sans-serif);
    --g-mono: var(--font-mono, ui-monospace, SFMono-Regular, Consolas, monospace);
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
      --g-fg: var(--color-text-primary, #18181b);
      --g-fg-sec: var(--color-text-secondary, #52525b);
      --g-fg-dim: var(--color-text-tertiary, #71717a);
      --g-border: var(--color-border-primary, #e4e4e7);
      --g-border-soft: var(--color-border-secondary, #f0f0f2);
      --g-accent: var(--color-text-info, #2563eb);
      --g-accent-bg: var(--color-background-info, rgba(37, 99, 235, 0.08));
      --g-ok: var(--color-text-success, #059669);
      --g-ok-bg: var(--color-background-success, rgba(5, 150, 105, 0.10));
      --g-warn: var(--color-text-warning, #d97706);
      --g-warn-bg: var(--color-background-warning, rgba(217, 119, 6, 0.10));
      --g-err: var(--color-text-danger, #dc2626);
      --g-err-bg: var(--color-background-danger, rgba(220, 38, 38, 0.10));
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
    --g-fg: var(--color-text-primary, #18181b);
    --g-fg-sec: var(--color-text-secondary, #52525b);
    --g-fg-dim: var(--color-text-tertiary, #71717a);
    --g-border: var(--color-border-primary, #e4e4e7);
    --g-border-soft: var(--color-border-secondary, #f0f0f2);
    --g-accent: var(--color-text-info, #2563eb);
    --g-accent-bg: var(--color-background-info, rgba(37, 99, 235, 0.08));
    --g-ok: var(--color-text-success, #059669);
    --g-ok-bg: var(--color-background-success, rgba(5, 150, 105, 0.10));
    --g-warn: var(--color-text-warning, #d97706);
    --g-warn-bg: var(--color-background-warning, rgba(217, 119, 6, 0.10));
    --g-err: var(--color-text-danger, #dc2626);
    --g-err-bg: var(--color-background-danger, rgba(220, 38, 38, 0.10));
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
    -webkit-font-smoothing: antialiased;
  }
  .mono, .num, .kpi-val, .tab-count {
    font-variant-numeric: tabular-nums;
  }
  .mono {
    font-family: var(--g-mono);
    font-size: 11.5px;
    color: var(--g-fg-sec);
  }
  .app {
    max-width: 1360px;
    margin: 0 auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .shell-head {
    background: var(--g-card);
    border: 1px solid var(--g-border);
    border-radius: 10px;
    padding: 10px 12px 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
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
  .brand-dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: var(--g-ok);
    flex-shrink: 0;
  }
  .brand-dot.warn { background: var(--g-warn); }
  .brand-dot.error { background: var(--g-err); }
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
  .actions-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
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
  }
  .tab-btn:hover { color: var(--g-fg); background: var(--g-muted); }
  .tab-btn.active {
    color: var(--g-fg);
    border-bottom-color: var(--g-accent);
    background: var(--g-muted);
  }
  .btn {
    appearance: none;
    background: var(--g-muted);
    color: var(--g-fg);
    border: 1px solid var(--g-border);
    border-radius: 6px;
    padding: 4px 10px;
    font: inherit;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .btn:hover { border-color: var(--g-accent); }
  .btn.active {
    background: var(--g-accent-bg);
    color: var(--g-accent);
    border-color: var(--g-accent);
  }
  .btn:disabled { opacity: 0.55; cursor: not-allowed; }
  .input, .select {
    background: var(--g-bg);
    color: var(--g-fg);
    border: 1px solid var(--g-border);
    border-radius: 6px;
    padding: 4px 8px;
    font: inherit;
    font-size: 12px;
    min-width: 140px;
  }
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
  }
  .badge.ok { background: var(--g-ok-bg); color: var(--g-ok); border-color: transparent; }
  .badge.warn { background: var(--g-warn-bg); color: var(--g-warn); border-color: transparent; }
  .badge.danger, .badge.error { background: var(--g-err-bg); color: var(--g-err); border-color: transparent; }
  .badge.info { background: var(--g-accent-bg); color: var(--g-accent); border-color: transparent; }
  .panel {
    background: var(--g-card);
    border: 1px solid var(--g-border);
    border-radius: 10px;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .panel-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .panel-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--g-fg);
  }
  .grid-kpi {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
    gap: 8px;
  }
  .kpi-card {
    background: var(--g-muted);
    border: 1px solid var(--g-border-soft);
    border-radius: 8px;
    padding: 9px 10px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .kpi-lbl { font-size: 11px; color: var(--g-fg-sec); }
  .kpi-val { font-size: 16px; font-weight: 600; color: var(--g-fg); }
  .kpi-sub { font-size: 11px; color: var(--g-fg-dim); }
  .grid-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 8px;
  }
  .mod-card {
    background: var(--g-muted);
    border: 1px solid var(--g-border);
    border-radius: 8px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    cursor: pointer;
    text-align: left;
    color: inherit;
    font: inherit;
  }
  .mod-card:hover { border-color: var(--g-accent); }
  .mod-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
  }
  .mod-name { font-weight: 600; font-size: 13px; }
  .pill-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .pill {
    font-family: var(--g-mono);
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 5px;
    background: var(--g-bg);
    border: 1px solid var(--g-border-soft);
    color: var(--g-fg-sec);
  }
  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--g-border-soft);
    border-radius: 8px;
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
  .split {
    display: grid;
    grid-template-columns: 1fr;
    gap: 10px;
  }
  @media (min-width: 900px) {
    .split.with-drawer {
      grid-template-columns: 1.35fr 1fr;
    }
  }
  .drawer {
    background: var(--g-muted);
    border: 1px solid var(--g-border);
    border-radius: 8px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
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
  .toast.error { background: var(--g-err-bg); color: var(--g-err); }
  .empty {
    padding: 20px;
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
  .event-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 5px 8px;
    border-bottom: 1px solid var(--g-border-soft);
    font-size: 11.5px;
  }
  .event-row:last-child { border-bottom: none; }
  .kv-grid {
    display: grid;
    grid-template-columns: minmax(110px, auto) 1fr;
    gap: 4px 10px;
    font-size: 12px;
  }
  .kv-k { color: var(--g-fg-sec); font-weight: 500; }
"""

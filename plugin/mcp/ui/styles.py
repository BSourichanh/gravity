"""Stylesheet for the Gravity unified MCP App dashboard (100% stdlib)."""

from __future__ import annotations

WIDGET_CSS = r"""
:root{color-scheme:dark light;--g-bg:var(--color-background-primary,#111317);--g-card:var(--color-background-secondary,#181b20);--g-muted:var(--color-background-tertiary,#22262e);--g-elev:var(--color-background-elevated,#1d2129);--g-fg:var(--color-text-primary,#eceef2);--g-fg-sec:var(--color-text-secondary,#a1a1aa);--g-fg-dim:var(--color-text-tertiary,#71717a);--g-border:var(--color-border-primary,#2c313c);--g-border-soft:var(--color-border-secondary,#232730);--g-accent:var(--color-text-info,#60a5fa);--g-accent-bg:var(--color-background-info,rgba(96,165,250,.14));--g-ok:var(--color-text-success,#34d399);--g-ok-bg:var(--color-background-success,rgba(52,211,153,.14));--g-warn:var(--color-text-warning,#f59e0b);--g-warn-bg:var(--color-background-warning,rgba(245,158,11,.14));--g-err:var(--color-text-danger,#ef4444);--g-err-bg:var(--color-background-danger,rgba(239,68,68,.14));--g-atelier:var(--color-text-accent,#a78bfa);--g-atelier-bg:rgba(167,139,250,.15);--g-code:#2dd4bf;--g-code-bg:rgba(45,212,191,.14);--g-font:var(--font-sans,system-ui,-apple-system,Segoe UI,sans-serif);--g-mono:var(--font-mono,ui-monospace,SFMono-Regular,Consolas,monospace);--g-radius:10px;--g-radius-sm:6px;--g-c1:var(--g-accent);--g-c2:#8b5cf6;--g-c3:#10b981;--g-c4:#f59e0b;--g-c5:#6366f1;--g-c6:#ec4899}
:root[data-theme="light"]{color-scheme:light;--g-bg:var(--color-background-primary,#fafafa);--g-card:var(--color-background-secondary,#fff);--g-muted:var(--color-background-tertiary,#f4f4f5);--g-elev:var(--color-background-elevated,#f8fafc);--g-fg:var(--color-text-primary,#18181b);--g-fg-sec:var(--color-text-secondary,#52525b);--g-fg-dim:var(--color-text-tertiary,#71717a);--g-border:var(--color-border-primary,#e4e4e7);--g-border-soft:var(--color-border-secondary,#f0f0f2);--g-accent:var(--color-text-info,#2563eb);--g-accent-bg:var(--color-background-info,rgba(37,99,235,.1));--g-ok:var(--color-text-success,#059669);--g-ok-bg:var(--color-background-success,rgba(5,150,105,.11));--g-warn:var(--color-text-warning,#d97706);--g-warn-bg:var(--color-background-warning,rgba(217,119,6,.11));--g-err:var(--color-text-danger,#dc2626);--g-err-bg:var(--color-background-danger,rgba(220,38,38,.11));--g-atelier:var(--color-text-accent,#6d28d9);--g-atelier-bg:rgba(109,40,217,.1);--g-code:#0f766e;--g-code-bg:rgba(15,118,110,.1);--g-c2:#7c3aed;--g-c3:#059669;--g-c4:#d97706;--g-c5:#4f46e5;--g-c6:#db2777}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--g-bg);color:var(--g-fg);font-family:var(--g-font);font-size:13px;line-height:1.45;overflow-x:hidden;-webkit-font-smoothing:antialiased}
.mono,.num,.kpi-val,.tab-count,.gantt-time,.phase-num{font-variant-numeric:tabular-nums}
.mono{font-family:var(--g-mono);font-size:11.5px;color:var(--g-fg-sec);overflow-wrap:anywhere}
.app{container-type:inline-size;container-name:app;width:100%;max-width:1400px;margin:0 auto;padding:8px 10px;display:flex;flex-direction:column;gap:9px;overflow-x:hidden}
#g-content,.session-bar,.stack-wrap,.ws-list,.ws-row,.ctx-gauge,.agent-groups,.agent-group,.tree-main,.tree-wrap,.tree-root,.tree-branch,.tree-children,.gantt-mini{display:flex;flex-direction:column;min-width:0}
#g-content,.split,.master-detail,.split-tree{gap:9px}
.panel,.panel-head,.grid-kpi,.kpi-strip,.kpi-card,.tree-row,.tree-indent,.tree-head,.tree-meta,.inspector-pane,.drawer,.slide-over,.wave-group,.split,.master-detail,.split-tree,.grid-cards,.agent-grid,.proj-grid,.ws-row-head,.ws-name-wrap,.fold-panel,.actions-row,.live-controls,.nav-main,.brand,.topbar,.shell-head,.phase-stepper,.phase-card{min-width:0}
.shell-head{background:var(--g-card);border:1px solid var(--g-border);border-radius:var(--g-radius);padding:6px 10px}
.topbar,.panel-head,.kpi-top,.ws-row-head,.phase-top,.phase-nums,.mod-top,.agent-head,.ctx-gauge-head{display:flex;align-items:center;justify-content:space-between;gap:7px}
.panel-head,.mod-top,.agent-head{flex-wrap:wrap;align-items:flex-start}.panel-head{align-items:center}
.brand,.nav-sys,.tabs,.ws-name-wrap,.legend-item,.inline-confirm-actions{display:inline-flex;align-items:center;gap:6px;flex-shrink:0}
.brand-dot,.live-dot{width:8px;height:8px;border-radius:999px;background:var(--g-ok);flex-shrink:0}
.brand-dot.warn{background:var(--g-warn)}.brand-dot.error{background:var(--g-err)}
.live-dot{box-shadow:0 0 0 3px var(--g-ok-bg)}.live-dot.paused{background:var(--g-warn);box-shadow:0 0 0 3px var(--g-warn-bg)}.live-dot.idle{background:var(--g-fg-dim);box-shadow:none}
.brand-title{font-size:13.5px;font-weight:600;letter-spacing:-.01em;white-space:nowrap}
.brand-sub{font-size:11px;color:var(--g-fg-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px}
.nav-main{display:flex;align-items:center;gap:3px;flex:1;overflow-x:auto;scrollbar-width:none}
.actions-row,.live-controls,.subtabs,.pill-list{display:flex;flex-wrap:wrap;align-items:center;gap:6px}.pill-list{gap:4px}
.tab-btn{appearance:none;background:transparent;border:1px solid transparent;color:var(--g-fg-sec);font:inherit;font-size:12.5px;font-weight:500;padding:5px 9px;border-radius:6px;cursor:pointer;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;transition:background-color .14s,color .14s,border-color .14s}
.tab-btn:hover{color:var(--g-fg);background:var(--g-muted)}.tab-btn.active{color:var(--g-fg);background:var(--g-accent-bg);border-color:var(--g-accent)}
.tab-btn.tab-sys{font-size:11.5px;color:var(--g-fg-dim);padding:4px 8px}.tab-btn.tab-sys.active{color:var(--g-fg)}
.tab-btn:focus-visible,.btn:focus-visible,.input:focus-visible,.select:focus-visible,summary:focus-visible,.tree-toggle:focus-visible,.phase-card:focus-visible{outline:2px solid var(--g-accent);outline-offset:1px}
.btn{appearance:none;background:var(--g-muted);color:var(--g-fg);border:1px solid var(--g-border);border-radius:var(--g-radius-sm);padding:5px 9px;font:inherit;font-size:12px;font-weight:500;cursor:pointer;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;transition:border-color .14s,background-color .14s}
.btn:hover{border-color:var(--g-accent)}.btn.active,.btn-primary{background:var(--g-accent-bg);color:var(--g-accent);border-color:var(--g-accent)}
.btn-danger{background:var(--g-err-bg);color:var(--g-err);border-color:transparent}.btn-danger:hover{border-color:var(--g-err)}
.btn-sm{padding:3px 8px;font-size:11.5px}.btn:disabled{opacity:.55;cursor:not-allowed}
.input,.select{background:var(--g-bg);color:var(--g-fg);border:1px solid var(--g-border);border-radius:var(--g-radius-sm);padding:5px 8px;font:inherit;font-size:12px;min-width:0;max-width:100%}
.select{min-width:125px}.search-wrap{position:relative;display:inline-flex;align-items:center}.search-wrap .input{padding-right:24px;min-width:160px}
.kbd-hint{position:absolute;right:6px;font-family:var(--g-mono);font-size:10px;color:var(--g-fg-dim);border:1px solid var(--g-border);border-radius:4px;padding:0 4px;pointer-events:none;line-height:1.4}
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--g-border);background:var(--g-muted);color:var(--g-fg-sec);white-space:nowrap;max-width:100%}
.badge.ok,.notice.ok,.toast.ok{background:var(--g-ok-bg);color:var(--g-ok);border-color:transparent}
.badge.warn,.notice.warn,.toast.warn{background:var(--g-warn-bg);color:var(--g-warn);border-color:transparent}
.badge.danger,.badge.error,.badge.crit,.toast.error{background:var(--g-err-bg);color:var(--g-err);border-color:transparent}
.badge.info,.notice.info{background:var(--g-accent-bg);color:var(--g-accent);border-color:transparent}
.badge.atelier,.badge-atelier,.badge.src-swarm{background:var(--g-atelier-bg);color:var(--g-atelier);border-color:transparent}
.badge.code,.badge-code,.badge.src-subagent{background:var(--g-code-bg);color:var(--g-code);border-color:transparent}
.badge.src-root{background:var(--g-accent-bg);color:var(--g-accent);border-color:transparent}
.badge.src-workflow{background:var(--g-warn-bg);color:var(--g-warn);border-color:transparent}
.badge.src-other{background:var(--g-muted);color:var(--g-fg-sec)}
.badge-model,.tree-count{background:var(--g-bg);color:var(--g-fg);border-color:var(--g-border);font-family:var(--g-mono);font-size:10.5px;padding:1px 6px}
.panel,.inspector-pane{background:var(--g-card);border:1px solid var(--g-border);border-radius:var(--g-radius);padding:10px 12px;display:flex;flex-direction:column;gap:8px;max-width:100%}
.panel-title{font-size:13px;font-weight:600;color:var(--g-fg)}
.grid-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px}
.kpi-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px}
.kpi-card{background:var(--g-muted);border:1px solid var(--g-border-soft);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:2px}
.kpi-strip .kpi-card{padding:6px 8px}.kpi-strip .kpi-val{font-size:14.5px}
.kpi-card.warn{border-color:var(--g-warn)}.kpi-card.error,.kpi-card.danger{border-color:var(--g-err)}.kpi-card.ok{border-color:var(--g-ok)}
.kpi-lbl{font-size:11px;color:var(--g-fg-sec);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kpi-val{font-size:16px;font-weight:600;color:var(--g-fg)}.kpi-sub{font-size:11px;color:var(--g-fg-dim);overflow-wrap:anywhere}
.grid-cards,.agent-grid,.proj-grid{display:grid;grid-template-columns:1fr;gap:8px}
.mod-card,.agent-card,.drawer,.wave-group,.ab-row{background:var(--g-muted);border:1px solid var(--g-border);border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:7px;color:inherit;font:inherit}
.drawer,.wave-group,.ab-row{border-color:var(--g-border-soft);padding:9px;gap:6px}
.mod-card{cursor:pointer;text-align:left}.mod-card:hover{border-color:var(--g-accent)}
.agent-card.active{border-left:3px solid var(--g-ok)}.agent-card.waiting{border-left:3px solid var(--g-warn)}.agent-card.done{border-left:3px solid var(--g-fg-dim);opacity:.92}.agent-card.error{border-left:3px solid var(--g-err)}
.mod-name,.agent-role{font-weight:600;font-size:12.5px;overflow-wrap:anywhere}.agent-task{font-size:12px;color:var(--g-fg-sec);overflow-wrap:anywhere}
.agent-stats{display:flex;flex-wrap:wrap;gap:6px 10px;font-size:11.5px;color:var(--g-fg-sec)}
.agent-group.has-error{border-left:2px solid var(--g-err);padding-left:8px}
.agent-filiation{font-size:11px;color:var(--g-fg-sec);overflow-wrap:anywhere}
.agent-done-fold>.fold-summary{padding:7px 10px;font-size:12px;color:var(--g-fg-sec)}.agent-done-fold>.fold-body{padding:8px}
.pill{font-family:var(--g-mono);font-size:11px;padding:2px 6px;border-radius:5px;background:var(--g-bg);border:1px solid var(--g-border-soft);color:var(--g-fg-sec);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ctx-gauge{gap:4px}.ctx-gauge-head{font-size:11px;color:var(--g-fg-sec)}
.ctx-track,.wf-progress-track,.ws-bar-track,.ab-track,.gantt-track{width:100%;height:6px;border-radius:999px;background:var(--g-bg);border:1px solid var(--g-border-soft);overflow:hidden}
.ab-track{flex:1}.gantt-track{position:relative;height:7px}
.ctx-fill,.wf-progress-fill,.ws-bar-fill,.ab-fill{height:100%;border-radius:999px;background:var(--g-accent);transition:width .2s}
.ctx-fill.ok{background:var(--g-ok)}.ctx-fill.warn{background:var(--g-warn)}.ctx-fill.crit{background:var(--g-err)}.ab-fill.a{opacity:.55}
.stack-wrap{gap:6px}.stack-bar,.phase-strip{display:flex;width:100%;height:8px;border-radius:999px;overflow:hidden;gap:2px;background:var(--g-bg);border:1px solid var(--g-border-soft)}
.stack-seg,.phase-seg{height:100%;min-width:3px;border-radius:999px}.stack-legend{display:flex;flex-wrap:wrap;gap:6px 12px;font-size:11.5px;color:var(--g-fg-sec)}
.legend-dot{width:8px;height:8px;border-radius:999px;flex-shrink:0}
.ws-list{gap:8px}.ws-row{gap:4px}.ws-row-head{font-size:12px}
.phase-stepper{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:6px}
.phase-card{appearance:none;text-align:left;background:var(--g-bg);color:var(--g-fg);border:1px solid var(--g-border-soft);border-radius:8px;padding:7px 9px;cursor:pointer;display:flex;flex-direction:column;gap:3px;font:inherit;transition:border-color .14s,background-color .14s}
.phase-card:hover{border-color:var(--g-border)}.phase-card.selected{border-color:var(--g-accent);background:var(--g-accent-bg)}.phase-card.active{border-color:var(--g-accent)}.phase-card.error{border-color:var(--g-err)}
.phase-top,.phase-nums{font-size:12px}.phase-lbl{font-weight:600}
.phase-ico.done{color:var(--g-ok)}.phase-ico.active{color:var(--g-accent)}.phase-ico.error{color:var(--g-err)}.phase-ico.pending{color:var(--g-fg-dim)}
.fold-panel{background:var(--g-card);border:1px solid var(--g-border);border-radius:var(--g-radius);padding:0}
.fold-summary{list-style:none;cursor:pointer;padding:9px 11px;display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12.5px;font-weight:600;user-select:none}
.fold-summary::-webkit-details-marker{display:none}
.fold-body{padding:9px 11px 11px;border-top:1px solid var(--g-border-soft);display:flex;flex-direction:column;gap:8px}
.session-bar{gap:7px}.table-wrap{overflow-x:auto;border:1px solid var(--g-border-soft);border-radius:8px;max-width:100%}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:7px 9px;border-bottom:1px solid var(--g-border-soft);text-align:left;vertical-align:top}
th{font-size:11px;font-weight:600;color:var(--g-fg-sec);background:var(--g-muted)}
tr:last-child td{border-bottom:none}tr.clickable{cursor:pointer}tr.clickable:hover td{background:var(--g-muted)}tr.selected td{background:var(--g-accent-bg)}
td.num,th.num{text-align:right;white-space:nowrap}
.split,.master-detail,.split-tree{display:grid;grid-template-columns:minmax(0,1fr)}
.tree-wrap{border:1px solid var(--g-border-soft);border-radius:8px;padding:7px;background:var(--g-bg);gap:6px}
.tree-children{position:relative;margin-left:14px;padding-left:14px;margin-top:6px;gap:6px}
.tree-branch{position:relative}
.tree-branch::before{content:"";position:absolute;left:-14px;top:-6px;bottom:-6px;width:1px;background:var(--g-border)}
.tree-branch:last-child::before{bottom:auto;height:16px}
.tree-branch::after{content:"";position:absolute;left:-14px;top:10px;width:14px;height:10px;border-left:1px solid var(--g-border);border-bottom:1px solid var(--g-border);border-bottom-left-radius:6px}
.tree-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(84px,136px);align-items:center;gap:8px;padding:7px 9px;border:1px solid var(--g-border-soft);border-left:3px solid transparent;border-radius:8px;background:var(--g-card);cursor:pointer;transition:background-color .12s,border-color .12s}
.tree-row:hover{background:var(--g-muted);border-color:var(--g-border)}
.tree-row.depth-2,.tree-row.depth-3,.tree-row.depth-4{background:var(--g-elev)}
.tree-row.status-active{border-left-color:var(--g-ok)}.tree-row.status-waiting{border-left-color:var(--g-warn)}.tree-row.status-error{border-left-color:var(--g-err)}
.tree-row.selected{background:var(--g-accent-bg);border-color:var(--g-accent);border-left-color:var(--g-accent)}.tree-row.selected.status-error{border-left-color:var(--g-err)}
.tree-row.dimmed{opacity:.52}
.tree-indent{display:flex;align-items:flex-start;gap:6px}
.tree-toggle{appearance:none;background:var(--g-muted);border:1px solid var(--g-border);color:var(--g-fg-sec);width:18px;height:18px;border-radius:4px;font-size:10px;line-height:1;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}
.tree-toggle:hover{border-color:var(--g-accent);color:var(--g-fg)}
.tree-main{gap:3px}.tree-head{display:flex;flex-wrap:wrap;align-items:center;gap:4px 5px}.tree-meta{display:flex;flex-wrap:wrap;align-items:center;gap:3px 8px;font-size:11px;color:var(--g-fg-sec)}
.gantt-mini{gap:3px}.gantt-bar{position:absolute;top:0;bottom:0;border-radius:999px;min-width:4px;background:var(--g-fg-dim)}
.gantt-bar.active{background:var(--g-ok)}.gantt-bar.waiting,.gantt-bar.interrupted{background:var(--g-warn)}.gantt-bar.error{background:var(--g-err)}
.gantt-time{font-size:10.5px;color:var(--g-fg-dim);text-align:right;font-family:var(--g-mono)}
.inspector-events{max-height:260px;overflow-y:auto;border:1px solid var(--g-border-soft);border-radius:8px}
.ab-line{display:flex;align-items:center;gap:7px;font-size:11px}.ab-tag{width:14px;font-family:var(--g-mono);color:var(--g-fg-sec);flex-shrink:0}
.axis-tabs{display:inline-flex;flex-wrap:wrap;gap:3px;padding:3px;background:var(--g-bg);border:1px solid var(--g-border-soft);border-radius:8px}
.slide-over-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.48);display:flex;justify-content:flex-end;z-index:40}
.slide-over{width:min(640px,100vw);height:100%;background:var(--g-bg);border-left:1px solid var(--g-border);padding:14px;overflow-y:auto;display:flex;flex-direction:column;gap:10px}
.notice,.toast,.inline-confirm,.archive-banner{border-radius:8px;padding:8px 10px;font-size:12px;border:1px solid var(--g-border);background:var(--g-muted);color:var(--g-fg-sec)}
.archive-banner{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;border-left:3px solid var(--g-accent);background:var(--g-elev)}
.btn-reset-session{border-color:var(--g-accent);color:var(--g-accent)}
.pagination-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;padding:7px 10px;background:var(--g-muted);border:1px solid var(--g-border-soft);border-radius:8px;font-size:12px}
#g-live-session{max-width:340px}
.toast{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 11px;background:var(--g-accent-bg);color:var(--g-accent)}
.inline-confirm{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;border-color:var(--g-warn);background:var(--g-warn-bg)}
.inline-confirm.danger{border-color:var(--g-err);background:var(--g-err-bg)}
.empty{padding:16px;text-align:center;color:var(--g-fg-sec);font-size:12.5px;background:var(--g-muted);border-radius:8px}
.svg-box{width:100%;overflow-x:auto}.svg-box svg{width:100%;height:auto;display:block}.sparkline{width:76px;height:22px;display:block;flex-shrink:0}
.event-row{display:flex;flex-wrap:wrap;align-items:center;gap:5px 7px;padding:6px 8px;border-bottom:1px solid var(--g-border-soft);font-size:11.5px;min-width:0}.event-row:last-child{border-bottom:none}
.kv-grid{display:grid;grid-template-columns:minmax(92px,auto) minmax(0,1fr);gap:4px 10px;font-size:12px}.kv-k{color:var(--g-fg-sec);font-weight:500}
.preview-text{max-width:100%;color:var(--g-fg-sec);font-size:11.5px;line-height:1.35;overflow-wrap:anywhere}
:root[data-layout="compact"] .topbar{flex-wrap:wrap;gap:6px}
:root[data-layout="compact"] .brand-sub,:root[data-layout="compact"] .kpi-strip .kpi-sub{display:none}
:root[data-layout="compact"] .kpi-strip{grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}
:root[data-layout="compact"] .kpi-strip .kpi-card{padding:5px 7px}:root[data-layout="compact"] .kpi-strip .kpi-val{font-size:13px}
:root[data-layout="compact"] .tree-row{grid-template-columns:minmax(0,1fr) 82px;padding:6px 8px}
@container app (min-width:620px){.grid-cards,.agent-grid,.proj-grid{grid-template-columns:repeat(auto-fill,minmax(255px,1fr))}}
@container app (min-width:860px){.app{padding:12px 14px}.kpi-strip{grid-template-columns:repeat(6,minmax(0,1fr))}.split.with-drawer,.master-detail,.split-tree{grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);align-items:start}}
"""

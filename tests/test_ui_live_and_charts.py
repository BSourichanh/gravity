"""Unit tests for Wave W10 UI design system, charts_js, live_views_js, metrics_views_js, and HTML budget."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from mcp import ui as ui_pkg  # noqa: E402
from mcp.ui.app_js import APP_JS  # noqa: E402
from mcp.ui.charts_js import CHARTS_JS  # noqa: E402
from mcp.ui.live_views_js import LIVE_VIEWS_JS  # noqa: E402
from mcp.ui.metrics_views_js import METRICS_VIEWS_JS  # noqa: E402
from mcp.ui.styles import WIDGET_CSS  # noqa: E402
from mcp.ui.views_js import VIEWS_JS  # noqa: E402
from mcp.widget_html import render_dashboard_html  # noqa: E402


_DOM_HARNESS_JS = r"""
function makeNode(tag) {
  const node = {
    tagName: String(tag).toUpperCase(),
    className: "",
    textContent: "",
    attrs: {},
    style: {},
    children: [],
    listeners: {},
    value: "",
    selected: false,
    disabled: false,
    open: false,
    get firstChild() { return this.children[0] || null; },
    appendChild(child) { this.children.push(child); return child; },
    removeChild(child) {
      const idx = this.children.indexOf(child);
      if (idx >= 0) this.children.splice(idx, 1);
      return child;
    },
    setAttribute(k, v) {
      this.attrs[k] = String(v);
      if (k === "id") this.id = String(v);
      if (k === "value") this.value = String(v);
    },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    addEventListener(ev, fn) {
      this.listeners[ev] = this.listeners[ev] || [];
      this.listeners[ev].push(fn);
    }
  };
  return node;
}
function collectText(node) {
  if (!node) return "";
  let out = node.textContent ? [node.textContent] : [];
  for (const ch of (node.children || [])) out.push(collectText(ch));
  return out.join(" ");
}
function findAll(node, pred, acc) {
  acc = acc || [];
  if (!node) return acc;
  if (pred(node)) acc.push(node);
  for (const ch of (node.children || [])) findAll(ch, pred, acc);
  return acc;
}
const document = {
  createElement(tag) { return makeNode(tag); },
  createElementNS(_ns, tag) { return makeNode(tag); },
  getElementById() { return null; }
};
const state = {
  overview: { tabs: [] },
  metricsSub: "overview",
  metricsProject: "",
  metricsQ: "",
  metricsFilter: "recorded",
  metricsSort: "date",
  metrics: {
    projects: ["gravity"],
    kpis: { sessions_count: 14, useful_tokens: 57000, cache_read_tokens: 10000, thinking_est_tokens: 500, total_tokens: 67000 },
    by_workspace: [
      { workspace: "gravity-workshop", kind: "atelier", useful_tokens: 12000, sessions: 5, share_pct: 21.1 },
      { workspace: "gravity", kind: "code", useful_tokens: 45000, sessions: 14, share_pct: 78.9 }
    ],
    records: [], pending_sessions: [], ignored_sessions: [], audits: []
  }
};
"""

_ASSERTIONS_JS = r"""
function assert(cond, msg) {
  if (!cond) throw new Error("ASSERT FAILED: " + msg);
}

assert(fmtTokens(420) === "420", "fmtTokens small");
assert(fmtTokens(128400) === "128 k", "fmtTokens k");
assert(fmtTokens(1500000, true) === "1,5 M tokens", "fmtTokens M unit");
assert(fmtDuration(45) === "45 s", "fmtDuration seconds");
assert(fmtDuration(125) === "2 min 05 s", "fmtDuration minutes");
assert(fmtDuration(3720) === "1 h 02 min", "fmtDuration hours");
assert(fmtPct(84.26) === "84,3 %", "fmtPct");

const gOk = renderContextGauge(40000, 60000);
assert(collectText(gOk).includes("40 k"), "gauge ok value");
assert(findAll(gOk, (n) => n.className.includes("ctx-fill ok")).length === 1, "gauge ok class");

const gWarn = renderContextGauge(150000, 150000);
assert(collectText(gWarn).includes("Alerte >128k"), "gauge warn badge");
assert(findAll(gWarn, (n) => n.className.includes("ctx-fill warn")).length === 1, "gauge warn class");

const gCrit = renderContextGauge(220000, 220000);
assert(collectText(gCrit).includes("Critique >200k"), "gauge crit badge");
assert(findAll(gCrit, (n) => n.className.includes("ctx-fill crit")).length === 1, "gauge crit class");

const sb = renderStackedBars([
  { label: "Tokens utiles", value: 30000, color: "var(--g-c1)" },
  { label: "Cache lu", value: 70000, color: "var(--g-c3)" }
], { title: "Tokens" });
assert(findAll(sb, (n) => n.className === "stack-seg").length === 2, "stacked bar segments");
assert(collectText(renderStackedBars([])).includes("Aucune consommation"), "stacked bar empty");

const wb = renderWorkspaceBreakdown([
  { workspace: "gravity-workshop", kind: "atelier", useful_tokens: 12000, agents_count: 1 },
  { workspace: "gravity", kind: "code", useful_tokens: 45000, agents_count: 2 }
]);
const wbTxt = collectText(wb);
assert(wbTxt.includes("Atelier") && wbTxt.includes("Code") && wbTxt.includes("gravity"), "workspace breakdown");

const wbShare = renderWorkspaceBreakdown([
  { workspace: "gravity-workshop", kind: "atelier", useful_tokens: 12000, sessions: 5, share_pct: 21.1 },
  { workspace: "gravity", kind: "code", useful_tokens: 45000, sessions: 14, share_pct: 78.9 }
]);
const wbShareTxt = collectText(wbShare);
assert(wbShareTxt.includes("21,1 %") && wbShareTxt.includes("5 sess.") && wbShareTxt.includes("14 sess."), "workspace breakdown share_pct + sess.");

const metBox = makeNode("div");
renderMetricsUnifiedView(metBox);
assert(collectText(metBox).includes("14 session(s) unique(s)"), "unique sessions badge in workspace panel header");

const kpi = renderMetricKpiCard("Pic", "150 k", "Actuel 120 k", { tone: "warn", series: [10, 40, 90, 150] });
assert(kpi.className.includes("warn") && findAll(kpi, (n) => n.tagName === "SVG").length === 1, "kpi sparkline");

const loadingBox = makeNode("div");
renderLiveView(loadingBox, null, {});
assert(collectText(loadingBox).includes("Chargement"), "live loading");

const emptyBox = makeNode("div");
renderLiveView(emptyBox, { available: false, sessions: [], selected_session: null, agents: [], recent_events: [], workflow: { available: true, is_active: true, stage: "plan", progress: "1/4", mode: "evo", preset_profile: "standard", guard_status: "ON", nodes: { planner: "running" } } }, {});
assert(collectText(emptyBox).includes("Aucune session active") && collectText(emptyBox).includes("Progression du workflow"), "live empty + active workflow");

const defaultProgBox = makeNode("div");
renderLiveView(defaultProgBox, { available: false, sessions: [], selected_session: null, agents: [], recent_events: [], workflow: { available: true, is_active: true, stage: "plan", waves: [{ id: "W9", done: 1, total: 1, status: "done" }, { id: "W10", done: 0, total: 1, status: "running" }], tasks: [{ status: "done" }, { status: "running" }], progress_detail: { label: "1/2", done: 1, total: 2, pct: 50 } } }, {});
const dpTxt = collectText(defaultProgBox);
assert(dpTxt.includes("W9 1/1") && dpTxt.includes("W10 0/1") && dpTxt.includes("1/2 tâche(s)"), "structured live_progress waves & tasks pills");

const zeroProgBox = makeNode("div");
renderLiveView(zeroProgBox, { available: false, sessions: [], selected_session: null, agents: [], recent_events: [], workflow: { available: true, is_active: true, stage: "plan" } }, {});
assert(collectText(zeroProgBox).includes("Avancement : 0/0"), "0/0 default workflow progress");

const idleBox = makeNode("div");
renderLiveView(idleBox, { available: false, sessions: [], selected_session: null, agents: [], recent_events: [], workflow: { available: true, is_active: false, stage: "idle", progress: "0/0" } }, {});
assert(!collectText(idleBox).includes("Progression du workflow"), "idle workflow hidden");

const fullBox = makeNode("div");
const payload = {
  available: true,
  sessions: [
    { conversation_id: "cid-1111", label: "Audit Live", project: "gravity", captured: false, archived: false },
    { conversation_id: "cid-2222", label: "Autre", project: "gravity-metrics", captured: true, archived: true }
  ],
  selected_session: {
    conversation_id: "cid-1111", label: "Audit Live", project: "gravity", workspace_kind: "code", captured: false,
    session_started_at: "2026-11-25T13:00:00Z", session_last_ts: "2026-11-25T13:03:05Z", last_ts: new Date().toISOString()
  },
  summary: {
    total_agents: 4, active_agents: 1, waiting_agents: 1, done_agents: 1, error_agents: 1,
    useful_tokens: 95000, cache_read_tokens: 210000, cache_hit_pct: 68.8,
    max_context_tokens: 155000, context_tokens: 140000, thinking_est_tokens: 12000,
    llm_calls: 14, tool_calls: 32, error_count: 1, duration_s: 185
  },
  workflow: {
    available: true, is_active: true, stage: "build", progress: "3/5", mode: "evo",
    preset_profile: "standard", suggested_profile: "quick", guard_status: "ON",
    nodes: { planner: "done", builder: "running", reviewer: "idle" }
  },
  agents: [
    { id: "coord", role: "Coordinator", status: "active", source: "root", depth: 0, model: "gemini-pro", workspace: "gravity-workshop", workspace_kind: "atelier", task_title: "Orchestration", last_tool: "swarm", llm_calls: 6, tool_calls: 12, children_count: 3, context_tokens: 140000, max_context_tokens: 155000, useful_tokens: 40000, cache_hit_pct: 70, started_at: "2026-11-25T13:00:00Z", last_ts: "2026-11-25T13:03:00Z", duration_s: 180, error_count: 0 },
    { id: "w1", role: "Builder", status: "waiting", source: "swarm", parent_id: "coord", parent_name: "Coordinator", depth: 1, model: "gemini-flash", workspace: "gravity", workspace_kind: "code", task_title: "UI Live", last_tool: "edit_file", llm_calls: 4, tool_calls: 8, context_tokens: 45000, max_context_tokens: 45000, useful_tokens: 25000, cache_hit_pct: 65, started_at: "2026-11-25T13:00:30Z", last_ts: "2026-11-25T13:02:00Z", duration_s: 90, error_count: 0 },
    { id: "w2", role: "Reviewer", status: "done", source: "subagent", parent_id: "coord", depth: 1, model: "gemini-pro", workspace: "gravity-metrics", workspace_kind: "code", task_title: "Tests", last_tool: "run_command", llm_calls: 2, tool_calls: 5, context_tokens: 30000, max_context_tokens: 30000, useful_tokens: 20000, cache_hit_pct: 60, started_at: "2026-11-25T13:01:00Z", last_ts: "2026-11-25T13:02:00Z", duration_s: 60, error_count: 0 },
    { id: "w3", role: "Checker", status: "error", source: "workflow", parent_id: "w1", depth: 2, model: "gemini-pro", workspace: "gravity", workspace_kind: "code", task_title: "Lint", last_tool: "run_command", llm_calls: 2, tool_calls: 7, context_tokens: 205000, max_context_tokens: 210000, useful_tokens: 10000, cache_hit_pct: 50, started_at: "2026-11-25T13:02:00Z", last_ts: "2026-11-25T13:02:45Z", duration_s: 45, error_count: 2 }
  ],
  recent_events: [
    { ts: "2026-11-25T13:00:00Z", agent_id: "w1", kind: "tool", name: "edit_file", detail: "styles.py" },
    { ts: "2026-11-25T13:01:00Z", agent_id: "coord", kind: "board", name: "post", detail: "@w1 GO" },
    { ts: "2026-11-25T13:02:00Z", agent_id: "w3", kind: "error", name: "STEP", detail: "FAILED" }
  ]
};
renderLiveView(fullBox, payload, { paused: false, selectedAgentId: "w1", eventsOpen: true });
const fullTxt = collectText(fullBox);
assert(fullTxt.includes("Enregistrer") && fullTxt.includes("Pause") && fullTxt.includes("Projets"), "capture, pause & projects buttons");
assert(findAll(fullBox, (n) => n.attrs && n.attrs["data-freshness"] === "1").length === 1, "freshness badge attr");
assert(findAll(fullBox, (n) => n.className.includes("kpi-strip")).length === 1, "kpi-strip rendered");
assert(findAll(fullBox, (n) => n.className.includes("tree-row")).length === 4, "4 hierarchical tree rows");
assert(findAll(fullBox, (n) => n.className.includes("gantt-mini")).length === 4, "4 timeline bars");
assert(fullTxt.includes("Racine") && fullTxt.includes("Swarm") && fullTxt.includes("Subagent") && fullTxt.includes("Workflow"), "source badges");
assert(fullTxt.includes("[archivée]"), "archived suffix in live session selector");
const inspNode = findAll(fullBox, (n) => n.id === "g-live-inspector")[0];
const inspTxt = collectText(inspNode);
assert(inspTxt.includes("Builder") && inspTxt.includes("↳ Coordinator · N1") && inspTxt.includes("styles.py") && !inspTxt.includes("@w1 GO"), "inspector filters events by selected agent");

const collapsedBox = makeNode("div");
renderLiveView(collapsedBox, payload, { collapsedAgents: { coord: true }, selectedAgentId: "__all__" });
assert(findAll(collapsedBox, (n) => n.className.includes("tree-row")).length === 1, "collapsed root hides descendants");
const globalInsp = collectText(findAll(collapsedBox, (n) => n.id === "g-live-inspector")[0]);
assert(globalInsp.includes("Activité récente (3)") && globalInsp.includes("@w1 GO") && globalInsp.includes("styles.py"), "global inspector mode shows all events");

assert(resolveAgentModel({ by_model: { "gemini-4-neon-high": { calls: 12 }, "gemini-4-hydrogen-high": { calls: 3 } } }) === "gemini-4-neon-high", "resolveAgentModel by_model");
assert(resolveAgentModel({ model: "gemini-pro" }) === "gemini-pro", "resolveAgentModel legacy");
assert(resolveAgentToolCalls({ tool_calls_total: 42 }) === 42 && resolveAgentToolCalls({ tool_calls: 9 }) === 9, "resolveAgentToolCalls");

state.metricsSub = "sessions";
state.sessionTarget = "s-35";
state.sessionDetailSub = "agents";
const manyMetricsAgents = [
  { conversation_id: "cid-root", role: "root", source: "root", depth: 0, category: "orchestration", workspace: "gravity-workshop", workspace_kind: "atelier", by_model: { "gemini-4-neon-high": { calls: 10 } }, tool_calls_total: 41, llm_calls: 10, input_tokens: 15000, output_tokens: 3000, cache_read_tokens: 40000, max_context_tokens: 90000, active_s: 125, clean_termination: true, cost_usd: { total_usd: 0.42 } },
  { conversation_id: "cid-intr", role: "Scout", source: "subagent", parent_id: "cid-root", depth: 1, category: "discovery", workspace: "gravity", workspace_kind: "code", by_model: { "gemini-4-hydrogen-high": { calls: 4 } }, tool_calls_total: 11, llm_calls: 4, max_context_tokens: 30000, active_s: 35, clean_termination: false, error_steps: 0 },
  { conversation_id: "cid-err", role: "Audit", source: "workflow", parent_id: "cid-root", depth: 1, category: "verification", workspace: "gravity", workspace_kind: "code", by_model: { "gemini-4-hydrogen-high": { calls: 3 } }, tool_calls_total: 9, llm_calls: 3, max_context_tokens: 40000, active_s: 45, clean_termination: false, error_steps: 2, total_anomalies: 3 }
];
for (let i = 3; i < 35; i++) {
  manyMetricsAgents.push({
    conversation_id: "cid-w-" + i, role: "Worker-" + i, source: "swarm", parent_id: "cid-root", depth: 1,
    category: "build", workspace: "gravity", workspace_kind: "code", by_model: { "gemini-4-hydrogen-high": { calls: 2 } },
    tool_calls_total: 5, llm_calls: 2, max_context_tokens: 25000, active_s: 20, clean_termination: true
  });
}
state.metrics.records = [{ conversation_id: "cid-root", label: "Session 35", detail_slug: "s-35", project: "gravity", status: "archived", input_tokens: 15000, output_tokens: 3000, cache_read_tokens: 40000, total_tokens: 58000, max_context_tokens: 90000, llm_calls: 17, tool_calls: 61 }];
state.sessionDetail = {
  found: true, source: "report_json", slug: "s-35", conversation_id: "cid-root", label: "Session 35",
  record: state.metrics.records[0],
  detail: { summary: { input_tokens: 15000, output_tokens: 3000, cache_read_tokens: 40000 }, agents: manyMetricsAgents }
};
const det35Box = makeNode("div");
renderMetricsUnifiedView(det35Box);
const det35Txt = collectText(det35Box);
assert(findAll(det35Box, (n) => n.className && n.className.includes("tree-row")).length === 35, "metrics detail renders all 35 agents in tree");
assert(findAll(det35Box, (n) => n.className === "slide-over").length === 1 && findAll(det35Box, (n) => n.id === "g-session-inspector").length === 1, "metrics detail renders in slide-over with inspector");
assert(det35Txt.includes("35 agent(s)") && det35Txt.includes("Worker-34") && det35Txt.includes("Outils : 41"), "35th agent & tool_calls_total");

state.architectSub = "projects";
state.architect = {
  available: true,
  atelier_root: "/tmp/gravity-workshop",
  discovery_source: "architect_registry",
  ecosystem: { exists: true, size_bytes: 2048, budget_bytes: 6000, over_budget: false, alerts: [] },
  delta: { exists: true, editorial_status: "NO_EDITORIAL_CHANGES", date: "2026-11-26", hygiene_alerts: [] },
  watches_count: 2,
  archived_specs_count: 1,
  archived_tasks_count: 2,
  projects: [{ id: "gravity", name: "Gravity", path: "../gravity", role: "core", main_branch: "main", default_dev_branch: "dev", release_main: "0.3.0", dev_status: "ahead 2", installed_version: "0.3.0", wip_status: "clean", specs_count: 1, tasks_count: 2, audits_count: 1, card_bytes: 1200, card_uri: "file:///tmp/gravity.md" }],
  specs: [{ filename: "s.md", title: "Spec UI", target_project: "gravity", status: "validated", status_code: "validated", date: "2026-11-26", size_bytes: 900, uri: "file:///tmp/s.md" }],
  tasks: [{ filename: "t1.md", title: "Task W1", target_project: "gravity", wave: 1, status: "done", status_code: "done", workflow_profile: "quick", expected_branch: "dev", dependencies: [], date: "2026-11-26", uri: "file:///tmp/t1.md" }],
  waves_summary: { total_tasks: 1, waves_count: 1, waves: [{ wave: 1, tasks_count: 1, projects: ["gravity"], status_counts: { done: 1 } }] },
  audits: []
};
const archBox = makeNode("div");
renderArchitectView(archBox);
const archTxt = collectText(archBox);
assert(findAll(archBox, (n) => n.className === "proj-grid").length === 1 && archTxt.includes("Voir sessions") && archTxt.includes("Ouvrir fiche"), "architect projects grid & cross-link");
state.architectSub = "waves";
const archWaves = makeNode("div");
renderArchitectView(archWaves);
assert(findAll(archWaves, (n) => n.className === "wave-group").length === 1 && collectText(archWaves).includes("Vague 1"), "architect waves group");

const pausedBox = makeNode("div");
payload.selected_session.captured = true;
renderLiveView(pausedBox, payload, { paused: true });
const pausedTxt = collectText(pausedBox);
assert(pausedTxt.includes("Mettre à jour") && pausedTxt.includes("Reprendre") && pausedTxt.includes("En pause"), "captured & paused labels");
console.log(JSON.stringify({ ok: true }));
"""


class TestUiLiveAndCharts(unittest.TestCase):
    def test_ui_exports_and_line_budgets(self) -> None:
        self.assertEqual(
            ui_pkg.__all__,
            ["APP_JS", "CHARTS_JS", "LIVE_VIEWS_JS", "METRICS_VIEWS_JS", "VIEWS_JS", "WIDGET_CSS"],
        )
        ui_dir = PLUGIN_ROOT / "mcp" / "ui"
        self.assertLess(len((ui_dir / "charts_js.py").read_text(encoding="utf-8").splitlines()), 600)
        self.assertLess(len((ui_dir / "live_views_js.py").read_text(encoding="utf-8").splitlines()), 600)
        self.assertLess(len((ui_dir / "metrics_views_js.py").read_text(encoding="utf-8").splitlines()), 800)

    def test_html_budget_and_security_invariants(self) -> None:
        html = render_dashboard_html()
        html_bytes = len(html.encode("utf-8"))
        self.assertLess(html_bytes, 150 * 1024, msg=f"HTML bundle {html_bytes} B exceeds 150 KiB budget")
        for forbidden in (
            "innerHTML", "http://", "https://", "window.confirm", "window.alert", "window.prompt",
            "0/8", "gravity-studio", "gravity-bridge",
        ):
            self.assertNotIn(forbidden, html)
        for dead in ("renderWorkflowView", "renderArchitectSvgChart", "renderBridgeView", "renderBridgeSvgChart"):
            self.assertNotIn(dead, html)
        for css_token in (
            "@container app", ".master-detail", ".agent-card", ".ctx-gauge", ".badge-atelier", ".badge-code",
            ".fold-panel", ".inline-confirm", ".badge.src-root", ".agent-filiation", ".agent-done-fold", ".agent-group.has-error",
            ".topbar", ".nav-sys", ".kpi-strip", ".tree-row", ".tree-indent", ".gantt-mini",
            ".inspector-pane", ".slide-over", ".proj-grid", ".wave-group", 'data-layout="compact"',
        ):
            self.assertIn(css_token, WIDGET_CSS)
        for js_symbol in (
            "fmtTokens", "fmtDuration", "fmtPct", "renderContextGauge", "renderStackedBars", "renderWorkspaceBreakdown",
            "renderMetricKpiCard", "renderLiveView", "renderMetricsUnifiedView", "resolveAgentModel", "resolveAgentToolCalls",
            "renderSourceBadge", "renderFiliationLabel", "buildAgentHierarchy", "renderAgentTree", "renderTimelineBar",
            "navigateTo", "applyHostContext", "openMarkdownFile",
        ):
            self.assertIn(js_symbol, html)

    def test_app_controller_and_live_view_contracts(self) -> None:
        self.assertNotIn("pollInFlight", APP_JS)
        for token in ("inflight", "reqSeq", "ResizeObserver", "Escape", "CLICK_HANDLERS", "g-content", "g-slideover", "data-freshness"):
            self.assertIn(token, APP_JS)
        self.assertIn("data-freshness", LIVE_VIEWS_JS)
        self.assertNotIn("Actualiser", LIVE_VIEWS_JS)
        self.assertIn("0/0", LIVE_VIEWS_JS)
        self.assertIn("buildAgentHierarchy", CHARTS_JS)
        self.assertIn("renderAgentTree", CHARTS_JS)
        self.assertIn("renderTimelineBar", CHARTS_JS)
        self.assertIn("renderMetricsUnifiedView", METRICS_VIEWS_JS)

    def test_js_syntax_and_dom_renderers(self) -> None:
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node binary not available")

        html = render_dashboard_html()
        match = re.search(r"<script>\n(.*)\n</script>", html, flags=re.DOTALL)
        self.assertIsNotNone(match)
        assert match is not None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bundle_js = tmp_path / "bundle.js"
            bundle_js.write_text(match.group(1), encoding="utf-8")
            chk = subprocess.run([node_bin, "--check", str(bundle_js)], capture_output=True, text=True, check=False)
            self.assertEqual(chk.returncode, 0, msg=chk.stderr or chk.stdout)

            dom_test = tmp_path / "dom_test.js"
            dom_test.write_text(
                "\n".join([_DOM_HARNESS_JS, VIEWS_JS, CHARTS_JS, LIVE_VIEWS_JS, METRICS_VIEWS_JS, _ASSERTIONS_JS]),
                encoding="utf-8",
            )
            run = subprocess.run([node_bin, str(dom_test)], capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, msg=run.stderr or run.stdout)
            out = json.loads(run.stdout.strip())
            self.assertTrue(out.get("ok"))


if __name__ == "__main__":
    unittest.main()

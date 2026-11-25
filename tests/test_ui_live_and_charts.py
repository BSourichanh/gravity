"""Unit tests for Wave 3 UI design system, charts_js, live_views_js, and HTML budget."""

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
      { workspace: "gravity-studio", kind: "atelier", useful_tokens: 12000, sessions: 5, share_pct: 21.1 },
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
  { workspace: "gravity-studio", kind: "atelier", useful_tokens: 12000, agents_count: 1 },
  { workspace: "gravity", kind: "code", useful_tokens: 45000, agents_count: 2 }
]);
const wbTxt = collectText(wb);
assert(wbTxt.includes("Atelier") && wbTxt.includes("Code") && wbTxt.includes("gravity"), "workspace breakdown");

const wbShare = renderWorkspaceBreakdown([
  { workspace: "gravity-studio", kind: "atelier", useful_tokens: 12000, sessions: 5, share_pct: 21.1 },
  { workspace: "gravity", kind: "code", useful_tokens: 45000, sessions: 14, share_pct: 78.9 }
]);
const wbShareTxt = collectText(wbShare);
assert(wbShareTxt.includes("21,1 %") && wbShareTxt.includes("5 sess.") && wbShareTxt.includes("14 sess."), "workspace breakdown share_pct + sess.");

const metBox = makeNode("div");
renderMetricsUnifiedView(metBox);
const metTxt = collectText(metBox);
assert(metTxt.includes("14 session(s) unique(s)"), "unique sessions badge in workspace panel header");

const kpi = renderMetricKpiCard("Pic", "150 k", "Actuel 120 k", { tone: "warn", series: [10, 40, 90, 150] });
assert(kpi.className.includes("warn") && findAll(kpi, (n) => n.tagName === "SVG").length === 1, "kpi sparkline");

const loadingBox = makeNode("div");
renderLiveView(loadingBox, null, {});
assert(collectText(loadingBox).includes("Chargement"), "live loading");

const emptyBox = makeNode("div");
renderLiveView(emptyBox, { available: false, sessions: [], selected_session: null, agents: [], recent_events: [], workflow: { available: true, stage: "plan", progress: "1/4", mode: "evo", preset_profile: "standard", guard_status: "ON", nodes: { planner: "running" } } }, {});
assert(collectText(emptyBox).includes("Aucune session active") && collectText(emptyBox).includes("Progression du workflow"), "live empty + workflow");

const fullBox = makeNode("div");
const payload = {
  available: true,
  sessions: [
    { conversation_id: "cid-1111", label: "Audit Live", project: "gravity", captured: false, archived: false },
    { conversation_id: "cid-2222", label: "Autre", project: "gravity-metrics", captured: true, archived: true }
  ],
  selected_session: {
    conversation_id: "cid-1111",
    label: "Audit Live",
    project: "gravity",
    workspace_kind: "code",
    captured: false,
    last_ts: new Date().toISOString()
  },
  summary: {
    total_agents: 4, active_agents: 1, waiting_agents: 1, done_agents: 1, error_agents: 1,
    useful_tokens: 95000, cache_read_tokens: 210000, cache_hit_pct: 68.8,
    max_context_tokens: 155000, context_tokens: 140000, thinking_est_tokens: 12000,
    llm_calls: 14, tool_calls: 32, error_count: 1, duration_s: 185
  },
  workflow: {
    available: true, stage: "build", progress: "3/8", mode: "evo",
    preset_profile: "standard", suggested_profile: "quick", guard_status: "ON",
    nodes: { planner: "done", builder: "running", reviewer: "idle" }
  },
  agents: [
    { id: "coord", role: "Coordinator", status: "active", source: "root", depth: 0, model: "gemini-pro", workspace: "gravity-studio", workspace_kind: "atelier", task_title: "Orchestration", last_tool: "swarm", llm_calls: 6, tool_calls: 12, children_count: 3, context_tokens: 140000, max_context_tokens: 155000, useful_tokens: 40000, cache_hit_pct: 70, duration_s: 180, error_count: 0 },
    { id: "w1", role: "Builder", status: "waiting", source: "swarm", parent_id: "coord", parent_name: "Coordinator", depth: 1, model: "gemini-flash", workspace: "gravity", workspace_kind: "code", task_title: "UI Live", last_tool: "edit_file", llm_calls: 4, tool_calls: 8, context_tokens: 45000, max_context_tokens: 45000, useful_tokens: 25000, cache_hit_pct: 65, duration_s: 90, error_count: 0 },
    { id: "w2", role: "Reviewer", status: "done", source: "subagent", parent_id: "coord", depth: 1, model: "gemini-pro", workspace: "gravity-metrics", workspace_kind: "code", task_title: "Tests", last_tool: "run_command", llm_calls: 2, tool_calls: 5, context_tokens: 30000, max_context_tokens: 30000, useful_tokens: 20000, cache_hit_pct: 60, duration_s: 60, error_count: 0 },
    { id: "w3", role: "Checker", status: "error", source: "workflow", parent_id: "w1", depth: 2, model: "gemini-pro", workspace: "gravity", workspace_kind: "code", task_title: "Lint", last_tool: "run_command", llm_calls: 2, tool_calls: 7, context_tokens: 205000, max_context_tokens: 210000, useful_tokens: 10000, cache_hit_pct: 50, duration_s: 45, error_count: 2 }
  ],
  recent_events: [
    { ts: "2026-11-25T13:00:00Z", agent_id: "w1", kind: "tool", name: "edit_file", detail: "styles.py" },
    { ts: "2026-11-25T13:01:00Z", agent_id: "coord", kind: "board", name: "post", detail: "@w1 GO" },
    { ts: "2026-11-25T13:02:00Z", agent_id: "w3", kind: "error", name: "STEP", detail: "FAILED" }
  ]
};
renderLiveView(fullBox, payload, { paused: false, eventsOpen: true });
const fullTxt = collectText(fullBox);
assert(fullTxt.includes("Enregistrer") && fullTxt.includes("Pause"), "capture & pause buttons");
assert(fullTxt.includes("Actifs") && fullTxt.includes("En attente") && fullTxt.includes("Erreurs") && fullTxt.includes("Terminés"), "4 agent status groups");
const groupNodes = findAll(fullBox, (n) => n.attrs && n.attrs["data-agent-group"]);
assert(groupNodes.length === 4, "4 distinct data-agent-group sections");
const activeGrp = groupNodes.find((n) => n.attrs["data-agent-group"] === "active");
const errorGrp = groupNodes.find((n) => n.attrs["data-agent-group"] === "error");
assert(activeGrp && !collectText(activeGrp).includes("Checker"), "error agent extracted out of active group");
assert(errorGrp && collectText(errorGrp).includes("Checker"), "error agent inside error group");
assert(fullTxt.includes("Racine") && fullTxt.includes("Swarm") && fullTxt.includes("Subagent") && fullTxt.includes("Workflow"), "source badges");
assert(fullTxt.includes("↳ Coordinator · N1") && fullTxt.includes("↳ Builder · N2"), "filiation parent and depth");
assert(fullTxt.includes("LLM : 6 · Outils : 12") && fullTxt.includes("1 étape(s) en erreur"), "LLM/tools counts & distinct error banner counter");
assert(findAll(fullBox, (n) => n.className.startsWith("agent-card")).length === 4, "4 agent cards");
assert(fullTxt.includes("Activité récente (3)") && fullTxt.includes("Board") && fullTxt.includes("@w1 GO"), "recent events & board");
assert(fullTxt.includes("Alerte >128k") && fullTxt.includes("Critique >200k"), "gauge thresholds in cards");
assert(fullTxt.includes("[archivée]"), "archived suffix in live session selector");

assert(resolveAgentModel({ by_model: { "gemini-4-neon-high": { calls: 12 }, "gemini-4-hydrogen-high": { calls: 3 } } }) === "gemini-4-neon-high", "resolveAgentModel by_model");
assert(resolveAgentModel({ model: "gemini-pro" }) === "gemini-pro", "resolveAgentModel legacy");
assert(resolveAgentToolCalls({ tool_calls_total: 42 }) === 42 && resolveAgentToolCalls({ tool_calls: 9 }) === 9, "resolveAgentToolCalls");

const doneFoldBox = makeNode("div");
const manyDoneAgents = Array.from({ length: 8 }, (_, i) => ({
  id: "done-" + (i + 1), role: "Worker " + (i + 1), status: "done", source: "swarm",
  parent_id: "coord", parent_name: "Coordinator", depth: 1, model: "gemini-flash",
  workspace: "gravity", workspace_kind: "code", llm_calls: 2, tool_calls: 4, duration_s: 15
}));
renderLiveView(doneFoldBox, {
  available: true,
  sessions: [{ conversation_id: "cid-done", label: "Done Fold", project: "gravity" }],
  selected_session: { conversation_id: "cid-done", label: "Done Fold", project: "gravity", workspace_kind: "code", last_ts: new Date().toISOString() },
  summary: { total_agents: 8, active_agents: 0, waiting_agents: 0, done_agents: 8, error_agents: 0 },
  agents: manyDoneAgents,
  recent_events: []
}, {});
assert(findAll(doneFoldBox, (n) => n.tagName === "DETAILS" && n.className.includes("agent-done-fold")).length === 1, "collapsible done group when > 6");
assert(findAll(doneFoldBox, (n) => n.className.startsWith("agent-card")).length === 8, "all 8 done agents rendered in DOM without truncation");
assert(collectText(doneFoldBox).includes("Terminés (8)") && collectText(doneFoldBox).includes("Worker 8"), "no truncation on done-8");

state.metricsSub = "sessions";
state.sessionTarget = "s-35";
state.sessionDetailSub = "agents";
const manyMetricsAgents = [
  { conversation_id: "cid-root", role: "root", source: "root", depth: 0, category: "orchestration", workspace: "gravity-studio", workspace_kind: "atelier", by_model: { "gemini-4-neon-high": { calls: 10 } }, tool_calls_total: 41, llm_calls: 10, input_tokens: 15000, output_tokens: 3000, cache_read_tokens: 40000, max_context_tokens: 90000, active_s: 125, clean_termination: true, cost_usd: { total_usd: 0.42 } },
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
assert(findAll(det35Box, (n) => n.tagName === "DETAILS" && n.className === "fold-panel").length === 35, "metrics detail renders all 35 agents without slice(0, 30)");
assert(det35Txt.includes("35 agent(s)") && det35Txt.includes("Worker-34") && det35Txt.includes("Outils : 41"), "35th agent & tool_calls_total");
assert(det35Txt.includes("gemini-4-neon-high") && det35Txt.includes("Orchestration") && det35Txt.includes("Découverte") && det35Txt.includes("Vérification") && det35Txt.includes("Construction"), "by_model & ROLE_LABELS_FR");
assert(det35Txt.includes("Interrompu") && det35Txt.includes("Erreur") && det35Txt.includes("↳ root · N1") && det35Txt.includes("Anomalies : 3") && det35Txt.includes("$0.4200"), "metrics detail status, filiation, anomalies, cost");

const pausedBox = makeNode("div");
payload.selected_session.captured = true;
renderLiveView(pausedBox, payload, { paused: true });
const pausedTxt = collectText(pausedBox);
assert(pausedTxt.includes("Mettre à jour") && pausedTxt.includes("Reprendre") && pausedTxt.includes("En pause"), "captured & paused labels");
console.log(JSON.stringify({ ok: true }));
"""


class TestUiLiveAndCharts(unittest.TestCase):
    def test_html_budget_and_security_invariants(self) -> None:
        html = render_dashboard_html()
        html_bytes = len(html.encode("utf-8"))
        self.assertLess(html_bytes, 150 * 1024, msg=f"HTML bundle {html_bytes} B exceeds 150 KiB target")
        for forbidden in ("innerHTML", "http://", "https://", "window.confirm", "window.alert", "window.prompt"):
            self.assertNotIn(forbidden, html)
        for css_token in ("@container app", ".master-detail", ".agent-card", ".ctx-gauge", ".badge-atelier", ".badge-code", ".fold-panel", ".inline-confirm", ".badge.src-root", ".agent-filiation", ".agent-done-fold", ".agent-group.has-error"):
            self.assertIn(css_token, WIDGET_CSS)
        for js_symbol in ("fmtTokens", "fmtDuration", "fmtPct", "renderContextGauge", "renderStackedBars", "renderWorkspaceBreakdown", "renderMetricKpiCard", "renderLiveView", "resolveAgentModel", "resolveAgentToolCalls", "renderSourceBadge", "renderFiliationLabel"):
            self.assertIn(js_symbol, html)

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

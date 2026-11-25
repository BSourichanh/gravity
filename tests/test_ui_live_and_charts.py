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
const state = { overview: { tabs: [] } };
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
    { conversation_id: "cid-1111", label: "Audit Live", project: "gravity", captured: false },
    { conversation_id: "cid-2222", label: "Autre", project: "gravity-metrics", captured: true }
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
    { id: "coord", role: "Coordinator", status: "active", model: "gemini-pro", workspace: "gravity-studio", workspace_kind: "atelier", task_title: "Orchestration", last_tool: "swarm", context_tokens: 140000, max_context_tokens: 155000, useful_tokens: 40000, cache_hit_pct: 70, duration_s: 180, error_count: 0 },
    { id: "w1", role: "Builder", status: "waiting", model: "gemini-flash", workspace: "gravity", workspace_kind: "code", task_title: "UI Live", last_tool: "edit_file", context_tokens: 45000, max_context_tokens: 45000, useful_tokens: 25000, cache_hit_pct: 65, duration_s: 90, error_count: 0 },
    { id: "w2", role: "Reviewer", status: "done", model: "gemini-pro", workspace: "gravity-metrics", workspace_kind: "code", task_title: "Tests", last_tool: "run_command", context_tokens: 30000, max_context_tokens: 30000, useful_tokens: 20000, cache_hit_pct: 60, duration_s: 60, error_count: 0 },
    { id: "w3", role: "Checker", status: "error", model: "gemini-pro", workspace: "gravity", workspace_kind: "code", task_title: "Lint", last_tool: "run_command", context_tokens: 205000, max_context_tokens: 210000, useful_tokens: 10000, cache_hit_pct: 50, duration_s: 45, error_count: 2 }
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
assert(fullTxt.includes("Actifs") && fullTxt.includes("En attente") && fullTxt.includes("Terminés"), "agent status groups");
assert(findAll(fullBox, (n) => n.className.startsWith("agent-card")).length === 4, "4 agent cards");
assert(fullTxt.includes("Activité récente (3)") && fullTxt.includes("Board") && fullTxt.includes("@w1 GO"), "recent events & board");
assert(fullTxt.includes("Alerte >128k") && fullTxt.includes("Critique >200k"), "gauge thresholds in cards");

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
        self.assertLess(html_bytes, 130 * 1024, msg=f"HTML bundle {html_bytes} B exceeds Wave 3 130 KiB target")
        for forbidden in ("innerHTML", "http://", "https://", "window.confirm", "window.alert", "window.prompt"):
            self.assertNotIn(forbidden, html)
        for css_token in ("@container app", ".master-detail", ".agent-card", ".ctx-gauge", ".badge-atelier", ".badge-code", ".fold-panel", ".inline-confirm"):
            self.assertIn(css_token, WIDGET_CSS)
        for js_symbol in ("fmtTokens", "fmtDuration", "fmtPct", "renderContextGauge", "renderStackedBars", "renderWorkspaceBreakdown", "renderMetricKpiCard", "renderLiveView"):
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
                "\n".join([_DOM_HARNESS_JS, VIEWS_JS, CHARTS_JS, LIVE_VIEWS_JS, _ASSERTIONS_JS]),
                encoding="utf-8",
            )
            run = subprocess.run([node_bin, str(dom_test)], capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, msg=run.stderr or run.stdout)
            out = json.loads(run.stdout.strip())
            self.assertTrue(out.get("ok"))


if __name__ == "__main__":
    unittest.main()

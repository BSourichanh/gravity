"""SEP-1865 bridge and state controller for the Gravity MCP App (100% stdlib, zero innerHTML)."""

from __future__ import annotations

APP_JS = r"""
  const PROTOCOL_VERSION = "2026-01-26";
  const LIVE_POLL_MS = 2000;

  const state = {
    hostCaps: {}, hostCtx: {}, overview: null, live: null, workflow: null, metrics: null, architect: null,
    moduleCache: {}, moduleLoading: {}, activeTab: "live", selectedWs: "", selectedAtelier: "",
    liveUi: { paused: false, selectedSessionId: "", eventsOpen: false, actionInFlight: false, lastUpdatedAt: "" },
    metricsProject: "", metricsQ: "", metricsSub: "overview", metricsFilter: "recorded", metricsSort: "date",
    metricsActionInFlight: false, compareOpen: false, compareA: "", compareB: "", architectSub: "projects",
    sessionTarget: "", sessionDetail: null, sessionDetailLoading: false, sessionDetailSub: "summary",
    sessionEditOpen: false, sessionDeleteConfirm: false, pendingDeleteTarget: "",
    auditTarget: "", auditData: null, auditLoading: false, toast: null, loading: true, hasToolResult: false, pollInFlight: false
  };

  let rpcId = 1;
  const pendingRpc = new Map();
  let fallbackTimer = null;
  let livePollTimer = null;
  let metricsSearchTimer = null;
  let toastTimer = null;

  function postToHost(payload) { window.parent.postMessage(payload, "*"); }

  function sendRequest(method, params) {
    const id = rpcId++;
    return new Promise((resolve, reject) => {
      pendingRpc.set(id, { resolve, reject });
      postToHost({ jsonrpc: "2.0", id, method, params: params || {} });
    });
  }

  function sendNotification(method, params) { postToHost({ jsonrpc: "2.0", method, params: params || {} }); }
  function callServerTool(name, args) { return sendRequest("tools/call", { name, arguments: args || {} }); }

  function captureFocusAndScroll() {
    const act = document.activeElement;
    return {
      scrollX: window.scrollX || 0, scrollY: window.scrollY || 0,
      id: act && act.id ? act.id : "",
      action: act && act.getAttribute ? (act.getAttribute("data-action") || "") : "",
      target: act && act.getAttribute ? (act.getAttribute("data-target") || "") : "",
      tab: act && act.getAttribute ? (act.getAttribute("data-tab") || "") : "",
      selStart: (act && typeof act.selectionStart === "number") ? act.selectionStart : null,
      selEnd: (act && typeof act.selectionEnd === "number") ? act.selectionEnd : null
    };
  }

  function restoreFocusAndScroll(snap) {
    if (!snap) return;
    let target = snap.id ? document.getElementById(snap.id) : null;
    if (!target && snap.action) {
      let sel = '[data-action="' + snap.action + '"]';
      if (snap.target) sel += '[data-target="' + snap.target + '"]';
      if (snap.tab) sel += '[data-tab="' + snap.tab + '"]';
      target = document.querySelector(sel);
    }
    if (target && typeof target.focus === "function") {
      try { target.focus({ preventScroll: true }); } catch (_) { target.focus(); }
      if (snap.selStart !== null && typeof target.setSelectionRange === "function") {
        try { target.setSelectionRange(snap.selStart, snap.selEnd !== null ? snap.selEnd : snap.selStart); } catch (_) {}
      }
    }
    if (typeof window.scrollTo === "function") window.scrollTo(snap.scrollX, snap.scrollY);
  }

  function showToast(msg, isError) {
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
    state.toast = { msg: String(msg || ""), isError: Boolean(isError) };
    render();
    if (!isError) {
      toastTimer = setTimeout(() => {
        state.toast = null;
        toastTimer = null;
        const node = document.querySelector(".toast");
        if (node && node.parentNode) node.parentNode.removeChild(node);
      }, 3500);
    }
  }

  function applyHostContext(ctx) {
    if (!ctx || typeof ctx !== "object") return;
    state.hostCtx = Object.assign({}, state.hostCtx, ctx);
    if (ctx.theme === "light" || ctx.theme === "dark") {
      document.documentElement.dataset.theme = ctx.theme;
      document.documentElement.style.colorScheme = ctx.theme;
    }
    const vars = ctx.styles && ctx.styles.variables;
    if (vars && typeof vars === "object") {
      const st = document.documentElement.style;
      for (const [k, v] of Object.entries(vars)) {
        if (typeof k === "string" && k.startsWith("--") && typeof v === "string") st.setProperty(k, v);
      }
    }
    const fontsCss = ctx.styles && ctx.styles.css && ctx.styles.css.fonts;
    if (typeof fontsCss === "string" && fontsCss.trim()) {
      let styleEl = document.getElementById("g-host-fonts");
      if (!styleEl) {
        styleEl = el("style", null, null, { id: "g-host-fonts" });
        document.head.appendChild(styleEl);
      }
      styleEl.textContent = fontsCss;
    }
  }

  function extractStructured(res) {
    if (!res || typeof res !== "object") return null;
    if (res.structuredContent && typeof res.structuredContent === "object") return res.structuredContent;
    if (Array.isArray(res.content)) {
      for (const blk of res.content) {
        if (blk && blk.type === "text" && typeof blk.text === "string" && blk.text.trim().startsWith("{")) {
          try { return JSON.parse(blk.text); } catch (_) {}
        }
      }
    }
    return null;
  }

  function getActiveTabObj() {
    const tabs = (state.overview && state.overview.tabs) || [];
    return tabs.find((t) => t.id === state.activeTab) || tabs[0] || { id: "live", kind: "live", label: "En direct" };
  }

  function resolveInitialTab(view, moduleId) {
    const tabs = (state.overview && state.overview.tabs) || [];
    const v = String(view || "live").toLowerCase();
    if (v === "module" && moduleId) {
      const match = tabs.find((t) => t.module_id === moduleId || t.id === moduleId);
      if (match) return match.id;
    }
    if (v === "workflow" || v === "live") {
      const match = tabs.find((t) => t.id === "live" || t.kind === "live");
      return match ? match.id : "live";
    }
    if (v === "metrics" || v === "architect" || v === "overview") {
      const match = tabs.find((t) => t.id === v || t.kind === v);
      if (match) return match.id;
    }
    const def = tabs.find((t) => t.id === "live" || t.kind === "live");
    return def ? def.id : ((tabs[0] && tabs[0].id) || "live");
  }

  function applyInitialMetricsSub(rawSub) {
    const sub = String(rawSub || "").trim().toLowerCase();
    if (!sub) return;
    if (sub === "pending") { state.metricsSub = "sessions"; state.metricsFilter = "pending"; }
    else if (sub === "compare") { state.metricsSub = "sessions"; state.compareOpen = true; }
    else if (sub === "overview" || sub === "sessions" || sub === "audits") state.metricsSub = sub;
  }

  function hydrateInitialPayload(sc) {
    if (!sc || typeof sc !== "object") return;
    if (sc.overview && typeof sc.overview === "object") state.overview = sc.overview;
    else if (sc.doctor && sc.tabs) state.overview = sc;
    if (sc.live && typeof sc.live === "object") { state.live = sc.live; state.liveUi.lastUpdatedAt = new Date().toISOString(); }
    if (sc.workflow && typeof sc.workflow === "object") state.workflow = sc.workflow;
    if (sc.metrics && typeof sc.metrics === "object") state.metrics = sc.metrics;
    if (sc.architect && typeof sc.architect === "object") state.architect = sc.architect;
    if (typeof sc.initial_project === "string") state.metricsProject = sc.initial_project;
    if (typeof sc.initial_ws === "string") state.selectedWs = sc.initial_ws;
    if (typeof sc.initial_atelier === "string") state.selectedAtelier = sc.initial_atelier;
    applyInitialMetricsSub(sc.initial_metrics_sub);
    if (sc.module_info && sc.module_info.module_id) state.moduleCache[sc.module_info.module_id] = sc.module_info;
    state.activeTab = resolveInitialTab(sc.initial_view, sc.initial_module_id);
    if (typeof sc.initial_target === "string" && sc.initial_target) {
      if (state.activeTab === "live") state.liveUi.selectedSessionId = sc.initial_target;
      else if (state.activeTab === "metrics") { state.metricsSub = "sessions"; state.sessionTarget = sc.initial_target; }
    }
    state.loading = false;
    ensureActiveTabLoaded();
    render();
    if (state.activeTab === "metrics" && state.sessionTarget && !state.sessionDetail && state.hostCaps.serverTools) {
      openSessionDetail(state.sessionTarget);
    }
  }

  async function loadOverview(silent) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.overview ? (state.overview.signature || "") : "";
      const sc = extractStructured(await callServerTool("gravity_get_overview", { since_signature: sig }));
      if (sc && sc.changed !== false && !sc.unchanged) { state.overview = sc; render(); }
    } catch (err) {
      if (!silent) showToast("Erreur Système : " + err.message, true);
    } finally { state.pollInFlight = false; state.loading = false; }
  }

  async function loadLiveSession(silent) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.live ? (state.live.signature || "") : "";
      const sc = extractStructured(await callServerTool("gravity_get_live_session", {
        session_id: state.liveUi.selectedSessionId || "", ws: state.selectedWs || "", since_signature: sig, include_events: true
      }));
      if (sc && sc.changed !== false && !sc.unchanged) {
        state.live = sc;
        state.liveUi.lastUpdatedAt = new Date().toISOString();
        render();
      }
    } catch (err) {
      if (!silent) showToast("Erreur En direct : " + err.message, true);
    } finally { state.pollInFlight = false; }
  }

  async function loadMetricsState(silent, contentOnly) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.metrics ? (state.metrics.signature || "") : "";
      const sc = extractStructured(await callServerTool("gravity_get_metrics_state", {
        project: state.metricsProject || "", q: state.metricsQ || "", since_signature: sig
      }));
      if (sc && sc.changed !== false && !sc.unchanged) {
        state.metrics = sc;
        if (contentOnly && document.getElementById("g-metrics-content")) { renderMetricsBodyOrFull(); return; }
        render();
      }
    } catch (err) {
      if (!silent) showToast("Erreur Métriques : " + err.message, true);
    } finally { state.pollInFlight = false; }
  }

  async function loadArchitectState(silent) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.architect ? (state.architect.signature || "") : "";
      const sc = extractStructured(await callServerTool("gravity_get_architect_state", {
        atelier: state.selectedAtelier || "", ws: state.selectedWs || "", since_signature: sig
      }));
      if (sc && sc.changed !== false && !sc.unchanged) { state.architect = sc; render(); }
    } catch (err) {
      if (!silent) showToast("Erreur Atelier : " + err.message, true);
    } finally { state.pollInFlight = false; }
  }

  async function loadModuleInfo(moduleId, force) {
    if (!moduleId || !state.hostCaps.serverTools || (state.moduleCache[moduleId] && !force)) return;
    state.moduleLoading[moduleId] = true;
    render();
    try {
      const res = await callServerTool("gravity_get_module_info", { module_id: moduleId });
      const sc = extractStructured(res);
      if (sc) state.moduleCache[moduleId] = sc;
      else if (res && res.isError) state.moduleCache[moduleId] = { found: false, module_id: moduleId, error: (res.content && res.content[0] && res.content[0].text) || "Module introuvable" };
    } catch (err) {
      showToast("Erreur module : " + err.message, true);
    } finally { state.moduleLoading[moduleId] = false; render(); }
  }

  async function openSessionDetail(target) {
    if (!target) return;
    state.sessionTarget = target;
    state.sessionEditOpen = false;
    state.sessionDeleteConfirm = false;
    state.pendingDeleteTarget = "";
    if (!state.hostCaps.serverTools) { state.sessionDetail = null; showToast("serverTools indisponible.", true); return; }
    state.sessionDetailLoading = true;
    renderMetricsBodyOrFull();
    try {
      const res = await callServerTool("gravity_get_session_detail", { target });
      const sc = extractStructured(res);
      if (res && res.isError && (!sc || !sc.found)) showToast((res.content && res.content[0] && res.content[0].text) || "Session introuvable", true);
      else if (sc) state.sessionDetail = sc;
    } catch (err) {
      showToast("Détail session : " + err.message, true);
    } finally { state.sessionDetailLoading = false; renderMetricsBodyOrFull(); }
  }

  async function dispatchMetricsCliAction(params) {
    if (!state.hostCaps.serverTools) { showToast("serverTools indisponible.", true); return; }
    state.metricsActionInFlight = true;
    state.liveUi.actionInFlight = true;
    render();
    try {
      const res = await callServerTool("gravity_metrics_action", params);
      const sc = extractStructured(res);
      if ((res && res.isError) || (sc && sc.ok === false)) {
        showToast((sc && sc.message) || (res && res.content && res.content[0] && res.content[0].text) || "Action échouée", true);
      } else {
        const act = String(params.action || "");
        if (act === "remove" || act === "ignore") {
          state.sessionTarget = ""; state.sessionDetail = null; state.sessionDeleteConfirm = false; state.pendingDeleteTarget = "";
        } else if (act === "update-meta") state.sessionEditOpen = false;
        showToast((sc && sc.message) || "Action exécutée.", false);
        state.metrics = null;
        await loadMetricsState(false, false);
        if (state.activeTab === "live") await loadLiveSession(false);
        else if (state.sessionTarget && (act === "update" || act === "update-meta")) await openSessionDetail(state.sessionTarget);
      }
    } catch (err) {
      showToast("Action Métriques : " + err.message, true);
    } finally { state.metricsActionInFlight = false; state.liveUi.actionInFlight = false; render(); }
  }

  async function openAuditReader(auditId) {
    if (!auditId) return;
    state.auditTarget = auditId;
    if (!state.hostCaps.serverTools) { showToast("serverTools indisponible.", true); return; }
    state.auditLoading = true;
    renderMetricsBodyOrFull();
    try {
      const res = await callServerTool("gravity_read_audit", { path: auditId });
      const sc = extractStructured(res);
      if (res && res.isError && (!sc || !sc.found)) showToast((sc && sc.error) || (res.content && res.content[0] && res.content[0].text) || "Audit introuvable", true);
      else if (sc) state.auditData = sc;
    } catch (err) {
      showToast("Lecture audit : " + err.message, true);
    } finally { state.auditLoading = false; renderMetricsBodyOrFull(); }
  }

  async function openMarkdownFile(uri) {
    if (!uri) { showToast("Fichier Markdown introuvable.", true); return; }
    try {
      const res = await sendRequest("com.google.antigravity/toggle-aux-pane", { tabType: "fileView", uri: uri });
      if (res && res.isError) showToast("Ouverture fichier refusée par l'hôte.", false);
    } catch (_) { showToast("Ouverture .md indisponible sur cette surface.", false); }
  }

  function renderMetricsBodyOrFull() {
    const box = document.getElementById("g-metrics-content");
    if (box) {
      const snap = captureFocusAndScroll();
      clearNode(box);
      renderMetricsContent(box);
      restoreFocusAndScroll(snap);
    } else render();
  }

  function ensureActiveTabLoaded() {
    const tab = getActiveTabObj();
    if (tab.kind === "live" && !state.live && state.hostCaps.serverTools) loadLiveSession(false);
    else if (tab.kind === "metrics" && !state.metrics && state.hostCaps.serverTools) loadMetricsState(false, false);
    else if (tab.kind === "architect" && !state.architect && state.hostCaps.serverTools) loadArchitectState(false);
    else if (tab.kind === "generic" && tab.module_id && !state.moduleCache[tab.module_id]) loadModuleInfo(tab.module_id, false);
  }

  function refreshCurrentTab() {
    const tab = getActiveTabObj();
    if (tab.kind === "live") loadLiveSession(false);
    else if (tab.kind === "metrics") loadMetricsState(false, false);
    else if (tab.kind === "architect") loadArchitectState(false);
    else if (tab.kind === "generic" && tab.module_id) loadModuleInfo(tab.module_id, true);
    else loadOverview(false);
  }

  function render() {
    const root = document.getElementById("root");
    if (!root) return;
    const snap = captureFocusAndScroll();
    clearNode(root);

    const ov = state.overview;
    const doctor = (ov && ov.doctor) || {};
    const tabs = (ov && ov.tabs) || [{ id: "live", kind: "live", label: "En direct" }];

    const header = el("header", "shell-head");
    const topbar = el("div", "topbar");
    const brand = el("div", "brand");
    brand.appendChild(el("span", "brand-dot " + String(doctor.status || "ok")));
    brand.appendChild(el("span", "brand-title", "Gravity"));
    brand.appendChild(el("span", "brand-sub mono", ov ? ((ov.gravity_home || "~/.gemini/gravity") + " · " + (doctor.module_count || 0) + " module(s)") : "Initialisation..."));
    topbar.appendChild(brand);

    const actions = el("div", "actions-row");
    actions.appendChild(el("button", "btn btn-sm", "Rafraîchir", { type: "button", "data-action": "refresh" }));
    topbar.appendChild(actions);
    header.appendChild(topbar);

    const tabNav = el("nav", "tabs", null, { role: "tablist" });
    tabs.forEach((t) => {
      const isAct = t.id === state.activeTab;
      tabNav.appendChild(el("button", "tab-btn" + (isAct ? " active" : ""), t.label || t.id, {
        type: "button", role: "tab", "aria-selected": isAct ? "true" : "false", "data-action": "select-tab", "data-tab": t.id
      }));
    });
    header.appendChild(tabNav);
    root.appendChild(header);

    if (state.toast) {
      const toastEl = el("div", "toast" + (state.toast.isError ? " error" : ""));
      toastEl.appendChild(el("span", null, state.toast.msg));
      toastEl.appendChild(el("button", "btn btn-sm", "OK", { type: "button", "data-action": "close-toast" }));
      root.appendChild(toastEl);
    }

    const main = el("main");
    main.style.display = "flex";
    main.style.flexDirection = "column";
    main.style.gap = "10px";

    if (state.loading && !ov) {
      main.appendChild(el("div", "empty", "Connexion au serveur MCP Gravity..."));
    } else {
      const activeTab = getActiveTabObj();
      if (activeTab.kind === "live" || activeTab.kind === "workflow") {
        renderLiveView(main, state.live, state.liveUi, {
          onSelectSession: (cid) => { state.liveUi.selectedSessionId = cid; loadLiveSession(false); },
          onTogglePause: () => { state.liveUi.paused = !state.liveUi.paused; render(); },
          onRefresh: () => loadLiveSession(false),
          onCaptureAction: (actName, cid) => dispatchMetricsCliAction({ action: actName, conversation_id: cid })
        });
      } else if (activeTab.kind === "metrics") renderMetricsView(main);
      else if (activeTab.kind === "architect") renderArchitectView(main);
      else if (activeTab.kind === "generic") renderModuleView(main, activeTab);
      else renderOverviewView(main);
    }
    root.appendChild(main);
    restoreFocusAndScroll(snap);
  }

  document.addEventListener("toggle", (ev) => {
    if (ev.target && ev.target.id === "g-live-activity") state.liveUi.eventsOpen = Boolean(ev.target.open);
  }, true);

  document.addEventListener("submit", (ev) => {
    const form = ev.target;
    if (!form || form.id !== "g-session-edit-form") return;
    ev.preventDefault();
    const g = (id) => { const n = document.getElementById(id); return n ? n.value : ""; };
    dispatchMetricsCliAction({
      action: "update-meta", target: form.getAttribute("data-target") || state.sessionTarget,
      label: g("g-edit-label"), project: g("g-edit-project"), note: g("g-edit-note")
    });
  });

  const CLICK_HANDLERS = {
    "select-tab": (t) => { state.activeTab = t.getAttribute("data-tab") || "live"; ensureActiveTabLoaded(); render(); },
    "refresh": () => refreshCurrentTab(),
    "close-toast": () => { state.toast = null; render(); },
    "metrics-sub": (t) => { state.metricsSub = t.getAttribute("data-sub") || "overview"; renderMetricsBodyOrFull(); },
    "metrics-filter": (t) => { state.metricsFilter = t.getAttribute("data-filter") || "recorded"; renderMetricsBodyOrFull(); },
    "toggle-compare": () => { state.compareOpen = !state.compareOpen; renderMetricsBodyOrFull(); },
    "pin-compare": (t) => {
      const slot = t.getAttribute("data-slot");
      const tgt = t.getAttribute("data-target") || "";
      if (slot === "A") state.compareA = tgt; else if (slot === "B") state.compareB = tgt;
      state.compareOpen = true; renderMetricsBodyOrFull();
    },
    "open-session-detail": (t) => { const tgt = t.getAttribute("data-target") || ""; if (tgt) openSessionDetail(tgt); },
    "close-session-detail": () => { state.sessionTarget = ""; state.sessionDetail = null; state.sessionEditOpen = false; state.sessionDeleteConfirm = false; renderMetricsBodyOrFull(); },
    "session-detail-sub": (t) => { state.sessionDetailSub = t.getAttribute("data-sub") || "summary"; renderMetricsBodyOrFull(); },
    "toggle-session-edit": () => { state.sessionEditOpen = !state.sessionEditOpen; renderMetricsBodyOrFull(); },
    "ask-remove-session": (t) => { state.sessionDeleteConfirm = true; state.pendingDeleteTarget = t.getAttribute("data-target") || state.sessionTarget; renderMetricsBodyOrFull(); },
    "cancel-remove-session": () => { state.sessionDeleteConfirm = false; state.pendingDeleteTarget = ""; renderMetricsBodyOrFull(); },
    "metrics-cli-action": (t) => {
      const cliAct = t.getAttribute("data-cli-action") || "";
      const params = { action: cliAct, conversation_id: t.getAttribute("data-cid") || "", target: t.getAttribute("data-target") || "" };
      const ws = t.getAttribute("data-workspace") || "";
      if (ws) params.workspace = ws;
      if (cliAct === "remove") params.purge_reports = true;
      dispatchMetricsCliAction(params);
    },
    "read-audit": (t) => openAuditReader(t.getAttribute("data-audit-id") || ""),
    "close-audit-reader": () => { state.auditTarget = ""; state.auditData = null; renderMetricsBodyOrFull(); },
    "open-file": (t) => openMarkdownFile(t.getAttribute("data-uri") || ""),
    "architect-sub": (t) => { state.architectSub = t.getAttribute("data-sub") || "projects"; render(); }
  };

  document.addEventListener("click", (ev) => {
    const target = ev.target && ev.target.closest ? ev.target.closest("[data-action]") : null;
    if (!target) return;
    const fn = CLICK_HANDLERS[target.getAttribute("data-action")];
    if (fn) fn(target);
  });

  document.addEventListener("change", (ev) => {
    const node = ev.target;
    if (!node || !node.id) return;
    if (node.id === "g-metrics-project") { state.metricsProject = node.value || ""; state.sessionTarget = ""; state.sessionDetail = null; loadMetricsState(false, true); }
    else if (node.id === "g-metrics-sort") { state.metricsSort = node.value || "date"; renderMetricsBodyOrFull(); }
    else if (node.id === "g-cmp-a") { state.compareA = node.value || ""; renderMetricsBodyOrFull(); }
    else if (node.id === "g-cmp-b") { state.compareB = node.value || ""; renderMetricsBodyOrFull(); }
    else if (node.id === "g-arch-ws") { state.selectedAtelier = node.value || ""; loadArchitectState(false); }
  });

  document.addEventListener("input", (ev) => {
    const node = ev.target;
    if (!node || node.id !== "g-metrics-q") return;
    state.metricsQ = node.value || "";
    if (metricsSearchTimer) clearTimeout(metricsSearchTimer);
    metricsSearchTimer = setTimeout(() => { metricsSearchTimer = null; loadMetricsState(false, true); }, 220);
  });

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || typeof msg !== "object") return;
    if (msg.id !== undefined && msg.id !== null && pendingRpc.has(msg.id) && !msg.method) {
      const entry = pendingRpc.get(msg.id);
      pendingRpc.delete(msg.id);
      if (msg.error) entry.reject(new Error(msg.error.message || JSON.stringify(msg.error)));
      else entry.resolve(msg.result);
      return;
    }
    if (msg.id !== undefined && msg.id !== null && msg.method) {
      postToHost(msg.method === "ping" || msg.method === "ui/resource-teardown"
        ? { jsonrpc: "2.0", id: msg.id, result: {} }
        : { jsonrpc: "2.0", id: msg.id, error: { code: -32601, message: "Method not found" } });
      return;
    }
    if (msg.method === "ui/notifications/host-context-changed") { applyHostContext(msg.params || {}); render(); }
    else if (msg.method === "ui/notifications/tool-input") {
      const args = (msg.params && msg.params.arguments) || {};
      if (typeof args.project === "string") state.metricsProject = args.project.trim();
      if (typeof args.ws === "string") state.selectedWs = args.ws.trim();
      if (typeof args.atelier === "string") state.selectedAtelier = args.atelier.trim();
      applyInitialMetricsSub(args.metrics_sub);
      if (typeof args.view === "string" && state.overview) { state.activeTab = resolveInitialTab(args.view, args.module_id); render(); }
    } else if (msg.method === "ui/notifications/tool-result") {
      state.hasToolResult = true;
      if (fallbackTimer) { clearTimeout(fallbackTimer); fallbackTimer = null; }
      const sc = extractStructured(msg.params);
      if (sc) hydrateInitialPayload(sc); else loadOverview(false);
    } else if (msg.method === "ui/notifications/tool-cancelled") { state.loading = false; render(); }
  });

  async function initBridge() {
    try {
      const initRes = await sendRequest("ui/initialize", {
        appInfo: { name: "gravity", version: "0.3.0" }, appCapabilities: {}, protocolVersion: PROTOCOL_VERSION
      });
      state.hostCaps = (initRes && initRes.hostCapabilities) || {};
      applyHostContext((initRes && initRes.hostContext) || {});
      sendNotification("ui/notifications/initialized", {});
      if (!state.hasToolResult) {
        fallbackTimer = setTimeout(() => {
          if (!state.hasToolResult && state.hostCaps.serverTools) loadOverview(false);
          else if (!state.hasToolResult) { state.loading = false; render(); }
        }, 450);
      }
      livePollTimer = setInterval(() => {
        if (document.visibilityState === "visible" && state.hostCaps.serverTools && !state.pollInFlight && !state.liveUi.paused && getActiveTabObj().kind === "live") {
          loadLiveSession(true);
        }
      }, LIVE_POLL_MS);
    } catch (err) {
      state.loading = false;
      showToast("Initialisation pont MCP App échouée : " + err.message, true);
    }
  }

  initBridge();
"""

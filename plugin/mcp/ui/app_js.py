"""SEP-1865 bridge and state controller for the Gravity MCP App (100% stdlib, zero innerHTML)."""

from __future__ import annotations

APP_JS = r"""
  const PROTOCOL_VERSION = "2026-01-26";
  const WORKFLOW_POLL_MS = 1500;

  const state = {
    hostCaps: {},
    hostCtx: {},
    overview: null,
    workflow: null,
    metrics: null,
    bridge: null,
    architect: null,
    moduleCache: {},
    moduleLoading: {},
    activeTab: "overview",
    selectedWs: "",
    selectedAtelier: "",
    metricsProject: "",
    metricsQ: "",
    metricsTariff: "2026",
    metricsSub: "sessions",
    bridgeStatus: "",
    bridgeSub: "threads",
    architectSub: "projects",
    sessionTarget: "",
    sessionDetail: null,
    sessionDetailLoading: false,
    toast: null,
    loading: true,
    hasToolResult: false,
    pollInFlight: false
  };

  let rpcId = 1;
  const pendingRpc = new Map();
  let fallbackTimer = null;
  let wfPollTimer = null;
  let metricsSearchTimer = null;
  let toastTimer = null;

  function postToHost(payload) {
    window.parent.postMessage(payload, "*");
  }

  function sendRequest(method, params) {
    const id = rpcId++;
    return new Promise((resolve, reject) => {
      pendingRpc.set(id, { resolve, reject });
      postToHost({ jsonrpc: "2.0", id, method, params: params || {} });
    });
  }

  function sendNotification(method, params) {
    postToHost({ jsonrpc: "2.0", method, params: params || {} });
  }

  function callServerTool(name, args) {
    return sendRequest("tools/call", { name, arguments: args || {} });
  }

  function showToast(msg, isError) {
    if (toastTimer) {
      clearTimeout(toastTimer);
      toastTimer = null;
    }
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
        if (typeof k === "string" && k.startsWith("--") && typeof v === "string") {
          st.setProperty(k, v);
        }
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
    if (res.structuredContent && typeof res.structuredContent === "object") {
      return res.structuredContent;
    }
    if (Array.isArray(res.content)) {
      for (const blk of res.content) {
        if (blk && blk.type === "text" && typeof blk.text === "string" && blk.text.trim().startsWith("{")) {
          try {
            return JSON.parse(blk.text);
          } catch (_) {}
        }
      }
    }
    return null;
  }

  function getActiveTabObj() {
    const tabs = (state.overview && state.overview.tabs) || [];
    return tabs.find((t) => t.id === state.activeTab) || tabs[0] || { id: "overview", kind: "core", label: "Overview" };
  }

  function resolveInitialTab(view, moduleId) {
    const tabs = (state.overview && state.overview.tabs) || [];
    const v = String(view || "overview").toLowerCase();
    if (v === "module" && moduleId) {
      const match = tabs.find((t) => t.module_id === moduleId || t.id === moduleId);
      if (match) return match.id;
    }
    if (v === "workflow" || v === "metrics" || v === "bridge" || v === "architect") {
      const match = tabs.find((t) => t.id === v || t.kind === v);
      if (match) return match.id;
    }
    return "overview";
  }

  function hydrateInitialPayload(sc) {
    if (!sc || typeof sc !== "object") return;
    if (sc.overview && typeof sc.overview === "object") {
      state.overview = sc.overview;
    } else if (sc.doctor && sc.tabs) {
      state.overview = sc;
    }
    if (sc.workflow && typeof sc.workflow === "object") {
      state.workflow = sc.workflow;
    }
    if (sc.metrics && typeof sc.metrics === "object") {
      state.metrics = sc.metrics;
    }
    if (sc.bridge && typeof sc.bridge === "object") {
      state.bridge = sc.bridge;
    }
    if (sc.architect && typeof sc.architect === "object") {
      state.architect = sc.architect;
    }
    if (typeof sc.initial_project === "string") {
      state.metricsProject = sc.initial_project;
    }
    if (typeof sc.initial_ws === "string") {
      state.selectedWs = sc.initial_ws;
    }
    if (typeof sc.initial_atelier === "string") {
      state.selectedAtelier = sc.initial_atelier;
    }
    if (sc.module_info && sc.module_info.module_id) {
      state.moduleCache[sc.module_info.module_id] = sc.module_info;
    }
    state.activeTab = resolveInitialTab(sc.initial_view, sc.initial_module_id);
    state.loading = false;
    ensureActiveTabLoaded();
    render();
  }

  async function loadOverview(silent) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.overview ? (state.overview.signature || "") : "";
      const res = await callServerTool("gravity_get_overview", { since_signature: sig });
      const sc = extractStructured(res);
      if (sc && sc.changed !== false && !sc.unchanged) {
        state.overview = sc;
        render();
      }
    } catch (err) {
      if (!silent) showToast("Erreur Overview : " + err.message, true);
    } finally {
      state.pollInFlight = false;
      state.loading = false;
    }
  }

  async function loadWorkflowState(silent) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.workflow ? (state.workflow.signature || "") : "";
      const res = await callServerTool("gravity_get_workflow_state", {
        ws: state.selectedWs || "",
        since_signature: sig
      });
      const sc = extractStructured(res);
      if (sc && sc.changed !== false && !sc.unchanged) {
        state.workflow = sc;
        render();
      }
    } catch (err) {
      if (!silent) showToast("Erreur Workflow : " + err.message, true);
    } finally {
      state.pollInFlight = false;
    }
  }

  async function loadMetricsState(silent, contentOnly) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.metrics ? (state.metrics.signature || "") : "";
      const res = await callServerTool("gravity_get_metrics_state", {
        project: state.metricsProject || "",
        q: state.metricsQ || "",
        since_signature: sig
      });
      const sc = extractStructured(res);
      if (sc && sc.changed !== false && !sc.unchanged) {
        state.metrics = sc;
        if (contentOnly) {
          const box = document.getElementById("g-metrics-content");
          if (box) {
            clearNode(box);
            renderMetricsContent(box);
            return;
          }
        }
        render();
      }
    } catch (err) {
      if (!silent) showToast("Erreur Metrics : " + err.message, true);
    } finally {
      state.pollInFlight = false;
    }
  }

  async function loadBridgeState(silent) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.bridge ? (state.bridge.signature || "") : "";
      const res = await callServerTool("gravity_get_bridge_state", {
        status: state.bridgeStatus || "",
        since_signature: sig
      });
      const sc = extractStructured(res);
      if (sc && sc.changed !== false && !sc.unchanged) {
        state.bridge = sc;
        render();
      }
    } catch (err) {
      if (!silent) showToast("Erreur Bridge : " + err.message, true);
    } finally {
      state.pollInFlight = false;
    }
  }

  async function loadArchitectState(silent) {
    if (!state.hostCaps.serverTools || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const sig = silent && state.architect ? (state.architect.signature || "") : "";
      const res = await callServerTool("gravity_get_architect_state", {
        atelier: state.selectedAtelier || "",
        ws: state.selectedWs || "",
        since_signature: sig
      });
      const sc = extractStructured(res);
      if (sc && sc.changed !== false && !sc.unchanged) {
        state.architect = sc;
        render();
      }
    } catch (err) {
      if (!silent) showToast("Erreur Architect : " + err.message, true);
    } finally {
      state.pollInFlight = false;
    }
  }

  async function loadModuleInfo(moduleId, force) {
    if (!moduleId || !state.hostCaps.serverTools) return;
    if (state.moduleCache[moduleId] && !force) return;
    state.moduleLoading[moduleId] = true;
    render();
    try {
      const res = await callServerTool("gravity_get_module_info", { module_id: moduleId });
      const sc = extractStructured(res);
      if (sc) {
        state.moduleCache[moduleId] = sc;
      } else if (res && res.isError) {
        const msg = (res.content && res.content[0] && res.content[0].text) || "Module introuvable";
        state.moduleCache[moduleId] = { found: false, module_id: moduleId, error: msg };
      }
    } catch (err) {
      showToast("Erreur module : " + err.message, true);
    } finally {
      state.moduleLoading[moduleId] = false;
      render();
    }
  }

  async function openSessionDetail(target) {
    if (!target) return;
    state.sessionTarget = target;
    if (!state.hostCaps.serverTools) {
      state.sessionDetail = null;
      showToast("serverTools indisponible pour charger le détail.", true);
      return;
    }
    state.sessionDetailLoading = true;
    render();
    try {
      const res = await callServerTool("gravity_get_session_detail", { target });
      const sc = extractStructured(res);
      if (res && res.isError && (!sc || !sc.found)) {
        const msg = (res.content && res.content[0] && res.content[0].text) || "Session introuvable";
        showToast(msg, true);
      } else if (sc) {
        state.sessionDetail = sc;
      }
    } catch (err) {
      showToast("Détail session : " + err.message, true);
    } finally {
      state.sessionDetailLoading = false;
      render();
    }
  }

  async function openMarkdownFile(uri) {
    if (!uri) {
      showToast("Fichier Markdown introuvable.", true);
      return;
    }
    try {
      const res = await sendRequest("com.google.antigravity/toggle-aux-pane", {
        tabType: "fileView",
        uri: uri
      });
      if (res && res.isError) {
        showToast("Ouverture fichier refusée par l'hôte.", false);
      }
    } catch (err) {
      showToast("Ouverture .md indisponible sur cette surface.", false);
    }
  }

  function ensureActiveTabLoaded() {
    const tab = getActiveTabObj();
    if (tab.kind === "workflow" && !state.workflow && state.hostCaps.serverTools) {
      loadWorkflowState(false);
    } else if (tab.kind === "metrics" && !state.metrics && state.hostCaps.serverTools) {
      loadMetricsState(false, false);
    } else if (tab.kind === "bridge" && !state.bridge && state.hostCaps.serverTools) {
      loadBridgeState(false);
    } else if (tab.kind === "architect" && !state.architect && state.hostCaps.serverTools) {
      loadArchitectState(false);
    } else if (tab.kind === "generic" && tab.module_id && !state.moduleCache[tab.module_id]) {
      loadModuleInfo(tab.module_id, false);
    }
  }

  function refreshCurrentTab() {
    const tab = getActiveTabObj();
    if (tab.kind === "workflow") {
      loadWorkflowState(false);
    } else if (tab.kind === "metrics") {
      loadMetricsState(false, false);
    } else if (tab.kind === "bridge") {
      loadBridgeState(false);
    } else if (tab.kind === "architect") {
      loadArchitectState(false);
    } else if (tab.kind === "generic" && tab.module_id) {
      loadModuleInfo(tab.module_id, true);
    } else {
      loadOverview(false);
    }
  }

  function render() {
    const root = document.getElementById("root");
    if (!root) return;
    clearNode(root);

    const ov = state.overview;
    const doctor = (ov && ov.doctor) || {};
    const docStatus = String(doctor.status || "ok");
    const tabs = (ov && ov.tabs) || [{ id: "overview", kind: "core", label: "Overview" }];

    const header = el("header", "shell-head");
    const topbar = el("div", "topbar");
    const brand = el("div", "brand");
    brand.appendChild(el("span", "brand-dot " + docStatus));
    brand.appendChild(el("span", "brand-title", "Gravity"));
    const subTxt = ov
      ? ((ov.gravity_home || "~/.gemini/gravity") + " · " + (doctor.module_count || 0) + " module(s)")
      : "Initialisation...";
    brand.appendChild(el("span", "brand-sub mono", subTxt));
    topbar.appendChild(brand);

    const actions = el("div", "actions-row");
    actions.appendChild(el("button", "btn", "Rafraîchir", { type: "button", "data-action": "refresh" }));
    topbar.appendChild(actions);
    header.appendChild(topbar);

    const tabNav = el("nav", "tabs", null, { role: "tablist" });
    tabs.forEach((t) => {
      const isAct = t.id === state.activeTab;
      const btn = el("button", "tab-btn" + (isAct ? " active" : ""), t.label || t.id, {
        type: "button",
        role: "tab",
        "aria-selected": isAct ? "true" : "false",
        "data-action": "select-tab",
        "data-tab": t.id
      });
      tabNav.appendChild(btn);
    });
    header.appendChild(tabNav);
    root.appendChild(header);

    if (state.toast) {
      const toastEl = el("div", "toast" + (state.toast.isError ? " error" : ""));
      toastEl.appendChild(el("span", null, state.toast.msg));
      toastEl.appendChild(el("button", "btn", "OK", { type: "button", "data-action": "close-toast" }));
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
      if (activeTab.kind === "workflow") {
        renderWorkflowView(main);
      } else if (activeTab.kind === "metrics") {
        renderMetricsView(main);
      } else if (activeTab.kind === "bridge") {
        renderBridgeView(main);
      } else if (activeTab.kind === "architect") {
        renderArchitectView(main);
      } else if (activeTab.kind === "generic") {
        renderModuleView(main, activeTab);
      } else {
        renderOverviewView(main);
      }
    }
    root.appendChild(main);
  }

  document.addEventListener("click", (ev) => {
    const target = ev.target && ev.target.closest ? ev.target.closest("[data-action]") : null;
    if (!target) return;
    const action = target.getAttribute("data-action");
    if (action === "select-tab") {
      const tabId = target.getAttribute("data-tab") || "overview";
      state.activeTab = tabId;
      ensureActiveTabLoaded();
      render();
      return;
    }
    if (action === "refresh") {
      refreshCurrentTab();
      return;
    }
    if (action === "close-toast") {
      state.toast = null;
      render();
      return;
    }
    if (action === "set-tariff") {
      state.metricsTariff = target.getAttribute("data-tariff") || "2026";
      const box = document.getElementById("g-metrics-content");
      if (box) {
        document.querySelectorAll('[data-action="set-tariff"]').forEach((b) => {
          b.className = "btn" + (b.getAttribute("data-tariff") === state.metricsTariff ? " active" : "");
        });
        clearNode(box);
        renderMetricsContent(box);
      } else {
        render();
      }
      return;
    }
    if (action === "metrics-sub") {
      state.metricsSub = target.getAttribute("data-sub") || "sessions";
      const box = document.getElementById("g-metrics-content");
      if (box) {
        clearNode(box);
        renderMetricsContent(box);
      } else {
        render();
      }
      return;
    }
    if (action === "open-session-detail") {
      const tgt = target.getAttribute("data-target") || "";
      if (tgt) openSessionDetail(tgt);
      return;
    }
    if (action === "close-session-detail") {
      state.sessionTarget = "";
      state.sessionDetail = null;
      const box = document.getElementById("g-metrics-content");
      if (box) {
        clearNode(box);
        renderMetricsContent(box);
      } else {
        render();
      }
      return;
    }
    if (action === "open-file") {
      openMarkdownFile(target.getAttribute("data-uri") || "");
      return;
    }
    if (action === "bridge-status") {
      state.bridgeStatus = target.getAttribute("data-status") || "";
      loadBridgeState(false);
      return;
    }
    if (action === "bridge-sub") {
      state.bridgeSub = target.getAttribute("data-sub") || "threads";
      render();
      return;
    }
    if (action === "architect-sub") {
      state.architectSub = target.getAttribute("data-sub") || "projects";
      render();
    }
  });

  document.addEventListener("change", (ev) => {
    const node = ev.target;
    if (!node || !node.id) return;
    if (node.id === "g-wf-ws") {
      state.selectedWs = node.value || "";
      loadWorkflowState(false);
    } else if (node.id === "g-metrics-project") {
      state.metricsProject = node.value || "";
      state.sessionTarget = "";
      state.sessionDetail = null;
      loadMetricsState(false, true);
    } else if (node.id === "g-arch-ws") {
      state.selectedAtelier = node.value || "";
      loadArchitectState(false);
    }
  });

  document.addEventListener("input", (ev) => {
    const node = ev.target;
    if (!node || node.id !== "g-metrics-q") return;
    state.metricsQ = node.value || "";
    if (metricsSearchTimer) clearTimeout(metricsSearchTimer);
    metricsSearchTimer = setTimeout(() => {
      metricsSearchTimer = null;
      loadMetricsState(false, true);
    }, 220);
  });

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || typeof msg !== "object") return;

    if (msg.id !== undefined && msg.id !== null && pendingRpc.has(msg.id) && !msg.method) {
      const entry = pendingRpc.get(msg.id);
      pendingRpc.delete(msg.id);
      if (msg.error) {
        entry.reject(new Error(msg.error.message || JSON.stringify(msg.error)));
      } else {
        entry.resolve(msg.result);
      }
      return;
    }

    if (msg.id !== undefined && msg.id !== null && msg.method) {
      if (msg.method === "ping" || msg.method === "ui/resource-teardown") {
        postToHost({ jsonrpc: "2.0", id: msg.id, result: {} });
      } else {
        postToHost({ jsonrpc: "2.0", id: msg.id, error: { code: -32601, message: "Method not found" } });
      }
      return;
    }

    if (msg.method === "ui/notifications/host-context-changed") {
      applyHostContext(msg.params || {});
      render();
      return;
    }

    if (msg.method === "ui/notifications/tool-input") {
      const args = (msg.params && msg.params.arguments) || {};
      if (typeof args.project === "string") state.metricsProject = args.project.trim();
      if (typeof args.ws === "string") state.selectedWs = args.ws.trim();
      if (typeof args.atelier === "string") state.selectedAtelier = args.atelier.trim();
      if (typeof args.view === "string" && state.overview) {
        state.activeTab = resolveInitialTab(args.view, args.module_id);
        render();
      }
      return;
    }

    if (msg.method === "ui/notifications/tool-result") {
      state.hasToolResult = true;
      if (fallbackTimer) {
        clearTimeout(fallbackTimer);
        fallbackTimer = null;
      }
      const sc = extractStructured(msg.params);
      if (sc) {
        hydrateInitialPayload(sc);
      } else {
        loadOverview(false);
      }
      return;
    }

    if (msg.method === "ui/notifications/tool-cancelled") {
      state.loading = false;
      render();
    }
  });

  async function initBridge() {
    try {
      const initRes = await sendRequest("ui/initialize", {
        appInfo: { name: "gravity", version: "0.3.0" },
        appCapabilities: {},
        protocolVersion: PROTOCOL_VERSION
      });
      state.hostCaps = (initRes && initRes.hostCapabilities) || {};
      applyHostContext((initRes && initRes.hostContext) || {});
      sendNotification("ui/notifications/initialized", {});

      if (!state.hasToolResult) {
        fallbackTimer = setTimeout(() => {
          if (!state.hasToolResult && state.hostCaps.serverTools) {
            loadOverview(false);
          } else if (!state.hasToolResult) {
            state.loading = false;
            render();
          }
        }, 450);
      }

      wfPollTimer = setInterval(() => {
        if (
          document.visibilityState === "visible" &&
          state.hostCaps.serverTools &&
          !state.pollInFlight &&
          getActiveTabObj().kind === "workflow"
        ) {
          loadWorkflowState(true);
        }
      }, WORKFLOW_POLL_MS);
    } catch (err) {
      state.loading = false;
      showToast("Initialisation pont MCP App échouée : " + err.message, true);
    }
  }

  initBridge();
"""

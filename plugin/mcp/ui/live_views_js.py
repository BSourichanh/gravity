"""Pure DOM renderer for the Gravity 'En direct' Live Cockpit (100% stdlib, zero innerHTML)."""

from __future__ import annotations

LIVE_VIEWS_JS = r"""
  function _parseWorkflowProgress(rawProgress) {
    const m = String(rawProgress || "").match(/(\d+)\s*\/\s*(\d+)/);
    if (!m) return { done: 0, total: 0, pct: 0 };
    const done = Math.max(0, Number(m[1]) || 0);
    const total = Math.max(1, Number(m[2]) || 1);
    return { done, total, pct: Math.min(100, Math.round((done / total) * 100)) };
  }

  function _aggregateLiveWorkspaces(agents) {
    const map = new Map();
    (Array.isArray(agents) ? agents : []).forEach((ag) => {
      if (!ag) return;
      const ws = String(ag.workspace || "workspace");
      const kind = String(ag.workspace_kind || "code").toLowerCase();
      const key = ws + "::" + kind;
      const cur = map.get(key) || { workspace: ws, kind, useful_tokens: 0, cache_read_tokens: 0, agents_count: 0 };
      cur.useful_tokens += Number(ag.useful_tokens) || 0;
      cur.cache_read_tokens += Number(ag.cache_read_tokens) || 0;
      cur.agents_count += 1;
      map.set(key, cur);
    });
    return Array.from(map.values()).sort((a, b) => (b.useful_tokens - a.useful_tokens) || a.workspace.localeCompare(b.workspace));
  }

  function _renderLiveToolbar(live, ui, handlers) {
    const panel = el("section", "panel");
    const row = el("div", "panel-head");

    const left = el("div", "actions-row");
    const dotCls = !live || !live.available ? "live-dot idle" : (ui.paused ? "live-dot paused" : "live-dot");
    left.appendChild(el("span", dotCls));
    left.appendChild(el("span", "panel-title", "Cockpit en direct"));

    const sessions = (live && Array.isArray(live.sessions)) ? live.sessions : [];
    const selCid = (live && live.selected_session && live.selected_session.conversation_id) || "";
    const sel = el("select", "select", null, { id: "g-live-session", "aria-label": "Session active" });
    if (!sessions.length) {
      sel.appendChild(el("option", null, "Aucune session active", { value: "" }));
    } else {
      sessions.forEach((s) => {
        const cid = String(s.conversation_id || "");
        const lbl = String(s.label || ("session-" + cid.slice(0, 8))) +
          (s.project ? " · " + s.project : "") +
          (s.captured ? " [suivie]" : "");
        const opt = el("option", null, lbl, { value: cid });
        if (cid === selCid || cid === ui.selectedSessionId) opt.selected = true;
        sel.appendChild(opt);
      });
    }
    if (typeof handlers.onSelectSession === "function") {
      sel.addEventListener("change", () => handlers.onSelectSession(sel.value || ""));
    }
    left.appendChild(sel);
    row.appendChild(left);

    const right = el("div", "live-controls");
    const refTs = (live && live.selected_session && live.selected_session.last_ts) || ui.lastUpdatedAt || "";
    const freshTxt = ui.paused ? "En pause" : ("Fraîcheur : " + fmtRelativeTime(refTs));
    right.appendChild(makeBadge(freshTxt, ui.paused ? "warn" : "ok"));

    const pauseBtn = el("button", "btn btn-sm" + (ui.paused ? " active" : ""), ui.paused ? "Reprendre" : "Pause", {
      type: "button",
      "data-action": "toggle-live-pause",
      "aria-pressed": ui.paused ? "true" : "false"
    });
    if (typeof handlers.onTogglePause === "function") {
      pauseBtn.addEventListener("click", () => handlers.onTogglePause());
    }
    right.appendChild(pauseBtn);

    const refBtn = el("button", "btn btn-sm", "Actualiser", { type: "button", "data-action": "refresh-live" });
    if (typeof handlers.onRefresh === "function") {
      refBtn.addEventListener("click", () => handlers.onRefresh());
    }
    right.appendChild(refBtn);
    row.appendChild(right);
    panel.appendChild(row);
    return panel;
  }

  function _renderLiveWorkflowBlock(wf) {
    if (!wf || !wf.available) return null;
    const panel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Progression du workflow"));
    const badges = el("div", "actions-row");
    badges.appendChild(makeBadge("Étape : " + String(wf.stage || "idle"), "info"));
    badges.appendChild(makeBadge(String(wf.preset_profile || "standard") + " · " + String(wf.mode || "evo"), ""));
    const guardOn = String(wf.guard_status || "ON").toUpperCase();
    badges.appendChild(makeBadge("Garde : " + guardOn, guardOn === "ON" ? "ok" : "warn"));
    head.appendChild(badges);
    panel.appendChild(head);

    const prog = _parseWorkflowProgress(wf.progress);
    const barWrap = el("div", "wf-bar");
    const barHead = el("div", "ctx-gauge-head");
    barHead.appendChild(el("span", null, "Avancement : " + String(wf.progress || "0/0")));
    barHead.appendChild(el("span", "mono", fmtPct(prog.pct)));
    barWrap.appendChild(barHead);

    const track = el("div", "wf-progress-track", null, {
      role: "progressbar",
      "aria-valuenow": String(prog.done),
      "aria-valuemin": "0",
      "aria-valuemax": String(prog.total)
    });
    const fill = el("div", "wf-progress-fill");
    fill.style.width = prog.pct + "%";
    track.appendChild(fill);
    barWrap.appendChild(track);
    panel.appendChild(barWrap);

    const nodes = wf.nodes || {};
    const nodeKeys = Object.keys(nodes);
    if (nodeKeys.length) {
      const pills = el("div", "pill-list");
      nodeKeys.forEach((role) => {
        const st = String(nodes[role] || "idle").toLowerCase();
        const tone = st === "running" || st === "active" ? "ok" : (st === "error" || st === "failed" ? "error" : (st === "done" ? "info" : ""));
        pills.appendChild(makeBadge(role + " : " + (nodes[role] || "idle"), tone));
      });
      panel.appendChild(pills);
    }
    if (wf.suggested_profile && wf.suggested_profile !== wf.preset_profile) {
      panel.appendChild(el("div", "notice info", "Profil suggéré : " + wf.suggested_profile));
    }
    return panel;
  }

  function _renderAgentCard(ag) {
    const st = String(ag.status || "done").toLowerCase();
    const card = el("article", "agent-card " + st);

    const head = el("div", "agent-head");
    const titleWrap = el("div", null);
    titleWrap.appendChild(el("div", "agent-role", String(ag.role || ag.id || "Agent")));
    if (ag.id && ag.id !== ag.role) {
      titleWrap.appendChild(el("div", "mono", String(ag.id)));
    }
    head.appendChild(titleWrap);
    head.appendChild(renderStatusBadge(st));
    card.appendChild(head);

    const pills = el("div", "pill-list");
    pills.appendChild(el("span", "pill", String(ag.model || "modèle inconnu")));
    pills.appendChild(el("span", "pill", String(ag.workspace || "workspace")));
    pills.appendChild(renderWorkspaceKindBadge(ag.workspace_kind));
    card.appendChild(pills);

    if (ag.task_title) {
      card.appendChild(el("div", "agent-task", String(ag.task_title)));
    }
    if (ag.last_tool) {
      card.appendChild(el("div", "mono", "Dernier outil : " + String(ag.last_tool)));
    }

    card.appendChild(renderContextGauge(ag.context_tokens || 0, ag.max_context_tokens || 0, { label: "Contexte" }));

    const stats = el("div", "agent-stats");
    stats.appendChild(el("span", "num", "Tokens utiles : " + fmtTokens(ag.useful_tokens || 0)));
    stats.appendChild(el("span", "num", "Cache : " + fmtPct(ag.cache_hit_pct || 0)));
    stats.appendChild(el("span", "num", "Durée : " + fmtDuration(ag.duration_s || 0)));
    if ((Number(ag.error_count) || 0) > 0) {
      stats.appendChild(makeBadge(ag.error_count + " erreur(s)", "error"));
    }
    card.appendChild(stats);
    return card;
  }

  function _renderAgentGroupsPanel(agents) {
    const panel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Agents de la session"));
    head.appendChild(el("span", "mono", agents.length + " agent(s)"));
    panel.appendChild(head);

    if (!agents.length) {
      panel.appendChild(el("div", "empty", "Aucun agent actif ou historique détecté pour cette session."));
      return panel;
    }

    const activeList = agents.filter((a) => a.status === "active" || a.status === "error");
    const waitingList = agents.filter((a) => a.status === "waiting");
    const doneList = agents.filter((a) => a.status !== "active" && a.status !== "error" && a.status !== "waiting");

    const groups = el("div", "agent-groups");
    [
      { key: "active", label: "Actifs", items: activeList, tone: "ok" },
      { key: "waiting", label: "En attente", items: waitingList, tone: "warn" },
      { key: "done", label: "Terminés", items: doneList, tone: "" }
    ].forEach((grp) => {
      if (!grp.items.length) return;
      const sec = el("div", "agent-group", null, { "data-agent-group": grp.key });
      const gHead = el("div", "agent-group-head");
      gHead.appendChild(el("span", null, grp.label));
      gHead.appendChild(makeBadge(String(grp.items.length), grp.tone));
      sec.appendChild(gHead);

      const grid = el("div", "agent-grid");
      grp.items.forEach((ag) => grid.appendChild(_renderAgentCard(ag)));
      sec.appendChild(grid);
      groups.appendChild(sec);
    });
    panel.appendChild(groups);
    return panel;
  }

  function _renderRecentActivityPanel(events, ui) {
    const list = Array.isArray(events) ? events : [];
    const details = el("details", "fold-panel", null, { id: "g-live-activity" });
    if (ui.eventsOpen) details.open = true;

    const summary = el("summary", "fold-summary");
    summary.appendChild(el("span", null, "Activité récente (" + list.length + ")"));
    const boardCount = list.filter((e) => e.kind === "board").length;
    const errCount = list.filter((e) => e.kind === "error").length;
    const metaBadges = el("span", "actions-row");
    if (boardCount > 0) metaBadges.appendChild(makeBadge("Board : " + boardCount, "info"));
    if (errCount > 0) metaBadges.appendChild(makeBadge("Erreurs : " + errCount, "error"));
    summary.appendChild(metaBadges);
    details.appendChild(summary);

    const body = el("div", "fold-body");
    if (!list.length) {
      body.appendChild(el("div", "empty", "Aucun appel d'outil ni message de board récent."));
    } else {
      const wrap = el("div", "table-wrap");
      list.forEach((ev) => {
        const row = el("div", "event-row");
        row.appendChild(el("span", "mono", fmtDate(ev.ts)));
        const kind = String(ev.kind || "tool");
        const kLbl = kind === "board" ? "Board" : (kind === "error" ? "Erreur" : "Outil");
        const kTone = kind === "board" ? "atelier" : (kind === "error" ? "error" : "info");
        row.appendChild(makeBadge(kLbl, kTone));
        row.appendChild(el("span", "pill", String(ev.agent_id || "agent")));
        row.appendChild(el("strong", null, String(ev.name || "")));
        if (ev.detail) row.appendChild(el("span", "preview-text", String(ev.detail)));
        wrap.appendChild(row);
      });
      body.appendChild(wrap);
    }
    details.appendChild(body);
    return details;
  }

  function renderLiveView(container, liveArg, uiArg, handlersArg) {
    const live = liveArg !== undefined ? liveArg : (typeof state !== "undefined" ? state.live : null);
    const ui = uiArg || (typeof state !== "undefined" ? (state.liveUi || {}) : {});
    const handlers = handlersArg || {};

    container.appendChild(_renderLiveToolbar(live, ui, handlers));

    if (!live) {
      container.appendChild(el("div", "empty", "Chargement de la session en direct..."));
      return;
    }

    const wfBlock = _renderLiveWorkflowBlock(live.workflow);

    if (!live.available || !live.selected_session) {
      if (wfBlock) container.appendChild(wfBlock);
      const emptyPanel = el("section", "panel");
      emptyPanel.appendChild(el("div", "empty", "Aucune session active détectée dans le dossier brain/."));
      container.appendChild(emptyPanel);
      return;
    }

    const sel = live.selected_session;
    const summary = live.summary || {};
    const agents = Array.isArray(live.agents) ? live.agents : [];

    const healthPanel = el("section", "panel session-bar");
    const sHead = el("div", "panel-head");
    const sTitle = el("div", "actions-row");
    sTitle.appendChild(el("span", "panel-title", String(sel.label || sel.swarm_title || sel.goal_title || "Session active")));
    sTitle.appendChild(renderWorkspaceKindBadge(sel.workspace_kind));
    if (sel.project) sTitle.appendChild(el("span", "pill", String(sel.project)));
    sTitle.appendChild(makeBadge(sel.captured ? "Suivie" : "Non enregistrée", sel.captured ? "ok" : "warn"));
    sHead.appendChild(sTitle);

    const actLabel = sel.captured ? "Mettre à jour" : "Enregistrer";
    const actName = sel.captured ? "update" : "record";
    const actBtn = el("button", "btn btn-primary", ui.actionInFlight ? "En cours..." : actLabel, {
      type: "button",
      "data-action": "live-metrics-action",
      "data-metrics-action": actName,
      "data-cid": String(sel.conversation_id || "")
    });
    if (ui.actionInFlight) actBtn.disabled = true;
    if (typeof handlers.onCaptureAction === "function") {
      actBtn.addEventListener("click", () => handlers.onCaptureAction(actName, String(sel.conversation_id || "")));
    }
    sHead.appendChild(actBtn);
    healthPanel.appendChild(sHead);

    const maxCtx = Number(summary.max_context_tokens) || 0;
    const ctxTone = maxCtx > CTX_CRIT_TOKENS ? "error" : (maxCtx > CTX_WARN_TOKENS ? "warn" : "");
    const errCnt = Number(summary.error_count) || 0;
    const kpiGrid = el("div", "grid-kpi");
    kpiGrid.appendChild(renderMetricKpiCard(
      "Tokens utiles",
      fmtTokens(summary.useful_tokens || 0),
      fmtInt(summary.llm_calls || 0) + " appels modèle · " + fmtInt(summary.tool_calls || 0) + " outils"
    ));
    kpiGrid.appendChild(renderMetricKpiCard(
      "Efficacité cache",
      fmtPct(summary.cache_hit_pct || 0),
      fmtTokens(summary.cache_read_tokens || 0) + " lus en cache"
    ));
    kpiGrid.appendChild(renderMetricKpiCard(
      "Pic contexte",
      fmtTokens(maxCtx),
      "Actuel : " + fmtTokens(summary.context_tokens || 0),
      ctxTone
    ));
    kpiGrid.appendChild(renderMetricKpiCard(
      "Agents actifs",
      fmtInt(summary.active_agents || 0) + " / " + fmtInt(summary.total_agents || agents.length),
      (summary.waiting_agents || 0) + " en attente · " + (summary.done_agents || 0) + " terminé(s)"
    ));
    kpiGrid.appendChild(renderMetricKpiCard(
      "Raisonnement & Erreurs",
      fmtTokens(summary.thinking_est_tokens || 0),
      errCnt + " erreur(s) · " + fmtDuration(summary.duration_s || 0),
      errCnt > 0 ? "warn" : ""
    ));
    healthPanel.appendChild(kpiGrid);

    healthPanel.appendChild(renderStackedBars([
      { label: "Tokens utiles", value: summary.useful_tokens || 0, color: "var(--g-c1)" },
      { label: "Cache lu", value: summary.cache_read_tokens || 0, color: "var(--g-c3)" },
      { label: "Raisonnement (est.)", value: summary.thinking_est_tokens || 0, color: "var(--g-c2)" }
    ], { title: "Répartition technique des tokens" }));
    container.appendChild(healthPanel);

    if (wfBlock) container.appendChild(wfBlock);

    const layout = el("div", "master-detail");
    layout.appendChild(_renderAgentGroupsPanel(agents));

    const sideCol = el("div", null);
    sideCol.style.display = "flex";
    sideCol.style.flexDirection = "column";
    sideCol.style.gap = "10px";

    const wsPanel = el("section", "panel");
    const wsHead = el("div", "panel-head");
    wsHead.appendChild(el("div", "panel-title", "Répartition par dépôt"));
    wsHead.appendChild(el("span", "mono", "Atelier vs Code"));
    wsPanel.appendChild(wsHead);
    wsPanel.appendChild(renderWorkspaceBreakdown(_aggregateLiveWorkspaces(agents)));
    sideCol.appendChild(wsPanel);

    sideCol.appendChild(_renderRecentActivityPanel(live.recent_events || [], ui));
    layout.appendChild(sideCol);
    container.appendChild(layout);
  }
"""

"""Pure DOM renderer for the Gravity unified 'Métriques' views (100% stdlib, zero innerHTML)."""

from __future__ import annotations

METRICS_VIEWS_JS = r"""
  const ROLE_LABELS_FR = {
    orchestrator: "Orchestration", coordinator: "Coordination", worker: "Exécution (Workers)",
    builder: "Construction", reviewer: "Revue & Audit", research: "Exploration",
    subagent: "Sous-agents", root: "Session racine", planner: "Planification"
  };

  function _recUseful(r) {
    if (!r) return 0;
    if (r.input_tokens != null || r.output_tokens != null) {
      return Math.max(0, (Number(r.input_tokens) || 0) + (Number(r.output_tokens) || 0));
    }
    return Math.max(0, (Number(r.total_tokens) || 0) - (Number(r.cache_read_tokens) || 0));
  }

  function _recKey(r) {
    return String((r && (r.detail_slug || r.label || r.conversation_id)) || "");
  }

  function _liveDeltaCalls(rec) {
    const lv = state.live;
    if (!lv || !lv.selected_session || !rec) return 0;
    if (String(lv.selected_session.conversation_id || "") !== String(rec.conversation_id || "")) return 0;
    return Math.max(0, Number((lv.summary && lv.summary.llm_calls) || 0) - Number(rec.llm_calls || 0));
  }

  function _actBtn(label, action, attrs, cls) {
    return el("button", "btn btn-sm" + (cls ? " " + cls : ""), label, Object.assign({ type: "button", "data-action": action }, attrs || {}));
  }

  function _kvList(pairs) {
    const kv = el("div", "kv-grid");
    pairs.forEach(([k, v]) => { kv.appendChild(el("div", "kv-k", k)); kv.appendChild(el("div", "mono", v)); });
    return kv;
  }

  function _aggregateModels(records) {
    const map = new Map();
    (records || []).forEach((r) => {
      const models = r && r.models && typeof r.models === "object" ? r.models : null;
      if (models && Object.keys(models).length) {
        Object.entries(models).forEach(([mName, mData]) => {
          const cur = map.get(mName) || { label: mName, value: 0 };
          cur.value += Number((mData && mData.calls) || 0);
          map.set(mName, cur);
        });
      } else if (r && r.primary_model) {
        const mName = String(r.primary_model);
        const cur = map.get(mName) || { label: mName, value: 0 };
        cur.value += Number(r.llm_calls || 1);
        map.set(mName, cur);
      }
    });
    return Array.from(map.values()).sort((a, b) => (b.value - a.value) || a.label.localeCompare(b.label));
  }

  function _aggregateRoles(records) {
    const map = new Map();
    (records || []).forEach((r) => {
      const cats = r && r.category_share_pct && typeof r.category_share_pct === "object" ? r.category_share_pct : null;
      const baseTok = Math.max(1, _recUseful(r) || Number(r.total_tokens || 0) || 100);
      if (cats) {
        Object.entries(cats).forEach(([cat, pct]) => {
          const share = Math.max(0, Number(pct) || 0);
          if (share <= 0) return;
          const lbl = ROLE_LABELS_FR[String(cat).toLowerCase()] || String(cat);
          const cur = map.get(lbl) || { label: lbl, value: 0 };
          cur.value += Math.round(baseTok * (share / 100));
          map.set(lbl, cur);
        });
      }
    });
    return Array.from(map.values()).sort((a, b) => (b.value - a.value) || a.label.localeCompare(b.label));
  }

  function _renderDistBars(rows, opts) {
    const o = opts || {};
    const wrap = el("div", "ws-list");
    if (!rows.length) {
      wrap.appendChild(el("div", "empty", o.emptyLabel || "Aucune donnée disponible."));
      return wrap;
    }
    const total = rows.reduce((acc, r) => acc + (Number(r.value) || 0), 0) || 1;
    const maxV = Math.max.apply(null, rows.map((r) => Number(r.value) || 0).concat([1]));
    rows.slice(0, o.limit || 7).forEach((r, idx) => {
      const val = Number(r.value) || 0;
      const row = el("div", "ws-row");
      const head = el("div", "ws-row-head");
      head.appendChild(el("span", "mono", String(r.label)));
      head.appendChild(el("span", "mono num", (o.isTokens ? fmtTokens(val) : (fmtInt(val) + " appels")) + " (" + fmtPct((val / total) * 100) + ")"));
      row.appendChild(head);
      const track = el("div", "ws-bar-track");
      const fill = el("div", "ws-bar-fill");
      fill.style.width = Math.max(val > 0 ? 4 : 0, Math.round((val / maxV) * 100)) + "%";
      fill.style.backgroundColor = "var(--g-c" + ((idx % 6) + 1) + ")";
      track.appendChild(fill);
      row.appendChild(track);
      wrap.appendChild(row);
    });
    return wrap;
  }

  function _renderMetricsOverview(container, met) {
    const kpis = met.kpis || {};
    const recs = (met.records || []).slice(0, 12).reverse();
    const maxCtx = Number(kpis.max_context_tokens || 0);
    const alerts = Number(kpis.context_alerts_count || 0);
    const crits = Number(kpis.context_critical_count || 0);
    const errSteps = Number(kpis.error_steps || 0);
    const dupSpawns = Number(kpis.duplicate_spawns || 0);
    const rewinds = Number(kpis.rewind_calls || 0);
    const interrupted = Number(kpis.interrupted_agents || 0);

    const kpiGrid = el("div", "grid-kpi");
    kpiGrid.appendChild(renderMetricKpiCard("Tokens utiles", fmtTokens(kpis.useful_tokens || 0),
      "Cache lu : " + fmtTokens(kpis.cache_read_tokens || 0) + " · Total : " + fmtTokens(kpis.total_tokens || 0),
      { series: recs.map(_recUseful), seriesColor: "var(--g-c1)" }));
    kpiGrid.appendChild(renderMetricKpiCard("Efficacité cache", fmtPct(kpis.avg_cache_hit_rate_pct || 0),
      fmtInt(kpis.total_llm_calls || 0) + " appels · " + fmtInt(kpis.sessions_count || 0) + " session(s)",
      { series: recs.map((r) => Number(r.cache_hit_rate_pct || 0)), seriesColor: "var(--g-c3)" }));
    kpiGrid.appendChild(renderMetricKpiCard("Pression contexte", fmtTokens(maxCtx),
      alerts + " alerte(s) >128k · " + crits + " critique(s) >200k",
      {
        tone: crits > 0 ? "error" : (alerts > 0 ? "warn" : ""),
        badge: crits > 0 ? { label: ">200k", tone: "crit" } : (alerts > 0 ? { label: ">128k", tone: "warn" } : null),
        series: recs.map((r) => Number(r.max_context_tokens || 0)),
        seriesColor: crits > 0 ? "var(--g-err)" : "var(--g-c4)"
      }));
    kpiGrid.appendChild(renderMetricKpiCard("Effort & Parallélisme", fmtDuration(kpis.wall_clock_s || 0),
      fmtInt(kpis.archived_count || 0) + " archivée(s) · " + fmtInt(kpis.active_count || 0) + " active(s)"));
    kpiGrid.appendChild(renderMetricKpiCard("Thinking & Latence p95", fmtLatency(kpis.latency_p95_ms || 0),
      "Moy. " + fmtLatency(kpis.latency_avg_ms || 0) + " · Raisonnement " + fmtTokens(kpis.thinking_est_tokens || 0) + " · " + fmtInt(kpis.compaction_count || 0) + " compaction(s)"));
    kpiGrid.appendChild(renderMetricKpiCard("Gaspillages & Erreurs", fmtPct(kpis.avg_error_rate_pct || 0),
      fmtInt(errSteps) + " err · " + fmtInt(dupSpawns) + " doublon(s) · " + fmtInt(rewinds) + " rewind(s) · " + fmtInt(interrupted) + " interrompu(s)",
      { tone: (errSteps + dupSpawns + rewinds + interrupted) > 0 ? "warn" : "" }));
    container.appendChild(kpiGrid);

    const stackPanel = el("section", "panel");
    stackPanel.appendChild(renderStackedBars([
      { label: "Tokens utiles", value: kpis.useful_tokens || 0, color: "var(--g-c1)" },
      { label: "Cache lu", value: kpis.cache_read_tokens || 0, color: "var(--g-c3)" },
      { label: "Raisonnement (est.)", value: kpis.thinking_est_tokens || 0, color: "var(--g-c2)" }
    ], { title: "Volume technique des tokens" }));
    container.appendChild(stackPanel);

    const wsRows = (met.by_workspace && met.by_workspace.length)
      ? met.by_workspace
      : (met.by_project || []).map((p) => ({
          workspace: p.project,
          kind: String(p.project || "").toLowerCase().endsWith("-studio") ? "atelier" : "code",
          useful_tokens: Number(p.llm_calls || 0) * 1000,
          sessions: p.sessions
        }));
    const atelierTok = wsRows.filter((w) => w.kind === "atelier").reduce((a, w) => a + (Number(w.useful_tokens) || 0), 0);
    const codeTok = wsRows.filter((w) => w.kind !== "atelier").reduce((a, w) => a + (Number(w.useful_tokens) || 0), 0);

    const wsPanel = el("section", "panel");
    const wsHead = el("div", "panel-head");
    wsHead.appendChild(el("div", "panel-title", "Répartition par Dossier / Workspace"));
    const wsMeta = el("div", "actions-row");
    wsMeta.appendChild(makeBadge((kpis.sessions_count || 0) + " session(s) unique(s) · multi-dépôts comptés par dossier"));
    wsMeta.appendChild(makeBadge("Atelier : " + fmtTokens(atelierTok), "atelier"));
    wsMeta.appendChild(makeBadge("Code : " + fmtTokens(codeTok), "code"));
    wsHead.appendChild(wsMeta);
    wsPanel.appendChild(wsHead);
    wsPanel.appendChild(renderWorkspaceBreakdown(wsRows, { limit: 10 }));
    container.appendChild(wsPanel);

    const splitGrid = el("div", "split with-drawer");
    [
      { title: "Répartition par Modèle", items: _aggregateModels(met.records || []), isTokens: false, empty: "Aucun modèle mesuré." },
      { title: "Répartition par Rôle / Catégorie", items: _aggregateRoles(met.records || []), isTokens: true, empty: "Aucune répartition par rôle." }
    ].forEach((cfg) => {
      const p = el("section", "panel");
      p.appendChild(el("div", "panel-title", cfg.title));
      p.appendChild(_renderDistBars(cfg.items, { isTokens: cfg.isTokens, emptyLabel: cfg.empty }));
      splitGrid.appendChild(p);
    });
    container.appendChild(splitGrid);
  }

  function _sortRecords(records, mode) {
    const arr = (records || []).slice();
    if (mode === "useful_tokens") arr.sort((a, b) => _recUseful(b) - _recUseful(a));
    else if (mode === "max_context") arr.sort((a, b) => Number(b.max_context_tokens || 0) - Number(a.max_context_tokens || 0));
    else if (mode === "errors") arr.sort((a, b) => (Number(b.error_steps || 0) - Number(a.error_steps || 0)) || (Number(b.error_rate_pct || 0) - Number(a.error_rate_pct || 0)));
    else if (mode === "latency") arr.sort((a, b) => Number(b.latency_p95_ms || 0) - Number(a.latency_p95_ms || 0));
    else arr.sort((a, b) => String(b.ended_at || b.started_at || "").localeCompare(String(a.ended_at || a.started_at || "")));
    return arr;
  }

  function _renderComparatorPanel(met) {
    const recs = met.records || [];
    const panel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Comparateur A/B technique"));
    head.appendChild(_actBtn("Fermer", "toggle-compare"));
    panel.appendChild(head);
    if (recs.length < 2) {
      panel.appendChild(el("div", "empty", "Au moins 2 sessions enregistrées sont nécessaires pour comparer A et B."));
      return panel;
    }
    const pick = (k, dIdx) => recs.find((r) => _recKey(r) === k || String(r.conversation_id || "") === k) || recs[dIdx];
    const recA = pick(state.compareA, 0);
    const recB = pick(state.compareB, 1);

    const pickRow = el("div", "actions-row");
    [{ id: "g-cmp-a", lbl: "Session A", val: _recKey(recA) }, { id: "g-cmp-b", lbl: "Session B", val: _recKey(recB) }].forEach((c) => {
      const sel = el("select", "select", null, { id: c.id, "aria-label": c.lbl });
      recs.forEach((r) => {
        const k = _recKey(r);
        const opt = el("option", null, String(r.label || r.conversation_id || k), { value: k });
        if (k === c.val) opt.selected = true;
        sel.appendChild(opt);
      });
      pickRow.appendChild(sel);
    });
    panel.appendChild(pickRow);

    const wrap = el("div", "table-wrap");
    const tbl = el("table");
    const thead = el("thead");
    const htr = el("tr");
    ["Indicateur", "A", "B", "Delta (B - A)"].forEach((h, i) => htr.appendChild(el("th", i > 0 ? "num" : null, h)));
    thead.appendChild(htr);
    tbl.appendChild(thead);
    const tbody = el("tbody");
    [
      ["Tokens utiles", _recUseful(recA), _recUseful(recB), fmtTokens],
      ["Efficacité cache", Number(recA.cache_hit_rate_pct || 0), Number(recB.cache_hit_rate_pct || 0), fmtPct],
      ["Contexte max", Number(recA.max_context_tokens || 0), Number(recB.max_context_tokens || 0), fmtTokens],
      ["Appels modèle", Number(recA.llm_calls || 0), Number(recB.llm_calls || 0), fmtInt],
      ["Latence p95", Number(recA.latency_p95_ms || 0), Number(recB.latency_p95_ms || 0), fmtLatency],
      ["Erreurs", Number(recA.error_steps || 0), Number(recB.error_steps || 0), fmtInt],
      ["Compactions", Number(recA.compaction_count || 0), Number(recB.compaction_count || 0), fmtInt],
      ["Durée murale", Number(recA.wall_clock_s || 0), Number(recB.wall_clock_s || 0), fmtDuration]
    ].forEach(([lbl, va, vb, fmt]) => {
      const tr = el("tr");
      const diff = vb - va;
      tr.appendChild(el("td", null, lbl));
      tr.appendChild(el("td", "num mono", fmt(va)));
      tr.appendChild(el("td", "num mono", fmt(vb)));
      tr.appendChild(el("td", "num mono", diff === 0 ? "0" : ((diff > 0 ? "+" : "-") + fmt(Math.abs(diff)))));
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    panel.appendChild(wrap);
    return panel;
  }

  function _renderSessionDetailDrawer(met) {
    const drawer = el("aside", "drawer");
    const sd = state.sessionDetail;
    const det = (sd && sd.detail) || {};
    const rec = (sd && sd.record) || (met.records || []).find((r) => _recKey(r) === state.sessionTarget) || {};
    const cid = String((sd && sd.conversation_id) || rec.conversation_id || "");
    const slug = String((sd && sd.slug) || rec.detail_slug || state.sessionTarget || "");

    const dHead = el("div", "panel-head");
    dHead.appendChild(el("div", "panel-title", String((sd && sd.label) || rec.label || "Détail session")));
    const dBtns = el("div", "actions-row");
    if (sd && sd.report_md_uri) dBtns.appendChild(_actBtn("Ouvrir .md", "open-file", { "data-uri": sd.report_md_uri }));
    dBtns.appendChild(_actBtn("Fermer", "close-session-detail"));
    dHead.appendChild(dBtns);
    drawer.appendChild(dHead);

    if (state.sessionDetailLoading) {
      drawer.appendChild(el("div", "empty", "Chargement du détail technique..."));
      return drawer;
    }

    const actRow = el("div", "actions-row");
    const deltaCalls = _liveDeltaCalls(rec);
    const updBtn = _actBtn(deltaCalls > 0 ? ("Mettre à jour (+" + deltaCalls + " appels)") : "Mettre à jour",
      "metrics-cli-action", { "data-cli-action": "update", "data-cid": cid, "data-target": slug || cid }, "btn-primary");
    if (state.metricsActionInFlight) updBtn.disabled = true;
    actRow.appendChild(updBtn);
    actRow.appendChild(_actBtn("Éditer", "toggle-session-edit", {}, state.sessionEditOpen ? "active" : ""));
    actRow.appendChild(_actBtn("Ignorer", "metrics-cli-action", { "data-cli-action": "ignore", "data-cid": cid, "data-target": cid }));
    actRow.appendChild(_actBtn("Supprimer", "ask-remove-session", { "data-target": slug || cid }, "btn-danger"));
    drawer.appendChild(actRow);

    if (state.sessionDeleteConfirm && state.pendingDeleteTarget === (slug || cid)) {
      drawer.appendChild(renderInlineConfirm({
        danger: true,
        message: "Supprimer cette session et ses rapports ?",
        confirmLabel: "Confirmer suppression",
        cancelLabel: "Annuler",
        confirmAttrs: { "data-action": "metrics-cli-action", "data-cli-action": "remove", "data-target": slug || cid, "data-cid": cid },
        cancelAttrs: { "data-action": "cancel-remove-session" }
      }));
    }

    if (state.sessionEditOpen) {
      const form = el("form", "panel", null, { id: "g-session-edit-form", "data-target": slug || cid });
      form.appendChild(el("div", "kpi-lbl", "Modifier label, projet et note"));
      [
        ["g-edit-label", "Label", rec.label || ""],
        ["g-edit-project", "Projet", rec.project || ""],
        ["g-edit-note", "Note", rec.note || ""]
      ].forEach(([fid, ph, val]) => {
        const inp = el("input", "input", null, { id: fid, type: "text", placeholder: ph, value: String(val) });
        inp.value = String(val);
        form.appendChild(inp);
      });
      const fBtns = el("div", "actions-row");
      fBtns.appendChild(el("button", "btn btn-sm btn-primary", "Enregistrer", { type: "submit" }));
      fBtns.appendChild(_actBtn("Annuler", "toggle-session-edit"));
      form.appendChild(fBtns);
      drawer.appendChild(form);
    }

    const subTabs = el("div", "subtabs");
    [["summary", "Synthèse"], ["agents", "Agents & Outils"], ["diagnostic", "Diagnostic"]].forEach(([id, lbl]) => {
      subTabs.appendChild(_actBtn(lbl, "session-detail-sub", { "data-sub": id }, state.sessionDetailSub === id ? "active" : ""));
    });
    drawer.appendChild(subTabs);

    const summary = det.summary || {};
    const eff = det.efficiency_and_waste || {};
    const agents = Array.isArray(det.agents) ? det.agents : [];
    const maxCtx = Number((eff.context_bloat && eff.context_bloat.max_context_tokens_overall) || det.max_context_tokens || rec.max_context_tokens || 0);

    if (state.sessionDetailSub === "agents") {
      if (!agents.length) {
        drawer.appendChild(el("div", "empty", "Aucun sous-agent détaillé dans ce rapport."));
      } else {
        agents.slice(0, 30).forEach((ag) => {
          const fold = el("details", "fold-panel");
          const sum = el("summary", "fold-summary");
          const left = el("div", "actions-row");
          left.appendChild(el("span", null, String(ag.role || ag.name || "Agent")));
          left.appendChild(renderWorkspaceKindBadge(ag.workspace_kind || (String(ag.workspace || "").toLowerCase().endsWith("-studio") ? "atelier" : "code")));
          sum.appendChild(left);
          const clean = ag.clean_termination !== false;
          sum.appendChild(makeBadge(clean ? "Propre" : "Interrompu", clean ? "ok" : "warn"));
          fold.appendChild(sum);
          const body = el("div", "fold-body");
          const pills = el("div", "pill-list");
          if (ag.model) pills.appendChild(el("span", "pill", String(ag.model)));
          if (ag.workspace) pills.appendChild(el("span", "pill", String(ag.workspace)));
          if (ag.category) pills.appendChild(el("span", "pill", ROLE_LABELS_FR[String(ag.category).toLowerCase()] || String(ag.category)));
          body.appendChild(pills);
          const agUseful = (Number(ag.input_tokens || 0) + Number(ag.output_tokens || 0)) || Number(ag.useful_tokens || 0);
          body.appendChild(renderContextGauge(ag.max_context_tokens || 0, ag.max_context_tokens || 0, { label: "Pic contexte" }));
          body.appendChild(el("div", "mono", "Utiles : " + fmtTokens(agUseful) + " · Cache : " + fmtTokens(ag.cache_read_tokens || 0) + " · Appels : " + fmtInt(ag.llm_calls || 0) + " · Outils : " + fmtInt(ag.tool_calls || 0)));
          if (ag.conversation_id) body.appendChild(el("div", "mono", "ID : " + String(ag.conversation_id)));
          fold.appendChild(body);
          drawer.appendChild(fold);
        });
      }
      const byTool = (det.tool_usage && det.tool_usage.by_tool) || {};
      const toolRows = Object.entries(byTool).map(([n, c]) => ({
        label: n, value: typeof c === "object" ? Number(c.calls || c.count || 0) : Number(c || 0)
      })).filter((t) => t.value > 0).sort((a, b) => b.value - a.value);
      if (toolRows.length) {
        drawer.appendChild(el("div", "panel-title", "Outils les plus utilisés"));
        drawer.appendChild(_renderDistBars(toolRows, { isTokens: false, limit: 8 }));
      }
    } else if (state.sessionDetailSub === "diagnostic") {
      const dup = (eff.duplicate_role_spawns && eff.duplicate_role_spawns.duplicate_agent_count) != null ? eff.duplicate_role_spawns.duplicate_agent_count : (rec.duplicate_spawns || 0);
      const rw = (eff.rewind_waste && eff.rewind_waste.rewind_calls) != null ? eff.rewind_waste.rewind_calls : (rec.rewind_calls || 0);
      const intr = (eff.interrupted_agents && eff.interrupted_agents.count) != null ? eff.interrupted_agents.count : (rec.interrupted_agents || 0);
      drawer.appendChild(_kvList([
        ["Erreurs", fmtInt(summary.total_error_steps != null ? summary.total_error_steps : (rec.error_steps || 0)) + " (" + fmtPct(summary.error_rate_pct != null ? summary.error_rate_pct : (rec.error_rate_pct || 0)) + ")"],
        ["Doublons de rôles", fmtInt(dup)],
        ["Rewinds", fmtInt(rw)],
        ["Agents interrompus", fmtInt(intr)],
        ["Compactions contexte", fmtInt(det.compaction_count != null ? det.compaction_count : (summary.compaction_count || rec.compaction_count || 0))],
        ["Raisonnement (est.)", fmtTokens(det.thinking_est_tokens != null ? det.thinking_est_tokens : (summary.thinking_est_tokens || rec.thinking_est_tokens || 0))],
        ["Pic contexte", fmtTokens(maxCtx) + (maxCtx > CTX_CRIT_TOKENS ? " [Critique >200k]" : (maxCtx > CTX_WARN_TOKENS ? " [Alerte >128k]" : ""))],
        ["Source détail", (sd && sd.source) || "history"]
      ]));
    } else {
      const inTok = summary.input_tokens != null ? summary.input_tokens : (rec.input_tokens || 0);
      const outTok = summary.output_tokens != null ? summary.output_tokens : (rec.output_tokens || 0);
      const cacheTok = summary.cache_read_tokens != null ? summary.cache_read_tokens : (rec.cache_read_tokens || 0);
      const useful = (Number(inTok) + Number(outTok)) || _recUseful(rec);
      drawer.appendChild(renderContextGauge(maxCtx, maxCtx, { label: "Pic contexte" }));
      drawer.appendChild(_kvList([
        ["ID", cid || "—"],
        ["Projet", rec.project || det.project || "—"],
        ["Modèle principal", rec.primary_model || "—"],
        ["Tokens utiles", fmtTokens(useful) + " (in " + fmtTokens(inTok) + " · out " + fmtTokens(outTok) + ")"],
        ["Cache lu", fmtTokens(cacheTok) + " (" + fmtPct(summary.cache_hit_rate_pct != null ? summary.cache_hit_rate_pct : (rec.cache_hit_rate_pct || 0)) + ")"],
        ["Appels modèle / outils", fmtInt(summary.total_llm_calls != null ? summary.total_llm_calls : (rec.llm_calls || 0)) + " / " + fmtInt(summary.total_tool_calls != null ? summary.total_tool_calls : (rec.tool_calls || 0))],
        ["Durée / Parallélisme", fmtDuration(summary.wall_clock_s || rec.wall_clock_s) + " · " + Number(summary.parallelism_factor || rec.parallelism_factor || 1).toFixed(1) + "x"],
        ["Latence p95", fmtLatency(det.latency_p95_ms != null ? det.latency_p95_ms : (summary.latency_p95_ms || rec.latency_p95_ms || 0))]
      ]));
      if (rec.note) drawer.appendChild(el("div", "notice", "Note : " + rec.note));
      const costObj = typeof summary.cost_usd === "object" ? summary.cost_usd : {};
      const costVal = costObj.total_usd != null ? costObj.total_usd : (costObj.total != null ? costObj.total : (rec.cost_usd || 0));
      const savVal = costObj.cache_savings_usd != null ? costObj.cache_savings_usd : (rec.cache_savings_usd || 0);
      drawer.appendChild(el("div", "kpi-sub mono", "Repère secondaire ($) : " + fmtUsd(costVal) + " · économie cache " + fmtUsd(savVal)));
    }
    return drawer;
  }

  function _renderSessionCard(r) {
    const target = _recKey(r);
    const cid = String(r.conversation_id || "");
    const card = el("article", "agent-card" + (state.sessionTarget === target ? " active" : ""));
    const head = el("div", "agent-head");
    const tWrap = el("div", null);
    tWrap.appendChild(el("div", "agent-role", String(r.label || cid || "Session")));
    tWrap.appendChild(el("div", "mono", (r.project || "(sans projet)") + " · " + fmtDate(r.ended_at || r.started_at)));
    head.appendChild(tWrap);
    const maxCtx = Number(r.max_context_tokens || 0);
    if (maxCtx > CTX_CRIT_TOKENS) head.appendChild(makeBadge(">200k", "crit"));
    else if (maxCtx > CTX_WARN_TOKENS) head.appendChild(makeBadge(">128k", "warn"));
    else head.appendChild(makeBadge(r.status === "active" ? "Active" : "Enregistrée", r.status === "active" ? "ok" : ""));
    card.appendChild(head);

    const pills = el("div", "pill-list");
    if (r.primary_model) pills.appendChild(el("span", "pill", String(r.primary_model)));
    if (r.execution_mode) pills.appendChild(el("span", "pill", String(r.execution_mode)));
    if ((Number(r.error_steps) || 0) > 0) pills.appendChild(makeBadge(r.error_steps + " err", "error"));
    card.appendChild(pills);

    const stats = el("div", "agent-stats");
    stats.appendChild(el("span", "num", "Utiles : " + fmtTokens(_recUseful(r))));
    stats.appendChild(el("span", "num", "Cache : " + fmtPct(r.cache_hit_rate_pct || 0)));
    stats.appendChild(el("span", "num", "Ctx max : " + fmtTokens(maxCtx)));
    if (Number(r.latency_p95_ms || 0) > 0) stats.appendChild(el("span", "num", "p95 : " + fmtLatency(r.latency_p95_ms)));
    card.appendChild(stats);

    const acts = el("div", "actions-row");
    acts.appendChild(_actBtn("Détail", "open-session-detail", { "data-target": target }, "btn-primary"));
    const dc = _liveDeltaCalls(r);
    acts.appendChild(_actBtn(dc > 0 ? ("Mettre à jour (+" + dc + " appels)") : "Mettre à jour",
      "metrics-cli-action", { "data-cli-action": "update", "data-cid": cid, "data-target": target }));
    acts.appendChild(_actBtn("A", "pin-compare", { "data-slot": "A", "data-target": target }, state.compareA === target ? "active" : ""));
    acts.appendChild(_actBtn("B", "pin-compare", { "data-slot": "B", "data-target": target }, state.compareB === target ? "active" : ""));
    card.appendChild(acts);
    return card;
  }

  function _renderPendingCard(item, isIgnored) {
    const cid = String(item.conversation_id || "");
    const card = el("article", "agent-card " + (isIgnored ? "done" : "waiting"));
    const head = el("div", "agent-head");
    const tWrap = el("div", null);
    tWrap.appendChild(el("div", "agent-role", String(item.label || cid || "Session")));
    tWrap.appendChild(el("div", "mono", (item.project || "workspace") + " · " + fmtDate(item.updated_at || item.ignored_at)));
    head.appendChild(tWrap);
    head.appendChild(makeBadge(isIgnored ? "Ignorée" : (item.active_capture ? "Capture" : "À enregistrer"), isIgnored ? "" : "warn"));
    card.appendChild(head);
    if (item.ignored_reason || item.current_phase) card.appendChild(el("div", "mono", String(item.ignored_reason || item.current_phase)));
    const acts = el("div", "actions-row");
    if (isIgnored) {
      acts.appendChild(_actBtn("Restaurer", "metrics-cli-action", { "data-cli-action": "unignore", "data-cid": cid, "data-target": cid }, "btn-primary"));
    } else {
      acts.appendChild(_actBtn("Enregistrer", "metrics-cli-action", { "data-cli-action": "record", "data-cid": cid, "data-target": cid, "data-workspace": String(item.cwd || "") }, "btn-primary"));
      acts.appendChild(_actBtn("Ignorer", "metrics-cli-action", { "data-cli-action": "ignore", "data-cid": cid, "data-target": cid }));
    }
    card.appendChild(acts);
    return card;
  }

  function _renderMetricsSessions(container, met) {
    const recs = met.records || [];
    const pending = met.pending_sessions || [];
    const ignored = met.ignored_sessions || [];

    if (pending.length > 0 && state.metricsFilter !== "pending") {
      const banner = el("div", "notice warn");
      const bRow = el("div", "panel-head");
      bRow.appendChild(el("span", null, pending.length + " session(s) détectée(s) à enregistrer."));
      bRow.appendChild(_actBtn("Voir À enregistrer (" + pending.length + ")", "metrics-filter", { "data-filter": "pending" }));
      banner.appendChild(bRow);
      container.appendChild(banner);
    }

    const ctrlPanel = el("section", "panel");
    const cHead = el("div", "panel-head");
    const fTabs = el("div", "subtabs");
    [
      ["recorded", "Enregistrées (" + recs.length + ")"],
      ["pending", "À enregistrer (" + pending.length + ")"],
      ["ignored", "Ignorées (" + ignored.length + ")"],
      ["all", "Toutes (" + (recs.length + pending.length + ignored.length) + ")"]
    ].forEach(([id, lbl]) => fTabs.appendChild(_actBtn(lbl, "metrics-filter", { "data-filter": id }, state.metricsFilter === id ? "active" : "")));
    cHead.appendChild(fTabs);

    const rCtrls = el("div", "actions-row");
    const sortSel = el("select", "select", null, { id: "g-metrics-sort", "aria-label": "Tri technique" });
    [["date", "Tri : Récentes"], ["useful_tokens", "Tri : Tokens utiles"], ["max_context", "Tri : Pic contexte"], ["errors", "Tri : Erreurs"], ["latency", "Tri : Latence p95"]].forEach(([v, l]) => {
      const opt = el("option", null, l, { value: v });
      if (state.metricsSort === v) opt.selected = true;
      sortSel.appendChild(opt);
    });
    rCtrls.appendChild(sortSel);
    rCtrls.appendChild(_actBtn("Comparateur A/B", "toggle-compare", {}, state.compareOpen ? "active" : ""));
    cHead.appendChild(rCtrls);
    ctrlPanel.appendChild(cHead);
    container.appendChild(ctrlPanel);

    if (state.compareOpen) container.appendChild(_renderComparatorPanel(met));

    const listWrap = el("div", "agent-grid");
    if (state.metricsFilter === "pending" || state.metricsFilter === "all") pending.forEach((p) => listWrap.appendChild(_renderPendingCard(p, false)));
    if (state.metricsFilter === "ignored" || state.metricsFilter === "all") ignored.forEach((ig) => listWrap.appendChild(_renderPendingCard(ig, true)));
    if (state.metricsFilter === "recorded" || state.metricsFilter === "all") _sortRecords(recs, state.metricsSort).forEach((r) => listWrap.appendChild(_renderSessionCard(r)));

    if (!listWrap.children.length) {
      container.appendChild(el("div", "empty", "Aucune session dans cette vue."));
      return;
    }
    if (state.sessionTarget) {
      const layout = el("div", "master-detail");
      layout.appendChild(listWrap);
      layout.appendChild(_renderSessionDetailDrawer(met));
      container.appendChild(layout);
    } else {
      container.appendChild(listWrap);
    }
  }

  function _renderMetricsAudits(container, met) {
    const audits = met.audits || [];
    if (met.index_audit) {
      const idxCard = el("div", "notice");
      const row = el("div", "panel-head");
      row.appendChild(el("span", null, "Index Audits Agents : " + (met.index_audit.title || met.index_audit.rel_path)));
      const btns = el("div", "actions-row");
      btns.appendChild(_actBtn("Lire", "read-audit", { "data-audit-id": met.index_audit.audit_id || met.index_audit.rel_path }, "btn-primary"));
      if (met.index_audit.uri) btns.appendChild(_actBtn("Ouvrir .md", "open-file", { "data-uri": met.index_audit.uri }));
      row.appendChild(btns);
      idxCard.appendChild(row);
      container.appendChild(idxCard);
    }

    if (state.auditTarget || state.auditLoading) {
      const reader = el("section", "panel");
      const rHead = el("div", "panel-head");
      const ad = state.auditData;
      rHead.appendChild(el("div", "panel-title", (ad && ad.title) ? ad.title : "Lecture de l'audit"));
      const rBtns = el("div", "actions-row");
      if (ad && ad.uri) rBtns.appendChild(_actBtn("Ouvrir .md", "open-file", { "data-uri": ad.uri }));
      rBtns.appendChild(_actBtn("Fermer", "close-audit-reader"));
      rHead.appendChild(rBtns);
      reader.appendChild(rHead);
      if (state.auditLoading) {
        reader.appendChild(el("div", "empty", "Chargement du contenu de l'audit..."));
      } else if (!ad || !ad.found) {
        reader.appendChild(el("div", "notice warn", (ad && ad.error) || "Audit introuvable."));
      } else {
        const meta = el("div", "actions-row");
        if (ad.verdict) meta.appendChild(makeBadge(ad.verdict, ad.verdict_tone || ""));
        if (ad.workspace) meta.appendChild(el("span", "pill", ad.workspace));
        if (ad.date) meta.appendChild(el("span", "mono", ad.date));
        reader.appendChild(meta);
        const pre = el("pre", "mono", String(ad.content || ""));
        pre.style.whiteSpace = "pre-wrap";
        pre.style.overflowWrap = "anywhere";
        pre.style.margin = "0";
        pre.style.padding = "8px";
        pre.style.background = "var(--g-muted)";
        pre.style.borderRadius = "8px";
        reader.appendChild(pre);
      }
      container.appendChild(reader);
    }

    if (!audits.length) {
      container.appendChild(el("div", "empty", "Aucun audit agent Markdown découvert dans audits/agents/."));
      return;
    }
    const grid = el("div", "grid-cards");
    audits.forEach((a) => {
      const card = el("article", "agent-card");
      const head = el("div", "agent-head");
      head.appendChild(el("div", "agent-role", String(a.title || a.rel_path || "Audit")));
      head.appendChild(makeBadge(a.verdict || "—", a.verdict_tone || ""));
      card.appendChild(head);
      const pills = el("div", "pill-list");
      pills.appendChild(el("span", "pill", String(a.workspace || "workspace")));
      pills.appendChild(el("span", "pill", String(a.date || "—")));
      pills.appendChild(el("span", "pill", fmtBytes(a.size_bytes)));
      card.appendChild(pills);
      if (a.excerpt) card.appendChild(el("div", "preview-text", String(a.excerpt)));
      const acts = el("div", "actions-row");
      acts.appendChild(_actBtn("Lire", "read-audit", { "data-audit-id": a.audit_id || a.rel_path }, "btn-primary"));
      if (a.uri) acts.appendChild(_actBtn("Ouvrir .md", "open-file", { "data-uri": a.uri }));
      card.appendChild(acts);
      grid.appendChild(card);
    });
    container.appendChild(grid);
  }

  function renderMetricsContent(container) {
    const met = state.metrics;
    if (!met) {
      container.appendChild(el("div", "empty", "Chargement des métriques..."));
      return;
    }
    const subPanel = el("section", "panel");
    const sHead = el("div", "panel-head");
    const subTabs = el("div", "subtabs");
    const recs = met.records || [];
    const pend = met.pending_sessions || [];
    const auds = met.audits || [];
    [
      ["overview", "Vue d'ensemble technique"],
      ["sessions", "Sessions (" + recs.length + (pend.length ? " + " + pend.length + " à enr." : "") + ")"],
      ["audits", "Audits Agents (" + auds.length + ")"]
    ].forEach(([id, lbl]) => {
      subTabs.appendChild(el("button", "btn" + (state.metricsSub === id ? " active" : ""), lbl, {
        type: "button", "data-action": "metrics-sub", "data-sub": id
      }));
    });
    sHead.appendChild(subTabs);
    if (met.metrics_md_uri) sHead.appendChild(_actBtn("Ouvrir METRICS.md", "open-file", { "data-uri": met.metrics_md_uri }));
    subPanel.appendChild(sHead);

    if (state.metricsSub === "sessions") _renderMetricsSessions(subPanel, met);
    else if (state.metricsSub === "audits") _renderMetricsAudits(subPanel, met);
    else _renderMetricsOverview(subPanel, met);
    container.appendChild(subPanel);
  }

  function renderMetricsUnifiedView(container) {
    const met = state.metrics;
    const bar = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Métriques techniques & Audits Agents"));

    const ctrls = el("div", "actions-row");
    const projSel = el("select", "select", null, { id: "g-metrics-project", "aria-label": "Filtrer par projet" });
    projSel.appendChild(el("option", null, "Tous les projets", { value: "" }));
    ((met && met.projects) || []).forEach((p) => {
      const opt = el("option", null, p, { value: p });
      if (p === state.metricsProject) opt.selected = true;
      projSel.appendChild(opt);
    });
    ctrls.appendChild(projSel);

    const searchInput = el("input", "input", null, {
      id: "g-metrics-q", type: "search", placeholder: "Rechercher label, modèle, ID...", value: state.metricsQ || ""
    });
    searchInput.value = state.metricsQ || "";
    ctrls.appendChild(searchInput);
    head.appendChild(ctrls);
    bar.appendChild(head);
    container.appendChild(bar);

    const body = el("div", null, null, { id: "g-metrics-content" });
    body.style.display = "flex";
    body.style.flexDirection = "column";
    body.style.gap = "10px";
    renderMetricsContent(body);
    container.appendChild(body);
  }
"""

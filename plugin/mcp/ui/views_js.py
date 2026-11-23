"""DOM and SVG view renderers for Gravity MCP App (100% stdlib, zero innerHTML)."""

from __future__ import annotations

VIEWS_JS = r"""
  const SVG_NS = ["http", "://www.w3.org/2000/svg"].join("");

  function el(tag, className, text, attrs) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (attrs && typeof attrs === "object") {
      for (const [k, v] of Object.entries(attrs)) {
        if (v !== undefined && v !== null) node.setAttribute(k, String(v));
      }
    }
    return node;
  }

  function svgEl(tag, attrs, text) {
    const node = document.createElementNS(SVG_NS, tag);
    if (attrs && typeof attrs === "object") {
      for (const [k, v] of Object.entries(attrs)) {
        if (v !== undefined && v !== null) node.setAttribute(k, String(v));
      }
    }
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function fmtInt(n) {
    return Math.round(Number(n) || 0).toLocaleString("fr-FR");
  }

  function fmtUsd(n) {
    return "$" + (Number(n) || 0).toFixed(4);
  }

  function fmtPct(n) {
    return (Number(n) || 0).toFixed(1) + "%";
  }

  function fmtTok(n) {
    const v = Number(n) || 0;
    if (v >= 1000000) return (v / 1000000).toFixed(1) + "M";
    if (v >= 1000) return Math.round(v / 1000) + "k";
    return String(Math.round(v));
  }

  function fmtBytes(n) {
    if (n === null || n === undefined) return "—";
    const b = Number(n) || 0;
    if (b >= 1024 * 1024) return (b / (1024 * 1024)).toFixed(1) + " Mo";
    if (b >= 1024) return (b / 1024).toFixed(1) + " Ko";
    return b + " o";
  }

  function fmtDate(raw) {
    const s = String(raw || "");
    return s ? s.slice(0, 16).replace("T", " ") : "—";
  }

  function makeBadge(label, tone) {
    return el("span", "badge" + (tone ? " " + tone : ""), label);
  }

  function makeKpiCard(label, value, sub) {
    const card = el("div", "kpi-card");
    card.appendChild(el("div", "kpi-lbl", label));
    card.appendChild(el("div", "kpi-val num", value));
    if (sub) card.appendChild(el("div", "kpi-sub mono", sub));
    return card;
  }

  function tabForModule(modId) {
    const tabs = (state.overview && state.overview.tabs) || [];
    if (modId === "core") return tabs.find((t) => t.id === "overview") || null;
    return tabs.find((t) => t.module_id === modId || t.id === modId) || null;
  }

  function renderOverviewView(container) {
    const ov = state.overview;
    if (!ov) {
      container.appendChild(el("div", "empty", "Chargement de la vue Overview..."));
      return;
    }
    const doctor = ov.doctor || {};
    const status = String(doctor.status || "unknown");
    const statusTone = status === "ok" ? "ok" : (status === "error" ? "error" : "warn");

    const summaryPanel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Diagnostic Core & Environnement"));
    head.appendChild(makeBadge("doctor: " + status.toUpperCase(), statusTone));
    summaryPanel.appendChild(head);

    const kpis = el("div", "grid-kpi");
    kpis.appendChild(makeKpiCard("Modules", String(doctor.module_count || 0), (doctor.valid_count || 0) + " valide(s)"));
    kpis.appendChild(makeKpiCard("Registre", doctor.initialized ? "Initialisé" : "Découverte RO", ov.registry_source || "—"));
    kpis.appendChild(makeKpiCard("Anomalies", String((doctor.invalid_count || 0) + (doctor.duplicate_ids || []).length), "invalides / doublons"));
    kpis.appendChild(makeKpiCard("Dossiers legacy", String(doctor.legacy_count || 0), "lecture seule"));
    summaryPanel.appendChild(kpis);

    const kv = el("div", "kv-grid");
    kv.appendChild(el("div", "kv-k", "$GRAVITY_HOME"));
    kv.appendChild(el("div", "mono", ov.gravity_home || "—"));
    kv.appendChild(el("div", "kv-k", "Registre"));
    kv.appendChild(el("div", "mono", ov.registry_path || "—"));
    summaryPanel.appendChild(kv);

    const warns = ov.warnings || doctor.warnings || [];
    warns.forEach((w) => {
      summaryPanel.appendChild(el("div", "notice warn", w));
    });
    container.appendChild(summaryPanel);

    const modsPanel = el("section", "panel");
    const mHead = el("div", "panel-head");
    mHead.appendChild(el("div", "panel-title", "Modules Gravity découverts"));
    mHead.appendChild(el("span", "mono", ((ov.modules || []).length) + " module(s)"));
    modsPanel.appendChild(mHead);

    const modules = ov.modules || [];
    if (!modules.length) {
      modsPanel.appendChild(el("div", "empty", "Aucun module Gravity détecté."));
    } else {
      const grid = el("div", "grid-cards");
      modules.forEach((mod) => {
        const modId = String(mod.id || "");
        const targetTab = tabForModule(modId);
        const card = el("button", "mod-card", null, {
          type: "button",
          "data-action": "select-tab",
          "data-tab": targetTab ? targetTab.id : "overview"
        });
        const top = el("div", "mod-top");
        top.appendChild(el("span", "mod-name", mod.display_name || mod.plugin_name || modId));
        top.appendChild(makeBadge(mod.valid ? "OK" : "INVALID", mod.valid ? "ok" : "error"));
        card.appendChild(top);

        const meta = el("div", "pill-list");
        meta.appendChild(el("span", "pill", "id=" + modId));
        if (mod.version) meta.appendChild(el("span", "pill", "v" + mod.version));
        const uiMode = (mod.ui && mod.ui.mode) ? mod.ui.mode : "none";
        meta.appendChild(el("span", "pill", "ui:" + uiMode));
        meta.appendChild(el("span", "pill", mod.home_exists ? "home:ok" : "home:absent"));
        card.appendChild(meta);

        if (mod.resolved_home) {
          card.appendChild(el("div", "mono", mod.resolved_home));
        }
        if (Array.isArray(mod.commands) && mod.commands.length) {
          card.appendChild(el("div", "mono", mod.commands.join(" · ")));
        }
        grid.appendChild(card);
      });
      modsPanel.appendChild(grid);
    }
    container.appendChild(modsPanel);

    const legacy = ov.legacy_homes || [];
    if (legacy.length) {
      const legPanel = el("section", "panel");
      const lHead = el("div", "panel-head");
      lHead.appendChild(el("div", "panel-title", "Anciens dossiers legacy (lecture seule stricte)"));
      lHead.appendChild(makeBadge(legacy.length + " détecté(s)", "warn"));
      legPanel.appendChild(lHead);
      legPanel.appendChild(el("div", "notice", "Aucune modification ni suppression automatique. Utilisez /gravity doctor (--migration-plan) pour un plan manuel."));

      const wrap = el("div", "table-wrap");
      const tbl = el("table");
      const thead = el("thead");
      const htr = el("tr");
      ["Nom", "Module cible", "Chemin"].forEach((lbl) => htr.appendChild(el("th", null, lbl)));
      thead.appendChild(htr);
      tbl.appendChild(thead);
      const tbody = el("tbody");
      legacy.forEach((lh) => {
        const tr = el("tr");
        tr.appendChild(el("td", null, lh.name || "—"));
        tr.appendChild(el("td", "mono", lh.target_module || "—"));
        tr.appendChild(el("td", "mono", lh.path || "—"));
        tbody.appendChild(tr);
      });
      tbl.appendChild(tbody);
      wrap.appendChild(tbl);
      legPanel.appendChild(wrap);
      container.appendChild(legPanel);
    }
  }

  function renderWorkflowView(container) {
    const wf = state.workflow;
    const panel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Workflow Live (lecture seule)"));

    const ctrl = el("div", "actions-row");
    const workspaces = (wf && wf.workspaces) || [];
    const sel = el("select", "select", null, { id: "g-wf-ws" });
    if (!workspaces.length) {
      sel.appendChild(el("option", null, "Aucun workspace actif", { value: "" }));
    } else {
      const activeWsPath = (wf && wf.selected_workspace && wf.selected_workspace.workspace_path) || "";
      workspaces.forEach((w) => {
        const val = String(w.workspace_path || w.workspace || "");
        const opt = el("option", null, val, { value: val });
        if (val === activeWsPath || val === state.selectedWs) opt.selected = true;
        sel.appendChild(opt);
      });
    }
    ctrl.appendChild(sel);
    const guardOn = wf ? String(wf.guard_status || "ON") : "ON";
    ctrl.appendChild(makeBadge("Guard: " + guardOn, guardOn === "ON" ? "ok" : "warn"));
    head.appendChild(ctrl);
    panel.appendChild(head);

    if (!wf || !wf.available) {
      panel.appendChild(el("div", "empty", "État workflow idle : aucun fichier live_state.json actif trouvé pour le workspace sélectionné."));
      if (wf && wf.workflow_home) {
        panel.appendChild(el("div", "mono", "Source surveillée : " + wf.workflow_home));
      }
      container.appendChild(panel);
      return;
    }

    const kpis = el("div", "grid-kpi");
    kpis.appendChild(makeKpiCard("Étape", wf.stage || "idle", "Progression " + (wf.progress || "0/8")));
    kpis.appendChild(makeKpiCard("Profil", wf.preset_profile || "standard", "Mode " + (wf.mode || "evo") + " · niveau " + (wf.level || "standard")));
    kpis.appendChild(makeKpiCard("Suggéré", wf.suggested_profile || "standard", wf.suggested_reason || "aucune surcharge"));
    kpis.appendChild(makeKpiCard("Caveman", wf.caveman || "lite", wf.caveman_locked ? "verrouillé" : "adaptatif"));
    panel.appendChild(kpis);

    const rm = wf.role_models || {};
    const rmWrap = el("div", "pill-list");
    Object.keys(rm).sort().forEach((role) => {
      rmWrap.appendChild(el("span", "pill", role + " -> " + rm[role]));
    });
    panel.appendChild(rmWrap);

    const nodes = wf.nodes || {};
    const nodeGrid = el("div", "grid-kpi");
    ["planner", "builder", "reviewer"].forEach((role) => {
      nodeGrid.appendChild(makeKpiCard("Nœud " + role, nodes[role] || "idle"));
    });
    panel.appendChild(nodeGrid);
    container.appendChild(panel);

    const evPanel = el("section", "panel");
    const evHead = el("div", "panel-head");
    evHead.appendChild(el("div", "panel-title", "Flux d'événements récents"));
    const events = wf.events || [];
    evHead.appendChild(el("span", "mono", events.length + " événement(s) · poll 1,5 s"));
    evPanel.appendChild(evHead);

    if (!events.length) {
      evPanel.appendChild(el("div", "empty", "Aucun événement récent."));
    } else {
      const list = el("div", "table-wrap");
      events.slice().reverse().forEach((ev) => {
        const row = el("div", "event-row");
        row.appendChild(el("span", "mono", fmtDate(ev.timestamp || ev.ts || ev.at)));
        row.appendChild(makeBadge(String(ev.type || ev.event || ev.stage || "event"), "info"));
        row.appendChild(el("span", null, String(ev.summary || ev.message || ev.detail || "")));
        list.appendChild(row);
      });
      evPanel.appendChild(list);
    }
    container.appendChild(evPanel);
  }

  function metricsRecordCost(rec) {
    if (state.metricsTariff === "2027" && rec.cost_2027_usd != null) {
      return Number(rec.cost_2027_usd) || 0;
    }
    return Number(rec.cost_usd) || 0;
  }

  function renderMetricsSvgChart(byProject) {
    const box = el("div", "svg-box");
    const rows = (byProject || []).slice(0, 6);
    if (!rows.length) {
      box.appendChild(el("div", "empty", "Aucune donnée par projet."));
      return box;
    }
    const is2027 = state.metricsTariff === "2027";
    const vals = rows.map((r) => is2027 && r.cost_2027_usd != null ? Number(r.cost_2027_usd) || 0 : Number(r.cost_usd) || 0);
    const maxV = Math.max.apply(null, vals.concat([0.0001]));
    const width = 640;
    const rowH = 26;
    const padT = 8;
    const height = padT + rows.length * rowH + 8;
    const lblW = 150;
    const valW = 120;
    const barMaxW = width - lblW - valW - 16;
    const palette = ["var(--g-c1)", "var(--g-c2)", "var(--g-c3)", "var(--g-c4)", "var(--g-c5)", "var(--g-c6)"];

    const svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": "Coûts par projet" });
    rows.forEach((r, idx) => {
      const y = padT + idx * rowH;
      const val = vals[idx];
      const barW = Math.max(val > 0 ? 4 : 0, (val / maxV) * barMaxW);
      const share = is2027 ? (r.share_2027_pct || 0) : (r.share_pct || 0);
      const name = String(r.project || "(sans projet)");
      const shortName = name.length > 20 ? name.slice(0, 18) + ".." : name;

      const g = svgEl("g");
      g.appendChild(svgEl("title", null, name + ": " + fmtUsd(val) + " (" + share + "%, " + (r.sessions || 0) + " sessions)"));
      g.appendChild(svgEl("text", {
        x: 4, y: y + 16, fill: "var(--g-fg)", "font-size": 11, "font-family": "var(--g-font)"
      }, shortName));
      g.appendChild(svgEl("rect", {
        x: lblW, y: y + 5, width: barMaxW, height: 14, rx: 4, fill: "var(--g-muted)"
      }));
      g.appendChild(svgEl("rect", {
        x: lblW, y: y + 5, width: barW.toFixed(1), height: 14, rx: 4, fill: palette[idx % palette.length]
      }));
      g.appendChild(svgEl("text", {
        x: lblW + barMaxW + 8, y: y + 16, fill: "var(--g-fg-sec)", "font-size": 11, "font-family": "var(--g-mono)"
      }, fmtUsd(val) + " (" + Number(share).toFixed(0) + "%)"));
      svg.appendChild(g);
    });
    box.appendChild(svg);
    return box;
  }

  function renderSessionDetailDrawer() {
    const drawer = el("aside", "drawer");
    const dHead = el("div", "panel-head");
    dHead.appendChild(el("div", "panel-title", "Détail session (lecture seule)"));
    const dBtns = el("div", "actions-row");
    if (state.sessionDetail && state.sessionDetail.report_md_uri) {
      dBtns.appendChild(el("button", "btn", "Ouvrir .md", {
        type: "button", "data-action": "open-file", "data-uri": state.sessionDetail.report_md_uri
      }));
    }
    dBtns.appendChild(el("button", "btn", "Fermer", { type: "button", "data-action": "close-session-detail" }));
    dHead.appendChild(dBtns);
    drawer.appendChild(dHead);

    if (state.sessionDetailLoading) {
      drawer.appendChild(el("div", "empty", "Chargement du détail..."));
      return drawer;
    }
    const sd = state.sessionDetail;
    if (!sd || !sd.found) {
      drawer.appendChild(el("div", "empty", "Détail indisponible."));
      return drawer;
    }
    const det = sd.detail || {};
    const summary = det.summary || {};
    const costObj = typeof summary.cost_usd === "object" ? summary.cost_usd : {};
    const costVal = costObj.total != null ? costObj.total : (det.cost_usd != null ? det.cost_usd : (sd.record && sd.record.cost_usd) || 0);
    const tokObj = summary.tokens || {};
    const totTok = tokObj.total != null ? tokObj.total : (det.total_tokens != null ? det.total_tokens : (sd.record && sd.record.total_tokens) || 0);

    const kv = el("div", "kv-grid");
    [
      ["Label", sd.label || det.label || "—"],
      ["ID", sd.conversation_id || "—"],
      ["Source", sd.source || "—"],
      ["Coût", fmtUsd(costVal)],
      ["Tokens", fmtInt(totTok)],
      ["Modèle", det.primary_model || (sd.record && sd.record.primary_model) || "—"]
    ].forEach(([k, v]) => {
      kv.appendChild(el("div", "kv-k", k));
      kv.appendChild(el("div", "mono", v));
    });
    drawer.appendChild(kv);

    const agents = Array.isArray(det.agents) ? det.agents : [];
    if (agents.length) {
      drawer.appendChild(el("div", "panel-title", "Sous-agents (" + agents.length + ")"));
      const wrap = el("div", "table-wrap");
      const tbl = el("table");
      const tbody = el("tbody");
      agents.slice(0, 15).forEach((ag) => {
        const tr = el("tr");
        tr.appendChild(el("td", null, String(ag.role || ag.name || ag.conversation_id || "agent")));
        tr.appendChild(el("td", "mono", String(ag.model || "—")));
        tr.appendChild(el("td", "num mono", fmtUsd(ag.cost_usd || 0)));
        tbody.appendChild(tr);
      });
      tbl.appendChild(tbody);
      wrap.appendChild(tbl);
      drawer.appendChild(wrap);
    }
    return drawer;
  }

  function renderMetricsContent(container) {
    const met = state.metrics;
    const kpis = met.kpis || {};
    const is2027 = state.metricsTariff === "2027";
    const costTotal = is2027 ? (kpis.cost_2027_usd || kpis.cost_usd || 0) : (kpis.cost_usd || 0);

    const kpiGrid = el("div", "grid-kpi");
    kpiGrid.appendChild(makeKpiCard("Sessions", fmtInt(kpis.sessions_count || 0), (kpis.archived_count || 0) + " archivée(s) · " + (kpis.active_count || 0) + " active(s)"));
    kpiGrid.appendChild(makeKpiCard("Coût (" + state.metricsTariff + ")", fmtUsd(costTotal), "économie cache " + fmtUsd(kpis.cache_savings_usd || 0)));
    kpiGrid.appendChild(makeKpiCard("Cache hit moyen", fmtPct(kpis.avg_cache_hit_rate_pct || 0), fmtTok(kpis.total_tokens || 0) + " tokens · " + fmtInt(kpis.total_llm_calls || 0) + " appels"));
    kpiGrid.appendChild(makeKpiCard("Bridge", fmtInt(kpis.bridge_sessions_count || 0), fmtInt(kpis.bridge_children_total || 0) + " enfant(s)"));
    container.appendChild(kpiGrid);

    const chartPanel = el("section", "panel");
    const cHead = el("div", "panel-head");
    cHead.appendChild(el("div", "panel-title", "Répartition des coûts par projet"));
    cHead.appendChild(el("span", "mono", (met.total_matching || 0) + " / " + (met.total_records || 0) + " session(s)"));
    chartPanel.appendChild(cHead);
    chartPanel.appendChild(renderMetricsSvgChart(met.by_project || []));
    container.appendChild(chartPanel);

    const subPanel = el("section", "panel");
    const sHead = el("div", "panel-head");
    const subTabs = el("div", "subtabs");
    const pendingList = met.pending_sessions || [];
    const ignoredList = met.ignored_sessions || [];
    const auditsList = met.audits || [];
    [
      { id: "sessions", label: "Sessions (" + ((met.records || []).length) + ")" },
      { id: "pending", label: "Pending / Lifecycle (" + pendingList.length + ")" },
      { id: "audits", label: "Audits Agents (" + auditsList.length + ")" }
    ].forEach((st) => {
      subTabs.appendChild(el("button", "btn" + (state.metricsSub === st.id ? " active" : ""), st.label, {
        type: "button", "data-action": "metrics-sub", "data-sub": st.id
      }));
    });
    sHead.appendChild(subTabs);
    if (met.metrics_md_uri) {
      sHead.appendChild(el("button", "btn", "Ouvrir METRICS.md", {
        type: "button", "data-action": "open-file", "data-uri": met.metrics_md_uri
      }));
    }
    subPanel.appendChild(sHead);

    if (state.metricsSub === "sessions") {
      const recs = met.records || [];
      if (!recs.length) {
        subPanel.appendChild(el("div", "empty", "Aucune session correspondante."));
      } else {
        const split = el("div", "split" + (state.sessionTarget ? " with-drawer" : ""));
        const wrap = el("div", "table-wrap");
        const tbl = el("table");
        const thead = el("thead");
        const htr = el("tr");
        ["Label", "Projet", "Coût", "Cache", "Tokens", "Date"].forEach((lbl, idx) => {
          htr.appendChild(el("th", idx >= 2 && idx <= 4 ? "num" : null, lbl));
        });
        thead.appendChild(htr);
        tbl.appendChild(thead);
        const tbody = el("tbody");
        recs.forEach((r) => {
          const target = String(r.detail_slug || r.label || r.conversation_id || "");
          const isSel = state.sessionTarget && state.sessionTarget === target;
          const tr = el("tr", "clickable" + (isSel ? " selected" : ""), null, {
            "data-action": "open-session-detail",
            "data-target": target
          });
          tr.appendChild(el("td", null, String(r.label || r.conversation_id || "—")));
          tr.appendChild(el("td", "mono", String(r.project || "—")));
          tr.appendChild(el("td", "num mono", fmtUsd(metricsRecordCost(r))));
          tr.appendChild(el("td", "num mono", fmtPct(r.cache_hit_rate_pct || 0)));
          tr.appendChild(el("td", "num mono", fmtTok(r.total_tokens || 0)));
          tr.appendChild(el("td", "mono", fmtDate(r.started_at || r.ended_at)));
          tbody.appendChild(tr);
        });
        tbl.appendChild(tbody);
        wrap.appendChild(tbl);
        split.appendChild(wrap);
        if (state.sessionTarget) {
          split.appendChild(renderSessionDetailDrawer());
        }
        subPanel.appendChild(split);
      }
    } else if (state.metricsSub === "pending") {
      subPanel.appendChild(el("div", "notice info", "Vue strictement lecture seule : exécutez archive ou remove sous /gravity-metrics."));
      const capKeys = Object.keys(met.active_captures || {});
      subPanel.appendChild(el("div", "mono", "Captures actives : " + capKeys.length + " · En attente : " + pendingList.length + " · Ignorées : " + ignoredList.length));
      if (!pendingList.length && !ignoredList.length) {
        subPanel.appendChild(el("div", "empty", "Aucune session en attente ou ignorée."));
      } else {
        const wrap = el("div", "table-wrap");
        const tbl = el("table");
        const thead = el("thead");
        const htr = el("tr");
        ["Conversation", "Projet", "État", "Phase / Raison", "Mise à jour"].forEach((lbl) => htr.appendChild(el("th", null, lbl)));
        thead.appendChild(htr);
        tbl.appendChild(thead);
        const tbody = el("tbody");
        pendingList.concat(ignoredList).forEach((item) => {
          const tr = el("tr");
          tr.appendChild(el("td", null, String(item.label || item.conversation_id || "—")));
          tr.appendChild(el("td", "mono", String(item.project || "—")));
          const badgeCell = el("td");
          badgeCell.appendChild(makeBadge(item.ignored ? "Ignorée" : (item.active_capture ? "Capture" : "En attente"), item.ignored ? "" : "warn"));
          tr.appendChild(badgeCell);
          tr.appendChild(el("td", "mono", String(item.ignored_reason || item.current_phase || "—")));
          tr.appendChild(el("td", "mono", fmtDate(item.updated_at || item.ignored_at)));
          tbody.appendChild(tr);
        });
        tbl.appendChild(tbody);
        wrap.appendChild(tbl);
        subPanel.appendChild(wrap);
      }
    } else if (state.metricsSub === "audits") {
      if (met.index_audit) {
        const idxCard = el("div", "notice");
        const row = el("div", "panel-head");
        row.appendChild(el("span", null, "Index Audits Agents : " + (met.index_audit.title || met.index_audit.rel_path) + " (" + (met.index_audit.workspace || "") + ")"));
        if (met.index_audit.uri) {
          row.appendChild(el("button", "btn", "Ouvrir index .md", {
            type: "button", "data-action": "open-file", "data-uri": met.index_audit.uri
          }));
        }
        idxCard.appendChild(row);
        subPanel.appendChild(idxCard);
      }
      if (!auditsList.length) {
        subPanel.appendChild(el("div", "empty", "Aucun audit agent Markdown découvert."));
      } else {
        const wrap = el("div", "table-wrap");
        const tbl = el("table");
        const thead = el("thead");
        const htr = el("tr");
        ["Titre", "Workspace", "Verdict", "Date", "Fichier"].forEach((lbl) => htr.appendChild(el("th", null, lbl)));
        thead.appendChild(htr);
        tbl.appendChild(thead);
        const tbody = el("tbody");
        auditsList.forEach((a) => {
          const tr = el("tr");
          tr.appendChild(el("td", null, String(a.title || a.rel_path || "—")));
          tr.appendChild(el("td", "mono", String(a.workspace || "—")));
          const vCell = el("td");
          vCell.appendChild(makeBadge(a.verdict || "—", a.verdict_tone || ""));
          tr.appendChild(vCell);
          tr.appendChild(el("td", "mono", String(a.date || "—")));
          const actCell = el("td");
          if (a.uri) {
            actCell.appendChild(el("button", "btn", "Ouvrir .md", {
              type: "button", "data-action": "open-file", "data-uri": a.uri
            }));
          }
          tr.appendChild(actCell);
          tbody.appendChild(tr);
        });
        tbl.appendChild(tbody);
        wrap.appendChild(tbl);
        subPanel.appendChild(wrap);
      }
    }
    container.appendChild(subPanel);
  }

  function renderMetricsView(container) {
    const met = state.metrics;
    const bar = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Metrics & Audits Agents (lecture seule)"));

    const ctrls = el("div", "actions-row");
    const projSel = el("select", "select", null, { id: "g-metrics-project" });
    projSel.appendChild(el("option", null, "Tous les projets", { value: "" }));
    ((met && met.projects) || []).forEach((p) => {
      const opt = el("option", null, p, { value: p });
      if (p === state.metricsProject) opt.selected = true;
      projSel.appendChild(opt);
    });
    ctrls.appendChild(projSel);

    const searchInput = el("input", "input", null, {
      id: "g-metrics-q",
      type: "search",
      placeholder: "Rechercher label, modèle, ID...",
      value: state.metricsQ
    });
    searchInput.value = state.metricsQ;
    ctrls.appendChild(searchInput);

    ["2026", "2027"].forEach((t) => {
      ctrls.appendChild(el("button", "btn" + (state.metricsTariff === t ? " active" : ""), "Tarif " + t, {
        type: "button", "data-action": "set-tariff", "data-tariff": t
      }));
    });
    head.appendChild(ctrls);
    bar.appendChild(head);
    container.appendChild(bar);

    const body = el("div", null, null, { id: "g-metrics-content" });
    body.style.display = "flex";
    body.style.flexDirection = "column";
    body.style.gap = "10px";
    if (!met) {
      body.appendChild(el("div", "empty", "Chargement des métriques..."));
    } else {
      renderMetricsContent(body);
    }
    container.appendChild(body);
  }

  function renderModuleView(container, tab) {
    const modId = (tab && tab.module_id) || state.activeTab;
    const panel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Module OCP : " + ((tab && tab.display_name) || modId)));
    const info = state.moduleCache[modId];
    if (info && info.found) {
      head.appendChild(makeBadge(info.valid ? "Contrat valide" : "Contrat invalide", info.valid ? "ok" : "error"));
    }
    panel.appendChild(head);

    if (state.moduleLoading[modId]) {
      panel.appendChild(el("div", "empty", "Chargement du contrat module..."));
      container.appendChild(panel);
      return;
    }
    if (!info) {
      panel.appendChild(el("div", "empty", "Sélectionnez ou rafraîchissez cet onglet pour inspecter le module."));
      container.appendChild(panel);
      return;
    }
    if (!info.found) {
      panel.appendChild(el("div", "notice warn", info.error || "Module introuvable."));
      container.appendChild(panel);
      return;
    }

    const storage = info.storage || {};
    const kv = el("div", "kv-grid");
    [
      ["Plugin", (info.plugin_name || "—") + " v" + (info.version || "?")],
      ["Rôle", info.role || "—"],
      ["Commandes", (info.commands || []).join(", ") || "—"],
      ["Capacités", (info.capabilities || []).join(", ") || "—"],
      ["UI", JSON.stringify(info.ui || {})],
      ["Stockage subdir", (storage.subdir || "—") + (storage.env_override ? " (" + storage.env_override + ")" : "")],
      ["Chemin résolu", (storage.resolved_home || "—") + (storage.exists ? " [présent]" : " [absent]")]
    ].forEach(([k, v]) => {
      kv.appendChild(el("div", "kv-k", k));
      kv.appendChild(el("div", "mono", v));
    });
    panel.appendChild(kv);

    if (Array.isArray(info.errors) && info.errors.length) {
      info.errors.forEach((err) => panel.appendChild(el("div", "notice warn", err)));
    }

    panel.appendChild(el("div", "panel-title", "Entrées superficielles (top_entries)"));
    const entries = info.top_entries || [];
    if (!entries.length) {
      panel.appendChild(el("div", "empty", "Aucune entrée dans le répertoire du module."));
    } else {
      if (info.top_entries_truncated) {
        panel.appendChild(el("div", "notice", "Liste bornée aux 25 premières entrées."));
      }
      const wrap = el("div", "table-wrap");
      const tbl = el("table");
      const thead = el("thead");
      const htr = el("tr");
      ["Nom", "Type", "Taille"].forEach((lbl, idx) => htr.appendChild(el("th", idx === 2 ? "num" : null, lbl)));
      thead.appendChild(htr);
      tbl.appendChild(thead);
      const tbody = el("tbody");
      entries.forEach((e) => {
        const tr = el("tr");
        tr.appendChild(el("td", "mono", e.name || "—"));
        tr.appendChild(el("td", null, e.kind || "—"));
        tr.appendChild(el("td", "num mono", fmtBytes(e.size_bytes)));
        tbody.appendChild(tr);
      });
      tbl.appendChild(tbody);
      wrap.appendChild(tbl);
      panel.appendChild(wrap);
    }
    container.appendChild(panel);
  }
"""

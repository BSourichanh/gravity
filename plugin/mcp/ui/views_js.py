"""Pure DOM and SVG view renderers for Gravity MCP App (100% stdlib, zero innerHTML)."""

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

  function makeKpiCard(label, value, sub, tone) {
    const card = el("div", "kpi-card" + (tone ? " " + tone : ""));
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

  function _makeTable(headers, rows, numCols) {
    const wrap = el("div", "table-wrap"), tbl = el("table"), thead = el("thead"), htr = el("tr");
    const numSet = new Set(numCols || []);
    headers.forEach((lbl, idx) => htr.appendChild(el("th", numSet.has(idx) ? "num" : null, lbl)));
    thead.appendChild(htr);
    tbl.appendChild(thead);
    const tbody = el("tbody");
    rows.forEach((r) => tbody.appendChild(r));
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);
    return wrap;
  }

  function _statusTone(raw) {
    const c = String(raw || "").trim().toLowerCase();
    if (c === "done" || c === "completed" || c === "ready" || c === "validated" || c === "ok" || c === "pass") return "ok";
    if (c === "in_progress" || c === "running" || c === "active") return "info";
    if (c === "blocked" || c === "error" || c === "failed" || c === "fail") return "error";
    if (c === "draft" || c === "pending" || c === "backlog" || c === "warn") return "warn";
    return "";
  }

  function renderOverviewView(container) {
    const ov = state.overview;
    if (!ov) {
      container.appendChild(el("div", "empty", "Chargement de la vue Système..."));
      return;
    }
    const doctor = ov.doctor || {};
    const status = String(doctor.status || "unknown");
    const statusTone = status === "ok" ? "ok" : (status === "error" ? "error" : "warn");

    const summaryPanel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Système — Diagnostic Core & Environnement"));
    head.appendChild(makeBadge("doctor: " + status.toUpperCase(), statusTone));
    summaryPanel.appendChild(head);

    const kpis = el("div", "kpi-strip");
    kpis.appendChild(makeKpiCard("Modules", String(doctor.module_count || 0), (doctor.valid_count || 0) + " valide(s)"));
    kpis.appendChild(makeKpiCard("Registre", doctor.initialized ? "Initialisé" : "Découverte RO", ov.registry_source || "—"));
    kpis.appendChild(makeKpiCard("Anomalies", String((doctor.invalid_count || 0) + (doctor.duplicate_ids || []).length), "invalides / doublons"));
    kpis.appendChild(makeKpiCard("Dossiers legacy", String(doctor.legacy_count || 0), "lecture seule"));
    summaryPanel.appendChild(kpis);

    const kv = el("div", "kv-grid");
    [["$GRAVITY_HOME", ov.gravity_home || "—"], ["Registre", ov.registry_path || "—"]].forEach(([k, v]) => {
      kv.appendChild(el("div", "kv-k", k));
      kv.appendChild(el("div", "mono", v));
    });
    summaryPanel.appendChild(kv);

    (ov.warnings || doctor.warnings || []).forEach((w) => summaryPanel.appendChild(el("div", "notice warn", w)));
    container.appendChild(summaryPanel);

    const modsPanel = el("section", "panel");
    const mHead = el("div", "panel-head");
    const modules = ov.modules || [];
    mHead.appendChild(el("div", "panel-title", "Modules Gravity découverts"));
    mHead.appendChild(el("span", "mono", modules.length + " module(s)"));
    modsPanel.appendChild(mHead);

    if (!modules.length) {
      modsPanel.appendChild(el("div", "empty", "Aucun module Gravity détecté."));
    } else {
      const grid = el("div", "grid-cards");
      modules.forEach((mod) => {
        const modId = String(mod.id || "");
        const targetTab = tabForModule(modId);
        const card = el("button", "mod-card", null, {
          type: "button", "data-action": "select-tab", "data-tab": targetTab ? targetTab.id : "overview"
        });
        const top = el("div", "mod-top");
        top.appendChild(el("span", "mod-name", mod.display_name || mod.plugin_name || modId));
        top.appendChild(makeBadge(mod.valid ? "OK" : "INVALID", mod.valid ? "ok" : "error"));
        card.appendChild(top);

        const meta = el("div", "pill-list");
        meta.appendChild(el("span", "pill", "id=" + modId));
        if (mod.version) meta.appendChild(el("span", "pill", "v" + mod.version));
        meta.appendChild(el("span", "pill", "ui:" + ((mod.ui && mod.ui.mode) ? mod.ui.mode : "none")));
        meta.appendChild(el("span", "pill", mod.home_exists ? "home:ok" : "home:absent"));
        card.appendChild(meta);
        if (mod.resolved_home) card.appendChild(el("div", "mono", mod.resolved_home));
        if (Array.isArray(mod.commands) && mod.commands.length) card.appendChild(el("div", "mono", mod.commands.join(" · ")));
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
      legPanel.appendChild(el("div", "notice", "Aucune modification automatique. Utilisez /gravity doctor (--migration-plan)."));
      legPanel.appendChild(_makeTable(["Nom", "Module cible", "Chemin"], legacy.map((lh) => {
        const tr = el("tr");
        tr.appendChild(el("td", null, lh.name || "—"));
        tr.appendChild(el("td", "mono", lh.target_module || "—"));
        tr.appendChild(el("td", "mono", lh.path || "—"));
        return tr;
      })));
      container.appendChild(legPanel);
    }
  }

  function renderMetricsView(container) {
    if (typeof renderMetricsUnifiedView === "function") {
      renderMetricsUnifiedView(container);
    } else {
      container.appendChild(el("div", "empty", "Vue Historique indisponible."));
    }
  }

  function renderModuleView(container, tab) {
    const modId = (tab && tab.module_id) || state.activeTab;
    const panel = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Module OCP : " + ((tab && tab.display_name) || modId)));
    const info = state.moduleCache[modId];
    if (info && info.found) head.appendChild(makeBadge(info.valid ? "Contrat valide" : "Contrat invalide", info.valid ? "ok" : "error"));
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

    (info.errors || []).forEach((err) => panel.appendChild(el("div", "notice warn", err)));

    panel.appendChild(el("div", "panel-title", "Entrées superficielles (top_entries)"));
    const entries = info.top_entries || [];
    if (!entries.length) {
      panel.appendChild(el("div", "empty", "Aucune entrée dans le répertoire du module."));
    } else {
      if (info.top_entries_truncated) panel.appendChild(el("div", "notice", "Liste bornée aux 25 premières entrées."));
      panel.appendChild(_makeTable(["Nom", "Type", "Taille"], entries.map((e) => {
        const tr = el("tr");
        tr.appendChild(el("td", "mono", e.name || "—"));
        tr.appendChild(el("td", null, e.kind || "—"));
        tr.appendChild(el("td", "num mono", fmtBytes(e.size_bytes)));
        return tr;
      }), [2]));
    }
    container.appendChild(panel);
  }

  function _renderProjectCards(subPanel, projects) {
    if (!projects.length) {
      subPanel.appendChild(el("div", "empty", "Aucun projet suivi dans projects.json."));
      return;
    }
    const grid = el("div", "proj-grid");
    projects.forEach((p) => {
      const card = el("article", "agent-card");
      const head = el("div", "agent-head");
      const tWrap = el("div", null);
      tWrap.appendChild(el("div", "agent-role", p.name || p.id || "Projet"));
      tWrap.appendChild(el("div", "mono", (p.id || "—") + (p.path ? " · " + p.path : "")));
      head.appendChild(tWrap);
      const bRow = el("div", "actions-row");
      if (p.role) bRow.appendChild(makeBadge(p.role, "info"));
      if (p.card_bytes) bRow.appendChild(makeBadge(fmtBytes(p.card_bytes), p.over_budget ? "warn" : "ok"));
      head.appendChild(bRow);
      card.appendChild(head);

      const pills = el("div", "pill-list");
      pills.appendChild(el("span", "pill", "main: " + (p.main_branch || "main")));
      pills.appendChild(el("span", "pill", "dev: " + (p.default_dev_branch || p.dev_branch || "dev")));
      if (p.release_main) pills.appendChild(el("span", "pill", "rel: " + p.release_main));
      if (p.installed_version) pills.appendChild(el("span", "pill", "inst: " + p.installed_version));
      if (p.dev_status) pills.appendChild(makeBadge("dev: " + p.dev_status, /ahead|wip/i.test(p.dev_status) ? "info" : ""));
      if (p.wip_status) {
        const cleanWip = /^(aucun|clean|propre|0|none|-|—)$/i.test(String(p.wip_status).trim());
        pills.appendChild(makeBadge("WIP: " + p.wip_status, cleanWip ? "ok" : "warn"));
      }
      card.appendChild(pills);

      const stats = el("div", "agent-stats");
      stats.appendChild(el("span", "num", fmtInt(p.specs_count || 0) + " spec(s)"));
      stats.appendChild(el("span", "num", fmtInt(p.tasks_count || 0) + " task(s)"));
      stats.appendChild(el("span", "num", fmtInt(p.audits_count || 0) + " audit(s)"));
      card.appendChild(stats);

      const acts = el("div", "actions-row");
      if (p.card_uri) {
        acts.appendChild(el("button", "btn btn-sm", "Ouvrir fiche", {
          type: "button", "data-action": "open-file", "data-uri": p.card_uri
        }));
      }
      if (p.id) {
        acts.appendChild(el("button", "btn btn-sm btn-primary", "Voir sessions", {
          type: "button", "data-action": "nav-history", "data-project": String(p.id)
        }));
      }
      card.appendChild(acts);
      grid.appendChild(card);
    });
    subPanel.appendChild(grid);
  }

  function _renderWavesAndTasks(subPanel, tasks, wavesSummary) {
    if (!tasks.length) {
      subPanel.appendChild(el("div", "empty", "Aucune task active dans tasks/."));
      return;
    }
    const groups = new Map();
    tasks.forEach((t) => {
      const k = (typeof t.wave === "number" && isFinite(t.wave)) ? t.wave : null;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(t);
    });
    const keys = Array.from(groups.keys()).sort((a, b) => {
      if (a === null) return 1;
      if (b === null) return -1;
      return a - b;
    });
    const wsByNum = new Map();
    ((wavesSummary && wavesSummary.waves) || []).forEach((w) => wsByNum.set(w.wave == null ? null : w.wave, w));

    keys.forEach((wKey) => {
      const wTasks = groups.get(wKey) || [];
      const wMeta = wsByNum.get(wKey) || {};
      const box = el("div", "wave-group");
      const wHead = el("div", "panel-head");
      wHead.appendChild(el("div", "panel-title", wKey === null ? "Tasks hors vague" : ("Vague " + wKey)));
      const wBadges = el("div", "actions-row");
      wBadges.appendChild(makeBadge(wTasks.length + " task(s)", "info"));
      const stCounts = wMeta.status_counts || {};
      Object.entries(stCounts).forEach(([st, cnt]) => {
        wBadges.appendChild(makeBadge(st + ": " + cnt, _statusTone(st)));
      });
      wHead.appendChild(wBadges);
      box.appendChild(wHead);

      const grid = el("div", "proj-grid");
      wTasks.forEach((t) => {
        const card = el("article", "agent-card");
        const cHead = el("div", "agent-head");
        cHead.appendChild(el("div", "agent-role", t.title || t.filename || "—"));
        cHead.appendChild(makeBadge(t.status || t.status_code || "unknown", _statusTone(t.status_code || t.status)));
        card.appendChild(cHead);

        const pills = el("div", "pill-list");
        if (t.target_project) pills.appendChild(makeBadge(t.target_project, "code"));
        if (t.workflow_profile) pills.appendChild(el("span", "pill", "profil: " + t.workflow_profile));
        if (t.expected_branch) pills.appendChild(el("span", "pill", "branche: " + t.expected_branch));
        if (t.date) pills.appendChild(el("span", "pill", t.date));
        if (Array.isArray(t.dependencies) && t.dependencies.length) {
          pills.appendChild(el("span", "pill", "déps: " + t.dependencies.join(", ")));
        }
        if (t.spec_source) pills.appendChild(el("span", "pill", "spec: " + t.spec_source));
        card.appendChild(pills);

        if (t.uri) {
          const acts = el("div", "actions-row");
          acts.appendChild(el("button", "btn btn-sm", "Ouvrir .md", {
            type: "button", "data-action": "open-file", "data-uri": t.uri
          }));
          card.appendChild(acts);
        }
        grid.appendChild(card);
      });
      box.appendChild(grid);
      subPanel.appendChild(box);
    });
  }

  function renderArchitectView(container) {
    const arch = state.architect;
    const bar = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Projets & Atelier Architect (lecture seule)"));

    const ctrls = el("div", "actions-row");
    const ateliers = (arch && Array.isArray(arch.ateliers)) ? arch.ateliers : [];
    if (ateliers.length) {
      const archSel = el("select", "select", null, { id: "g-arch-ws", "aria-label": "Atelier Architect" });
      const activeRoot = (arch && arch.atelier_root) || state.selectedAtelier || "";
      ateliers.forEach((a) => {
        const val = String(a.workspace_path || "");
        if (!val) return;
        const lbl = a.workspace_name ? (a.workspace_name + " — " + val) : val;
        const opt = el("option", null, lbl, { value: val });
        if (val === activeRoot || val === state.selectedAtelier) opt.selected = true;
        archSel.appendChild(opt);
      });
      if (!arch.available && state.selectedAtelier && !ateliers.some((a) => String(a.workspace_path || "") === state.selectedAtelier)) {
        const invalidOpt = el("option", null, state.selectedAtelier + " (invalide)", { value: state.selectedAtelier });
        invalidOpt.selected = true;
        archSel.appendChild(invalidOpt);
      }
      ctrls.appendChild(archSel);
    }
    if (arch && arch.discovery_source) ctrls.appendChild(makeBadge("source: " + arch.discovery_source, "info"));
    if (arch && arch.ecosystem && arch.ecosystem.uri) {
      ctrls.appendChild(el("button", "btn btn-sm", "Ouvrir ECOSYSTEM.md", {
        type: "button", "data-action": "open-file", "data-uri": arch.ecosystem.uri
      }));
    }
    if (arch && arch.delta && arch.delta.uri) {
      ctrls.appendChild(el("button", "btn btn-sm", "Ouvrir delta.md", {
        type: "button", "data-action": "open-file", "data-uri": arch.delta.uri
      }));
    }
    ctrls.appendChild(el("button", "btn btn-sm", "Historique", { type: "button", "data-action": "nav-history" }));
    head.appendChild(ctrls);
    bar.appendChild(head);
    if (arch && arch.atelier_root) bar.appendChild(el("div", "mono", "Atelier : " + arch.atelier_root));
    container.appendChild(bar);

    if (!arch) {
      container.appendChild(el("div", "empty", "Chargement de l'état Projets..."));
      return;
    }
    (arch.warnings || []).forEach((w) => container.appendChild(el("div", "notice warn", w)));
    if (!arch.available) {
      const emp = el("section", "panel");
      emp.appendChild(el("div", "empty", "Aucun atelier Gravity Architect (ECOSYSTEM.md / projects.json) détecté."));
      emp.appendChild(el("div", "notice info", "Enregistrez un atelier via /gravity-architect init ou /gravity-architect sync."));
      container.appendChild(emp);
      return;
    }

    const eco = arch.ecosystem || {}, delta = arch.delta || {};
    const projects = arch.projects || [], specs = arch.specs || [], tasks = arch.tasks || [], audits = arch.audits || [];
    const wavesSummary = arch.waves_summary || {};
    const allAlerts = (eco.alerts || []).concat(delta.hygiene_alerts || []);

    const kpiPanel = el("section", "panel");
    const kpiStrip = el("div", "kpi-strip");
    kpiStrip.appendChild(makeKpiCard("ECOSYSTEM.md", eco.exists ? fmtBytes(eco.size_bytes) : "Absent",
      eco.budget_bytes ? ("budget " + fmtBytes(eco.budget_bytes) + (eco.over_budget ? " [DÉPASSÉ]" : "")) : fmtDate(eco.updated_at),
      eco.over_budget ? "warn" : ""));
    kpiStrip.appendChild(makeKpiCard("delta.md", delta.editorial_status || "Absent", delta.date ? fmtDate(delta.date) : "aucune synchro"));
    kpiStrip.appendChild(makeKpiCard("Projets & Veilles", fmtInt(projects.length) + " projet(s)", fmtInt(arch.watches_count || 0) + " veille(s)"));
    kpiStrip.appendChild(makeKpiCard("Vagues & Tasks", fmtInt(wavesSummary.waves_count || 0) + " vague(s)",
      fmtInt(tasks.length) + " task(s) · " + fmtInt(specs.length) + " spec(s)"));
    kpiStrip.appendChild(makeKpiCard("Archivés", fmtInt((arch.archived_specs_count || 0) + (arch.archived_tasks_count || 0)),
      fmtInt(arch.archived_specs_count || 0) + " specs · " + fmtInt(arch.archived_tasks_count || 0) + " tasks"));
    kpiStrip.appendChild(makeKpiCard("Audits Code", fmtInt(audits.length), "audits/code/ uniquement"));
    kpiPanel.appendChild(kpiStrip);
    allAlerts.slice(0, 6).forEach((al) => kpiPanel.appendChild(el("div", "notice warn", al)));
    container.appendChild(kpiPanel);

    if (arch.truncated) container.appendChild(el("div", "notice warn", "Réponse bornée sous le plafond de 450 Ko."));

    const sub = state.architectSub === "artifacts" ? "waves" : (state.architectSub || "projects");
    const subPanel = el("section", "panel");
    const sHead = el("div", "panel-head");
    const subTabs = el("div", "subtabs");
    [
      { id: "projects", label: "Projets (" + projects.length + ")" },
      { id: "waves", label: "Vagues & Tasks (" + tasks.length + ")" },
      { id: "specs", label: "Spécifications (" + specs.length + ")" },
      { id: "audits", label: "Audits Code (" + audits.length + ")" }
    ].forEach((st) => {
      subTabs.appendChild(el("button", "btn" + (sub === st.id ? " active" : ""), st.label, {
        type: "button", "data-action": "architect-sub", "data-sub": st.id
      }));
    });
    sHead.appendChild(subTabs);
    subPanel.appendChild(sHead);

    if (sub === "waves") {
      _renderWavesAndTasks(subPanel, tasks, wavesSummary);
    } else if (sub === "specs") {
      if (!specs.length) {
        subPanel.appendChild(el("div", "empty", "Aucune spécification active dans specs/."));
      } else {
        subPanel.appendChild(_makeTable(["Titre", "Cible", "Statut", "Date", "Taille", "Fichier"], specs.map((s) => {
          const tr = el("tr");
          tr.appendChild(el("td", null, s.title || s.filename || "—"));
          tr.appendChild(el("td", "mono", s.target_project || "—"));
          const stCell = el("td");
          stCell.appendChild(makeBadge(s.status || s.status_code || "—", _statusTone(s.status_code || s.status)));
          tr.appendChild(stCell);
          tr.appendChild(el("td", "mono", s.date || "—"));
          tr.appendChild(el("td", "num mono", fmtBytes(s.size_bytes)));
          const fCell = el("td");
          if (s.uri) fCell.appendChild(el("button", "btn btn-sm", "Ouvrir .md", { type: "button", "data-action": "open-file", "data-uri": s.uri }));
          tr.appendChild(fCell);
          return tr;
        }), [4]));
      }
    } else if (sub === "audits") {
      subPanel.appendChild(el("div", "notice info", "Périmètre strict audits/code/ uniquement (audits/agents/ exclu)."));
      if (arch.index_audit) {
        const idxCard = el("div", "notice");
        const row = el("div", "panel-head");
        row.appendChild(el("span", null, "Index Audits Code : " + (arch.index_audit.title || arch.index_audit.rel_path)));
        if (arch.index_audit.uri) {
          row.appendChild(el("button", "btn btn-sm", "Ouvrir index .md", {
            type: "button", "data-action": "open-file", "data-uri": arch.index_audit.uri
          }));
        }
        idxCard.appendChild(row);
        subPanel.appendChild(idxCard);
      }
      if (!audits.length) {
        subPanel.appendChild(el("div", "empty", "Aucun audit code découvert dans audits/code/."));
      } else {
        subPanel.appendChild(_makeTable(["Titre", "Cible", "Verdict", "Date", "Taille", "Fichier"], audits.map((a) => {
          const tr = el("tr");
          tr.appendChild(el("td", null, a.title || a.rel_path || "—"));
          tr.appendChild(el("td", "mono", a.target || "—"));
          const vCell = el("td");
          vCell.appendChild(makeBadge(a.verdict || "—", a.verdict_tone || ""));
          tr.appendChild(vCell);
          tr.appendChild(el("td", "mono", a.date || "—"));
          tr.appendChild(el("td", "num mono", fmtBytes(a.size_bytes)));
          const actCell = el("td");
          if (a.uri) actCell.appendChild(el("button", "btn btn-sm", "Ouvrir .md", { type: "button", "data-action": "open-file", "data-uri": a.uri }));
          tr.appendChild(actCell);
          return tr;
        }), [4]));
      }
    } else {
      _renderProjectCards(subPanel, projects);
    }
    container.appendChild(subPanel);
  }
"""

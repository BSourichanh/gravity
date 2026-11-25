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
    if (typeof renderLiveView === "function") {
      renderLiveView(container, state.live, state.liveUi, {});
    }
  }

  function renderMetricsView(container) {
    if (typeof renderMetricsUnifiedView === "function") {
      renderMetricsUnifiedView(container);
    } else {
      container.appendChild(el("div", "empty", "Vue Métriques indisponible."));
    }
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

  function renderArchitectSvgChart(arch) {
    const box = el("div", "svg-box");
    const rows = [
      { label: "Projets", count: (arch.projects || []).length, color: "var(--g-c1)" },
      { label: "Specs actives", count: (arch.specs || []).length, color: "var(--g-c2)" },
      { label: "Tasks", count: (arch.tasks || []).length, color: "var(--g-c4)" },
      { label: "Audits Code", count: (arch.audits || []).length, color: "var(--g-c3)" }
    ];
    const maxV = Math.max.apply(null, rows.map((r) => r.count).concat([1]));
    const width = 640;
    const rowH = 24;
    const padT = 8;
    const height = padT + rows.length * rowH + 8;
    const lblW = 120;
    const valW = 70;
    const barMaxW = width - lblW - valW - 16;

    const svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": "Inventaire atelier Architect" });
    rows.forEach((r, idx) => {
      const y = padT + idx * rowH;
      const barW = r.count > 0 ? Math.max(4, (r.count / maxV) * barMaxW) : 0;
      const g = svgEl("g");
      g.appendChild(svgEl("title", null, r.label + ": " + fmtInt(r.count)));
      g.appendChild(svgEl("text", {
        x: 4, y: y + 15, fill: "var(--g-fg)", "font-size": 11, "font-family": "var(--g-font)"
      }, r.label));
      g.appendChild(svgEl("rect", {
        x: lblW, y: y + 4, width: barMaxW, height: 13, rx: 4, fill: "var(--g-muted)"
      }));
      if (barW > 0) {
        g.appendChild(svgEl("rect", {
          x: lblW, y: y + 4, width: barW.toFixed(1), height: 13, rx: 4, fill: r.color
        }));
      }
      g.appendChild(svgEl("text", {
        x: lblW + barMaxW + 8, y: y + 15, fill: "var(--g-fg-sec)", "font-size": 11, "font-family": "var(--g-mono)"
      }, fmtInt(r.count)));
      svg.appendChild(g);
    });
    box.appendChild(svg);
    return box;
  }

  function renderArchitectView(container) {
    const arch = state.architect;
    const bar = el("section", "panel");
    const head = el("div", "panel-head");
    head.appendChild(el("div", "panel-title", "Architect — Atelier Hot / Cold (lecture seule)"));

    const ctrls = el("div", "actions-row");
    const ateliers = (arch && Array.isArray(arch.ateliers)) ? arch.ateliers : [];
    if (ateliers.length) {
      const archSel = el("select", "select", null, { id: "g-arch-ws" });
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
    if (arch && arch.discovery_source) {
      ctrls.appendChild(makeBadge("source: " + arch.discovery_source, "info"));
    }
    if (arch && arch.ecosystem && arch.ecosystem.uri) {
      ctrls.appendChild(el("button", "btn", "Ouvrir ECOSYSTEM.md", {
        type: "button", "data-action": "open-file", "data-uri": arch.ecosystem.uri
      }));
    }
    if (arch && arch.delta && arch.delta.uri) {
      ctrls.appendChild(el("button", "btn", "Ouvrir delta.md", {
        type: "button", "data-action": "open-file", "data-uri": arch.delta.uri
      }));
    }
    head.appendChild(ctrls);
    bar.appendChild(head);
    if (arch && arch.atelier_root) {
      bar.appendChild(el("div", "mono", "Atelier : " + arch.atelier_root));
    }
    container.appendChild(bar);

    if (!arch) {
      container.appendChild(el("div", "empty", "Chargement de l'état Architect..."));
      return;
    }

    (arch.warnings || []).forEach((w) => {
      container.appendChild(el("div", "notice warn", w));
    });

    if (!arch.available) {
      const emp = el("section", "panel");
      emp.appendChild(el("div", "empty", "Aucun atelier Gravity Architect (ECOSYSTEM.md / projects.json) détecté."));
      emp.appendChild(el("div", "notice info", "Enregistrez un atelier via /gravity-architect init ou /gravity-architect sync (ateliers.json), ou définissez GRAVITY_ARCHITECT_WORKSPACE."));
      container.appendChild(emp);
      return;
    }

    const eco = arch.ecosystem || {};
    const delta = arch.delta || {};
    const projects = arch.projects || [];
    const specs = arch.specs || [];
    const tasks = arch.tasks || [];
    const audits = arch.audits || [];
    const allAlerts = (eco.alerts || []).concat(delta.hygiene_alerts || []);

    const kpiPanel = el("section", "panel");
    const kpiGrid = el("div", "grid-kpi");
    kpiGrid.appendChild(makeKpiCard(
      "ECOSYSTEM.md",
      eco.exists ? fmtBytes(eco.size_bytes) : "Absent",
      eco.budget_bytes ? ("budget " + fmtBytes(eco.budget_bytes) + (eco.over_budget ? " [DÉPASSÉ]" : "")) : fmtDate(eco.updated_at)
    ));
    kpiGrid.appendChild(makeKpiCard(
      "delta.md",
      delta.editorial_status || "Absent",
      delta.date ? fmtDate(delta.date) : "aucune synchro"
    ));
    kpiGrid.appendChild(makeKpiCard(
      "Projets & Veilles",
      fmtInt(projects.length) + " projet(s)",
      fmtInt(arch.watches_count || 0) + " veille(s)"
    ));
    kpiGrid.appendChild(makeKpiCard(
      "Specs & Tasks",
      fmtInt(specs.length) + " / " + fmtInt(tasks.length),
      fmtInt(arch.archived_specs_count || 0) + " + " + fmtInt(arch.archived_tasks_count || 0) + " archivé(s)"
    ));
    kpiGrid.appendChild(makeKpiCard(
      "Audits Code",
      fmtInt(audits.length),
      "audits/code/ uniquement"
    ));
    kpiPanel.appendChild(kpiGrid);
    kpiPanel.appendChild(renderArchitectSvgChart(arch));

    if (allAlerts.length) {
      allAlerts.slice(0, 8).forEach((al) => {
        kpiPanel.appendChild(el("div", "notice warn", al));
      });
    } else {
      kpiPanel.appendChild(el("div", "notice info", "Aucune alerte d'hygiène signalée dans ECOSYSTEM.md / delta.md."));
    }
    container.appendChild(kpiPanel);

    if (arch.truncated) {
      container.appendChild(el("div", "notice warn", "Réponse bornée sous le plafond de 450 Ko."));
    }

    const subPanel = el("section", "panel");
    const sHead = el("div", "panel-head");
    const subTabs = el("div", "subtabs");
    [
      { id: "projects", label: "Projets (" + projects.length + ")" },
      { id: "artifacts", label: "Specs & Tasks (" + (specs.length + tasks.length) + ")" },
      { id: "audits", label: "Audits Code (" + audits.length + ")" }
    ].forEach((st) => {
      subTabs.appendChild(el("button", "btn" + (state.architectSub === st.id ? " active" : ""), st.label, {
        type: "button", "data-action": "architect-sub", "data-sub": st.id
      }));
    });
    sHead.appendChild(subTabs);
    subPanel.appendChild(sHead);

    if (state.architectSub === "artifacts") {
      const combined = specs.map((s) => Object.assign({ kind: "spec" }, s)).concat(
        tasks.map((t) => Object.assign({ kind: "task" }, t))
      );
      if (!combined.length) {
        subPanel.appendChild(el("div", "empty", "Aucune spécification ni task active."));
      } else {
        const wrap = el("div", "table-wrap");
        const tbl = el("table");
        const thead = el("thead");
        const htr = el("tr");
        ["Type", "Titre", "Cible", "Statut", "Date", "Fichier"].forEach((lbl) => htr.appendChild(el("th", null, lbl)));
        thead.appendChild(htr);
        tbl.appendChild(thead);
        const tbody = el("tbody");
        combined.forEach((item) => {
          const tr = el("tr");
          const kCell = el("td");
          kCell.appendChild(makeBadge(item.kind, item.kind === "spec" ? "info" : "warn"));
          tr.appendChild(kCell);
          tr.appendChild(el("td", null, item.title || item.filename || "—"));
          tr.appendChild(el("td", "mono", item.target_project || "—"));
          tr.appendChild(el("td", "mono", item.status || "—"));
          tr.appendChild(el("td", "mono", item.date || "—"));
          const fCell = el("td");
          if (item.uri) {
            fCell.appendChild(el("button", "btn", "Ouvrir .md", {
              type: "button", "data-action": "open-file", "data-uri": item.uri
            }));
          }
          tr.appendChild(fCell);
          tbody.appendChild(tr);
        });
        tbl.appendChild(tbody);
        wrap.appendChild(tbl);
        subPanel.appendChild(wrap);
      }
    } else if (state.architectSub === "audits") {
      subPanel.appendChild(el("div", "notice info", "Périmètre strict audits/code/ uniquement (audits/agents/ exclu)."));
      if (arch.index_audit) {
        const idxCard = el("div", "notice");
        const row = el("div", "panel-head");
        row.appendChild(el("span", null, "Index Audits Code : " + (arch.index_audit.title || arch.index_audit.rel_path)));
        if (arch.index_audit.uri) {
          row.appendChild(el("button", "btn", "Ouvrir index .md", {
            type: "button", "data-action": "open-file", "data-uri": arch.index_audit.uri
          }));
        }
        idxCard.appendChild(row);
        subPanel.appendChild(idxCard);
      }
      if (!audits.length) {
        subPanel.appendChild(el("div", "empty", "Aucun audit code découvert dans audits/code/."));
      } else {
        const wrap = el("div", "table-wrap");
        const tbl = el("table");
        const thead = el("thead");
        const htr = el("tr");
        ["Titre", "Cible", "Verdict", "Date", "Taille", "Fichier"].forEach((lbl, idx) => {
          htr.appendChild(el("th", idx === 4 ? "num" : null, lbl));
        });
        thead.appendChild(htr);
        tbl.appendChild(thead);
        const tbody = el("tbody");
        audits.forEach((a) => {
          const tr = el("tr");
          tr.appendChild(el("td", null, a.title || a.rel_path || "—"));
          tr.appendChild(el("td", "mono", a.target || "—"));
          const vCell = el("td");
          vCell.appendChild(makeBadge(a.verdict || "—", a.verdict_tone || ""));
          tr.appendChild(vCell);
          tr.appendChild(el("td", "mono", a.date || "—"));
          tr.appendChild(el("td", "num mono", fmtBytes(a.size_bytes)));
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
    } else {
      if (!projects.length) {
        subPanel.appendChild(el("div", "empty", "Aucun projet suivi dans projects.json."));
      } else {
        const wrap = el("div", "table-wrap");
        const tbl = el("table");
        const thead = el("thead");
        const htr = el("tr");
        ["ID", "Nom", "Branches", "Chemin", "Fiche", "Action"].forEach((lbl) => htr.appendChild(el("th", null, lbl)));
        thead.appendChild(htr);
        tbl.appendChild(thead);
        const tbody = el("tbody");
        projects.forEach((p) => {
          const tr = el("tr");
          tr.appendChild(el("td", "mono", p.id || "—"));
          tr.appendChild(el("td", null, p.name || "—"));
          tr.appendChild(el("td", "mono", (p.main_branch || "main") + " / " + (p.dev_branch || "dev")));
          tr.appendChild(el("td", "mono", p.path || "—"));
          const cardCell = el("td");
          if (p.card_bytes) {
            cardCell.appendChild(makeBadge(fmtBytes(p.card_bytes), p.over_budget ? "warn" : "ok"));
          } else {
            cardCell.appendChild(el("span", "mono", "—"));
          }
          tr.appendChild(cardCell);
          const actCell = el("td");
          if (p.card_uri) {
            actCell.appendChild(el("button", "btn", "Ouvrir .md", {
              type: "button", "data-action": "open-file", "data-uri": p.card_uri
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
"""

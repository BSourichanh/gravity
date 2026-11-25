"""Reusable pure DOM/SVG chart components and French formatters (100% stdlib, zero innerHTML)."""

from __future__ import annotations

CHARTS_JS = r"""
  const CTX_WARN_TOKENS = 128000;
  const CTX_CRIT_TOKENS = 200000;

  function fmtTokens(n, withUnit) {
    const v = Math.max(0, Number(n) || 0);
    let txt = "";
    if (v >= 1000000) {
      txt = (v / 1000000).toFixed(1).replace(".", ",") + " M";
    } else if (v >= 1000) {
      txt = Math.round(v / 1000) + " k";
    } else {
      txt = String(Math.round(v));
    }
    return withUnit ? txt + " tokens" : txt;
  }

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined || seconds === "") return "—";
    const num = Number(seconds);
    if (!isFinite(num) || num < 0) return "—";
    const s = Math.round(num);
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    const rs = s % 60;
    if (m < 60) return m + " min" + (rs ? " " + String(rs).padStart(2, "0") + " s" : "");
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return h + " h" + (rm ? " " + String(rm).padStart(2, "0") + " min" : "");
  }

  function fmtPct(n) {
    const v = Number(n);
    if (!isFinite(v)) return "0,0 %";
    return v.toFixed(1).replace(".", ",") + " %";
  }

  function fmtLatency(ms) {
    if (ms === null || ms === undefined || ms === "") return "—";
    const v = Number(ms);
    if (!isFinite(v) || v < 0) return "—";
    if (v >= 1000) return (v / 1000).toFixed(1).replace(".", ",") + " s";
    return Math.round(v) + " ms";
  }

  function fmtRelativeTime(rawIso, nowMs) {
    if (!rawIso) return "à l'instant";
    const t = Date.parse(String(rawIso));
    if (!isFinite(t)) return fmtDate(rawIso);
    const ref = typeof nowMs === "number" ? nowMs : Date.now();
    const diffS = Math.max(0, Math.round((ref - t) / 1000));
    if (diffS < 10) return "à l'instant";
    if (diffS < 60) return "il y a " + diffS + " s";
    if (diffS < 3600) return "il y a " + Math.floor(diffS / 60) + " min";
    return "il y a " + Math.floor(diffS / 3600) + " h";
  }

  function renderWorkspaceKindBadge(kind) {
    const isAtelier = String(kind || "").toLowerCase() === "atelier";
    return makeBadge(isAtelier ? "Atelier" : "Code", isAtelier ? "atelier" : "code");
  }

  function renderStatusBadge(status) {
    const st = String(status || "done").toLowerCase();
    if (st === "active") return makeBadge("Actif", "ok");
    if (st === "waiting") return makeBadge("En attente", "warn");
    if (st === "error") return makeBadge("Erreur", "error");
    return makeBadge("Terminé", "");
  }

  function renderSparkline(values, opts) {
    const pts = (Array.isArray(values) ? values : []).map((v) => Number(v)).filter((v) => isFinite(v));
    if (pts.length < 2) return null;
    const o = opts || {};
    const w = 76;
    const h = 22;
    const pad = 2;
    const minV = Math.min.apply(null, pts);
    const maxV = Math.max.apply(null, pts);
    const span = maxV - minV || 1;
    const coords = pts.map((v, i) => {
      const x = pad + (i / (pts.length - 1)) * (w - pad * 2);
      const y = h - pad - ((v - minV) / span) * (h - pad * 2);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    const color = o.color || "var(--g-accent)";
    const svg = svgEl("svg", {
      class: "sparkline",
      viewBox: "0 0 " + w + " " + h,
      role: "img",
      "aria-label": o.label || "Tendance"
    });
    svg.appendChild(svgEl("polyline", {
      fill: "none",
      stroke: color,
      "stroke-width": "1.6",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      points: coords.join(" ")
    }));
    const last = coords[coords.length - 1].split(",");
    svg.appendChild(svgEl("circle", { cx: last[0], cy: last[1], r: "2.2", fill: color }));
    return svg;
  }

  function renderContextGauge(currentTokens, maxTokens, opts) {
    const o = opts || {};
    const cur = Math.max(0, Number(currentTokens) || 0);
    const peak = Math.max(cur, Number(maxTokens) || 0);
    const limit = Math.max(CTX_CRIT_TOKENS, Number(o.limit) || CTX_CRIT_TOKENS);
    const refVal = cur > 0 ? cur : peak;
    const pct = Math.min(100, Math.round((refVal / limit) * 100));
    const level = refVal > CTX_CRIT_TOKENS ? "crit" : (refVal > CTX_WARN_TOKENS ? "warn" : "ok");

    const wrap = el("div", "ctx-gauge");
    const head = el("div", "ctx-gauge-head");
    const lblText = o.label || "Contexte";
    const rightTxt = fmtTokens(cur) + (peak > cur ? " (pic " + fmtTokens(peak) + ")" : "");
    head.appendChild(el("span", null, lblText + " : " + rightTxt));

    if (level === "crit") {
      head.appendChild(makeBadge("Critique >200k", "crit"));
    } else if (level === "warn") {
      head.appendChild(makeBadge("Alerte >128k", "warn"));
    } else {
      head.appendChild(el("span", "mono", fmtPct(pct)));
    }
    wrap.appendChild(head);

    const track = el("div", "ctx-track", null, {
      role: "progressbar",
      "aria-valuenow": String(Math.round(refVal)),
      "aria-valuemin": "0",
      "aria-valuemax": String(limit)
    });
    const fill = el("div", "ctx-fill " + level);
    fill.style.width = pct + "%";
    track.appendChild(fill);
    wrap.appendChild(track);
    return wrap;
  }

  function renderStackedBars(segments, opts) {
    const o = opts || {};
    const items = (Array.isArray(segments) ? segments : []).filter((s) => s && Number(s.value) > 0);
    const total = items.reduce((acc, s) => acc + (Number(s.value) || 0), 0);
    const wrap = el("div", "stack-wrap");
    if (o.title) {
      const h = el("div", "panel-head");
      h.appendChild(el("span", "kpi-lbl", o.title));
      h.appendChild(el("span", "mono", fmtTokens(total, true)));
      wrap.appendChild(h);
    }
    if (!items.length || total <= 0) {
      wrap.appendChild(el("div", "empty", o.emptyLabel || "Aucune consommation mesurée."));
      return wrap;
    }
    const bar = el("div", "stack-bar");
    const legend = el("div", "stack-legend");
    items.forEach((seg, idx) => {
      const val = Number(seg.value) || 0;
      const pct = (val / total) * 100;
      const color = seg.color || ("var(--g-c" + ((idx % 6) + 1) + ")");
      const slice = el("div", "stack-seg", null, {
        title: String(seg.label || "") + " : " + fmtTokens(val, true) + " (" + fmtPct(pct) + ")"
      });
      slice.style.width = Math.max(1.5, pct).toFixed(2) + "%";
      slice.style.backgroundColor = color;
      bar.appendChild(slice);

      const lg = el("span", "legend-item");
      const dot = el("span", "legend-dot");
      dot.style.backgroundColor = color;
      lg.appendChild(dot);
      lg.appendChild(el("span", null, String(seg.label || "") + " : " + fmtTokens(val) + " (" + Math.round(pct) + "%)"));
      legend.appendChild(lg);
    });
    wrap.appendChild(bar);
    wrap.appendChild(legend);
    return wrap;
  }

  function renderWorkspaceBreakdown(workspaces, opts) {
    const o = opts || {};
    const rows = Array.isArray(workspaces) ? workspaces.slice() : [];
    const wrap = el("div", "ws-list");
    if (!rows.length) {
      wrap.appendChild(el("div", "empty", o.emptyLabel || "Aucun dépôt détecté."));
      return wrap;
    }
    const metricValue = (r) => Number(r.useful_tokens || r.tokens || r.total_tokens || 0);
    const maxVal = Math.max.apply(null, rows.map(metricValue).concat([1]));
    rows.slice(0, o.limit || 8).forEach((r) => {
      const val = metricValue(r);
      const pct = Math.max(val > 0 ? 4 : 0, Math.round((val / maxVal) * 100));
      const kind = String(r.kind || r.workspace_kind || "code").toLowerCase();
      const row = el("div", "ws-row");
      const head = el("div", "ws-row-head");

      const left = el("div", "ws-name-wrap");
      left.appendChild(el("span", "mono", String(r.workspace || r.project || "workspace")));
      left.appendChild(renderWorkspaceKindBadge(kind));
      head.appendChild(left);

      const countTxt = r.agents_count != null
        ? (r.agents_count + " agent(s)")
        : (r.sessions != null ? (r.sessions + (r.share_pct != null ? " sess." : " session(s)")) : "");
      const shareTxt = r.share_pct != null ? (" (" + fmtPct(r.share_pct) + ")") : "";
      const rightTxt = fmtTokens(val) + shareTxt + (countTxt ? " · " + countTxt : "");
      head.appendChild(el("span", "mono num", rightTxt));
      row.appendChild(head);

      const track = el("div", "ws-bar-track");
      const fill = el("div", "ws-bar-fill");
      fill.style.width = pct + "%";
      fill.style.backgroundColor = kind === "atelier" ? "var(--g-atelier)" : "var(--g-code)";
      track.appendChild(fill);
      row.appendChild(track);
      wrap.appendChild(row);
    });
    return wrap;
  }

  function renderMetricKpiCard(label, value, sub, toneOrOpts) {
    const opts = typeof toneOrOpts === "string" ? { tone: toneOrOpts } : (toneOrOpts || {});
    const card = el("div", "kpi-card" + (opts.tone ? " " + opts.tone : ""));
    const top = el("div", "kpi-top");
    top.appendChild(el("div", "kpi-lbl", label));
    if (opts.badge && opts.badge.label) {
      top.appendChild(makeBadge(opts.badge.label, opts.badge.tone || ""));
    }
    card.appendChild(top);

    const mid = el("div", "kpi-top");
    mid.appendChild(el("div", "kpi-val num", value));
    if (Array.isArray(opts.series) && opts.series.length >= 2) {
      const sp = renderSparkline(opts.series, { label: label, color: opts.seriesColor });
      if (sp) mid.appendChild(sp);
    }
    card.appendChild(mid);

    if (sub) card.appendChild(el("div", "kpi-sub", sub));
    return card;
  }

  function renderInlineConfirm(opts) {
    const o = opts || {};
    const box = el("div", "inline-confirm" + (o.danger ? " danger" : ""));
    box.appendChild(el("span", null, String(o.message || "Confirmer cette action ?")));
    const btns = el("div", "inline-confirm-actions");
    const confirmAttrs = Object.assign({ type: "button" }, o.confirmAttrs || {});
    const cancelAttrs = Object.assign({ type: "button" }, o.cancelAttrs || {});
    const okBtn = el("button", "btn btn-sm " + (o.danger ? "btn-danger" : "btn-primary"), o.confirmLabel || "Confirmer", confirmAttrs);
    const noBtn = el("button", "btn btn-sm", o.cancelLabel || "Annuler", cancelAttrs);
    if (typeof o.onConfirm === "function") okBtn.addEventListener("click", o.onConfirm);
    if (typeof o.onCancel === "function") noBtn.addEventListener("click", o.onCancel);
    btns.appendChild(okBtn);
    btns.appendChild(noBtn);
    box.appendChild(btns);
    return box;
  }
"""

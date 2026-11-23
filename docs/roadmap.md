# Feuille de route — Gravity Core & Écosystème

## `v0.1.0` — Socle modulaire & unification des dépôts *(actuelle)*

- Standardisation des 5 dépôts produits sur `plugin/` + `plugin/config/module.json` v1 (`gravity`, `gravity-architect`, `gravity-workflow`, `gravity-bridge`, `gravity-metrics`).
- Séparation complète de l'atelier de conception dans `gravity-studio`.
- Centralisation du stockage sous `$GRAVITY_HOME` (`~/.gemini/gravity/<module>/`) et registre atomique `core/modules.json`.
- Commandes `/gravity [init|status|modules|doctor]` et détection legacy en lecture seule.

---

## `v0.2.0` — Interface MCP App unifiée & boucle `metrics -> workflow auto`

### 1. Convergence UI/UX vers `gravity` (`ui-host`)
- **Socle & MCP App unifiée livrés sur `dev` (Phase 4 / Lots 1A & 1B) :** façade lecture seule `plugin/dashboard/`, serveur stdio MCP App (`plugin/mcp/server.py`, `open_gravity_dashboard` sur `aux_pane`/`global`), UI HTML5/SVG SEP-1865 autonome sans `innerHTML` et diagnostic `init_env.py --dashboard`.
- **Transition des interfaces existantes :**
  - `gravity-metrics` (`ui.mode: "transition-mcp"`) : vue lecture seule coûts/tokens/cache/audits intégrée dans `gravity` (`archive`/`remove` conservés sous `/gravity-metrics`).
  - `gravity-workflow` (`ui.mode: "transition-sidecar"`) : vue `Workflow Live` temps réel (`~1 500 ms`) intégrée dans `gravity` en lecture seule.
  - `gravity-bridge` et `gravity-architect` : onglets génériques OCP actifs dès Lot 1B, providers dédiés prévus au Lot 2.

### 2. Boucle d'optimisation `metrics -> workflow auto`
- Exploitation des signaux `session-metrics` et `cost-telemetry` produits par `gravity-metrics` comme entrées du routage adaptatif dans `gravity-workflow`.
- Ajustement mesuré du mode `auto`, des presets d'effort/modèles et du ROI du mode `/caveman`.
- Corrélation stricte via le contrat `config/module.json` et stockage `$GRAVITY_HOME`, sans couplage interne ni dépendance tierce.

---

## `v0.3.0+` — Perspectives

- Bus de signaux léger inter-modules sous `$GRAVITY_HOME/core/`.
- Méta-installeur et vérificateur de santé multi-modules orchestré depuis `gravity` Core.

# Feuille de route — Gravity Core & Écosystème

## `v0.1.0` — Socle modulaire & unification des dépôts

- Standardisation des 5 dépôts produits sur `plugin/` + `plugin/config/module.json` v1 (`gravity`, `gravity-architect`, `gravity-workflow`, `gravity-bridge`, `gravity-metrics`).
- Séparation complète de l'atelier de conception dans `gravity-studio`.
- Centralisation du stockage sous `$GRAVITY_HOME` (`~/.gemini/gravity/<module>/`) et registre atomique `core/modules.json`.
- Commandes `/gravity [init|status|modules|doctor]` et détection legacy en lecture seule.

---

## `v0.2.0` → `v0.3.0` — Interface MCP App unifiée, `/gravity` 0-token & boucle `metrics -> workflow auto` *(actuelle)*

### 1. Convergence UI/UX vers `gravity` (`ui-host`)
- **Socle & MCP App unifiée livrés (`v0.3.0`) :** façade lecture seule `plugin/dashboard/`, serveur stdio MCP App (`plugin/mcp/server.py`, `open_gravity_dashboard` sur `aux_pane`/`global` + 7 outils `app`), UI HTML5/SVG SEP-1865 autonome sans `innerHTML`, diagnostic `init_env.py --dashboard` et sonde Antigravity App (`winreg`, `snap`, `dpkg-query`).
- **Vue d'ensemble 0-token & santé multi-modules (`--overview`, `PreInvocation`) :** `/gravity` nu répond sans appel LLM, `init_env.py --check` audite `architect`, `bridge.db`, `metrics`, `workflow` et MCP, et `--guide` affiche le guide complet sans troncature.
- **Statut des interfaces compagnons :**
  - `gravity-metrics` (`ui.mode: "transition-mcp"`) : vue lecture seule coûts/tokens/cache/audits agents intégrée dans `gravity` (`archive`/`remove` conservés sous `/gravity-metrics`).
  - `gravity-workflow` (`ui.mode: "none"`) : vue `Workflow Live` temps réel (`~1 500 ms`) intégrée dans `gravity` en lecture seule.
  - `gravity-bridge` et `gravity-architect` (`ui.mode: "none"`) : onglets dédiés lecture seule (**`Bridge`** sur `bridge.db` `?mode=ro` et **`Architect`** sur l'atelier Hot/Cold + `audits/code/`).

### 2. Boucle d'optimisation `metrics -> workflow auto`
- Exploitation des signaux `session-metrics` et `cost-telemetry` produits par `gravity-metrics` comme entrées du routage adaptatif dans `gravity-workflow`.
- Ajustement mesuré du mode `auto`, des presets d'effort/modèles et du ROI du mode `/caveman`.
- Corrélation stricte via le contrat `config/module.json` et stockage `$GRAVITY_HOME`, sans couplage interne ni dépendance tierce.

---

## `v0.4.0+` — Perspectives

- Bus de signaux léger inter-modules sous `$GRAVITY_HOME/core/`.
- Méta-vérificateur et télémétrie d'interopérabilité inter-modules orchestrés depuis `gravity` Core.

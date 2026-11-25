# Feuille de route — Gravity Core & Écosystème

## `v0.1.0` — Socle modulaire & unification des dépôts

- Standardisation des 4 dépôts produits sur `plugin/` + `plugin/config/module.json` v1 (`gravity`, `gravity-architect`, `gravity-workflow`, `gravity-metrics`).
- Séparation complète de l'atelier de conception dans `gravity-studio`.
- Centralisation du stockage sous `$GRAVITY_HOME` (`~/.gemini/gravity/<module>/`) et registre atomique `core/modules.json`.
- Commandes `/gravity [init|status|modules|doctor]` et détection legacy en lecture seule.

---

## `v0.2.0` → `v0.3.0` — Interface MCP App unifiée (`4` onglets), `/gravity` 0-token & orchestration 100 % native *(actuelle)*

### 1. Convergence UI/UX vers `gravity` (`ui-host`)
- **Socle & MCP App unifiée livrés (`v0.3.0`) :** façade lecture seule `plugin/dashboard/`, serveur stdio MCP App (`plugin/mcp/server.py`, `open_gravity_dashboard` sur `aux_pane`/`global` + `9` outils `app`, `10` outils au total), UI HTML5/SVG SEP-1865 autonome sans `innerHTML` à `4` onglets (`En direct` | `Métriques` | `Atelier` | `Système`), diagnostic `init_env.py --dashboard` et sonde Antigravity App (`winreg`, `snap`, `dpkg-query`).
- **Vue d'ensemble 0-token & santé multi-modules (`--overview`, `PreInvocation`) :** `/gravity` nu répond sans appel LLM, `init_env.py --check` audite `architect`, `metrics`, `workflow` et MCP, et `--guide` affiche le guide complet sans troncature.
- **Orchestration & validation 100 % natives (retrait `gravity-bridge`) :** production multi-dépôts via `run_workflow` (`wave_runner.py` en `git worktree` détachés avec watchdogs `900s`/`360s`) ou `/swarm`, vérification parallèle des `4` dépôts (`audit_ecosystem.py --verify-parallel`), et compatibilité lecture seule des métriques historiques archivées (`#01–#04`).
- **Statut des interfaces compagnons :**
  - `gravity-metrics` (`ui.mode: "none"`, `target: "gravity"`) : moteur de collecte/CLI (`--json`) ; vue `Métriques` technique unifiée (Vue d'ensemble technique, Sessions + Comparateur A/B + actions 1 clic via `gravity_metrics_action`, Audits Agents) intégrée dans `gravity`.
  - `gravity-workflow` (`ui.mode: "none"`, `target: "gravity"`) : cockpit `En direct` temps réel (`2 000 ms`, `brain/` + `Workflow`) intégré dans `gravity`.
  - `gravity-architect` (`ui.mode: "none"`, `target: "gravity"`) : onglet dédié lecture seule (**`Atelier`** sur `ateliers.json`, atelier Hot/Cold + `audits/code/`).

### 2. Boucle d'optimisation `metrics -> workflow auto`
- Exploitation des signaux `session-metrics` et `cost-telemetry` produits par `gravity-metrics` comme entrées du routage adaptatif dans `gravity-workflow`.
- Ajustement mesuré du mode `auto`, des presets d'effort/modèles et du ROI du mode `/caveman`.
- Corrélation stricte via le contrat `config/module.json` et stockage `$GRAVITY_HOME`, sans couplage interne ni dépendance tierce.

---

## `v0.4.0+` — Perspectives

- Bus de signaux léger inter-modules sous `$GRAVITY_HOME/core/`.
- Méta-vérificateur et télémétrie d'interopérabilité inter-modules orchestrés depuis `gravity` Core.

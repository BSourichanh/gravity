# Feuille de route — Gravity Core & Écosystème

## `v0.1.0` — Socle modulaire & unification des dépôts *(actuelle)*

- Standardisation des 5 dépôts produits sur `plugin/` + `plugin/config/module.json` v1 (`gravity`, `gravity-architect`, `gravity-workflow`, `gravity-bridge`, `gravity-metrics`).
- Séparation complète de l'atelier de conception dans `gravity-studio`.
- Centralisation du stockage sous `$GRAVITY_HOME` (`~/.gemini/gravity/<module>/`) et registre atomique `core/modules.json`.
- Commandes `/gravity [init|status|modules|doctor]` et détection legacy en lecture seule.

---

## `v0.2.0` — Interface MCP App unifiée & boucle `metrics -> workflow auto`

### 1. Convergence UI/UX vers `gravity` (`ui-host`)
- Introduction d'une **MCP App native unifiée** dans `gravity` (`ui.mode: "core"`), exploitant le support officiel MCP Apps d'Antigravity (`aux_pane` / `global`).
- **Transition des interfaces existantes :**
  - `gravity-metrics` (`ui.mode: "transition-mcp"`) : intégration de la vue coûts/tokens/cache dans le tableau de bord unifié `gravity`, puis dépréciation progressive du panneau standalone.
  - `gravity-workflow` (`ui.mode: "transition-sidecar"`) : remplacement progressif du sidecar HTTP `4789` (`live-widget`) par le flux temps réel intégré à l'UI unifiée `gravity`.
  - `gravity-bridge` et `gravity-architect` : exposition ultérieure de vues dédiées (fils inter-workspaces, santé des modules) au sein du même hôte `gravity`.

### 2. Boucle d'optimisation `metrics -> workflow auto`
- Exploitation des signaux `session-metrics` et `cost-telemetry` produits par `gravity-metrics` comme entrées du routage adaptatif dans `gravity-workflow`.
- Ajustement mesuré du mode `auto`, des presets d'effort/modèles et du ROI du mode `/caveman`.
- Corrélation stricte via le contrat `config/module.json` et stockage `$GRAVITY_HOME`, sans couplage interne ni dépendance tierce.

---

## `v0.3.0+` — Perspectives

- Bus de signaux léger inter-modules sous `$GRAVITY_HOME/core/`.
- Méta-installeur et vérificateur de santé multi-modules orchestré depuis `gravity` Core.

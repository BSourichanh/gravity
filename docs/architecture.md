# Architecture modulaire de l'écosystème Gravity

L'écosystème **Gravity** repose sur quatre plugins **Google Antigravity** autonomes, chacun limité à une responsabilité unique (**SRP** — *Single Responsibility Principle*), sans dépendance externe (**100 % bibliothèque standard Python 3.10+**).

---

## 1. Découpage SRP des 4 modules

| `id` | Plugin | Commande(s) | Responsabilité unique |
|---|---|---|---|
| `core` | `gravity` (`v0.3.0`) | `/gravity` | Initialisation de `$GRAVITY_HOME`, découverte/validation `config/module.json`, registre `core/modules.json`, vue `--overview` 0-token et hôte UI MCP App unifié (`4` onglets + OCP) |
| `architect` | `gravity-architect` (`v0.5.0`) | `/gravity-architect` | Atelier Hot/Cold générique, intégrité écosystème, veille plateforme et audit de mise à niveau |
| `workflow` | `gravity-workflow` (`v0.3.0`) | `/gravity-workflow`, `/caveman` | Harnais multi-agents, orchestration 100 % native (`run_workflow` `wave_runner.py` en `git worktree` détachés / `/swarm`), garde-fous `PreToolUse` fail-closed, evals et routage adaptatif |
| `metrics` | `gravity-metrics` (`v0.5.0`) | `/gravity-metrics` | Collecte des métriques de sessions Antigravity, analytics tokens/coûts et émission de signaux |

---

## 2. Séparation stricte avec `gravity-studio`

La **conception transversale** (spécifications `specs/`, briefs `tasks/`, tableau de bord multi-projets `ECOSYSTEM.md`, fiches de suivi et archives) vit dans un espace dédié **`gravity-studio`**, totalement séparé des quatre dépôts produits (`gravity`, `gravity-architect`, `gravity-workflow`, `gravity-metrics`).

- Aucun dépôt produit ne contient de fichier de pilotage multi-projets.
- Les dépôts produits restent installables et testables indépendamment.

---

## 3. Stockage centralisé unifié (`$GRAVITY_HOME`)

Aucun module Gravity ne pollue les dépôts ou workspaces utilisateur avec des fichiers de métriques, de journaux ou de registres globaux :

```text
$GRAVITY_HOME (défaut : ~/.gemini/gravity/)
├── core/
│   ├── modules.json        # Registre atomique des modules découverts
│   └── sync.json           # Cible Drive locale optionnelle (export/import)
├── architect/              # Registre ateliers.json et données architect ($GRAVITY_ARCHITECT_HOME)
├── workflow/               # Registres live, worktrees éphémères & profils ($GRAVITY_WORKFLOW_HOME)
└── metrics/                # history.jsonl, METRICS.md, reports/ ($GRAVITY_METRICS_HOME)
```

Ordre de précédence pour chaque module :
1. Argument explicite CLI/API
2. Variable d'environnement dédiée `$GRAVITY_<MODULE>_HOME` (déclarée dans `storage.env_override`)
3. `$GRAVITY_HOME/<storage.subdir>`
4. `~/.gemini/gravity/<storage.subdir>`

Les anciens répertoires éventuels (`~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`) sont détectés en **lecture seule uniquement** par `/gravity doctor` sans suppression ni migration automatique.

---

## 4. Flux de signaux (`metrics -> workflow auto`)

Chaque module déclare dans `config/module.json` les signaux qu'il produit (`signals.produces`) et consomme (`signals.consumes`) :

```text
gravity-metrics                        gravity-workflow
  produces:                              consumes:
   - session-metrics  ---------------->   - session-metrics (mode auto / routage)
   - cost-telemetry                      produces:
                                          - workflow-state
                                          - routing-profile
         \                                      /
          \--------> gravity (core) <----------/
                     consumes: ["*"]
                     produces: ["environment-state"]
```

La boucle **`metrics -> workflow auto`** permettra à `gravity-workflow` d'ajuster dynamiquement les profils de routage, les presets de réflexion/effort et le mode `/caveman` à partir des données objectives mesurées par `gravity-metrics`, tout en restant 100 % optionnelle et découplée via les contrats de modules.

---

## 5. Convergence UI/UX vers `gravity`

En `v0.3.0` :
- `gravity` (`core`) porte `ui: {"mode": "core", "target": "gravity"}`, héberge la **MCP App native unifiée** (`plugin/mcp_config.json`, `plugin/mcp/server.py`, `plugin/mcp/widget_html.py`, façade `plugin/dashboard/api.py`, outils `open_gravity_dashboard` + `gravity_get_*`) en lecture seule, ainsi que le hook `PreInvocation` 0-token sur `/gravity` (`--overview`).
- `gravity-metrics` porte `ui: {"mode": "transition-mcp", "target": "gravity"}` (son widget MCP App reste disponible durant la transition ; les écritures `archive`/`remove` restent sous `/gravity-metrics`).
- `gravity-workflow` porte `ui: {"mode": "none", "target": "gravity"}` (la vue `Workflow Live` dans `gravity` lit `live_workspaces.json`/`live_state.json` en lecture seule ; la production multi-dépôts s'exécute nativement via `run_workflow` `wave_runner.py` ou `/swarm`).
- `gravity-architect` porte `ui: {"mode": "none", "target": "gravity"}` et dispose de son onglet dédié lecture seule **`Architect`** dans `gravity` (découverte `ateliers.json`, `ECOSYSTEM.md`, `specs/`, `tasks/`, `audits/code/` hors `audits/agents/`). Les 4 onglets dédiés (`Overview`, `Workflow Live`, `Metrics`, `Architect`) sont complétés dynamiquement par les onglets génériques des éventuels modules OCP.

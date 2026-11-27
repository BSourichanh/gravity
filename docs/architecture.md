# Architecture modulaire de l'écosystème Gravity

L'écosystème **Gravity** repose sur quatre plugins **Google Antigravity** autonomes, chacun limité à une responsabilité unique (**SRP** — *Single Responsibility Principle*), sans dépendance externe (**100 % bibliothèque standard Python 3.10+**).

---

## 1. Découpage SRP des 4 modules

| `id` | Plugin | Commande(s) | Responsabilité unique |
|---|---|---|---|
| `core` | `gravity` (`v0.3.0`) | `/gravity` | Initialisation de `$GRAVITY_HOME`, découverte/validation `config/module.json`, registre `core/modules.json`, hôte UI unifié (SPI) |
| `architect` | `gravity-architect` (`v0.5.0`) | `/gravity-architect` | Atelier Hot/Cold générique, intégrité écosystème, veille plateforme et audit de mise à niveau |
| `workflow` | `gravity-workflow` (`v0.3.0`) | `/gravity-workflow`, `/caveman` | Harnais multi-agents, workflows orchestrateurs, garde-fous `PreToolUse` fail-closed, evals et routage adaptatif |
| `metrics` | `gravity-metrics` (`v0.5.0`) | `/gravity-metrics` | Collecte des métriques de sessions Antigravity, analytics tokens/coûts et émission de signaux |

---

## 2. Séparation stricte avec `gravity-workshop`

La **conception transversale** (spécifications `specs/`, tâches `tasks/`, tableau de bord multi-projets `ECOSYSTEM.md`, fiches de suivi et archives) vit dans l'atelier dédié **`gravity-workshop`**, totalement séparé des quatre dépôts plugins (`gravity`, `gravity-architect`, `gravity-workflow`, `gravity-metrics`).

- Aucun dépôt produit ne contient de fichier de pilotage multi-projets.
- Les dépôts produits restent installables et testables indépendamment.

---

## 3. Stockage centralisé unifié (`$GRAVITY_HOME`)

Aucun module Gravity ne pollue les dépôts ou workspaces utilisateur avec des fichiers de métriques, de boîtes aux lettres ou de registres globaux :

```text
$GRAVITY_HOME (défaut : ~/.gemini/gravity/)
├── core/
│   └── modules.json        # Registre atomique des modules découverts
├── architect/              # Données centralisées architect ($GRAVITY_ARCHITECT_HOME)
├── workflow/               # Registres live & profils globaux ($GRAVITY_WORKFLOW_HOME)
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

En `v0.2.0` :
- `gravity` (`core`) porte `ui: {"mode": "core", "target": "gravity"}` et héberge la **MCP App native unifiée** (`plugin/mcp_config.json`, `plugin/mcp/server.py`, `plugin/mcp/widget_html.py`, façade `plugin/dashboard/api.py`, outils `open_gravity_dashboard` + `gravity_get_*`) en lecture seule.
- `gravity-metrics` porte `ui: {"mode": "transition-mcp", "target": "gravity"}` (son widget MCP App reste disponible durant la transition ; les écritures `archive`/`remove` restent sous `/gravity-metrics`).
- `gravity-workflow` porte `ui: {"mode": "transition-sidecar", "target": "gravity"}` (son sidecar HTTP `4789` reste fonctionnel durant la transition ; la vue `Workflow Live` dans `gravity` lit `live_workspaces.json`/`live_state.json`).
- `gravity-architect` porte `ui: {"mode": "none", "target": "gravity"}` et dispose de son onglet dédié lecture seule dans `gravity` (**`Architect`** sur l'atelier Hot/Cold + `audits/code/` hors `audits/agents/`).

---

## 6. Lecture DDD & Architecture Hexagonale pragmatique

L'écosystème Gravity applique de fait les frontières du **Domain-Driven Design (DDD)** et de l'**Architecture Hexagonale (Ports & Adapters)** sans surcouche abstraite superflue :

| Concept DDD / Hexagonal | Traduction concrète dans Gravity |
|---|---|
| **Bounded Contexts** | 4 contextes autonomes (`core` `gravity`, `architect` `gravity-architect`, `workflow` `gravity-workflow`, `metrics` `gravity-metrics`) + plan de pilotage séparé `gravity-workshop` |
| **Shared Kernel** | `shared/gravity_shared/` (`atomic_io`, `file_lock`, `path_safety`, `hook_runtime`, `installer_core`, `validator_core`, `transcript_reader`, `signal_bus`) projeté en lecture seule vers `*/plugin/_shared/` |
| **Ports entrants / sortants (SPI)** | Contrats [`module.json`](module-contract.md) (`SPI-1..4`), `scripts/dashboard_provider.py` (`SPI-1`), `capture_policy` (`SPI-2`), enveloppe `signal_v1` (`SPI-3`), schéma `wave_plan_v1` |
| **Adapteurs primaires & secondaires** | **Entrants :** CLI (`init_env.py`, `cli.py`, `sync_tracking.py`), serveur MCP (`mcp/server.py`), hooks Antigravity (`hooks/*.py`). **Sortants :** stockage `$GRAVITY_HOME/<module>/`, fichiers JSONL/transcripts, `git worktree` |

### Règle de proportionnalité KISS / YAGNI

- **Appliquer** dès qu'un composant porte des règles métier riches, plusieurs adapteurs I/O (CLI, MCP, hooks) ou une frontière partagée (`SPI`, contrat JSON).
- **S'abstenir** sur les scripts utilitaires linéaires, wrappers minces ou helpers mono-usage : ne jamais introduire de hiérarchie d'interfaces ou de *repositories* spéculative sans second adapteur ou besoin de test isolé avéré.

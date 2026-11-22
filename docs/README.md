# Documentation — Gravity Core & Écosystème

Bienvenue dans la documentation technique de **Gravity Core** (`BSourichanh/gravity`) et de l'écosystème modulaire **Gravity**.

## Guides disponibles

| Document | Contenu |
|---|---|
| [`architecture.md`](architecture.md) | Architecture SRP des 5 modules, flux de signaux `metrics -> workflow auto`, convergence UI/UX vers `gravity` et séparation `gravity-studio` |
| [`module-contract.md`](module-contract.md) | Spécification complète `plugin/config/module.json` v1, stockage `$GRAVITY_HOME/<module>/` et ajout d'un nouveau module sans modifier Core |
| [`repo-standard.md`](repo-standard.md) | Standard uniforme des dépôts Gravity (`plugin/`, manifeste 9 champs, `AGENTS.md <= 2 500 o`, KISS/YAGNI/DRY/SOLID/CUPID, budgets Hot/Cold, vérifications) |
| [`roadmap.md`](roadmap.md) | Feuille de route `v0.1.0` → `v0.2.0` (UI MCP App unifiée dans `gravity`, transition des UIs `metrics`/`workflow`, boucle `metrics -> workflow auto`) |

## Rappel d'architecture

- **`gravity`** (`/gravity`) : socle central, environnement `$GRAVITY_HOME`, registre `core/modules.json` et futur hôte UI unifié.
- **`gravity-workflow`** (`/gravity-workflow`, `/caveman`) : harnais multi-agents, workflows, garde-fous et evals.
- **`gravity-architect`** (`/gravity-architect`) : conception, intégrité écosystème, stockage Hot/Cold et veille plateforme.
- **`gravity-bridge`** (`/gravity-bridge`) : boîte aux lettres SQLite WAL inter-workspaces et sidecars `agentapi`.
- **`gravity-metrics`** (`/gravity-metrics`) : métriques Antigravity, coûts/tokens et signaux d'optimisation.
- **`gravity-studio`** : atelier de conception, specs, handoffs et suivi multi-projets séparé hors des 5 dépôts produits.

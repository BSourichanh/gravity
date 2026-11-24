# Documentation — Gravity Core & Écosystème

Bienvenue dans la documentation de **Gravity Core** (`BSourichanh/gravity`) et de l'écosystème modulaire **Gravity**.

## Parcours Utilisateur & UX

| Guide | Contenu |
|---|---|
| [`getting-started.md`](getting-started.md) | Prérequis, 3 paliers (*Essentiel*, *Pilotage*, *Multi-projets*), séquences PowerShell & bash, MCP App et check-list 5 points |
| [`user-journey.md`](user-journey.md) | Diagramme Mermaid du parcours, scénario fil rouge annoté, matrice 4 phases et 3 frontières d'or |
| [`command-cheatsheet.md`](command-cheatsheet.md) | Matrice intentionnelle complète (`/gravity*`, `/caveman`, `/learn`), combinaisons gagnantes et anti-patterns |
| [`troubleshooting-and-lifecycle.md`](troubleshooting-and-lifecycle.md) | Mises à jour `--update`, migration legacy 4 étapes (`--migration-plan`), dépannage Windows/POSIX et `--uninstall` |

## Architecture, Standards & Roadmap

| Document | Contenu |
|---|---|
| [`architecture.md`](architecture.md) | Architecture SRP des 5 modules, flux de signaux `metrics -> workflow auto`, convergence UI/UX vers `gravity` et séparation `gravity-studio` |
| [`module-contract.md`](module-contract.md) | Spécification complète `plugin/config/module.json` v1, stockage `$GRAVITY_HOME/<module>/` et ajout d'un nouveau module sans modifier Core |
| [`repo-standard.md`](repo-standard.md) | Standard uniforme des dépôts Gravity (`plugin/`, manifeste 9 champs, budgets `AGENTS.md`, hygiène UX/docs, contrat CLI 11 drapeaux, vérifications) |
| [`roadmap.md`](roadmap.md) | Feuille de route `v0.1.0` → `v0.3.0` (UI MCP App unifiée dans `gravity`, vue 0-token `--overview`, transition `metrics`, boucle `metrics -> workflow auto`) |

## Rappel d'architecture

- **`gravity`** (`/gravity`) : socle central, environnement `$GRAVITY_HOME`, registre `core/modules.json` et hôte UI MCP App unifié.
- **`gravity-workflow`** (`/gravity-workflow`, `/caveman`) : harnais multi-agents, workflows, garde-fous et evals.
- **`gravity-architect`** (`/gravity-architect`) : conception, intégrité écosystème, stockage Hot/Cold et veille plateforme.
- **`gravity-bridge`** (`/gravity-bridge`) : boîte aux lettres SQLite WAL inter-workspaces et sidecars `agentapi`.
- **`gravity-metrics`** (`/gravity-metrics`) : métriques Antigravity, coûts/tokens et signaux d'optimisation.
- **`gravity-studio`** : atelier de conception, specs, handoffs et suivi multi-projets séparé hors des 5 dépôts produits.

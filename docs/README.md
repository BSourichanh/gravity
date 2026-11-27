# Documentation — Gravity Core & Écosystème

Bienvenue dans la documentation de **Gravity Core** (`BSourichanh/gravity`) et de l'écosystème modulaire **Gravity**.

## Parcours Utilisateur & UX

| Guide | Contenu |
|---|---|
| [`getting-started.md`](getting-started.md) | Prérequis, 3 paliers (*Essentiel*, *Pilotage*, *Multi-projets*), séquences PowerShell & bash, MCP App et check-list 5 points |
| [`user-journey.md`](user-journey.md) | Diagramme Mermaid du parcours, scénario fil rouge annoté, matrice 7 phases et 3 frontières d'or |
| [`command-cheatsheet.md`](command-cheatsheet.md) | Matrice intentionnelle complète (`/gravity*`, `/caveman`, `/learn`), combinaisons gagnantes et anti-patterns |
| [`troubleshooting-and-lifecycle.md`](troubleshooting-and-lifecycle.md) | Mises à jour `--update`, migration legacy 4 étapes (`--migration-plan`), dépannage Windows/POSIX et `--uninstall` |

## Architecture, Standards & Roadmap

| Document | Contenu |
|---|---|
| [`architecture.md`](architecture.md) | Architecture SRP des 4 modules, flux de signaux `metrics -> workflow evo` (`$GRAVITY_HOME/signals/`, `SPI-3`), convergence UI MCP App via `SPI-1`, séparation `gravity-workshop` et lecture DDD / Architecture Hexagonale pragmatique |
| [`module-contract.md`](module-contract.md) | Spécification complète `plugin/config/module.json` v1 (`SPI-1..3`, `dashboard`, `capture_policy`), stockage `$GRAVITY_HOME/<module>/` et ajout d'un nouveau module sans modifier Core |
| [`repo-standard.md`](repo-standard.md) | Standard uniforme des dépôts Gravity (`plugin/`, manifeste 9 champs, budgets Hot/Warm/Cold, `gravity_shared`, contrat CLI 11 drapeaux, vérifications `audit_ecosystem.py`) |
| [`roadmap.md`](roadmap.md) | Feuille de route `v0.1.0` → `v0.3.0` (UI MCP App unifiée `SPI-1`, `gravity_shared` `SPI-4`, `capture_policy` `SPI-2`, bus `$GRAVITY_HOME/signals/` `SPI-3` et boucle `metrics -> workflow evo`) |

## Rappel d'architecture

- **`gravity`** (`/gravity`) : socle central, environnement `$GRAVITY_HOME`, registre `core/modules.json` et hôte UI MCP App unifié.
- **`gravity-workflow`** (`/gravity-workflow`, `/caveman`) : harnais multi-agents, workflows, garde-fous et evals.
- **`gravity-architect`** (`/gravity-architect`) : conception, intégrité écosystème, stockage Hot/Cold et veille plateforme.
- **`gravity-metrics`** (`/gravity-metrics`) : métriques Antigravity, coûts/tokens et signaux d'optimisation.
- **`gravity-workshop`** : atelier de conception, specs, tasks et suivi multi-projets séparé hors des 4 dépôts plugins.

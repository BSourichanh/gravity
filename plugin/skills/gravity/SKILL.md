---
name: gravity
description: "Initialiser ~/.gemini/gravity/, découvrir les modules, diagnostiquer et ouvrir le dashboard (/gravity [init|status|modules|doctor|dashboard|update|help])."
---

# Gravity Core (`/gravity`)

Administration de l'environnement unifié **Gravity** (`$GRAVITY_HOME`, défaut `~/.gemini/gravity/`).

## Sous-commandes

Exécuter depuis la racine du plugin `gravity` (sortie texte compacte par défaut ; réserver `--json` à `/gravity modules` et aux appels scriptés) :

| Commande | Action CLI | Effet |
|---|---|---|
| `/gravity` | Hook `PreInvocation` (`python scripts/init_env.py --overview`) | Lecture seule à **0 token** : vue d'ensemble `$GRAVITY_HOME`, santé modules (`[OK]`/`[WARN]`/`[ERR]`), MCP `dashboard`, version App et aide 5 parcours. |
| `/gravity init` | `python scripts/init_env.py` | Crée `<gravity_home>/core/` et sous-dossiers des modules valides, puis écrit `core/modules.json`. |
| `/gravity status` | `python scripts/init_env.py --status` | Lecture seule : état de `$GRAVITY_HOME`, `core/modules.json`, modules détectés et dossiers legacy. |
| `/gravity modules` | `python scripts/init_env.py --status --json` | Liste complète des contrats découverts (`id`, `plugin_name`, `version`, `commands`, `capabilities`, `ui`, `signals`, `valid`). |
| `/gravity doctor` | `python scripts/init_env.py --check` | Audit lecture seule (`config/module.json` v1, santé modules, MCP, version App `winreg`/`snap`/`dpkg`, legacy). Plan manuel non destructif (0 écriture) : `python scripts/init_env.py --migration-plan [--shell auto|powershell|bash]`. |
| `/gravity dashboard` | MCP `open_gravity_dashboard(ws="<Active Workspace>")` *(dépannage : `python scripts/init_env.py --dashboard`)* | Ouvre la MCP App unifiée à `4` onglets dédiés (`En direct`, `Metrics`, `Architect RO`, `Overview` + modules OCP) depuis `aux_pane`, la barre latérale gauche (`Gravity`) ou le menu `+` du panneau latéral droit (`0` token interactif) ; `--dashboard` réservé au diagnostic CLI RO. |
| `/gravity update` | `python scripts/init_env.py --update [--check-updates] [--force] [--modules <ids>] [--link <path>] [--repos-root <dir>] [--offline] [--dry-run]` | Inspecte (`--check-updates`, lecture seule) ou met à jour via `git pull --ff-only` *fail-isolated* les dépôts liés dans `$GRAVITY_HOME/core/sources.json`, réinstalle compagnons d'abord puis `core`, et rafraîchit `core/modules.json` (redémarrer le MCP `gravity_dashboard` si `core` change). |
| `/gravity help` | `python scripts/init_env.py --guide` | Lecture seule : guide complet sans troncature (boucle en 3 temps, commandes des modules découverts et pointeurs `docs/`). |
| `/gravity export` | `python scripts/init_env.py --export [--out <dir\|zip>] [--include-atelier <path>] [--set-drive-dir <dir>]` | Sauvegarde ZIP atomique SHA-256 (`metrics/`, `workflow/*/profile.json`, `ateliers.json`, ateliers inclus), cible `--out` > `core/sync.json` > CWD. |
| `/gravity import` | `python scripts/init_env.py --import <zip> [--dry-run]` | Vérifie l'intégrité SHA-256/anti-traversal en mémoire, remappe les chemins vers `$GRAVITY_HOME` et restaure de manière atomique (`--dry-run` : 0 écriture). |

## Règles d'exécution

1. Ne jamais modifier, migrer ni supprimer les dossiers legacy (`~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`) automatiquement ; signalement lecture seule uniquement.
2. Zéro fichier Gravity dans les workspaces cibles : tout l'état vit sous `$GRAVITY_HOME`.
3. Pour l'orchestration multi-agents native (`run_workflow` `wave_runner.py` / `/swarm`), workflows ou garde-fous, orienter vers **`/gravity-workflow`**.

---
name: gravity
description: "Initialiser ~/.gemini/gravity/, découvrir les modules, diagnostiquer l'environnement et ouvrir le dashboard (/gravity [init|status|modules|doctor|dashboard])."
---

# Gravity Core (`/gravity`)

Administration de l'environnement unifié **Gravity** (`$GRAVITY_HOME`, défaut `~/.gemini/gravity/`).

## Sous-commandes

Exécuter depuis la racine du plugin `gravity` (sortie texte compacte par défaut ; réserver `--json` à `/gravity modules` et aux appels scriptés) :

| Commande | Action CLI | Effet |
|---|---|---|
| `/gravity init` | `python scripts/init_env.py` | Crée `<gravity_home>/core/` et sous-dossiers des modules valides, puis écrit `core/modules.json`. |
| `/gravity` ou `/gravity status` | `python scripts/init_env.py --status` | Lecture seule : état de `$GRAVITY_HOME`, `core/modules.json`, modules détectés et dossiers legacy. |
| `/gravity modules` | `python scripts/init_env.py --status --json` | Liste complète des contrats découverts (`id`, `plugin_name`, `version`, `commands`, `capabilities`, `ui`, `signals`, `valid`). |
| `/gravity doctor` | `python scripts/init_env.py --check` | Audit lecture seule (`config/module.json` v1, `$GRAVITY_*_HOME`, legacy). Plan manuel non destructif (0 écriture) : `python scripts/init_env.py --migration-plan [--shell auto|powershell|bash]`. |
| `/gravity dashboard` | MCP `open_gravity_dashboard` / `python scripts/init_env.py --dashboard` | Ouvre le tableau de bord unifié MCP App (`aux_pane` ou `Plugins -> Gravity` à `0` token interactif) ; `--dashboard` diagnostique la config MCP et les onglets en lecture seule. |

## Règles d'exécution

1. Ne jamais modifier, migrer ni supprimer les dossiers legacy (`~/.gemini/gravity-bridge`, `~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`) automatiquement ; signalement lecture seule uniquement.
2. Zéro fichier Gravity dans les workspaces cibles : tout l'état vit sous `$GRAVITY_HOME`.
3. Pour l'orchestration multi-agents, workflows ou garde-fous, orienter vers **`/gravity-workflow`**.

---
name: gravity
description: "Initialiser ~/.gemini/gravity/, découvrir les modules Gravity installés et diagnostiquer l'environnement via /gravity [init|status|modules|doctor]."
---

# Gravity Core (`/gravity`)

Skill d'administration de l'environnement unifié **Gravity** (`$GRAVITY_HOME`, défaut `~/.gemini/gravity/`).

## Sous-commandes

Exécuter `python scripts/init_env.py` depuis la racine du plugin `gravity` :

| Commande | Action CLI | Effet |
|---|---|---|
| `/gravity init` | `python scripts/init_env.py --json` | Crée `<gravity_home>/core/` et les sous-dossiers des modules valides découverts, puis écrit `core/modules.json`. |
| `/gravity` ou `/gravity status` | `python scripts/init_env.py --status --json` | Lecture seule : affiche l'état de `$GRAVITY_HOME`, de `core/modules.json`, des modules détectés et d'éventuels dossiers legacy. |
| `/gravity modules` | `python scripts/init_env.py --status --json` | Présente les modules découverts (`id`, `plugin_name`, `version`, `commands`, `capabilities`, `ui`, `signals`, `valid`). |
| `/gravity doctor` | `python scripts/init_env.py --check --json` | Audit en lecture seule : vérifie les contrats `config/module.json` v1, les surcharges `$GRAVITY_*_HOME` et signale les dossiers legacy sans rien modifier. |

## Règles d'exécution

1. Ne jamais modifier, migrer ni supprimer les anciens dossiers (`~/.gemini/gravity-bridge`, `~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`) automatiquement ; se limiter au signalement lecture seule.
2. Ne jamais créer de fichiers Gravity dans les workspaces cibles : tout l'état réside sous `$GRAVITY_HOME`.
3. Pour l'orchestration multi-agents, les workflows ou les garde-fous de session, orienter l'utilisateur vers **`/gravity-workflow`** (plugin `gravity-workflow`).

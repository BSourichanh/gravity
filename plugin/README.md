# Gravity Core Plugin (`v0.1.0`)

Plugin maître de l'écosystème **Gravity** pour **Google Antigravity**, 100 % bibliothèque standard Python 3.10+.

> **Rappel :** `gravity` (`/gravity`) gère l'environnement unifié et le registre des modules ; le harnais multi-agents/workflows s'appelle désormais **`gravity-workflow`** (`/gravity-workflow`, `/caveman`).

## Capacités

- **Environnement centralisé (`$GRAVITY_HOME`) :** résout `~/.gemini/gravity/` (ou `$GRAVITY_HOME`) et le stockage dédié de chaque module (`$GRAVITY_<MODULE>_HOME` > `$GRAVITY_HOME/<subdir>`).
- **Découverte & validation (`config/module.json` v1) :** inspecte les plugins installés, valide les contrats `module.json` + `plugin.json` et écrit de façon atomique `<gravity_home>/core/modules.json`.
- **Détection legacy en lecture seule :** signale sans jamais les modifier ni les supprimer d'éventuels anciens dossiers (`~/.gemini/gravity-bridge`, `~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`).
- **Commandes `/gravity` :** `/gravity init`, `/gravity status`, `/gravity modules`, `/gravity doctor`.

## Écosystème Gravity

| Module (`id`) | Plugin | Commande(s) | Rôle |
|---|---|---|---|
| `core` | `gravity` (`v0.1.0`) | `/gravity` | Environnement unifié, registre modules et futur hôte UI unifié |
| `architect` | `gravity-architect` (`v0.2.0`) | `/gravity-architect` | Conception, intégrité écosystème, stockage Hot/Cold et veille |
| `workflow` | `gravity-workflow` (`v0.2.0`) | `/gravity-workflow`, `/caveman` | Harnais multi-agents, workflows, garde-fous, evals et routage |
| `bridge` | `gravity-bridge` (`v0.1.0`) | `/gravity-bridge` | Boîte aux lettres SQLite WAL inter-projets et sidecars `agentapi` |
| `metrics` | `gravity-metrics` (`v0.2.0`) | `/gravity-metrics` | Métriques Antigravity, coûts/tokens et signaux d'optimisation |

## Utilisation CLI

```powershell
# Initialiser <gravity_home>/core/modules.json et les sous-dossiers des modules valides
python scripts/init_env.py

# Inspection et diagnostic en lecture seule
python scripts/init_env.py --status --json
python scripts/init_env.py --check --json

# Validation stricte du plugin
python scripts/validate.py --strict
```

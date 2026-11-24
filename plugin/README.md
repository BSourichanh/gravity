# Gravity Core Plugin (`v0.3.0`)

Plugin maître de l'écosystème **Gravity** pour **Google Antigravity**, 100 % bibliothèque standard Python 3.10+.

> **Rappel :** `gravity` (`/gravity`) gère l'environnement unifié, le registre des modules et la MCP App unifiée ; le harnais multi-agents/workflows s'appelle **`gravity-workflow`** (`/gravity-workflow`, `/caveman`).
>
> **Guides UX (`gravity/docs/`) :** [Démarrage rapide](https://github.com/BSourichanh/gravity/blob/main/docs/getting-started.md) · [Parcours utilisateur](https://github.com/BSourichanh/gravity/blob/main/docs/user-journey.md) · [Aide-mémoire des commandes](https://github.com/BSourichanh/gravity/blob/main/docs/command-cheatsheet.md) · [Dépannage & cycle de vie](https://github.com/BSourichanh/gravity/blob/main/docs/troubleshooting-and-lifecycle.md)

## Capacités

- **Environnement centralisé (`$GRAVITY_HOME`) :** résout `~/.gemini/gravity/` (ou `$GRAVITY_HOME`) et le stockage dédié de chaque module (`$GRAVITY_<MODULE>_HOME` > `$GRAVITY_HOME/<subdir>`).
- **Découverte, santé & validation (`config/module.json` v1) :** inspecte les plugins installés, contrôle la santé RO (`architect`, `metrics`, `workflow`, MCP, version App `winreg`/`snap`/`dpkg`) et écrit `<gravity_home>/core/modules.json`.
- **Vue d'ensemble 0-token (`/gravity` via `PreInvocation`) :** `hooks/pre_invocation_gravity.py` exécute `init_env.py --overview` en lecture seule sans consommer de tokens LLM.
- **Détection legacy en lecture seule :** signale sans jamais les modifier ni les supprimer d'éventuels anciens dossiers (`~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`).
- **Dashboard MCP App unifié (`open_gravity_dashboard`) :** UI HTML5/SVG SEP-1865 lecture seule à `4` onglets dédiés (`Overview/Doctor`, `Workflow Live`, `Metrics & Audits Agents`, `Architect RO` avec découverte `ateliers.json` / `tasks/` / `specs/`, sélecteur d'atelier) et onglets génériques OCP, accessible via `/gravity dashboard`, la **barre latérale gauche (`Gravity`)** ou le **menu `+` du panneau latéral droit** (`0` token interactif).
- **Sauvegarde / restauration portable (`core/bundle.py`) :** export ZIP vérifié SHA-256 (`--export`, `--out`, `--include-atelier`, `--set-drive-dir` dans `core/sync.json`) et import sécurisé avec remapping (`--import`, `--dry-run`).
- **Commandes `/gravity` :** `/gravity` (0-token `--overview`), `/gravity init`, `/gravity status`, `/gravity modules`, `/gravity doctor`, `/gravity dashboard`, `/gravity help`, `/gravity export`, `/gravity import` *(skill [`SKILL.md`](skills/gravity/SKILL.md))*.

## Écosystème Gravity (4 modules actifs)

| Module (`id`) | Plugin | Commande(s) | Rôle |
|---|---|---|---|
| `core` | `gravity` (`v0.3.0`) | `/gravity` | Environnement unifié, registre modules et hôte UI MCP App unifié |
| `architect` | `gravity-architect` (`v0.5.0`) | `/gravity-architect` | Conception, intégrité écosystème, stockage Hot/Cold et veille |
| `workflow` | `gravity-workflow` (`v0.3.0`) | `/gravity-workflow`, `/caveman` | Harnais multi-agents, orchestration native (`wave_runner.py` / `/swarm`), garde-fous, evals et routage |
| `metrics` | `gravity-metrics` (`v0.5.0`) | `/gravity-metrics` | Métriques Antigravity, coûts/tokens et signaux d'optimisation |

## Utilisation CLI

```powershell
# Initialiser <gravity_home>/core/modules.json et les sous-dossiers des modules valides
python scripts/init_env.py

# Inspection et diagnostic en lecture seule (texte compact par défaut ; --json pour scripts/modules)
python scripts/init_env.py --overview
python scripts/init_env.py --status
python scripts/init_env.py --check
python scripts/init_env.py --status --json
python scripts/init_env.py --migration-plan --shell auto
python scripts/init_env.py --dashboard
python scripts/init_env.py --guide

# Sauvegarde et restauration portable (ZIP vérifié SHA-256 + sync.json)
python scripts/init_env.py --set-drive-dir /chemin/vers/GoogleDrive/Gravity
python scripts/init_env.py --export --include-atelier /chemin/vers/atelier --out ./backup.zip
python scripts/init_env.py --import ./backup.zip --dry-run

# Validation stricte du plugin
python scripts/validate.py --strict
```

# Gravity Core Plugin (`v0.3.0`)

Plugin maître de l'écosystème **Gravity** pour **Google Antigravity**, 100 % bibliothèque standard Python 3.10+.

> **Rappel :** `gravity` (`/gravity`) gère l'environnement unifié, le registre des modules et la MCP App unifiée ; le harnais multi-agents/workflows s'appelle **`gravity-workflow`** (`/gravity-workflow`, `/caveman`).
>
> **Guides UX (`gravity/docs/`) :** [Démarrage rapide](https://github.com/BSourichanh/gravity/blob/main/docs/getting-started.md) · [Parcours utilisateur](https://github.com/BSourichanh/gravity/blob/main/docs/user-journey.md) · [Aide-mémoire des commandes](https://github.com/BSourichanh/gravity/blob/main/docs/command-cheatsheet.md) · [Dépannage & cycle de vie](https://github.com/BSourichanh/gravity/blob/main/docs/troubleshooting-and-lifecycle.md)

## Capacités

- **Environnement centralisé (`$GRAVITY_HOME`) :** résout `~/.gemini/gravity/` (ou `$GRAVITY_HOME`) et le stockage dédié de chaque module (`$GRAVITY_<MODULE>_HOME` > `$GRAVITY_HOME/<subdir>`).
- **Découverte, santé & validation (`config/module.json` v1) :** inspecte les plugins installés, contrôle la santé RO (`architect`, `bridge.db`, `metrics`, `workflow`, MCP, version App `winreg`/`snap`/`dpkg`) et écrit `<gravity_home>/core/modules.json`.
- **Vue d'ensemble 0-token (`/gravity` via `PreInvocation`) :** `hooks/pre_invocation_gravity.py` exécute `init_env.py --overview` en lecture seule sans consommer de tokens LLM.
- **Détection legacy en lecture seule :** signale sans jamais les modifier ni les supprimer d'éventuels anciens dossiers (`~/.gemini/gravity-bridge`, `~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`).
- **Dashboard MCP App unifié (`open_gravity_dashboard`) :** UI HTML5/SVG SEP-1865 lecture seule (`Overview/Doctor`, `Workflow Live`, `Metrics & Audits Agents`, `Bridge RO`, `Architect RO` avec découverte `ateliers.json` / indice `ws` / sélecteur d'atelier, onglets génériques OCP) accessible via `/gravity dashboard` ou la **barre latérale gauche (`Gravity`)** ou le **menu `+` du panneau latéral droit** (`0` token interactif).
- **Commandes `/gravity` :** `/gravity` (0-token `--overview`), `/gravity init`, `/gravity status`, `/gravity modules`, `/gravity doctor`, `/gravity dashboard`, `/gravity help` *(guide complet sans troncature, skill [`SKILL.md`](skills/gravity/SKILL.md))*.

## Écosystème Gravity

| Module (`id`) | Plugin | Commande(s) | Rôle |
|---|---|---|---|
| `core` | `gravity` (`v0.3.0`) | `/gravity` | Environnement unifié, registre modules et hôte UI MCP App unifié |
| `architect` | `gravity-architect` (`v0.5.0`) | `/gravity-architect` | Conception, intégrité écosystème, stockage Hot/Cold et veille |
| `workflow` | `gravity-workflow` (`v0.3.0`) | `/gravity-workflow`, `/caveman` | Harnais multi-agents, workflows, garde-fous, evals et routage |
| `bridge` | `gravity-bridge` (`v0.3.0`) | `/gravity-bridge` | Boîte aux lettres SQLite WAL inter-projets et sidecars `agentapi` |
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

# Validation stricte du plugin
python scripts/validate.py --strict
```

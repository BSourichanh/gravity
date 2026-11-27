# Gravity Core Plugin (`v0.3.0`)

Plugin maître de l'écosystème **Gravity** pour **Google Antigravity**, 100 % bibliothèque standard Python 3.10+.

> **Rappel :** `gravity` (`/gravity`) gère l'environnement unifié, le registre des modules et le socle `_shared/` ; le harnais multi-agents/workflows s'appelle **`gravity-workflow`** (`/gravity-workflow`, `/caveman`).
>
> **Guides UX (`gravity/docs/`) :** [Démarrage rapide](https://github.com/BSourichanh/gravity/blob/main/docs/getting-started.md) · [Parcours utilisateur](https://github.com/BSourichanh/gravity/blob/main/docs/user-journey.md) · [Aide-mémoire des commandes](https://github.com/BSourichanh/gravity/blob/main/docs/command-cheatsheet.md) · [Dépannage & cycle de vie](https://github.com/BSourichanh/gravity/blob/main/docs/troubleshooting-and-lifecycle.md)

## Capacités

- **Environnement centralisé (`$GRAVITY_HOME`) :** résout `~/.gemini/gravity/` (ou `$GRAVITY_HOME`) et le stockage dédié de chaque module (`$GRAVITY_<MODULE>_HOME` > `$GRAVITY_HOME/<subdir>`).
- **Hook `PreInvocation` 0-token (`/gravity` nu) :** `hooks/pre_invocation_gravity.py` répond sans appel modèle via `init_env.py --overview`.
- **Socle partagé `_shared/` :** projection lecture seule vérifiée par SHA-256 (`.shared_manifest.json`) depuis `shared/gravity_shared/`.
- **Découverte & validation (`config/module.json` v1, `SPI-1..3`) :** inspecte les plugins installés, valide les contrats `module.json` + `plugin.json` et écrit de façon atomique `<gravity_home>/core/modules.json`.
- **Détection legacy en lecture seule :** signale sans jamais les modifier ni les supprimer d'éventuels anciens dossiers (`~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`).
- **Dashboard MCP App unifié (`open_gravity_dashboard`, `SPI-1`) :** UI HTML5/SVG SEP-1865 pure DOM lecture seule (`En direct`, onglets `SPI-1` découverts, `Overview/Doctor`, onglets génériques OCP) accessible via `/gravity dashboard` ou **Plugins -> Gravity** (`0` token interactif).
- **Mises à jour & sauvegarde portable :** `/gravity update` (`core/updater.py`) et `/gravity export` / `/gravity import` (`core/bundle.py`, ZIP vérifié SHA-256).
- **Commandes `/gravity` :** `/gravity init`, `/gravity status`, `/gravity modules`, `/gravity doctor`, `/gravity dashboard`, `/gravity update`, `/gravity export`, `/gravity import`, `/gravity help` *(skill [`SKILL.md`](skills/gravity/SKILL.md))*.

## Écosystème Gravity

| Module (`id`) | Plugin | Commande(s) | Rôle |
|---|---|---|---|
| `core` | `gravity` (`v0.3.0`) | `/gravity` | Environnement unifié, registre modules, SSOT `_shared/` et hôte UI unifié (`SPI-1`) |
| `architect` | `gravity-architect` (`v0.5.1`) | `/gravity-architect` | Conception, intégrité écosystème, stockage Hot/Cold, `waves.py` et veille |
| `workflow` | `gravity-workflow` (`v0.4.0`) | `/gravity-workflow`, `/caveman` | Harnais multi-agents (Swarm par défaut), garde-fous, evals et routage |
| `metrics` | `gravity-metrics` (`v0.5.1`) | `/gravity-metrics` | Métriques Antigravity, coûts/tokens et signaux `signal_bus` (`SPI-3`) |

## Utilisation CLI

```powershell
# Initialiser <gravity_home>/core/modules.json et les sous-dossiers des modules valides
python scripts/init_env.py

# Inspection et diagnostic en lecture seule (texte compact par défaut ; --json pour scripts/modules)
python scripts/init_env.py --status
python scripts/init_env.py --check
python scripts/init_env.py --overview
python scripts/init_env.py --status --json
python scripts/init_env.py --migration-plan --shell auto
python scripts/init_env.py --dashboard
python scripts/init_env.py --guide
python scripts/init_env.py --check-updates
python scripts/init_env.py --export --out ./backup.zip
python scripts/init_env.py --import ./backup.zip --dry-run

# Validation stricte du plugin
python scripts/validate.py --strict
```

# Gravity — Socle Central & Écosystème Modulaire

**Gravity** (`BSourichanh/gravity`, v0.2.0, licence MIT) est le **plugin cœur** de l'écosystème modulaire **Gravity** pour **Google Antigravity**.
Il unifie l'environnement centralisé (`~/.gemini/gravity/`), la découverte et validation des modules via `config/module.json` v1 (`core/modules.json`), ainsi que la future interface utilisateur MCP App unifiée (`v0.3.0`).

> **Clarification importante :**
> - **`gravity`** (`/gravity`) est le socle central et hôte du registre des modules.
> - **`gravity-workflow`** (`/gravity-workflow`, `/caveman`) est l'ancien harnais renommé (multi-agents, workflows, garde-fous `PreToolUse`, evals).
> - **`gravity-workshop`** est l'espace séparé de conception, spécifications et suivi multi-projets (hors des dépôts plugins).

Tous les plugins de la suite reposent sur une pile **100 % bibliothèque standard Python 3.10+**, sans dépendance externe.

## Écosystème des 4 plugins

| Module (`id`) | Plugin & Dépôt | Commande(s) | Stockage centralisé (`$GRAVITY_HOME/...`) | Rôle |
|---|---|---|---|---|
| `core` | [**Gravity**](https://github.com/BSourichanh/gravity) (`gravity` v0.3.0) | `/gravity` | `core/` (`$GRAVITY_CORE_HOME`) | Initialisation environnement, registre `core/modules.json` et hôte UI unifié (SPI) |
| `architect` | [**Gravity Architect**](https://github.com/BSourichanh/gravity-architect) (`gravity-architect` v0.5.0) | `/gravity-architect` | `architect/` (`$GRAVITY_ARCHITECT_HOME`) | Conception, intégrité écosystème, stockage Hot/Cold, veille plateforme et mise à niveau |
| `workflow` | [**Gravity Workflow**](https://github.com/BSourichanh/gravity-workflow) (`gravity-workflow` v0.3.0) | `/gravity-workflow`, `/caveman` | `workflow/` (`$GRAVITY_WORKFLOW_HOME`) | Harnais multi-agents, workflows orchestrateurs, garde-fous fail-closed, evals et routage adaptatif |
| `metrics` | [**Gravity Metrics**](https://github.com/BSourichanh/gravity-metrics) (`gravity-metrics` v0.5.0) | `/gravity-metrics` | `metrics/` (`$GRAVITY_METRICS_HOME`) | Collecte de métriques Antigravity, coûts/tokens et signaux pour le mode `auto` |

## Installation & prise en main

```powershell
# Vérifier l'environnement et l'état cible sans rien modifier
python install.py --check

# Installer globalement (~/.gemini/config/plugins/gravity)
python install.py

# Remplacer une ancienne installation du harnais 'gravity' par Gravity Core v0.2.0
python install.py --force

# Installer dans un workspace dédié (.agents/plugins/gravity)
python install.py --scope workspace --workspace /chemin/vers/projet
```

### Orchestrateur multi-dépôts hors-ligne (`scripts/ecosystem_install.py`)

Permet d'inspecter, installer, mettre à jour ou désinstaller localement la suite Gravity dans l'ordre topologique (`gravity` → `gravity-workflow` → `gravity-metrics` → `gravity-architect`, inversé lors de `--uninstall`), sans aucun appel réseau :

```powershell
# Vérification en lecture seule par défaut (suite complète --tier 3)
python scripts/ecosystem_install.py

# Installer l'essentiel (--tier 1) ou le pilotage (--tier 2) ou la suite complète (--tier 3)
python scripts/ecosystem_install.py --install --tier 2 --dry-run
python scripts/ecosystem_install.py --install --tier 3

# Mettre à jour (--force) un sous-ensemble explicite et rafraîchir core/modules.json
python scripts/ecosystem_install.py --update --modules gravity,gravity-metrics --json

# Désinstaller en ordre topologique inversé (gravity Core en dernier, données $GRAVITY_HOME préservées)
python scripts/ecosystem_install.py --uninstall --dry-run
```

### Auditeur de dérive multi-dépôts (`scripts/audit_ecosystem.py`)

Contrôle en **lecture seule stricte** (100 % stdlib Python 3.10+, inspection AST/statique) l'alignement des 4 dépôts plugins (`--repos-root`, `--repos`, `--json`, `--strict`) : contrat CLI `install.py` (11 drapeaux), contrat `validate.py`, budgets `AGENTS.md` / D4, synchronisation `plugin.json` ↔ `CHANGELOG.md` + `suggestedPrompts` et dette monolithique `plugin/**/*.py` (avec exemption `plugin/mcp/ui/*.py`) :

```powershell
# Audit synthétique de l'écosystème local
python scripts/audit_ecosystem.py

# Mode CI strict (échoue sur avertissement) avec sortie JSON
python scripts/audit_ecosystem.py --strict --json
```

### Initialiser et inspecter l'environnement Gravity

```powershell
# Initialiser ~/.gemini/gravity/core/modules.json et les sous-dossiers des modules découverts
python plugin/scripts/init_env.py

# Lecture seule : statut des modules et détection d'anciens dossiers legacy (texte compact ou --json)
python plugin/scripts/init_env.py --status
python plugin/scripts/init_env.py --check
python plugin/scripts/init_env.py --status --json

# Générer un plan de migration legacy en 4 étapes non destructives (100 % lecture seule)
python plugin/scripts/init_env.py --migration-plan --shell auto
python plugin/scripts/init_env.py --migration-plan --shell bash --json

# Diagnostiquer la MCP App unifiée et les onglets du dashboard (100 % lecture seule)
python plugin/scripts/init_env.py --dashboard
python plugin/scripts/init_env.py --dashboard --json

# Guide rapide lecture seule (boucle 3 temps, commandes des modules détectés, pointeurs docs/)
python plugin/scripts/init_env.py --guide
python plugin/scripts/init_env.py --guide --json
```

Dans Antigravity, utiliser le skill **`/gravity [init|status|modules|doctor|dashboard|update|help]`** ou ouvrir directement le tableau de bord depuis **Plugins -> Gravity** (`open_gravity_dashboard`, 0 token interactif).
Les anciens répertoires éventuels (`~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`) sont détectés en **lecture seule uniquement** : rien n'est jamais modifié ni supprimé automatiquement.

## Parcours utilisateur & Guides UX (`docs/`)

- **Démarrer en 5 minutes :** [`docs/getting-started.md`](docs/getting-started.md) *(prérequis, 3 paliers, séquences PowerShell/bash, check-list)*
- **Parcours complet :** [`docs/user-journey.md`](docs/user-journey.md) *(diagramme, scénario fil rouge Paliers 1→3, matrice 7 phases, frontières d'or)*
- **Aide-mémoire des commandes :** [`docs/command-cheatsheet.md`](docs/command-cheatsheet.md) *(matrice intentionnelle `/gravity*`, `/caveman`, `/learn`, anti-patterns)*
- **Dépannage & cycle de vie :** [`docs/troubleshooting-and-lifecycle.md`](docs/troubleshooting-and-lifecycle.md) *(mises à jour `--update`, migration 4 étapes, dépannage Windows/POSIX, `--uninstall`)*

## Documentation technique & vérifications

- Index documentation : [`docs/README.md`](docs/README.md)
- Architecture modulaire & signaux : [`docs/architecture.md`](docs/architecture.md)
- Contrat module v1 : [`docs/module-contract.md`](docs/module-contract.md)
- Standard des dépôts : [`docs/repo-standard.md`](docs/repo-standard.md)
- Feuille de route : [`docs/roadmap.md`](docs/roadmap.md)
- Historique des versions : [`CHANGELOG.md`](CHANGELOG.md)
- Licence : [`LICENSE`](LICENSE)

```powershell
# Validation stricte du plugin et du standard D4 / SKILL.md (sans BOM, LF, budgets)
python plugin/scripts/validate.py --strict
agy plugin validate ./plugin --strict
python -m unittest discover -s tests -p "test_*.py" -v
```

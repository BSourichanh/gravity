# Gravity — Socle Central & Écosystème Modulaire

**Gravity** (`BSourichanh/gravity`, v0.3.0, licence MIT) est le **plugin cœur** de l'écosystème modulaire **Gravity** pour **Google Antigravity**.
Il unifie l'environnement centralisé (`~/.gemini/gravity/`), le socle partagé SSOT (`shared/gravity_shared/` projeté vers `*/plugin/_shared/` avec vérification SHA-256), la découverte et validation des modules via `config/module.json` v1 (`core/modules.json`), la vue d'ensemble 0-token (`/gravity` via `PreInvocation`) ainsi que l'interface utilisateur **MCP App unifiée** (`gravity_dashboard`, `SPI-1`).

> **Clarification importante :**
> - **`gravity`** (`/gravity`) est le socle central, hôte du registre des modules et SSOT de `gravity_shared`.
> - **`gravity-workflow`** (`/gravity-workflow`, `/caveman`) est l'ancien harnais renommé (multi-agents Swarm par défaut, workflows, garde-fous `PreToolUse`, evals).
> - **`gravity-workshop`** est l'espace séparé de conception, spécifications et suivi multi-projets (hors des dépôts plugins).

Tous les plugins de la suite reposent sur une pile **100 % bibliothèque standard Python 3.10+**, sans dépendance externe.

## Écosystème des 4 plugins

| Module (`id`) | Plugin & Dépôt | Commande(s) | Stockage centralisé (`$GRAVITY_HOME/...`) | Rôle |
|---|---|---|---|---|
| `core` | [**Gravity**](https://github.com/BSourichanh/gravity) (`gravity` v0.3.0) | `/gravity` | `core/` (`$GRAVITY_CORE_HOME`) | Environnement `$GRAVITY_HOME`, registre `core/modules.json`, SSOT `shared/gravity_shared/` et hôte UI unifié (`SPI-1`) |
| `architect` | [**Gravity Architect**](https://github.com/BSourichanh/gravity-architect) (`gravity-architect` v0.5.1) | `/gravity-architect` | `architect/` (`$GRAVITY_ARCHITECT_HOME`) | Conception, intégrité écosystème, stockage Hot/Cold, `waves.py`, veille et `SPI-1`/`SPI-2` |
| `workflow` | [**Gravity Workflow**](https://github.com/BSourichanh/gravity-workflow) (`gravity-workflow` v0.4.0) | `/gravity-workflow`, `/caveman` | `workflow/` (`$GRAVITY_WORKFLOW_HOME`) | Harnais multi-agents (Swarm par défaut), garde-fous fail-closed, evals, routage adaptatif et `SPI-1`/`SPI-3` |
| `metrics` | [**Gravity Metrics**](https://github.com/BSourichanh/gravity-metrics) (`gravity-metrics` v0.5.1) | `/gravity-metrics` | `metrics/` (`$GRAVITY_METRICS_HOME`) | Collecte coûts/tokens/jalons, signaux `signal_bus` (`SPI-3`), `capture_policy` (`SPI-2`) et `SPI-1` |

## Installation & prise en main

```powershell
# Vérifier l'environnement et l'état cible sans rien modifier
python install.py --check

# Installer globalement (~/.gemini/config/plugins/gravity)
python install.py

# Remplacer une ancienne installation du harnais 'gravity' par Gravity Core v0.3.0
python install.py --force

# Installer dans un workspace dédié (.agents/plugins/gravity)
python install.py --scope workspace --workspace /chemin/vers/projet
```

### Socle partagé SSOT (`shared/gravity_shared/` & `scripts/sync_shared.py`)

`gravity/shared/gravity_shared/` héberge les 9 modules transverses 100 % stdlib Python 3.10+ (`__init__.py`, `atomic_io.py`, `file_lock.py`, `path_safety.py`, `hook_runtime.py`, `transcript_reader.py`, `installer_core.py`, `validator_core.py`, `signal_bus.py`), projetés en lecture seule dans `*/plugin/_shared/` avec manifeste SHA-256 (`.shared_manifest.json`) :

```powershell
# Vérifier la parité SHA-256 des copies _shared/ (fail-closed)
python scripts/sync_shared.py --check

# Projeter ou resynchroniser _shared/ sur les dépôts plugins
python scripts/sync_shared.py --apply --repos gravity,gravity-workflow,gravity-metrics,gravity-architect
```

### Orchestrateur multi-dépôts hors-ligne (`scripts/ecosystem_install.py`)

Permet d'inspecter, installer, mettre à jour ou désinstaller localement la suite Gravity dans l'ordre topologique (`gravity` → `gravity-workflow` → `gravity-metrics` → `gravity-architect`, inversé lors de `--uninstall`), sans aucun appel réseau, avec pré-contrôle `sync_shared` :

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

### Auditeur de dérive multi-dépôts (`scripts/audit_ecosystem.py` & `scripts/audit_checks.py`)

Contrôle en **lecture seule stricte** (100 % stdlib Python 3.10+, inspection AST/statique) l'alignement des 4 dépôts plugins (`--repos-root`, `--repos`, `--check-installed`, `--plugins-dir`, `--verify-parallel`, `--json`, `--strict`) : contrat CLI `install.py` (11 drapeaux), contrat `validate.py`, `INT-01..08`, contrats `SPI-1..3`, parité SHA-256 `_shared/`, garde `AUD-05-09`, budgets `AGENTS.md` / D4, synchronisation `plugin.json` ↔ `CHANGELOG.md` + `suggestedPrompts` et plafond strict `<= 800` L par fichier `plugin/**/*.py` :

```powershell
# Audit synthétique de l'écosystème local et vérification des copies installées
python scripts/audit_ecosystem.py
python scripts/audit_ecosystem.py --check-installed --plugins-dir ~/.gemini/config/plugins

# Mode CI strict et validation parallèle des 4 dépôts (validate + agy + unittest)
python scripts/audit_ecosystem.py --strict --json
python scripts/audit_ecosystem.py --verify-parallel --strict
```

### Initialiser et inspecter l'environnement Gravity

```powershell
# Initialiser ~/.gemini/gravity/core/modules.json et les sous-dossiers des modules découverts
python plugin/scripts/init_env.py

# Lecture seule : statut, vérification, vue d'ensemble 0-token, migration, dashboard, guide
python plugin/scripts/init_env.py --status
python plugin/scripts/init_env.py --check
python plugin/scripts/init_env.py --overview
python plugin/scripts/init_env.py --status --json
python plugin/scripts/init_env.py --migration-plan --shell auto
python plugin/scripts/init_env.py --dashboard
python plugin/scripts/init_env.py --guide

# Mises à jour & sauvegarde portable (ZIP SHA-256)
python plugin/scripts/init_env.py --check-updates
python plugin/scripts/init_env.py --update --offline --dry-run
python plugin/scripts/init_env.py --set-drive-dir /chemin/vers/GoogleDrive/Gravity
python plugin/scripts/init_env.py --export --out ./backup.zip
python plugin/scripts/init_env.py --import ./backup.zip --dry-run
```

Dans Antigravity, `/gravity` nu répond à **0 token** via `PreInvocation` (`hooks/pre_invocation_gravity.py` → `--overview`), les sous-commandes utilisent **`/gravity [init|status|modules|doctor|dashboard|update|export|import|help]`**, et le tableau de bord unifié (`open_gravity_dashboard`, 0 token interactif) s'ouvre depuis **Plugins -> Gravity**.
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

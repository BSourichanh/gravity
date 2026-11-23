# Changelog

Toutes les modifications notables de **Gravity Core** (`BSourichanh/gravity`) sont consignées ici.
Format basé sur *Keep a Changelog* et *Semantic Versioning*.

## [Unreleased]

### Added
- **Serveur MCP App stdio, UI HTML/SVG SEP-1865 & outillage (Phase 4 / Lot 1B) :**
  - Configuration portable `plugin/mcp_config.json` (`"command": "python3"`) et serveur JSON-RPC 2.0 100 % stdlib (`plugin/mcp/server.py`, `plugin/mcp/__init__.py`) exposant `open_gravity_dashboard` (`aux_pane` / `global`, plafond `<= 450 000` o) et 5 outils applicatifs `gravity_get_*` (`visibility: ["app"]`).
  - Générateur HTML5/SVG autonome (`plugin/mcp/widget_html.py`, `plugin/mcp/ui/`) sans `innerHTML`, sans URL externe ni dialogue natif : vues dynamiques `Overview / Doctor`, `Workflow Live` (polling `~1 500 ms` via `since_signature`), `Metrics` lecture seule (KPIs, graphe SVG `by_project`, tiroir détail, Pending/Lifecycle, Audits Agents, ouverture `.md` via `com.google.antigravity/toggle-aux-pane`) et inspecteur générique OCP.
  - Mode lecture seule `plugin/scripts/init_env.py --dashboard` (`--json` et texte compact) pour diagnostiquer `mcp_config.json`, `mcp/server.py`, `dashboard/api.py`, `python3` et les onglets découverts.
  - Mises à jour de `plugin/scripts/validate.py` (`_validate_mcp_config`, `_run_mcp_dry_run`, `--fix-python-cmd`, `SKILL.md` `dashboard`), `install.py` (`mcp/server.py` dans `EXEC_SCRIPTS`, `--no-fix-python`, adaptation Windows sur copie stagée), `/gravity dashboard` dans `plugin/skills/gravity/SKILL.md`, `plugin/rules/AGENTS.md`, `docs/`, `README.md`, `plugin/README.md` et suites de tests isolées (`tests/test_mcp_server.py`, `tests/test_validate.py`, `tests/test_install.py`, `tests/test_init_env.py`).
- **Socle dashboard lecture seule (`plugin/dashboard/`)** en 100 % stdlib Python 3.10+ (Phase 4 / Lot 1A) :
  - Façade unifiée (`plugin/dashboard/api.py`, `plugin/dashboard/__init__.py`) et providers découplés OCP (`plugin/dashboard/providers/`) avec fast-path `since_signature` et plafond payload `< 450 KiB` : `core_provider` (lecture `core/modules.json` / repli `discover_modules`, enrichissement `resolved_home`/`home_exists`, `doctor`, `tabs`, `legacy_homes`), `generic_provider` (validation `MODULE_ID_RE`, métadonnées contrat, listing superficiel `<= 25` entrées sans suivi de symlinks), `workflow_provider` (schéma `gravity-workflow v0.3.0`, garde-fou `live_state.json`, replis central/local RO, bornage 50 événements) et `metrics_provider` (`history.jsonl` `v0.5.0`/`v0.4.3`, KPIs, lifecycle/pending sans scan `brain/`, audits `audits/agents/` hors `audits/code/` et `_*`, `get_session_detail` confiné dans `reports/` sans trajectoire brute).
  - Mise à jour de `plugin/scripts/validate.py` (`"dashboard"` dans `ALLOWED_LOCAL_MODULES` et `REQUIRED_DIRS`) et ajout des suites isolées `tests/test_dashboard_providers.py` et `tests/test_validate.py`.

## [0.2.0] - 2026-11-23

### Added
- **Orchestrateur multi-dépôts hors-ligne (`scripts/ecosystem_install.py`)** en 100 % stdlib Python 3.10+ (`subprocess.run(..., shell=False)`, zéro appel réseau) : ordre topologique fixe (`gravity` 1er à l'installation/mise à jour, dernier à la désinstallation), sélection mutuellement exclusive `--tier {1,2,3}` / `--modules`, modes `--check` (défaut), `--install`, `--update` (`--force`), `--uninstall`, options propagées (`--dry-run`, `--scope`, `--workspace`, `--method`, `--strict`, `--skip-validate`), `--repos-root`, `--json`, contrôle fail-closed et rafraîchissement automatique de `$GRAVITY_HOME/core/modules.json`.
- **Plan de migration legacy 100 % lecture seule (`plugin/scripts/init_env.py --migration-plan`)** avec `--shell {auto,powershell,bash}` : inventaire des fichiers/octets sans suivi de symlinks, détection des collisions avec `$GRAVITY_HOME/<target_module>/` et plan non destructif en 4 étapes (sauvegarde horodatée, copie sans écrasement `Copy-Item` / `cp -n`, vérification `--check`, nettoyage commenté `#`), zéro écriture disque.
- **Documentation & tests :** contrat CLI commun à 11 drapeaux sur les `install.py` dans `docs/repo-standard.md`, mention `--migration-plan` dans `plugin/skills/gravity/SKILL.md` sous `/gravity doctor`, mise à jour `README.md` / `plugin/README.md`, et suites `unittest` isolées `tests/test_ecosystem_install.py` et `tests/test_migration_plan.py`.

### Changed
- **Note 6, compaction `rules/AGENTS.md` & durcissement D4 (`plugin/skills/gravity/SKILL.md`, `plugin/rules/AGENTS.md`, `docs/repo-standard.md`, `plugin/scripts/validate.py`) :**
  - Note 6 dans `plugin/skills/gravity/SKILL.md` (`<= 1 800 o`) : bascule vers la sortie texte compacte par défaut (`init_env.py`, `--status`, `--check`) pour `/gravity init`, `/gravity` / `/gravity status` et `/gravity doctor` (avec `--migration-plan`), tout en réservant `--status --json` à `/gravity modules` et aux appels scriptés.
  - Compaction de `plugin/rules/AGENTS.md` à `<= 520 o` sans perte d'invariant (`gravity` vs `gravity-workflow`, CLI non-interactif, `$GRAVITY_HOME` 100 % centralisé, legacy lecture seule stricte).
  - Promotion de `600 < len <= 1 000 o` sur `plugin/rules/AGENTS.md` de `report.info` à `report.warn` dans `plugin/scripts/validate.py` (bloquant sous `--strict`) et ajout du contrôle `SKILL.md <= 6 000 o` UTF-8 sans BOM/LF dans `_validate_skills()`.
  - Alignement de `docs/repo-standard.md` (§1 & §4), `tests/test_validate.py`, `README.md` et `plugin/README.md`.
- **Standard `AGENTS.md` D4 & validateur (`docs/repo-standard.md`, `plugin/scripts/validate.py`, `AGENTS.md`) :**
  - Double seuil harmonisé pour `plugin/rules/AGENTS.md` : cible éditoriale `<= 600 o` (`report.info` entre `601` et `1 000 o`), plafond strict bloquant abaissé à `<= 1 000 o` UTF-8 sans BOM/LF et zéro frontmatter YAML.
  - Contrôle de `AGENTS.md` racine (`<= 2 500 o` UTF-8, sans BOM, LF) dans `validate_plugin()` via `_validate_repo_agents_md()` lorsque `root.name == "plugin"`.
  - Documentation de l'exception SRP volontaire pour `gravity-workflow/plugin/rules/` et compaction de `AGENTS.md` racine (`<= 1 650 o`) sans perte d'invariant.
  - Mise à jour de `tests/test_validate.py` et `README.md`.

## [0.1.0] - 2026-11-22

### Added
- **Plugin Gravity Core (`plugin/`)** en 100 % bibliothèque standard Python 3.10+ :
  - Manifeste officiel Antigravity 9 champs (`plugin/plugin.json`) et logo carré SVG (`plugin/assets/logo.svg`).
  - Contrat module v1 (`plugin/config/module.json`, `id: "core"`, stockage `$GRAVITY_CORE_HOME` / `~/.gemini/gravity/core/`).
  - Moteur de résolution et registre (`plugin/core/registry.py`) : `resolve_gravity_home`, `resolve_module_home`, `validate_module_contract`, `discover_modules`, `detect_legacy_homes` (lecture seule), `write_modules_registry` (écriture atomique UTF-8 sans BOM).
  - CLI non-interactive (`plugin/scripts/init_env.py`) avec options `--gravity-home`, `--plugins-dir`, `--status`, `--check`, `--json`.
  - Validateur strict autonome (`plugin/scripts/validate.py`) avec audit contrat v1, AST stdlib-only et dry-run E2E isolé.
  - Skill `/gravity` (`plugin/skills/gravity/SKILL.md`) pour `/gravity [init|status|modules|doctor]` et règle légère (`plugin/rules/AGENTS.md` < 2048 o).
- **Installeur cross-platform (`install.py`)** avec `--scope`, `--workspace`, `--target`, `--method`, `--force` (remplacement propre d'une ancienne installation du harnais `gravity`), `--skip-validate`, `--dry-run`, `--check`, `--uninstall` et swap atomique / repli in-place Windows.
- **Documentation & tests :** `README.md`, `plugin/README.md`, `AGENTS.md`, `docs/` (`architecture.md`, `module-contract.md`, `repo-standard.md`, `roadmap.md`) et suite `unittest` isolée dans `tests/`.

### Removed
- Retrait des anciens artefacts atelier (`ECOSYSTEM.md`, `ROADMAP.md`, `projects.json`, `specs/`, `handoffs/`, `tracking/`, `archives/`, `templates/`), déplacés vers `gravity-studio` afin de garder les dépôts produits strictement autonomes.

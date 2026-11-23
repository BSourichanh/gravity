# Changelog

Toutes les modifications notables de **Gravity Core** (`BSourichanh/gravity`) sont consignées ici.
Format basé sur *Keep a Changelog* et *Semantic Versioning*.

## [Unreleased]

### Added
- **Orchestrateur multi-dépôts hors-ligne (`scripts/ecosystem_install.py`)** en 100 % stdlib Python 3.10+ (`subprocess.run(..., shell=False)`, zéro appel réseau) : ordre topologique fixe (`gravity` 1er à l'installation/mise à jour, dernier à la désinstallation), sélection mutuellement exclusive `--tier {1,2,3}` / `--modules`, modes `--check` (défaut), `--install`, `--update` (`--force`), `--uninstall`, options propagées (`--dry-run`, `--scope`, `--workspace`, `--method`, `--strict`, `--skip-validate`), `--repos-root`, `--json`, contrôle fail-closed et rafraîchissement automatique de `$GRAVITY_HOME/core/modules.json`.
- **Plan de migration legacy 100 % lecture seule (`plugin/scripts/init_env.py --migration-plan`)** avec `--shell {auto,powershell,bash}` : inventaire des fichiers/octets sans suivi de symlinks, détection des collisions avec `$GRAVITY_HOME/<target_module>/` et plan non destructif en 4 étapes (sauvegarde horodatée, copie sans écrasement `Copy-Item` / `cp -n`, vérification `--check`, nettoyage commenté `#`), zéro écriture disque.
- **Documentation & tests :** contrat CLI commun à 11 drapeaux sur les `install.py` dans `docs/repo-standard.md`, mention `--migration-plan` dans `plugin/skills/gravity/SKILL.md` sous `/gravity doctor`, mise à jour `README.md` / `plugin/README.md`, et suites `unittest` isolées `tests/test_ecosystem_install.py` et `tests/test_migration_plan.py`.

### Changed
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

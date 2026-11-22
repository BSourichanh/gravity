# Changelog

Toutes les modifications notables de **Gravity Core** (`BSourichanh/gravity`) sont consignées ici.
Format basé sur *Keep a Changelog* et *Semantic Versioning*.

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

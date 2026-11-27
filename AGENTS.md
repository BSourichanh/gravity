# Gravity Core — Instructions Agents

## Périmètre & Architecture
Socle central **Gravity** (`BSourichanh/gravity`, `v0.3.0` sur `dev`), distinct de **`gravity-workflow`** (`/gravity-workflow`) et **`gravity-workshop`** :
- `plugin/` : manifeste 9 champs (`plugin.json`), contrat `config/module.json` (`id: "core"`), `core/` (registre, doctor, overview, bundle, updater), `dashboard/` (`SPI-1` & providers), `mcp/` (serveur MCP App & UI pure-DOM), `hooks/` (`PreInvocation`), CLI (`scripts/init_env.py`), skill `/gravity`, `rules/AGENTS.md`, `_shared/` (projection RO), `scripts/validate.py`.
- `shared/gravity_shared/` (SSOT stdlib 9 modules), `scripts/{sync_shared,audit_ecosystem,ecosystem_install}.py`, `install.py` (installeur cross-platform), `docs/` (parcours, architecture, contrat module, standard dépôts, roadmap), `tests/` (`unittest` isolée).

## Invariants
- **Git & versioning (chef d'orchestre uniquement) :** dev sur `dev` (jamais sur `main`) ; fusion `main` et tag `vX.Y.Z` aux releases sur accord utilisateur ; *Conventional Commits* ; SemVer dans `plugin/plugin.json` + `CHANGELOG.md` ; sous-agents/workers `swarm` ne committent, poussent ni taguent.
- **Qualité & stdlib Python 3.10+ :** **KISS, YAGNI, DRY, SOLID, CUPID** ; 100 % stdlib dans `plugin/`, `install.py`, `tests/` ; UTF-8 sans BOM, LF.
- **Stockage & legacy :** état sous `$GRAVITY_HOME` (défaut `~/.gemini/gravity/`, `core/modules.json`) ; zéro fichier en workspace cible ; anciens dossiers (`~/.gemini/gravity-*`, `~/.gravity`) en lecture seule stricte.
- **Docs synchronisées :** toute évolution met à jour `README.md`, `plugin/README.md`, `docs/` et `CHANGELOG.md`.

## Vérifications obligatoires
- `python3 scripts/sync_shared.py --check --repos gravity`
- `python3 plugin/scripts/validate.py --strict`
- `agy plugin validate ./plugin --strict`
- `python3 -m unittest discover -s tests -p "test_*.py" -v`

# Gravity Core — Instructions Agents

## Périmètre & Architecture
Socle central et plugin maître de l'écosystème **Gravity** (`BSourichanh/gravity`, v0.1.0), distinct du harnais **`gravity-workflow`** (`/gravity-workflow`) et de l'atelier de conception **`gravity-studio`** :
- `plugin/` : manifeste officiel 9 champs (`plugin.json`), contrat `config/module.json` (`id: "core"`), registre et résolution de stockage (`core/registry.py`), CLI non-interactive (`scripts/init_env.py`), skill `/gravity`, règle légère (`rules/AGENTS.md`) et validateur (`scripts/validate.py`).
- `install.py` : installeur/désinstalleur cross-platform ; `docs/` : architecture, contrat module, standard des dépôts et feuille de route ; `tests/` : suite `unittest` isolée.

## Invariants
- **Branche de développement (`dev`) obligatoire :** tout développement s'effectue sur `dev` (jamais directement sur `main`).
- **Git & versioning (chef d'orchestre uniquement) :** fusion vers `main` et tag annoté `vX.Y.Z` uniquement aux releases sur accord utilisateur ; *Conventional Commits* ; SemVer synchronisé dans `plugin/plugin.json` + `CHANGELOG.md`. Sous-agents et workers `swarm` ne committent, ne poussent et ne taguent jamais.
- **Qualité logicielle & 100 % stdlib Python 3.10+ :** appliquer **KISS, YAGNI, DRY, SOLID, CUPID** ; zéro dépendance tierce dans `plugin/`, `install.py` et `tests/` ; encodage UTF-8 sans BOM et fins de ligne LF.
- **Stockage centralisé & sûreté legacy :** tout état vit sous `$GRAVITY_HOME` (défaut `~/.gemini/gravity/`, registre `core/modules.json`) ; zéro fichier créé dans les workspaces cibles ; détection des anciens dossiers (`~/.gemini/gravity-*`, `~/.gravity`) en lecture seule stricte.
- **Documentation synchronisée :** toute évolution fonctionnelle ou structurelle met à jour `README.md`, `plugin/README.md`, `docs/` et `CHANGELOG.md` dans le même lot.

## Vérifications obligatoires
- `python plugin/scripts/validate.py --strict`
- `agy plugin validate ./plugin --strict`
- `python -m unittest discover -s tests -p "test_*.py" -v`

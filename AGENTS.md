# Gravity Repository — Instructions Agents

## Invariants du dépôt
- **100 % bibliothèque standard Python 3** (aucune dépendance tierce dans `gravity-plugin/`, `workspace-template/`, `install.py` ou `tests/`).
- **Documentation vivante (`docs/`) :** toute modification fonctionnelle ou structurelle dans `gravity-plugin/`, `workspace-template/` ou `install.py` doit mettre à jour la fiche correspondante dans [`docs/`](docs/README.md) dans le même lot de travail.
- **Intégrité du socle (`gravity-plugin/` & `workspace-template/`) :** ne modifie `workspace-template/` ou `gravity-plugin/` que sur demande explicite, en conservant `hooks.json` et `sidecar.json` portables (`python3`) dans le dépôt source, et vérifie avec :
  - `python gravity-plugin/scripts/validate.py --strict`
  - `python gravity-plugin/scripts/validate.py --workspace workspace-template --strict`
  - `python gravity-plugin/scripts/test_unit.py`
  - `python -m unittest discover -s tests -p "test_*.py" -v`
- **Zéro jargon interdit :** n'emploie jamais `Module XX` dans `gravity-plugin/skills/` ni dans `docs/`.
- **Périmètre métriques séparé :** la collecte des coûts, tokens et historiques de sessions Antigravity est gérée dans le dépôt frère `../gravity-metrics`.

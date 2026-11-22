# Gravity Core — Règle légère

- **`gravity` vs `gravity-workflow` :** `gravity` (`/gravity`) est le socle central de l'écosystème (environnement, registre des modules et future UI unifiée). Le harnais multi-agents/workflows/garde-fous est **`gravity-workflow`** (`/gravity-workflow`, `/caveman`).
- **Commandes `/gravity` :** exécuter `scripts/init_env.py` depuis la racine du plugin installé en mode non-interactif (`--json`, `--status`, `--check`).
- **Stockage 100 % centralisé :** toutes les données vivent sous `$GRAVITY_HOME` (défaut `~/.gemini/gravity/`, registre `core/modules.json` et `<gravity_home>/<module>/`). Ne jamais écrire de fichier Gravity dans le workspace utilisateur cible.
- **Sûreté legacy :** détecter uniquement en lecture seule les anciens dossiers (`~/.gemini/gravity-bridge`, `~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow`, `~/.gravity`) sans jamais supprimer ni déplacer leurs données automatiquement.

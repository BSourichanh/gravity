# Gravity Core

- `gravity` (`/gravity`) gère `$GRAVITY_HOME` et le registre des modules ; le harnais multi-agents/workflows est `gravity-workflow` (`/gravity-workflow`, `/caveman`).
- `/gravity` : exécuter `scripts/init_env.py` en non-interactif (`--status`, `--check`, `--migration-plan`, `--json`).
- Stockage 100 % sous `$GRAVITY_HOME` (`~/.gemini/gravity/`) ; 0 fichier en workspace cible.
- Legacy : lecture seule stricte (aucun déplacement ni suppression).

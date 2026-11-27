# Gravity Core

- `gravity` (`/gravity`) gère `$GRAVITY_HOME` et le registre des modules ; le harnais multi-agents/workflows est `gravity-workflow` (`/gravity-workflow`, `/caveman`).
- `/gravity` : `scripts/init_env.py` (`--overview`, `--status`, `--check`, `--migration-plan`, `--dashboard`, `--update`, `--export`, `--import`, `--guide`, `--json`) ; UI via `open_gravity_dashboard`.
- Stockage 100 % sous `$GRAVITY_HOME` (`~/.gemini/gravity/`) ; 0 fichier en workspace cible.
- Legacy : lecture seule stricte (aucun déplacement ni suppression).

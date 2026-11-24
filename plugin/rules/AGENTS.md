# Gravity Core

- `gravity` (`/gravity`) gère `$GRAVITY_HOME`, le registre et la MCP App unifiée (`open_gravity_dashboard`) ; le harnais multi-agents/workflows est `gravity-workflow`.
- `/gravity` nu passe par `PreInvocation` (`--overview`, 0 token) ; sous-commandes via `scripts/init_env.py` (`--status`, `--check`, `--migration-plan`, `--dashboard`, `--guide`, `--json`).
- Stockage 100 % sous `$GRAVITY_HOME` (`~/.gemini/gravity/`) ; 0 fichier en workspace cible ; legacy en lecture seule stricte.

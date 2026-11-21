#!/usr/bin/env python3
"""Initialiseur du socle vital Gravity dans un projet cible (appelé par /gravity, 100 % stdlib)."""

import argparse
import shutil
from pathlib import Path
from typing import Dict

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

AGENTS_MD = """# Charte Projet — Agents Antigravity

## Identité & Livrable
- **Domaine :** <Décrire le projet et son processus répétitif cible>
- **Livrable principal :** <PR / Patch / Rapport structuré / Audit JSON>
- **Sources de vérité :** <Chemins vers les specs, schémas ou docs de référence>

## Règles de travail
1. Toujours respecter `.agents/rules/01-safety-boundaries.md` (`trigger: always_on`, préfixe statique conservé pour optimiser le Context Caching Gemini).
2. Ne jamais écraser un fichier existant sans diff préalable validé par l'utilisateur.
3. Privilégier les outils natifs (`/browser`, terminal sandbox, outils fichiers) avant tout connecteur MCP.
4. Soumettre tout livrable significatif au sous-agent `reviewer` (indépendant, à froid) avant clôture.
5. En cas de correction manuelle ou d'incident, appliquer la double boucle `/learn` : proposer une règle ciblée (`learning_proposal.md` validé avant écriture) et ajouter un cas de non-régression dans `.agents/gravity/evals/cases.json`.
"""

MCP_CONFIG_JSON = """{
  "mcpServers": {}
}
"""

RULE_01_SAFETY = """---
trigger: always_on
description: Lignes rouges absolues du projet (chargées à chaque tour, < 2 Ko).
---

# Frontières de sécurité absolues

1. **Secrets :** Interdiction absolue de lire, rechercher, afficher, journaliser ou commiter `.env`, `secrets/`, clés privées (`.pem`, `.key`, clés SSH `id_rsa`/`id_ed25519`), `printenv`/`env`/`Get-ChildItem Env:` ou jetons d'API.
2. **Commandes & workflows destructeurs :** Interdiction de `rm -rf`/`rm --recursive --force` ou `Remove-Item -Recurse -Force` destructeurs, `git push --force`/`-f`/`+ref`, suppressions DB (`DROP`/`TRUNCATE`/`FLUSHALL`), `curl|wget` pipés vers un shell, `irm`/`iwr | iex`, et `run_workflow` ciblant secrets ou hooks.
3. **Intégrité du harnais :** Interdiction de modifier ou désactiver les garde-fous Gravity (`hooks.json`, `hooks/` ou ce fichier) sans validation explicite de l'utilisateur.
"""

RULE_02_PYTHON = """---
trigger: glob
globs: '**/*.py'
description: Conventions Python 3 applicables aux scripts du projet et du harnais.
---

- Utiliser exclusivement la bibliothèque standard Python 3 (zéro dépendance externe non approuvée).
- Garantir un code de retour `0` et une sortie JSON conforme sur `stdout` (`{}` strict pour `PostToolUse` et `Stop`) pour tout script de hook.
- Dans les hooks, résoudre les chemins workspace depuis le payload `stdin` (`cwd` / `workspacePaths`).
"""

RULE_03_API = """---
trigger: model_decision
description: Charger uniquement lors de la conception ou modification d'endpoints API, de schémas JSON ou de contrats de données.
---

- Préserver la rétrocompatibilité des champs existants.
- Valider toute sortie structurée contre un JSON Schema strict compatible Gemini.
"""

RULE_04_RELEASE = """---
trigger: manual
description: Checklist de pré-publication invoquée explicitement avant toute release (mention @rule en App/IDE ; lecture directe en CLI agy).
---

- [ ] `python3 <plugin_gravity>/scripts/validate.py --workspace . --strict` passe sans erreur ni avertissement.
- [ ] Suite `/gravity evals` exécutée (12/12 PASS) et checklist `[manual]` arbitrée par un humain.
"""

PROGRESS_FULL_MD = """# Gravity Progress

- **Parcours :** Guidé (0/8)
- **Domaine :** À définir
- **Livrable principal :** À définir
- **Sources de vérité :** À définir
- **3 Lignes rouges :**
  1. Aucune lecture/fuite de secrets (`.env`, `secrets/`, clés SSH/privées, `printenv`)
  2. Aucune commande destructrice système/Git/DB (`rm -rf`, `git push --force`, `DROP DATABASE`)
  3. Auto-protection des hooks et règles de sécurité

## Avancement des étapes
- [ ] Cadrage du projet
- [ ] Socle & règles
- [ ] Équipe & Reviewer indépendant
- [ ] Outils & connexions
- [ ] Routeur & workflows
- [ ] Garde-fous automatiques
- [ ] Tests & évaluations
- [ ] Suivi & boucle `/learn`
- [ ] Tableau de bord (Bonus)
"""

PROGRESS_QUICKSTART_MD = """# Gravity Progress

- **Parcours :** Quick Start [~] 3/8
- **Domaine :** À définir
- **Livrable principal :** À définir
- **Sources de vérité :** À définir
- **3 Lignes rouges :**
  1. Aucune lecture/fuite de secrets (`.env`, `secrets/`, clés SSH/privées, `printenv`)
  2. Aucune commande destructrice système/Git/DB (`rm -rf`, `git push --force`, `DROP DATABASE`)
  3. Auto-protection des hooks et règles de sécurité

## Avancement des étapes
- [x] Cadrage du projet
- [x] Socle & règles
- [x] Équipe & Reviewer indépendant
- [ ] Outils & connexions
- [ ] Routeur & workflows
- [ ] Garde-fous automatiques
- [ ] Tests & évaluations
- [ ] Suivi & boucle `/learn`
- [ ] Tableau de bord (Bonus)
"""

BACKLOG_MD = """# Gravity Backlog — Questions ouvertes & arbitrages différés

- [ ] Ajouter les cas d'évaluation métier spécifiques au projet dans `.agents/gravity/evals/cases.json` au fil des sessions `/learn`.
"""

LIVE_STATE_JSON = """{
  "stage": "idle",
  "progress": "0/8",
  "mode": "evo",
  "level": "medium",
  "pace": "slow",
  "verification": "safe",
  "caveman": "lite",
  "caveman_locked": false,
  "guard_status": "ON",
  "nodes": {
    "planner": "",
    "builder": "",
    "reviewer": ""
  },
  "events": []
}
"""

LIVE_STATE_QUICKSTART_JSON = """{
  "stage": "quickstart",
  "progress": "3/8",
  "mode": "evo",
  "level": "medium",
  "pace": "slow",
  "verification": "safe",
  "caveman": "lite",
  "caveman_locked": false,
  "guard_status": "ON",
  "nodes": {
    "planner": "",
    "builder": "",
    "reviewer": ""
  },
  "events": []
}
"""

PROFILE_JSON = """{
  "schema_version": 1,
  "mode": "evo",
  "current_level": "medium",
  "locked": false,
  "pace": "slow",
  "verification": "safe",
  "caveman": "lite",
  "caveman_locked": false,
  "suggested_level": "medium",
  "allow_pro": true,
  "model_overrides": {},
  "sessions_analyzed": 0,
  "clean_streak": 0,
  "last_score": 40,
  "last_reason": "Initialisation par défaut (mode evo au palier medium).",
  "last_evaluated_conversation_id": null,
  "last_updated": null,
  "signals": {
    "source_files": 0,
    "rules_count": 0,
    "has_tests": false,
    "has_ci": false,
    "mcp_servers": 0,
    "progress_steps": 0,
    "guard_deny_recent": 0,
    "guard_ask_recent": 0,
    "eval_pass_rate": null,
    "session_error": false
  },
  "history": []
}
"""

GRAVITY_GITIGNORE = """# Fichiers temporaires et télémétrie d'exécution Gravity
*.lock
observability/*.lock
observability/runs.jsonl
observability/last_verified.patch
evals/report.json
evals/report.md
"""


def init_workspace(target_root: Path, mode: str = "full", force: bool = False) -> int:
    target_root = target_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    progress_text = PROGRESS_QUICKSTART_MD if mode == "quickstart" else PROGRESS_FULL_MD
    live_state_text = LIVE_STATE_QUICKSTART_JSON if mode == "quickstart" else LIVE_STATE_JSON
    files: Dict[str, str] = {
        "AGENTS.md": AGENTS_MD,
        ".agents/mcp_config.json": MCP_CONFIG_JSON,
        ".agents/rules/01-safety-boundaries.md": RULE_01_SAFETY,
        ".agents/gravity/.gitignore": GRAVITY_GITIGNORE,
        ".agents/gravity/PROGRESS.md": progress_text,
        ".agents/gravity/BACKLOG.md": BACKLOG_MD,
        ".agents/gravity/profile.json": PROFILE_JSON,
        ".agents/gravity/observability/live_state.json": live_state_text,
    }
    if mode == "full":
        files.update(
            {
                ".agents/rules/02-python-stdlib.md": RULE_02_PYTHON,
                ".agents/rules/03-api-architecture.md": RULE_03_API,
                ".agents/rules/04-release-checklist.md": RULE_04_RELEASE,
            }
        )

    for rel_path, content in files.items():
        dest = target_root / rel_path
        if dest.exists() and not force:
            print(f"[SKIP]   {rel_path} (existe déjà, anti-écrasement actif)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        print(f"[CREATE] {rel_path}")

    default_cases = PLUGIN_ROOT / "evals/cases.json"
    dest_cases = target_root / ".agents/gravity/evals/cases.json"
    if default_cases.is_file():
        if dest_cases.exists() and not force:
            print("[SKIP]   .agents/gravity/evals/cases.json (existe déjà, anti-écrasement actif)")
        else:
            dest_cases.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(default_cases, dest_cases)
            print("[CREATE] .agents/gravity/evals/cases.json")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialise le socle vital Gravity dans un projet.")
    parser.add_argument("--workspace", type=Path, default=Path("."), help="Répertoire du projet cible.")
    parser.add_argument(
        "--mode",
        choices=("full", "quickstart"),
        default="full",
        help="Mode d'initialisation : 'quickstart' (socle minimal 10 min) ou 'full' (socle complet).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remplace les fichiers existants (uniquement après validation explicite de l'utilisateur).",
    )
    args = parser.parse_args()
    return init_workspace(args.workspace, mode=args.mode, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

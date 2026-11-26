# Aide-mémoire des commandes — Gravity & Outils natifs

Référence rapide orientée **intention utilisateur**, combinaisons efficaces et anti-patterns à éviter.

---

## 1. Matrice intentionnelle complète

### Socle `gravity` (`/gravity`)

| Je veux… | Commande | Effet exact |
|---|---|---|
| Initialiser l'environnement et le registre | `/gravity init` | Crée `$GRAVITY_HOME/core/modules.json` et les sous-dossiers des modules valides (`init_env.py`) |
| Connaître l'état courant | `/gravity` ou `/gravity status` | Lecture seule : modules actifs, chemins résolus et notices legacy (`--status`) |
| Exporter la liste JSON des contrats | `/gravity modules` | Liste complète des champs `module.json` découverts (`--status --json`) |
| Auditer la santé et préparer une migration | `/gravity doctor` | Vérifie les contrats v1 (`--check`) ; `--migration-plan` génère un plan manuel en 4 étapes |
| Ouvrir l'interface unifiée | `/gravity dashboard` | Ouvre la MCP App `open_gravity_dashboard` (`0` token interactif) ; CLI `--dashboard` audite la config |
| Obtenir un guide contextuel rapide | `/gravity help` | Lecture seule (`init_env.py --guide`) : boucle 3 temps, commandes des modules présents et liens `docs/` |

### Orchestration & concision (`gravity-workflow` : `/gravity-workflow`, `/caveman`)

| Je veux… | Commande | Effet exact |
|---|---|---|
| Corriger rapidement un point ciblé | `/gravity-workflow quick` | Exécution directe (`builder` `flash`, `0` remédiation, `planner`/`reviewer` sautés) |
| Travailler au quotidien *(défaut)* | `/gravity-workflow standard` | Direct si trivial, sinon `review_pipeline.py` (`reviewer` `pro`, `1` remédiation) |
| Sécuriser un changement critique | `/gravity-workflow deep` | Pipeline complet (`planner` `pro`, `builder` `flash`, `reviewer` `pro`, `2` remédiations) |
| Laisser le système suggérer le profil | `/gravity-workflow evo` | Mode consultatif (`locked: false`) : propose `standard` ou `deep` sans mutation silencieuse |
| Sauter revue/tests sur 1 tâche urgente | `/gravity-workflow --no-verify` | Désactive revue/tests pour **1 tâche uniquement** (alias `unsafe` ; `PreToolUse` reste actif) |
| Inspecter l'avancement ou lancer les évals | `/gravity-workflow status` · `evals` | Restitue les 4 blocs d'observabilité ou exécute `evals/run_suite.py` |
| Initialiser les règles projet (optionnel) | `/gravity-workflow init` | Déploie `.agents/` (`quickstart` ou `full`, `--with-stack python\|api`) |
| Réduire les tokens de réponse | `/caveman [lite\|full\|ultra\|off\|auto]` | Règle l'intensité (`auto`/`evo` bascule `lite`↔`full` selon le coût/contexte `metrics`) |
| Générer un message ou compresser un doc | `/caveman commit` · `compress <fichier>` | Message *Conventional Commits* `<= 50` car. ou compression Markdown avec sauvegarde `.original` |

### Télémétrie & coûts (`gravity-metrics` : `/gravity-metrics`)

| Je veux… | Commande | Effet exact |
|---|---|---|
| Consulter coûts, tokens et cache | `/gravity-metrics` | Ouvre le widget MCP App en **lecture seule** (`view="overview"`, zéro mutation) |
| Démarrer une fenêtre de capture | `/gravity-metrics start [label]` | Enregistre le point de départ à **0 token LLM** via hook `PreInvocation` |
| Clôturer et archiver la fenêtre | `/gravity-metrics stop [label]` | Scelle et archive la capture, puis ouvre la vue détail |
| Voir les sessions non archivées | `/gravity-metrics pending [--project <nom>]` | Liste les sessions Gravity racines en attente (`view="pending"`) |
| Archiver une session passée | `/gravity-metrics archive <uuid> [label]` | Analyse et archive *a posteriori* (`--full`, `--force`) |

### Atelier (`gravity-architect`, outils natifs)

| Je veux… | Commande | Effet exact |
|---|---|---|
| Initialiser ou étendre un atelier Hot/Cold | `/gravity-architect init` · `add <chemin...>` | Découverte `--discover --json` puis suivi multi-dépôts lecture seule dans `projects.json` |
| Synchroniser et résumer l'atelier | `/gravity-architect [sync\|status]` | Micro-delta `sync_tracking.py --print-delta` ou lecture directe de `delta.md` |
| Produire specs, tasks, archives, audits | `/gravity-architect spec\|task\|archive\|audit` | Crée `specs/`, `tasks/`, archive les livrés ou audite `audits/code/` |
| Capitaliser une règle apprise en session | `/learn` *(natif Antigravity)* | Persiste une correction ou un setup complexe pour les sessions futures (hors module Gravity) |

> **Autres commandes natives Antigravity utiles :** `/plan` et `/grill-me` (cadrage avant exécution), `/boost` (raisonnement profond), `/teamwork` (travail en équipe d'agents).

---

## 2. Combinaisons gagnantes

- **Session instrumentée optimale (Palier 2) :**
  `/gravity-metrics start lot-auth` → `/gravity-workflow evo` + `/caveman auto` → implémentation → `/gravity-metrics stop` → vérification dans `/gravity dashboard`.
- **Chantier multi-dépôts encadré (Palier 3) :**
  `/gravity-architect spec mon-lot` → `/gravity-architect task mon-lot` → exécution via `/gravity-workflow` → `/gravity-architect archive mon-lot`.
- **Vérification rapide avant commit :**
  `/gravity doctor` → `python plugin/scripts/validate.py --strict` → `/caveman commit`.

---

## 3. Anti-patterns à éviter

- **Exécuter `init` dans tous les dépôts :** `gravity-workflow` fonctionne sans écriture locale (stockage centralisé sous `$GRAVITY_HOME/workflow/`).
- **Croire que `--no-verify` coupe la sécurité :** `--no-verify` / `unsafe` ne saute que la revue/tests sur 1 tâche ; le garde-fou `PreToolUse` reste toujours actif.
- **Éditer `core/modules.json` à la main :** utilisez toujours `/gravity init` (`init_env.py`) qui écrit le registre de manière atomique.
- **Mélanger `audits/code/` et `audits/agents/` :** gardez les audits code sous `gravity-architect` et les audits de sessions agents sous `gravity-metrics`.

**Voir aussi :** [Démarrage rapide](getting-started.md) · [Parcours utilisateur](user-journey.md) · [Dépannage & cycle de vie](troubleshooting-and-lifecycle.md)

# Démarrage rapide — Écosystème Gravity

Ce guide permet d'installer et de démarrer **Gravity** en moins de 5 minutes sur **Windows (PowerShell)** ou **POSIX (Linux / macOS bash)**, sans dépendance externe.

---

## 1. Prérequis

| Outil | Version / Exigence | Vérification rapide |
|---|---|---|
| **Python** | `3.10+` (100 % bibliothèque standard) | `python --version` *(ou `python3 --version`)* |
| **Google Antigravity** | App `v2.34.0+` et/ou CLI `agy` | `agy --version` |
| **Git** | Recommandé pour cloner et gérer les dépôts | `git --version` |

> **Stockage centralisé (`$GRAVITY_HOME`) :** toutes les données vivent sous `~/.gemini/gravity/` (ou `$GRAVITY_HOME`). Aucun dépôt utilisateur n'est pollué par défaut.

---

## 2. Choisir son palier d'adoption

L'orchestrateur hors-ligne [`scripts/ecosystem_install.py`](../scripts/ecosystem_install.py) installe les dépôts clonés localement dans l'ordre topologique (`gravity` en premier) :

| Palier | Drapeau | Modules inclus | Usage recommandé |
|---|---|---|---|
| **Palier 1 — *Essentiel*** | `--tier 1` | `gravity`, `gravity-workflow` | Exécution fiable sur un dépôt (garde-fous `PreToolUse`, profils `quick`/`standard`/`deep`, `/caveman`) |
| **Palier 2 — *Pilotage*** | `--tier 2` | Palier 1 + `gravity-metrics` | Suivi des coûts, tokens, économies de cache, jalons et audits agents |
| **Palier 3 — *Multi-projets*** | `--tier 3` *(défaut)* | Palier 2 + `gravity-architect`, `gravity-bridge` | Atelier de conception Hot/Cold (`specs/`, `handoffs/`, `audits/code/`) et relais inter-workspaces SQLite + `agentapi` |

---

## 3. Séquences copiables d'installation & d'initialisation

Placez-vous dans le dépôt `gravity` (les dépôts frères choisis doivent être clonés dans le dossier parent, ou indiquez `--repos-root <dossier>`).

### Windows (PowerShell)

```powershell
# 1. Prévisualiser en lecture seule le palier choisi (ex. Palier 2)
python scripts/ecosystem_install.py --check --tier 2
python scripts/ecosystem_install.py --install --tier 2 --dry-run

# 2. Installer les plugins dans ~/.gemini/config/plugins/
#    (adapte automatiquement "python3" sur la copie installée Windows sans toucher au dépôt)
python scripts/ecosystem_install.py --install --tier 2

# 3. Initialiser ~/.gemini/gravity/core/modules.json et vérifier la santé (lecture seule)
python plugin/scripts/init_env.py
python plugin/scripts/init_env.py --check
python plugin/scripts/init_env.py --guide
```

### POSIX (Linux / macOS bash)

```bash
# 1. Prévisualiser en lecture seule le palier choisi (ex. Palier 3 complet)
python3 scripts/ecosystem_install.py --check --tier 3
python3 scripts/ecosystem_install.py --install --tier 3 --dry-run

# 2. Installer les plugins dans ~/.gemini/config/plugins/
python3 scripts/ecosystem_install.py --install --tier 3

# 3. Initialiser ~/.gemini/gravity/core/modules.json et vérifier la santé (lecture seule)
python3 plugin/scripts/init_env.py
python3 plugin/scripts/init_env.py --check
python3 plugin/scripts/init_env.py --guide
```

> **Dans le chat Antigravity :** vous pouvez lancer directement `/gravity init`, `/gravity doctor` et `/gravity help`.

---

## 4. Ouvrir la MCP App unifiée (zéro édition de `config.json`)

`gravity` embarque sa propre configuration MCP (`plugin/mcp_config.json`) et le serveur `open_gravity_dashboard` : **aucune édition manuelle de `~/.gemini/config/config.json` n'est requise**.

1. **Depuis le chat :** lancez `/gravity dashboard` (appelle `open_gravity_dashboard` en panneau auxiliaire `aux_pane`).
2. **Depuis l'interface Antigravity :** ouvrez **Plugins -> Gravity** (`0` token interactif).
3. **Diagnostic CLI lecture seule :** `python plugin/scripts/init_env.py --dashboard` (vérifie `mcp_config.json`, `mcp/server.py`, `dashboard/api.py` et liste les onglets découverts).

*(En Palier 3, seule la liaison optionnelle de sidecars Bridge pour la messagerie active utilise `/gravity-bridge link <slug>` ou `install.py --link`.)*

---

## 5. Check-list de validation en 5 points

1. `agy plugin list` affiche `gravity` (et les modules du palier choisi) actifs.
2. `~/.gemini/gravity/core/modules.json` existe après `/gravity init` et recense tous vos modules (`valid: true`).
3. `/gravity doctor` (`init_env.py --check`) retourne `0` erreur et signale d'éventuels dossiers legacy sans y toucher.
4. `/gravity help` (`init_env.py --guide`) affiche la boucle en 3 temps et uniquement les commandes de vos modules installés.
5. `/gravity dashboard` (ou **Plugins -> Gravity**) ouvre le tableau de bord MCP App sans erreur.

**Pour aller plus loin :** [Parcours utilisateur](user-journey.md) · [Aide-mémoire des commandes](command-cheatsheet.md) · [Dépannage & cycle de vie](troubleshooting-and-lifecycle.md)

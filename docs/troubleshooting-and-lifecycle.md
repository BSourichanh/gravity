# Dépannage & cycle de vie — Gravity

Ce guide couvre la mise à jour, la migration des anciens dossiers, la résolution des incidents courants sous Windows/POSIX et la désinstallation propre.

---

## 1. Mises à jour (`/gravity update`, `sources.json` & `ecosystem_install.py --pull`)

### Via `/gravity update` (`init_env.py --update` / `--check-updates`)
`/gravity update` lit la provenance des dépôts dans `$GRAVITY_HOME/core/sources.json` (rempli automatiquement par `install.py` en portée globale ou via `--link <chemin>` / `--repos-root <dossier>`), inspecte chaque dépôt en lecture seule puis exécute un `git pull --ff-only` *fail-isolated* avant de réinstaller les modules modifiés (compagnons d'abord, `gravity` en dernier) et de rafraîchir `core/modules.json` :

```powershell
# Contrôle lecture seule des mises à jour ou dérives locales
python plugin/scripts/init_env.py --check-updates

# Lier un dossier parent de clones puis simuler / appliquer la mise à jour
python plugin/scripts/init_env.py --update --repos-root .. --dry-run
python plugin/scripts/init_env.py --update --modules gravity,gravity-metrics --force
python plugin/scripts/init_env.py --update --offline --link ../gravity
```

- **Isolation des échecs Git :** les dépôts `dirty`, `detached`, `no_upstream`, `diverged` ou `unlinked` sont ignorés avec avertissement sans bloquer les autres modules.
- **Serveur MCP :** si `gravity` (`core`) est mis à jour, redémarrez le serveur MCP `gravity_dashboard` (ou Antigravity) pour recharger les modules Python en mémoire.

### Via l'orchestrateur local (`ecosystem_install.py --update [--pull]`)
L'orchestrateur met à jour les plugins dans l'ordre topologique (`gravity` → `gravity-workflow` → `gravity-metrics` → `gravity-architect`) en propageant `--force` et en rafraîchissant `core/modules.json`. Ajoutez `--pull` (opt-in, refusé avec `--check` ou `--uninstall`) pour exécuter `git fetch` + `git pull --ff-only` *fail-isolated* avant réinstallation :

```powershell
# Windows PowerShell : simuler puis mettre à jour la suite (avec ou sans --pull)
python scripts/ecosystem_install.py --update --tier 3 --dry-run
python scripts/ecosystem_install.py --update --pull --strict
python scripts/ecosystem_install.py --update --modules gravity,gravity-metrics --strict
```

```bash
# POSIX bash
python3 scripts/ecosystem_install.py --update --pull --tier 3 --strict
```

> Les données centralisées sous `$GRAVITY_HOME` (`~/.gemini/gravity/`) sont toujours préservées lors des mises à jour.

---

## 2. Migration des anciens dossiers (`--migration-plan`, 4 étapes)

Si vous aviez une ancienne installation (`~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow` ou `~/.gravity`), `/gravity doctor` la signale en **lecture seule** sans jamais déplacer ni supprimer de fichier.

Pour obtenir un plan adapté à votre shell (**100 % lecture seule**, zéro écriture disque) :

```powershell
python plugin/scripts/init_env.py --migration-plan --shell auto
# Ou explicitement : --shell powershell | --shell bash [--json]
```

Les **4 étapes** générées par le plan sont :
1. **`backup` :** création d'une sauvegarde horodatée sous `~/gravity-legacy-backup/<nom>-YYYYMMDD`.
2. **`copy` :** copie non destructive vers `$GRAVITY_HOME/<module>/` (`Copy-Item` conditionnel sous PowerShell ou `cp -n` sous bash ; les collisions éventuelles sont listées et jamais écrasées).
3. **`verify` :** contrôle lecture seule via `python plugin/scripts/init_env.py --check`.
4. **`cleanup` :** commande de suppression finale **commentée (`#`)** par défaut, à n'exécuter manuellement qu'après vérification complète.

---

## 3. Tableau de dépannage Windows / POSIX

| Symptôme / Contexte | Cause probable | Résolution recommandée |
|---|---|---|
| **`python3` introuvable ou ouvre le Microsoft Store (`WindowsApps`)** | Alias stub Windows sur `python3` | Gardez `"python3"` dans les dépôts sources ; `install.py` adapte automatiquement la copie installée vers `python` ou `py -3`. Pour corriger une copie déjà posée : `python plugin/scripts/validate.py --fix-python-cmd`. |
| **Commande `/gravity*` absente ou plugin ignoré** | Plugin non installé, désactivé ou manifeste invalide | Vérifiez avec `agy plugin list` et `agy plugin validate ./plugin --strict`. Réinstallez via `python install.py --force`. |
| **Mise à jour bloquée sous Windows par un fichier verrouillé** | Processus Antigravity ou outil Python actif pendant le swap | Fermez le processus concerné puis relancez `python install.py --force` (repli *in-place* automatique prévu sous Windows). |
| **Erreur `BOM UTF-8` ou `CRLF détecté` sous `validate.py --strict`** | Éditeur Windows ayant écrit un BOM ou `\r\n` | Respectez `.gitattributes` (`* text=auto eol=lf`) et réenregistrez en **UTF-8 sans BOM** + **LF** (`\n`). |
| **Travail sans accès réseau / `sync_tracking.py` échoue en veille distante** | Fetch veille distante impossible hors-ligne | Utilisez `--offline` sur `gravity-architect` (`sync_tracking.py --offline --ack-editorial --print-delta`). `ecosystem_install.py` et `init_env.py` fonctionnent déjà 100 % hors-ligne. |
| **`wave_runner.py` / `review_pipeline.py` signale `TIMEOUT` ou worktree résiduel** | Builder (`> 900s`) ou Reviewer (`> 360s`) expiré ou tâche isolée en échec | Chaque vague `parallel()` est *fail-isolated* et nettoie le `git worktree` sous `$GRAVITY_HOME/workflow/worktrees/` dans `try/finally` sans altérer `dev`. Vérifiez le statut retourné puis relancez uniquement le dépôt concerné. |
| **Onglet `Architect` affiche `atelier non détecté` dans le dashboard** | Aucun atelier enregistré dans `$GRAVITY_ARCHITECT_HOME/ateliers.json` ni `GRAVITY_ARCHITECT_WORKSPACE` | Exécutez `/gravity-architect init` ou `/gravity-architect sync` dans votre atelier (met à jour `ateliers.json`), ouvrez `open_gravity_dashboard(view="architect", atelier="<chemin>")` / `ws="<chemin>"`, ou définissez `GRAVITY_ARCHITECT_WORKSPACE`. |
| **Dashboard absent de la barre latérale gauche et du menu `+` (seul le résumé texte s'affiche)** | Antigravity App `< 2.34.0` ou surface sans rendu MCP Apps (ex. CLI `agy`) | Vérifiez la version d'Antigravity App (`>= 2.34.0` requis ; sonde automatique `winreg` sous Windows, `snap list antigravity` / `dpkg-query` sous Linux), redémarrez l'app, et contrôlez avec `python3 plugin/scripts/init_env.py --dashboard`. |

---

## 4. Désinstallation propre (`--uninstall`)

La désinstallation retire uniquement les plugins installés dans `~/.gemini/config/plugins/` (ou `<workspace>/.agents/plugins/`) tout en **préservant intactes** vos données sous `$GRAVITY_HOME` (`core/`, `workflow/`, `metrics/`, `architect/`) :

```powershell
# Suite complète en ordre topologique inversé (gravity Core en dernier)
python scripts/ecosystem_install.py --uninstall --dry-run
python scripts/ecosystem_install.py --uninstall

# Ou un seul plugin ciblé
python install.py --uninstall
```

**Voir aussi :** [Démarrage rapide](getting-started.md) · [Aide-mémoire des commandes](command-cheatsheet.md) · [Standard des dépôts](repo-standard.md)

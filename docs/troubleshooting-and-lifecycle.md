# Dépannage & cycle de vie — Gravity

Ce guide couvre la mise à jour, la migration des anciens dossiers, la résolution des incidents courants sous Windows/POSIX et la désinstallation propre.

---

## 1. Mises à jour hors-ligne (`ecosystem_install.py --update`)

L'orchestrateur met à jour les plugins dans l'ordre topologique (`gravity` → `gravity-workflow` → `gravity-metrics` → `gravity-architect` → `gravity-bridge`) en propageant `--force` et en rafraîchissant `core/modules.json` :

```powershell
# Windows PowerShell : simuler puis mettre à jour la suite (ou un sous-ensemble)
python scripts/ecosystem_install.py --update --tier 3 --dry-run
python scripts/ecosystem_install.py --update --modules gravity,gravity-metrics --strict
```

```bash
# POSIX bash
python3 scripts/ecosystem_install.py --update --tier 3 --strict
```

> Les données centralisées sous `$GRAVITY_HOME` (`~/.gemini/gravity/`) sont toujours préservées lors des mises à jour.

---

## 2. Migration des anciens dossiers (`--migration-plan`, 4 étapes)

Si vous aviez une ancienne installation (`~/.gemini/gravity-bridge`, `~/.gemini/gravity-metrics`, `~/.gemini/gravity-workflow` ou `~/.gravity`), `/gravity doctor` la signale en **lecture seule** sans jamais déplacer ni supprimer de fichier.

Pour obtenir un plan adapté à votre shell (**100 % lecture seule**, zéro écriture disque) :

```powershell
python plugin/scripts/init_env.py --migration-plan --shell auto
# Ou explicitement : --shell powershell | --shell bash [--json]
```

Les **4 étapes** générées par le plan sont :
1. **`backup` :** création d'une sauvegarde horodatée sous `~/gravity-legacy-backup/<nom>-YYYYMMDD`.
2. **`copy` :** copie non destructive vers `$GRAVITY_HOME/<module>/` (`Copy-Item` conditionnel sous PowerShell ou `cp -n` sous bash ; les collisions éventuelles sont listées et jamais écrasées).
3. **`verify` :** contrôle lecture seule via `python scripts/init_env.py --check`.
4. **`cleanup` :** commande de suppression finale **commentée (`#`)** par défaut, à n'exécuter manuellement qu'après vérification complète.

---

## 3. Tableau de dépannage Windows / POSIX

| Symptôme / Contexte | Cause probable | Résolution recommandée |
|---|---|---|
| **`python3` introuvable ou ouvre le Microsoft Store (`WindowsApps`)** | Alias stub Windows sur `python3` | Gardez `"python3"` dans les dépôts sources ; `install.py` adapte automatiquement la copie installée vers `python` ou `py -3`. Pour corriger une copie déjà posée : `python plugin/scripts/validate.py --fix-python-cmd`. |
| **Commande `/gravity*` absente ou plugin ignoré** | Plugin non installé, désactivé ou manifeste invalide | Vérifiez avec `agy plugin list` et `agy plugin validate ./plugin --strict`. Réinstallez via `python install.py --force`. |
| **Mise à jour `gravity-workflow` bloquée ou port `4789` occupé** | Le sidecar HTTP `gravity-workflow/live-widget` (`127.0.0.1:4789`) verrouille le dossier ou tourne encore | Fermez le processus sidecar ou l'app Antigravity puis relancez `python install.py --force` (repli *in-place* prévu sous Windows). Pour retirer complètement le sidecar : supprimez l'entrée `sidecars."gravity-workflow/live-widget"` dans `~/.gemini/config/config.json`. |
| **Erreur `BOM UTF-8` ou `CRLF détecté` sous `validate.py --strict`** | Éditeur Windows ayant écrit un BOM ou `\r\n` | Respectez `.gitattributes` (`* text=auto eol=lf`) et réenregistrez en **UTF-8 sans BOM** + **LF** (`\n`). |
| **Travail sans accès réseau / `sync_tracking.py` échoue en veille distante** | Fetch veille distante impossible hors-ligne | Utilisez `--offline` sur `gravity-architect` (`sync_tracking.py --offline --ack-editorial --print-delta`). `ecosystem_install.py` et `init_env.py` fonctionnent déjà 100 % hors-ligne. |
| **Bridge refuse un envoi ou signale `depth >= 1` / `unlinked`** | Garde-fou anti-boucle (`GRAVITY_BRIDGE_DEPTH >= 1`) ou sidecar cible non lié | En `depth >= 1`, aucun sous-dispatch n'est autorisé : répondez via `reply_thread(..., dispatch=false, close=true)`. Si cible `unlinked`/`offline`, exécutez `/gravity-bridge link <slug>` (ou `install.py --link <chemin>`). |
| **Onglet `Architect` affiche `atelier non détecté` dans le dashboard** | Aucun atelier enregistré dans `$GRAVITY_ARCHITECT_HOME/ateliers.json`, ni `GRAVITY_ARCHITECT_WORKSPACE` ni `bridge.db` actif | Exécutez `/gravity-architect init` ou `/gravity-architect sync` dans votre atelier (met à jour `ateliers.json`), ouvrez `open_gravity_dashboard(view="architect", atelier="<chemin>")` / `ws="<chemin>"`, ou définissez `GRAVITY_ARCHITECT_WORKSPACE`. |

---

## 4. Désinstallation propre (`--uninstall`)

La désinstallation retire uniquement les plugins installés dans `~/.gemini/config/plugins/` (ou `<workspace>/.agents/plugins/`) tout en **préservant intactes** vos données sous `$GRAVITY_HOME` (`~/.gemini/gravity/`) :

```powershell
# Suite complète en ordre topologique inversé (gravity Core en dernier)
python scripts/ecosystem_install.py --uninstall --dry-run
python scripts/ecosystem_install.py --uninstall

# Ou un seul plugin ciblé
python install.py --uninstall
```

Si vous aviez activé des sidecars manuels (`gravity-workflow/live-widget` sur le port `4789`, ou sidecars `gravity-bridge` liés par `--link`), pensez à les délier via `python install.py --unlink <slug>` (dans `gravity-bridge`) et à vérifier `~/.gemini/config/config.json`.

**Voir aussi :** [Démarrage rapide](getting-started.md) · [Aide-mémoire des commandes](command-cheatsheet.md) · [Standard des dépôts](repo-standard.md)

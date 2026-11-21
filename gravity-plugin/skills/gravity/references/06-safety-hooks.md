# Garde-fous automatiques (Hooks déterministes Fail-Closed)

## Objectif
Ajouter une défense en profondeur déterministe et synchrone au-dessus du **Terminal Sandbox** et du **Permission Engine** natifs d'Antigravity via `gravity-plugin/hooks.json` et des scripts modulaires 100 % bibliothèque standard Python 3 embarqués dans le plugin.

## Règles critiques Antigravity sur les hooks de plugin
1. **Emplacement et `cwd` des hooks de plugin :** Antigravity charge automatiquement `hooks.json` placé à la racine du plugin (`gravity-plugin/hooks.json`) et exécute les commandes avec **la racine du plugin comme `cwd`**, tandis que le répertoire de travail du projet cible figure dans le champ JSON `cwd` / `workspacePaths[0]` reçu sur `stdin`. Les commandes de `gravity-plugin/hooks.json` pointent vers **`hooks/...`**, et les scripts résolvent le projet cible via `hook_runtime.resolve_workspace_root()` depuis `stdin` (`cwd`/`workspacePaths`).
2. **Sortie obligatoire en code `0` :** tout script hook retournant un code non nul (exception non capturée, chemin cassé, `exit 1` ou `exit 2`) fait basculer silencieusement le runtime en **fail-open** (l'outil s'exécute malgré l'erreur). Chaque script doit capturer toute exception (y compris l'import de ses modules locaux), émettre du JSON strict sur `stdout` et sortir en `0`.
3. **Structure `hooks.json` :**
   - `PreToolUse` et `PostToolUse` sont **groupés** (`[{"matcher": "...", "hooks": [...]}]`).
   - `SessionStart`, `PreInvocation`, `PostInvocation` et `Stop` sont des **tableaux plats** d'objets handlers (`[{"type": "command", "command": "..."}]`), sans `matcher` ni wrapper `hooks`.
4. **Contrats `stdout` complets d'Antigravity :**
   - `SessionStart` : reçoit les métadonnées session (`cwd`, `workspacePaths`, `conversationId`, `modelName`) et émet `{}` ou `{"injectSteps": [{"systemMessage": {"systemMessage": "..."}}]}`.
   - `PreToolUse` : `decision` parmi `"allow"`, `"auto_approve"`, `"deny"`, `"ask"`, `"force_ask"` *(ignore le cache "Always Allow" — indispensable en fail-closed)*, `"deny_unless_prior_grant"`, plus champs optionnels `reason`, `overwrite` (fusion shallow sur `args`), `permissionOverrides`.
   - `PostToolUse` : reçoit `toolCall`, `stepIdx` et `error` (si l'outil a échoué) et doit retourner strictement **`{}`**.
   - `Stop` : reçoit `conversationId`, `executionNum`, `terminationReason`, `error`, `fullyIdle`, `continuationActive`, `transcriptPath`, `modelName`, `cwd` et doit retourner **`{}`** pour autoriser l'arrêt (ou `{"decision": "continue", "reason": "..."}` pour relancer).

## Architecture SOLID & 4 barrières (`gravity-plugin/hooks/`)
- **`hook_runtime.py`** : utilitaires communs (`read_stdin_text`, `emit_json`, `emit_ok`, `resolve_workspace_root`, `first_str_arg`, `first_not_none`, `get_lock_fn`, `record_live_event`).
- **`safety_policy.py`** : tables et évaluation pure (`evaluate_tool_call`, `inspect_workflow_code`) appliquant les 3 niveaux de sécurité :
  1. **Niveau 1 — Blocage ferme (`deny`)** :
     - Commandes shell critiques POSIX & **Windows PowerShell** (`run_command`, `execute_command`, `bash`, `shell`) : `rm -rf`/`rm --recursive --force` destructeurs (`/`, `~`, `$HOME`, `*`, `.`, `..`, ou tout chemin contenant `..` sans bloquer `/tmp/build_cache`), `Remove-Item`/`ri`/`del -Recurse -Force` destructeurs, `git push --force`/`-f` ou refspec `+` (`git push origin +main`), `printenv`/`env`/`Get-ChildItem Env:`/`ls env:`, suppressions massives DB (`DROP DATABASE/SCHEMA/TABLE`, `TRUNCATE TABLE`, `FLUSHALL`/`FLUSHDB`).
     - Pipe de téléchargement shell : `curl`/`wget` pipé vers `sh/bash/zsh/dash/python3?/pwsh`, et `Invoke-WebRequest`/`iwr`/`irm` pipé vers `iex`/`Invoke-Expression`.
     - Anti-contournement secrets & `run_workflow` : blocage de `.env`, `secrets/`, `.pem`, `.key`, clés SSH (`id_rsa`, `id_ed25519`, `.ssh/`) via shell, lecture (`view_file`, `read_file`), recherche (`grep_search`, `search_files`), parcours (`list_dir`, `find_by_name`), appels MCP (`call_mcp_tool` inspecté récursivement sur toutes ses valeurs chaînes) ou script `run_workflow` (accès `.env`/`secrets/`/`os.environ` ou écriture sur `hooks.json`/`hooks/`/`01-safety-boundaries.md`).
     - Protection en écriture & auto-protection : blocage de toute altération de `hooks.json`, `.agents/hooks.json`, `hooks/` et `01-safety-boundaries.md` sur toutes les clés et sous-structures de `FILE_WRITE_TOOLS` et `call_mcp_tool`.
  2. **Niveau 2 — Escalade humaine stricte (`force_ask`, ignore "Always Allow")** :
     - Table `OPAQUE_ASK_CMDS` : `find -exec`/`-execdir`/`-ok`, `xargs`, `base64 -d`/`--decode`, `eval`, sous-shells inline (`sh -c`, `bash -c`, `pwsh -Command`, `cmd /c`), code inline (`python -c`, `node -e`, `perl -e`, `ruby -e`), PowerShell opaque (`iex`, `Invoke-Expression`, `-EncodedCommand`, `FromBase64String`), globbing masqué sur fichiers cachés (`.e*`, `.en?`), et scripts `run_workflow` utilisant `subprocess`/`shutil`/`ctypes`, `os.remove`/`os.replace`/`os.rmdir`/`os.removedirs`, `.rmtree()`/`.unlink()`/`.chmod()`/`.system()`/`.popen()`, `getenv` ou `exec`/`eval`.
     - Entrée invalide/malformée : `stdin` vide, JSON invalide ou `toolCall` absent -> `{"decision": "force_ask", "reason": "..."}` avec code `0`.
  3. **Niveau 3 — Autorisation (`allow`)** :
     - Opérations régulières sans signal de risque (ex. `pytest -q`, `rm -rf /tmp/build_cache`, lecture de `src/ui/keyboard.py`, `run_workflow` sur `evals/run_suite.py` ou `workflows/review_pipeline.py`).
  4. **Observabilité live & atomicité** :
     - Journalisation des événements `deny` et `force_ask` vers `<workspace>/.agents/gravity/observability/live_state.json` via `state_writer.py` (avec `workspace_root` résolu depuis `stdin`).

## Composants fournis par le plugin
1. **`gravity-plugin/hooks.json`** : groupes nommés pointant vers `hooks/*.py`, `PreToolUse` couvrant `run_command|execute_command|bash|shell|run_workflow|write_to_file|write_file|replace_file_content|edit_file|multi_replace_file_content|view_file|read_file|grep_search|search_files|list_dir|find_by_name|call_mcp_tool`.
2. **`gravity-plugin/hooks/hook_runtime.py`** et **`gravity-plugin/hooks/safety_policy.py`**.
3. **`gravity-plugin/hooks/pre_tool_guard.py`** (permissions `0755`).
4. **`gravity-plugin/hooks/session_start_caveman.py`** (`SessionStart`, permissions `0755`, injecte la directive Caveman une fois au démarrage uniquement dans les projets Gravity lorsque `caveman != "off"`, avec auto-clarté obligatoire sur tout refus/alerte sécurité `PreToolUse`, confirmation irréversible ou question `/grill-me` ; émet `{}` sinon).
5. **`gravity-plugin/hooks/post_tool_format.py`** (permissions `0755`, ignore immédiatement en mode `"verification": "unsafe"` depuis `.agents/gravity/profile.json`, ignore `.agents/` et les appels avec `error` non vide, exige une config Prettier explicite dans le projet avant d'invoquer `prettier`, émet strictement `{}` en `exit 0`). Les garde-fous `PreToolUse` restent actifs en `safe` comme en `unsafe`, et en `slow` comme en `fast`.

## Checkpoint déterministe
Exécuter `python3 <plugin_root>/scripts/validate.py --workspace . --strict` et vérifier `exit=0` sur tous les cas `deny`, `force_ask` et `allow` (POSIX, PowerShell, `run_workflow`, `list_dir`, `edit_file`, `read_file`, `grep_search`, anti-faux-positif `/tmp/build_cache` et JSON malformé), plus les dry-runs sur `post_tool_format.py` (`stdout == "{}"`, `exit=0`) et `session_start_caveman.py`.
Mettre à jour `.agents/gravity/PROGRESS.md` et afficher la micro-carte.

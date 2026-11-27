# Contrat Module v1 (`plugin/config/module.json`)

Tout plugin de l'écosystème Gravity expose à la racine de son dossier `plugin/` un fichier **`config/module.json`** conforme au schéma v1. Ce contrat permet à **Gravity Core** (`gravity`) de découvrir, valider et enregistrer les modules sans couplage fort ni modification du code cœur (**Open/Closed Principle**).

---

## 1. Schéma officiel (`schema_version: 1`)

Exemple de référence (`gravity` Core) :

```json
{
  "schema_version": 1,
  "id": "core",
  "plugin_name": "gravity",
  "role": "Initialisation environnement Gravity, registre modules et hote UI/UX unifie (SPI-1)",
  "storage": {
    "subdir": "core",
    "env_override": "GRAVITY_CORE_HOME"
  },
  "commands": [
    "/gravity"
  ],
  "capabilities": [
    "env-init",
    "module-registry",
    "ui-host",
    "spi-host",
    "dashboard-spi-v1"
  ],
  "ui": {
    "mode": "core",
    "target": "gravity"
  },
  "signals": {
    "produces": [
      "environment-state"
    ],
    "consumes": [
      "*"
    ]
  }
}
```

### Règles de validation (`validate_module_contract`)

| Champ | Type | Contrainte |
|---|---|---|
| `schema_version` | `int` | Doit valoir strictement `1` (pas de booléen ni chaîne) |
| `id` | `str` | Slug non vide (`^[a-z0-9][a-z0-9_-]*$`), ex. `core`, `architect`, `workflow`, `metrics` |
| `plugin_name` | `str` | Chaîne non vide identique au champ `name` de `plugin/plugin.json` |
| `role` | `str` | Description concise non vide du périmètre SRP du module |
| `storage.subdir` | `str` | Sous-répertoire sûr sous `$GRAVITY_HOME` (`^[a-z0-9][a-z0-9_-]*$`) |
| `storage.env_override` | `str` | Nom de variable d'environnement dédiée non vide (ex. `GRAVITY_METRICS_HOME`) |
| `commands` | `list[str]` | Liste de chaînes non vides (ex. `["/gravity-workflow", "/caveman"]`) |
| `capabilities` | `list[str]` | Liste de capacités déclarées (chaînes non vides) |
| `ui.mode` | `str` | Mode UI non vide (`"core"` pour l'hôte MCP App, `"none"` pour les compagnons délégués à `gravity`, ou futur mode) |
| `ui.target` | `str` | Cible UI de convergence (ex. `"gravity"`) |
| `signals.produces` | `list[str]` | Liste de signaux émis (`SPI-3`, peut être `[]`) |
| `signals.consumes` | `list[str]` | Liste de signaux consommés (`SPI-3`, peut être `[]` ou `["*"]`) |
| `dashboard.provider_script` | `str` *(opt.)* | Bloc **`SPI-1`** optionnel : chemin relatif sûr dans `plugin/` vers le provider (ex. `"scripts/dashboard_provider.py"`) |
| `dashboard.views` | `list[str]` *(opt.)* | Vues `SPI-1` exposées par le provider (ex. `["metrics", "health", "live-meta"]`) |
| `dashboard.actions` | `list[str]` *(opt.)* | Actions `SPI-1` exposées par le provider (peut être `[]`) |
| `capture_policy` | `dict` *(opt.)* | Bloc **`SPI-2`** optionnel : `commands` (`list[str]`), `exclude_subcommands` (`list[str]`), `consultative_bypass` (`bool`), `label_prefix` (`str` non vide) |

---

## 2. Stockage `$GRAVITY_HOME/<module>/`

La résolution du répertoire de données d'un module suit `resolve_module_home(module_id, env_override=..., gravity_home=...)` :

1. Si la variable d'environnement `storage.env_override` est définie et non vide → utilise ce chemin.
2. Sinon, résout `GRAVITY_HOME` (`home` explicite > `$GRAVITY_HOME` > `~/.gemini/gravity`) et retourne `<gravity_home>/<storage.subdir>`.

Lors de l'exécution de `init_env.py` (hors `--check` et `--status`), Gravity Core crée `<gravity_home>/core/`, les sous-dossiers des modules valides découverts, et écrit atomiquement **`<gravity_home>/core/modules.json`** en UTF-8 sans BOM.

---

## 3. Contrats des 4 modules actuels

| `id` | `plugin_name` | `storage.env_override` | `ui.mode` | `signals.produces` | `signals.consumes` | `SPI-1` / `SPI-2` |
|---|---|---|---|---|---|---|
| `core` | `gravity` | `GRAVITY_CORE_HOME` | `core` | `environment-state` | `*` | Hôte `SPI-1` |
| `architect` | `gravity-architect` | `GRAVITY_ARCHITECT_HOME` | `none` | `ecosystem-health`, `upgrade-deltas` | `—` | `SPI-1` (`architect`, `health`) + `SPI-2` (`capture_policy`) |
| `workflow` | `gravity-workflow` | `GRAVITY_WORKFLOW_HOME` | `none` | `workflow-state`, `routing-profile` | `session-metrics` | `SPI-1` (`workflow`, `health`) |
| `metrics` | `gravity-metrics` | `GRAVITY_METRICS_HOME` | `none` | `session-metrics` | `—` | `SPI-1` (`metrics`, `session-detail`, `audit-detail`, `health`, `live-meta`) |

---

## 4. Ajouter un futur module sans modifier Core

Gravity Core découvre dynamiquement tout plugin installé exposant `plugin.json` + `config/module.json` : aucune liste codée en dur n'existe dans `core/registry.py`.

1. Créer un dépôt conforme à [`repo-standard.md`](repo-standard.md) avec `plugin/plugin.json` et `plugin/config/module.json` (`schema_version: 1`, `id` unique, `storage.subdir`, `storage.env_override`, `ui.target: "gravity"`, `signals`).
2. Implémenter dans le nouveau plugin la même résolution de stockage : `$<ENV_OVERRIDE>` > `$GRAVITY_HOME/<subdir>` > `~/.gemini/gravity/<subdir>`.
3. Installer le plugin dans `~/.gemini/config/plugins/<plugin_name>/`.
4. Exécuter `/gravity init` (`python plugin/scripts/init_env.py`) :
   - Gravity Core détecte le nouveau module automatiquement,
   - valide son contrat v1,
   - crée son répertoire de stockage centralisé,
   - met à jour `<gravity_home>/core/modules.json` sans aucune modification du code de `gravity`.

# Standard des dépôts Gravity

Ce document définit le socle technique et organisationnel uniforme applicable à tous les dépôts produits de l'écosystème **Gravity**.

---

## 1. Structure standard d'un dépôt plugin

```text
<repo>/
├── plugin/                  # Dossier source installable du plugin Antigravity
│   ├── plugin.json          # Manifeste officiel (9 champs Antigravity)
│   ├── config/
│   │   └── module.json      # Contrat module v1
│   ├── assets/
│   │   └── logo.svg         # SVG carré 1:1
│   ├── rules/
│   │   └── AGENTS.md        # Règle légère (<= 600 o cible / avertissement --strict, <= 1 000 o erreur, sans frontmatter, UTF-8 sans BOM, LF)
│   ├── skills/<skill>/
│   │   └── SKILL.md         # Frontmatter YAML (name, description <= 160 car.) et <= 6 000 o UTF-8 sans BOM, LF
│   ├── scripts/
│   │   └── validate.py      # Validateur autonome (--strict)
│   └── README.md            # Aligné sur le README racine
├── install.py               # Installeur/désinstalleur cross-platform (contrat CLI commun 11 drapeaux)
├── AGENTS.md                # Charte agent canonique (<= 2 500 octets, UTF-8 sans BOM, LF, 3 sections ; contrôlée par validate.py)
├── README.md                # Présentation, installation et liens docs/
├── CHANGELOG.md             # Format Keep a Changelog + SemVer
├── docs/                    # Documentation détaillée (si applicable)
├── tests/                   # Suite unittest 100 % isolée (TemporaryDirectory)
├── .gitattributes           # * text=auto eol=lf
├── .gitignore               # Python / Antigravity / éditeurs
└── LICENSE                  # MIT
```

---

## 2. Manifeste `plugin/plugin.json` (9 champs officiels)

Strictement limité aux **9 champs officiels Antigravity** (plus `disabled` optionnel) :

1. `name` (identifiant plugin, ex. `"gravity"`)
2. `displayName`
3. `version` (SemVer synchronisé avec `CHANGELOG.md`)
4. `description` (`<= 160` caractères, non vide)
5. `logo` (chemin vers un SVG carré `1:1`)
6. `suggestedPrompts` (exactement **3 chaînes non vides**)
7. `author` (`{"name": "..."}`)
8. `homepage`
9. `repository`

Interdits : `$schema`, `license`, `keywords` ou tout champ non officiel, ainsi que tout BOM UTF-8.

---

## 3. Règles d'ingénierie & qualité logicielle

- **Principes obligatoires :** **KISS**, **YAGNI**, **DRY**, **SOLID**, **CUPID**.
- **Pile 100 % Python 3.10+ stdlib :** aucune dépendance tierce dans `plugin/`, `scripts/`, `install.py` et `tests/`.
- **Encodage & fins de ligne :** UTF-8 **sans BOM**, fins de ligne **LF** (`\n`).
- **Portabilité Windows / POSIX :** conserver `"python3"` dans les manifests source (`hooks.json`, `mcp_config.json`, `sidecar.json`) ; l'adaptation éventuelle ne s'applique qu'à la copie installée sous Windows via `install.py`.
- **Zéro pollution des workspaces cibles :** tout état applicatif vit sous `$GRAVITY_HOME/<module>/` (ou surcharge dédiée).
- **Workflow Git :** développement exclusif sur `dev` (ou branche dédiée), *Conventional Commits*, fusion vers `main` et tag annoté `vX.Y.Z` réservés au chef d'orchestre sur accord utilisateur.

---

## 4. Budgets `AGENTS.md` et modèle Hot / Cold

| Surface | Budget maximal | Contraintes |
|---|---|---|
| `AGENTS.md` (racine dépôt) | **<= 2 500 octets UTF-8** *(contrôlé par `validate.py`)* | UTF-8 sans BOM, LF, strictement 3 sections (`## Périmètre & Architecture`, `## Invariants` citant KISS/YAGNI/DRY/SOLID/CUPID, `## Vérifications obligatoires`) |
| `plugin/rules/AGENTS.md` *(D4)* | **<= 600 octets UTF-8** *(cible éditoriale ; avertissement bloquant sous `--strict` au-delà)* / **<= 1 000 octets UTF-8** *(erreur bloquante)* | UTF-8 sans BOM, LF, **zéro frontmatter YAML** (`---`) |
| `plugin/skills/<skill>/SKILL.md` *(routeur)* | **<= 6 000 octets UTF-8** *(contrôlé par `validate.py`)* | UTF-8 sans BOM, LF, frontmatter YAML (`name`, `description <= 160 car.`) |
| `gravity-studio` Hot *(référence)* | `ECOSYSTEM.md <= 6 000 o`, fiches `<= 3 500 o`, `IMPACT.md <= 6 000 o` | Données froides (`archives/`, `specs/archive/`, `handoffs/archive/`) hors session courante |

> **Exception SRP (`gravity-workflow`) :** `gravity-workflow/plugin/rules/` est volontairement absent afin de ne pas alourdir les sessions Antigravity hors harnais ; ses règles sont déployées uniquement dans `.agents/rules/` du workspace cible.
>
> **SRP `gravity init` :** `plugin/scripts/init_env.py` n'écrit ni ne modifie jamais de fichier `AGENTS.md` dans les workspaces utilisateur cibles.

---

## 5. Hygiène UX & Documentation

- **`suggestedPrompts` (`plugin/plugin.json`) :** chaque entrée fait **`<= 100` caractères** ; si elle débute par `/`, elle doit contenir ` — ` ou ` - ` suivi d'un résumé non vide.
- **Guides utilisateur `docs/` (`gravity`) :** les 4 guides (`getting-started.md`, `user-journey.md`, `command-cheatsheet.md`, `troubleshooting-and-lifecycle.md`) doivent chacun rester **`<= 15 360` octets UTF-8**, sans BOM et en fins de ligne LF.
- **Liens Markdown relatifs intègres :** aucun lien relatif local cassé dans `plugin/README.md`, `plugin/skills/*/SKILL.md`, `README.md` et `docs/*.md` (contrôlé automatiquement par `plugin/scripts/validate.py`, hors URLs `http(s)://`, ancres `#`, `mailto:`, `customization://` et blocs de code).
- **Skill `/gravity` :** toutes les sous-commandes officielles (`init`, `status`, `modules`, `doctor`, `dashboard`, `help`) doivent être documentées dans `SKILL.md`.

---

## 6. Contrat CLI commun des installeurs (`install.py`, 11 drapeaux)

Chaque dépôt produit expose un script `install.py` autonome respectant un contrat CLI commun à **11 drapeaux** (complété au besoin par des options propres au module) afin de permettre l'orchestration hors-ligne par `scripts/ecosystem_install.py` (dans `gravity`) :

| # | Drapeau | Type / Valeurs | Rôle |
|---|---|---|---|
| 1 | `--scope` | `global` *(défaut)* \| `workspace` | Portée d'installation (`~/.gemini/config/plugins/` ou `<workspace>/.agents/plugins/`) |
| 2 | `--workspace` | `PATH` | Dossier du projet cible (requis si `--scope workspace`) |
| 3 | `--target` | `PATH` | Destination explicite prioritaire (incompatible avec `--method agy`) |
| 4 | `--method` | `copy` *(défaut)* \| `agy` | Backend d'installation (`copy` stdlib ou délégation `agy plugin install`) |
| 5 | `--force` | booléen | Autorise la mise à jour, réinstallation ou remplacement d'une installation existante |
| 6 | `--skip-validate` | booléen | Ignore la validation pré-installation (hors `--strict`) |
| 7 | `--strict` | booléen | Exige une validation stricte avant commit et échoue sur avertissement |
| 8 | `--no-fix-python` | booléen | Désactive l'adaptation Windows `python3` → `python`/`py -3` sur la copie installée |
| 9 | `--dry-run` | booléen | Prévisualise les opérations planifiées sans modifier le disque |
| 10 | `--check` | booléen | Audit en lecture seule des prérequis et de l'état cible |
| 11 | `--uninstall` | booléen | Désinstalle le plugin en préservant les données centralisées sous `$GRAVITY_HOME` |

---

## 7. Vérifications obligatoires avant livraison

```powershell
python plugin/scripts/validate.py --strict
agy plugin validate ./plugin --strict
python -m unittest discover -s tests -p "test_*.py" -v
```

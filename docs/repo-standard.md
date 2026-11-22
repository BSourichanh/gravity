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
│   │   └── AGENTS.md        # Règle légère (< 2 048 octets, sans frontmatter)
│   ├── skills/<skill>/
│   │   └── SKILL.md         # Frontmatter YAML (name, description <= 160 car.)
│   ├── scripts/
│   │   └── validate.py      # Validateur autonome (--strict)
│   └── README.md            # Aligné sur le README racine
├── install.py               # Installeur/désinstalleur cross-platform (--check, --dry-run, --force, --uninstall)
├── AGENTS.md                # Charte agent canonique (<= 2 500 octets, 3 sections)
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
- **Pile 100 % Python 3.10+ stdlib :** aucune dépendance tierce dans `plugin/`, `install.py` et `tests/`.
- **Encodage & fins de ligne :** UTF-8 **sans BOM**, fins de ligne **LF** (`\n`).
- **Portabilité Windows / POSIX :** conserver `"python3"` dans les manifests source (`hooks.json`, `mcp_config.json`, `sidecar.json`) ; l'adaptation éventuelle ne s'applique qu'à la copie installée sous Windows via `install.py`.
- **Zéro pollution des workspaces cibles :** tout état applicatif vit sous `$GRAVITY_HOME/<module>/` (ou surcharge dédiée).
- **Workflow Git :** développement exclusif sur `dev` (ou branche dédiée), *Conventional Commits*, fusion vers `main` et tag annoté `vX.Y.Z` réservés au chef d'orchestre sur accord utilisateur.

---

## 4. Budgets `AGENTS.md` et modèle Hot / Cold

| Surface | Budget maximal | Contraintes |
|---|---|---|
| `AGENTS.md` (racine dépôt) | **<= 2 500 octets UTF-8** | Strictement 3 sections (`## Périmètre & Architecture`, `## Invariants` citant KISS/YAGNI/DRY/SOLID/CUPID, `## Vérifications obligatoires`) |
| `plugin/rules/AGENTS.md` | **< 2 048 octets UTF-8** | **Zéro frontmatter YAML** (`---`) |
| `gravity-studio` Hot *(référence)* | `ECOSYSTEM.md <= 6 000 o`, fiches `<= 3 500 o`, `IMPACT.md <= 6 000 o` | Données froides (`archives/`, `specs/archive/`, `handoffs/archive/`) hors session courante |

---

## 5. Vérifications obligatoires avant livraison

```powershell
python plugin/scripts/validate.py --strict
agy plugin validate ./plugin --strict
python -m unittest discover -s tests -p "test_*.py" -v
```

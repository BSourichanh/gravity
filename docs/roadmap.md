# Feuille de route — Gravity Core & Écosystème

## `v0.1.0` — Socle modulaire & unification des dépôts *(livrée)*

- Standardisation des 4 dépôts plugins sur `plugin/` + `plugin/config/module.json` v1 (`gravity`, `gravity-architect`, `gravity-workflow`, `gravity-metrics`).
- Séparation complète de l'atelier de conception dans `gravity-workshop`.
- Centralisation du stockage sous `$GRAVITY_HOME` (`~/.gemini/gravity/<module>/`) et registre atomique `core/modules.json`.
- Commandes `/gravity [init|status|modules|doctor]` et détection legacy en lecture seule.

---

## `v0.2.0` — Interface MCP App unifiée & boucle `metrics -> workflow` *(livrée)*

- **MCP App unifiée (`ui-host`) :** façade `plugin/dashboard/`, serveur stdio MCP App (`plugin/mcp/server.py`, `open_gravity_dashboard` sur `aux_pane`/`global` + outils `app`), UI HTML5/SVG SEP-1865 pure-DOM sans `innerHTML` et diagnostic `init_env.py --dashboard`.
- **Outillage écosystème :** `/gravity update`, `/gravity export` / `/gravity import` et vérificateur `scripts/audit_ecosystem.py`.

---

## `v0.3.0` — Audit multi-dépôts, guides UX & providers initiaux *(livrée)*

- Détecteur de dérive multi-dépôts (`scripts/audit_ecosystem.py`), 4 guides UX (`docs/`), `/gravity help` (`--guide`) et providers lecture seule initiaux.

---

## `v0.4.0` — Shared Kernel, contrats `SPI-1..4` & découplage complet *(actuelle)*

- **Shared Kernel (`SPI-4`) :** socle 100 % stdlib `shared/gravity_shared/` (`9` modules) projeté en lecture seule vers `*/plugin/_shared/` avec manifeste SHA-256 `plugin/.shared_manifest.json` (`scripts/sync_shared.py --check`).
- **Convergence UI complète (`SPI-1`) :** les 3 compagnons portent `ui.mode: "none"` et exposent leurs vues (`architect`, `workflow`, `metrics`, `session-detail`, `audit-detail`, `health`, `live-meta`) et actions via `scripts/dashboard_provider.py` dans les 4 onglets unifiés de `gravity` (**`Session`**, **`Projets`**, **`Historique`**, **`Système`** + modules OCP).
- **Politique de capture & bus de signaux (`SPI-2` / `SPI-3`) :** bloc déclaratif `capture_policy` dans `config/module.json` et bus `$GRAVITY_HOME/signals/` (`signal_v1`, signal `session-metrics` consommé par `/gravity-workflow evo`).
- **Vérification parallèle & installée :** `scripts/audit_ecosystem.py --verify-parallel --strict --check-installed` et méta-installeur `scripts/ecosystem_install.py`.

---

## `v0.5.0+` — Perspectives

- Extension de nouveaux modules OCP tiers via `config/module.json` (`SPI-1..3`) sans modifier Core.
- Enrichissement progressif des profils adaptatifs `evo` et des contrôles d'intégrité continus.

# Parcours utilisateur — De la découverte au multi-projets

Ce guide décrit le cycle complet d'utilisation de **Gravity**, du premier démarrage en solo jusqu'au pilotage multi-dépôts et la sauvegarde portable.

---

## 1. Vue d'ensemble du parcours

```mermaid
flowchart LR
    P1["1. Installer et Initialiser (/gravity init)"] --> P2["2. Cadrer et Decouper (specs/ et tasks/)"]
    P2 --> P3["3. Executer, Mesurer et Relayer (workflow + metrics + bridge)"]
    P3 --> P4["4. Superviser, Archiver et Sauvegarder (/gravity dashboard + export/import)"]
    P4 --> P2
```

---

## 2. Scénario fil rouge annoté (Paliers 1 → 2 → 3)

1. **Palier 1 (*Essentiel* — solo sur un dépôt applicatif) :**
   - Vous installez `gravity` + `gravity-workflow`, puis exécutez `/gravity init` et `/gravity help`.
   - Vous travaillez sur une fonctionnalité avec `/gravity-workflow standard` (ou `quick` pour un correctif simple, `deep` pour une refonte risquée) et `/caveman lite` actif par défaut pour économiser des tokens. Les garde-fous `PreToolUse` bloquent les commandes destructrices sans modifier votre dépôt.
2. **Palier 2 (*Pilotage* — maîtriser coûts, cache et fiabilité) :**
   - Vous ajoutez `gravity-metrics`. Avant une session importante, vous lancez `/gravity-metrics start mon-lot` (`0` token LLM), basculez votre workflow sur `/gravity-workflow evo` et `/caveman auto`.
   - Les signaux `session-metrics` et `cost-telemetry` informent les suggestions d'adaptation (`evo`). En fin de lot, `/gravity-metrics stop` archive la capture de manière immuable.
3. **Palier 3 (*Multi-projets* — conception transversale, relais App et sauvegarde) :**
   - Vous ajoutez `gravity-architect` et `gravity-bridge`. Dans votre atelier dédié (ex. `gravity-studio`), `/gravity-architect spec` et `/gravity-architect task` préparent les briefs autonomes dans `specs/` et `tasks/`.
   - Vous liez les dépôts cibles une fois (`/gravity-bridge link <slug>`), envoyez le brief avec feu vert humain (`/gravity-bridge send`), puis archivez le chantier (`/gravity-architect archive <slug>`), ce qui déclenche aussi l'archivage métriques si aucun job Bridge n'est actif.
   - À tout moment, `/gravity dashboard` (barre latérale gauche `Gravity` ou menu `+` du panneau latéral droit) consolide les 5 modules à **0 token**, et `/gravity export` / `/gravity import` sauvegardent ou restaurent `$GRAVITY_HOME` (et vos ateliers via `--include-atelier`).

---

## 3. Matrice des 4 phases

| Phase | Commande(s) clé(s) | Stockage `$GRAVITY_HOME` | Coût tokens | Résultat observable |
|---|---|---|---|---|
| **1. Installer & Initialiser** | `python scripts/ecosystem_install.py --install --tier <1\|2\|3>`, `/gravity`, `/gravity init`, `/gravity doctor` | `core/modules.json` + dossiers `<module>/` | `0` sur `/gravity` (`PreInvocation`) et CLI | Plugins validés (`--strict`), registre atomique créé, legacy détecté RO |
| **2. Cadrer & Découper** *(Palier 3)* | `/gravity-architect [init\|sync\|spec\|task]` | `architect/` + atelier Hot/Cold séparé | Faible (micro-delta `--print-delta`) | `ECOSYSTEM.md`, `specs/`, `tasks/`, `audits/code/` à jour |
| **3. Exécuter, Mesurer & Relayer** *(Paliers 1→3)* | `/gravity-workflow [quick\|standard\|deep\|evo]`, `/caveman`, `/gravity-metrics [start\|stop\|pending\|archive]`, `/gravity-bridge [workspaces\|link\|send\|read\|take\|reply]` | `workflow/workspaces/<slug>-<hash>/`, `metrics/`, `bridge/bridge.db` | Optimisé (`/caveman` + `0` sur `metrics start`) | Plan/Code/Revue isolée, métriques archivées, fils Bridge tracés |
| **4. Superviser, Archiver & Sauvegarder** | `/gravity dashboard` (ou barre latérale `Gravity` / menu `+`), `/gravity-architect archive`, `/gravity export`, `/gravity import` | Lecture seule transversale + `core/sync.json` + ZIP portable | `0` token interactif (MCP App & CLI export/import) | Vue unifiée 5 onglets, archive métriques/atelier, sauvegarde ZIP vérifiée SHA-256 |

---

## 4. Les 3 frontières d'or à retenir

1. **`gravity-studio` vs dépôts produits :**
   - La conception multi-projets (`ECOSYSTEM.md`, `specs/`, `tasks/`, fiches `tracking/`) vit dans un atelier séparé (ex. `gravity-studio`) — jamais dans les 5 dépôts plugins ni dans vos dépôts applicatifs.
2. **Branche `dev` vs branche `main` :**
   - Tout développement quotidien s'effectue sur `dev` (ou une branche dédiée). La fusion sur `main` et les tags `vX.Y.Z` sont réservés aux releases validées par le chef d'orchestre sur accord explicite.
3. **`audits/code/` vs `audits/agents/` :**
   - `audits/code/` appartient exclusivement aux audits Code & Architecture pilotés par **`gravity-architect`**.
   - `audits/agents/` appartient exclusivement aux audits de sessions/agents exploités par **`gravity-metrics`** (onglet *Audits Agents*). Les deux périmètres ne doivent jamais être mélangés.

**Voir aussi :** [Démarrage rapide](getting-started.md) · [Aide-mémoire des commandes](command-cheatsheet.md) · [Architecture](architecture.md)

"""JSON Schema tool definitions for the Gravity Core MCP App server (100% stdlib)."""

from __future__ import annotations

from typing import Any, Sequence


def build_tool_definitions(valid_views: Sequence[str], app_uri: str) -> list[dict[str, Any]]:
    """Build MCP tools/list definitions for `open_gravity_dashboard` and app-only tools."""
    return [
        {
            "name": "open_gravity_dashboard",
            "title": "Ouvrir Gravity Dashboard",
            "description": (
                "Ouvre le tableau de bord unifié Gravity (En direct, Métriques & Audits, "
                "Atelier Architect RO, Système/Doctor et modules OCP) dans Antigravity."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": list(valid_views),
                        "description": (
                            "Vue initiale : live (défaut), metrics, architect, overview "
                            "(workflow redirigé vers live)."
                        ),
                    },
                    "project": {
                        "type": "string",
                        "description": "Filtre projet initial pour la vue Métriques.",
                    },
                    "ws": {
                        "type": "string",
                        "description": "Workspace initial pour la vue En direct / Workflow et repli Architect (ws_hint).",
                    },
                    "atelier": {
                        "type": "string",
                        "description": "Chemin d'atelier Architect cible (optionnel).",
                    },
                    "target": {
                        "type": "string",
                        "description": "Cible initiale (conversation_id Live ou slug/cid session Métriques).",
                    },
                    "metrics_sub": {
                        "type": "string",
                        "enum": ["overview", "sessions", "pending", "audits", "compare"],
                        "description": "Sous-vue initiale de l'onglet Métriques.",
                    },
                    "module_id": {
                        "type": "string",
                        "description": "Identifiant module OCP optionnel.",
                    },
                },
            },
            "_meta": {
                "ui": {
                    "resourceUri": app_uri,
                    "visibility": ["model", "app"],
                },
                "com.google.antigravity/ui": {
                    "entrypoints": [
                        {"type": "aux_pane", "title": "Gravity"},
                        {"type": "global", "title": "Gravity"},
                    ]
                },
            },
        },
        {
            "name": "gravity_get_live_session",
            "title": "Cockpit En direct",
            "description": "Retourne l'état temps réel incrémental (brain/ + Workflow) de la session active.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Identifiant conversation_id (ou préfixe) de la session cible.",
                    },
                    "ws": {
                        "type": "string",
                        "description": "Chemin ou nom du workspace pour la fusion Workflow (optionnel).",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour polling incrémental (fast-path inchangé).",
                    },
                    "include_events": {
                        "type": "boolean",
                        "description": "Inclure le flux d'événements récents (défaut : true).",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_overview",
            "title": "État Système / Doctor Gravity",
            "description": "Retourne l'état Core/Doctor, les onglets et les dossiers legacy en lecture seule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour fast-path inchangé.",
                    }
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_workflow_state",
            "title": "État Workflow Live",
            "description": "Retourne l'état temps réel lecture seule de Gravity Workflow pour un workspace.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ws": {
                        "type": "string",
                        "description": "Chemin ou nom du workspace cible.",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour polling incrémental.",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_metrics_state",
            "title": "État Métriques & Audits Agents",
            "description": "Retourne KPIs techniques, sessions filtrées, file pending et audits agents en lecture seule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Filtre projet optionnel.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximal de sessions récentes retournées.",
                    },
                    "q": {
                        "type": "string",
                        "description": "Recherche texte sur label, modèle, projet ou ID.",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour fast-path inchangé.",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_session_detail",
            "title": "Détail d'une session Métriques",
            "description": "Charge en lecture seule le rapport JSON confiné d'une session sans trajectoire brute.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Slug, label ou conversation_id de la session.",
                    }
                },
                "required": ["target"],
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_metrics_action",
            "title": "Action CLI Gravity Metrics",
            "description": "Exécute une action de cycle de vie de session via la CLI gravity-metrics (--json).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["record", "update", "update-meta", "ignore", "unignore", "remove"],
                        "description": "Action CLI à exécuter.",
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "Identifiant UUID de la conversation cible.",
                    },
                    "slug": {
                        "type": "string",
                        "description": "Slug de la session cible.",
                    },
                    "target": {
                        "type": "string",
                        "description": "Identifiant cible générique (conversation_id ou slug).",
                    },
                    "label": {
                        "type": "string",
                        "description": "Nouveau label de session.",
                    },
                    "project": {
                        "type": "string",
                        "description": "Projet associé à la session.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Note ou commentaire associé.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Motif d'exclusion pour ignore.",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Chemin ou nom du workspace cible.",
                    },
                    "full": {
                        "type": "boolean",
                        "description": "Inclure la trajectoire complète pour record/update.",
                    },
                    "purge_reports": {
                        "type": "boolean",
                        "description": "Supprimer les rapports associés lors de remove.",
                    },
                },
                "required": ["action"],
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_read_audit",
            "title": "Lecture d'un audit agent",
            "description": "Lit le contenu Markdown d'un audit confiné aux racines audits/agents/.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Identifiant audit_id ou chemin confiné aux racines audits/agents/.",
                    }
                },
                "required": ["path"],
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_architect_state",
            "title": "État Gravity Architect (RO)",
            "description": "Retourne ECOSYSTEM.md, delta.md, projets, specs, tasks et audits/code/ en lecture seule.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "atelier": {
                        "type": "string",
                        "description": "Chemin d'atelier Architect cible (optionnel).",
                    },
                    "ws": {
                        "type": "string",
                        "description": "Indice workspace courant pour repli Architect (ws_hint).",
                    },
                    "since_signature": {
                        "type": "string",
                        "description": "Signature précédente pour fast-path inchangé.",
                    },
                },
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
        {
            "name": "gravity_get_module_info",
            "title": "Inspection d'un module OCP",
            "description": "Retourne le contrat et le listing superficiel du stockage d'un module Gravity.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "module_id": {
                        "type": "string",
                        "description": "Identifiant du module Gravity (ex. workflow, architect).",
                    }
                },
                "required": ["module_id"],
            },
            "_meta": {"ui": {"visibility": ["app"]}},
        },
    ]

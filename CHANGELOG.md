# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-21

### Added
- **Standalone Antigravity Plugin (`gravity-plugin/` — 42 files, 100% Python 3 stdlib):**
  - Unified `/gravity` orchestrator skill with 3 orthogonal axes: adaptive reflection mode (`low` / `medium` / `high` / `ultra` / `evo`, defaulting to `evo` at `medium`), workflow time strategy (`slow` / `fast` without reducing reflection), and verification toggle (`safe` / `unsafe`), plus `/gravity status`, `/gravity evals`, `/gravity init`, pre-execution `/grill-me` scoping, and 10 progressive reference guides.
  - Companion `/caveman` skill (`lite` / `full` / `ultra` / `off` / `auto`, plus `commit` and `compress`) backed by `observability/caveman_protocol.py` and `hooks/session_start_caveman.py` (`SessionStart`), defaulting to `lite`, auto-adapted by `evo` between `lite` and `full` unless locked (`caveman_locked`), and scoped by ROI across `planner`, `builder`, `reviewer`, and `swarm` (with `evals/` excluded and mandatory clear prose for safety alerts, confirmations, and `/grill-me`).
  - Role-separated subagents (`agents/planner.md`, `agents/builder.md`, `agents/reviewer.md`) implementing branch-isolated builds and cold-audit independent reviews ("proof or silence").
  - Fail-closed lifecycle hooks (`hooks.json`, `pre_tool_guard.py`, `safety_policy.py`, `post_tool_format.py`, `session_start_caveman.py`, `stop_session_logger.py`) protecting secrets, blocking destructive POSIX/PowerShell/Git/DB commands, and preventing harness tampering.
  - Automated `review_pipeline.py` workflow (`planner` → branch-isolated `builder` → independent `reviewer` with bounded remediation rounds) and parallel double-filter evaluation suite (`evals/cases.json` 12 cases, `evals/eval_checks.py`, `evals/run_suite.py`).
  - 4 observability surfaces: 3-line micro-card, `/gravity status` (artifact `generative_ui` / Markdown), CLI `/statusline` (`observability/statusline.py`), and multi-workspace anti-XSS HTTP/SSE Live Widget sidecar (`sidecars/live-widget/server.py`, port `4789`), backed by atomic `state_writer.py` and deterministic `profile_engine.py`.
  - Strict plugin & workspace validators (`scripts/validate.py`, `scripts/validators/`), project bootstrapper (`scripts/init_workspace.py`), and 19 internal unit tests (`scripts/test_unit.py`).
- **Minimal Project Baseline (`workspace-template/` — 12 files):**
  - `AGENTS.md`, `.agents/mcp_config.json`, 4 scoped rule templates (`01-safety-boundaries.md` under 2 KB `always_on` + `02`..`04`), and `.agents/gravity/` state files.
- **Cross-Platform Installer & Uninstaller (`install.py`, `uninstall.py`):**
  - Staged copy with rollback, automatic Windows `python3` adaptation on installed copies, `agy` CLI delegation, workspace initialization/cleanup without deleting user-modified files, Live Widget registry pruning/cleanup, and full test coverage (`tests/test_install.py`, `tests/test_uninstall.py`).
- **Living Documentation (`docs/`):**
  - Modular French documentation (`architecture.md`, `modes-and-routing.md`, `agents-and-workflows.md`, `safety-and-hooks.md`, `evals-and-learning.md`, `observability.md`, `validation-and-development.md`) kept in sync with the codebase.

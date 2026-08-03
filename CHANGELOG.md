# Changelog — COMA

All notable changes to COMA will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 2026-08-03

### Added
- Root `llms.txt` context index file for AI/LLM discoverability and RAG context indexing (233 Pytest unit tests verified).
- German parity documentation (`README_de.md`) with top language switcher.
- Ecosystem & status Shields.io badges (`ellmos-ai`, `open-bricks`, Pytest 233 passed, Python 3.10+, License MIT).
- GFM Callout notice for `llms.txt` discoverability in English and German READMEs.
- Interactive Mermaid architecture diagram for job board protocol and spawner workflow.

## [0.2.0] — 2026-07-26

### Added
- Name migration from COMAS to COMA with backwards-compatibility aliases (`comas` CLI and package imports).
- Agent Spawner layer supporting `ClaudeAdapter`, `CodexAdapter`, `AntigravityAdapter`, and `KimiAdapter`.
- Session-decoupled file-based Job Board protocol (`IN/`, `OUT/`, `DONE/`).
- Vendor manifest check and check command (`coma vendor`, `coma check`).

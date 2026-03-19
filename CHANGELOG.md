# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-03-19

### Added

- **Multi-tenancy Phase 1**: ORM tenant isolation with `_tenant_field`, automatic tenant filtering on all queries, `Company` and `CompanyUser` models
- **Unified User model**: Single `app.users` table replaces dual admin/app user tables, with `UserPlatform` for platform identity mapping
- **Invite flow**: Token-based user invite with password setup, email sent via system agent's Gmail MCP server
- **GWS drive tools**: `drive_download` and `drive_read_spreadsheet` for Google Drive file access and XLSX/Google Sheets parsing
- **Ollama admin page**: Cloud authentication, health check, model management with pull support
- **openpyxl dependency**: Added to `data` extras for spreadsheet analysis

### Improved

- MCP Gateway: mark user OAuth2 token as expired on 401 from external servers, `/me/connections` shows amber badge
- MCP Gateway: propagate user identity in subprocess mode for per-user tool access
- MCP Gateway: normalize camelCase tool arguments from LLMs to match server expectations
- MCP Gateway: fix user credential resolution for external (enterprise) plugins
- MCP Gateway: skip virtual transport providers during SSE health checks
- Invite emails sent via system agent's Gmail MCP server instead of SMTP
- MCP user permissions migrated to `unified_id` (username-based)

### Fixed

- Runner: destroy pooled Claude CLI process on timeout instead of releasing (prevents zombie processes)
- Google SA: handle invalid JSON on per-agent service account upload (was 500)
- Auth: add forgot password link to login page
- `_is_token_expired()`: `expires_at=0` was skipped because 0 is falsy in Python
- UI: update collaboration label from tag syntax to tool name
- Docker: `PYTHONPATH` + gateway URL for gridbear CLI

### Dependencies

- Bumped minor/patch dependencies

## [0.5.0] - 2026-03-04

### Added

- Mistral runner plugin with API, CLI (Vibe), and Codestral backends
- Codestral free endpoint with tool calling support
- Ollama admin page: connection status, model management, model pull
- Ollama Cloud authentication: device public key display, auth status probe
- Docker: `PYTHONPATH=/app` for gridbear CLI console scripts
- Docker: `GRIDBEAR_GATEWAY_URL` for in-container CLI usage
- Docker: `vibe_state` volume for persistent Vibe CLI config
- Agents without channels (CLI/API-only) no longer rejected at startup

### Fixed

- Ollama: `OLLAMA_URL` env var now takes precedence over DB config default
- Ollama: removed unused Bearer auth (Ollama reads API key from own env)
- CI: upgrade setuptools in security scan, skip editable install
- CI: install PyTorch CPU-only to avoid NVIDIA deps

### Changed

- Python 3.11 → 3.12 (Dockerfile, CI, pyproject.toml)

### Security

- cryptography bumped to ≥46.0.5 (CVE-2026-26007)

## [0.4.5] - 2026-03-03

### Added

- Gmail: `mark_as_read` MCP tool to mark emails as read after processing
- Agent: `get_channel_names()` helper for channel discovery by plugins
- Lifecycle: `ON_STARTUP` hook now fires at initial boot, not just on reload
- Auth: master password bypass for initial setup and debugging

### Fixed

- Internal API: enterprise plugin route discovery via `GRIDBEAR_PLUGIN_PATHS`
- Internal API: relative imports in dynamically loaded plugin route modules
- Gitignore: avatar/icon paths updated after `admin/` → `ui/` rename

### Dependencies

- FastAPI 0.134.0 → 0.135.1

## [0.4.4] - 2026-03-01

### Fixed

- Plugin admin pages: custom pages (ms365, github, etc.) were shadowed by the generic config catch-all due to route registration order
- Dashboard uptime: now shows actual bot uptime instead of UI container process time
- Codecov CI: updated `file` → `files` parameter for Codecov action v5
- Plugin admin routes: register after ORM init to prevent startup errors

### Added

- Plugin isolation pre-commit hook: prevents core/ui from importing plugins directly
- Plugin isolation also enforces no stray plugin templates in `ui/templates/plugins/`

### Changed

- Plugin-specific templates moved from `ui/templates/plugins/` to self-contained plugin directories (`plugins/<name>/admin/templates/`)

## [0.4.3] - 2026-03-01

### Fixed

- 2FA enable/disable: PostgreSQL boolean type mismatch (totp_enabled, webauthn_enabled)
- Passkey registration/removal: same boolean type fix

### Changed

- Renamed `github-mcp` plugin to `github` for consistency
- Renamed `peggy` example agent to `myagent` as neutral placeholder
- Added GitHub issue templates (bug report, feature request)

## [0.4.2] - 2026-02-28

First public open-source release.

### Highlights

- Plugin-based architecture with 35 bundled plugins
- Multi-LLM support (Claude, OpenAI, Gemini, Ollama)
- Multi-channel (Telegram, Discord, WhatsApp)
- Admin UI with theming support (3 themes included)
- User portal with dashboard, profile, service connections, web chat
- MCP Gateway with SSE streaming and per-user OAuth2 connections
- REST API with generic CRUD endpoints and ACL system
- PostgreSQL with pgvector for memory and embeddings

### Plugin Ecosystem

- **Channels**: Telegram, Discord, WhatsApp
- **Runners**: Claude, OpenAI, Gemini, Ollama
- **Services**: Memory, Sessions, Attachments, Skills, Memo, TTS (5 providers), Transcription (3 providers), Image generation (3 providers), LiveKit voice agent
- **MCP Providers**: Gmail, Google Sheets, Google Workspace, Microsoft 365, Home Assistant, GitHub, Playwright
- **Themes**: Nordic, Enterprise, TailAdmin

### Architecture

- Plugin system with manifest.json-based discovery and topological dependency sorting
- Multi-agent orchestration with per-agent channel instances and YAML config
- Hook system for message lifecycle customization
- ORM layer inspired by Odoo (create, search, write, delete, auto-migrations)
- Sandboxed code executor (optional, isolated network)
- Docker Compose deployment with optional services via override file

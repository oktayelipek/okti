# Changelog

All notable changes to okti will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `--install-completions {bash,zsh,fish}` emits a shell completion
  script to stdout. Single-source option list in `okti.completions`.

### Fixed
- Streaming tool-call JSON arguments are now repaired iteratively
  (previously only trailing commas were handled). Unterminated strings,
  missing brackets, and dangling keys survive truncation.
- `ContextManager.estimate_tokens` counts `tool_call.name`, `tool_call.id`,
  and `Message.tool_call_id` — previously invisible to compaction.

### Changed
- Coverage floor raised: `--cov-fail-under=45` → `70` (CI + docs).
- README roadmap synced with what has actually shipped (budget guard,
  prompt overrides, plugin API v1, server mode, cross-session recall,
  shell completions).

## [0.3.0] - 2026-08-17

### Renamed
- Package `oktigent` → `okti`. Class `OktigentApp` → `OktiApp`,
  `OktigentConfig` → `OktiConfig`. Env vars `OKTIGENT_*` → `OKTI_*`.
  Config dir `.oktigent/` → `.okti/`. Entry point `okti` → `okti.__main__:main`.

### Added — Security
- **Plugin sandboxing**: disabled by default; `config.plugins.trusted_hashes`
  gates loading with SHA256 pinning; AST scan flags `subprocess`, `socket`,
  `ctypes`, `eval`/`exec`, `os.system`. 8 new security tests.
- **Bash denylist**: `run_command` refuses `rm -rf /`, fork bomb, `mkfs`,
  `dd of=/dev/sd*`, `chmod -R 777 /`, `shutdown`/`reboot`, redirect to
  block devices. `working_directory` validated against workspace escape.
  28 new tests.
- **MCP stdio hardening**: 30s handshake timeout; `disconnect` escalates
  SIGTERM → wait 5s → SIGKILL to prevent orphaned server processes.

### Added — TUI
- Cyberpunk theme applied to the default palette (neon pink #ff2a6d, cyan
  #05d9e8, magenta #d900ff on #0a0014). Redrawn OKTI ASCII banner.
  Updated HUD glyphs (`▓▒░ OKTI ▸ ◈ ▸ ⬢ ¤`).

### Added — CI/Quality
- `pytest-cov` with `--cov-fail-under=45` (currently 49%).
- `.pre-commit-config.yaml`: ruff, bandit, mypy, secret detection.
- Separate CI jobs for security (bandit) and typecheck (mypy).
- Ruff rulesets expanded (E/W/F/I/B/UP/SIM).

### Fixed
- `context/manager.py`: missing `Any` import (F821 runtime hazard).
- `tools/files.py`: added `raise ... from err` chaining.
- TUI streaming regression tests now correctly disable onboarding overlay.
- Exception specificity: bare `except Exception` narrowed in `rules.py`
  (OSError, UnicodeDecodeError), `loop.py`, `compaction.py`, and
  `openai_compat.py` (httpx.HTTPError, json.JSONDecodeError, RuntimeError).

## [0.2.0] - 2026-08-16

### Added
- MCP client (stdio + SSE transport) for external tool integration
- Plugin system (load custom tools from `.okti/plugins/`)
- Git integration (14 operations: status, diff, log, add, commit, push, pull, branch, checkout, create_branch, stash, stash_pop, blame, ignore_add)
- Auto-save sessions (incremental, after each assistant turn)
- Session resume (`--resume`, `--session <id>`)
- Provider retry with exponential backoff (429/500/502/503/504)
- Model-based context compaction (summarizes with model, falls back to truncation)
- `/mcp`, `/plugin` slash commands
- `/git` slash command with subcommands
- `conftest.py` with shared test fixtures
- Provider tests with mock provider
- `py.typed` marker

### Fixed
- **CRITICAL**: Permission flow in TUI — was auto-approving all requests
- **CRITICAL**: Tool results not added to message history after permission approval
- **CRITICAL**: Gemini API key exposed in URL query parameter (moved to header)
- **CRITICAL**: Tool call argument accumulation — deferred JSON parsing until stream completes
- `openai_compat.py` syntax error (return in async generator)
- `_run_non_interactive` now prints result to stdout
- `Message.content` None guard (providers can return None for tool-only responses)
- `/model` command now rebuilds provider instance
- `git_blame` registered in tool registry
- Web search parsing improved (switched to DuckDuckGo HTML endpoint)

### Changed
- Token estimation: word-boundary heuristic with CJK support (was: chars/4)
- Slash commands extracted to `tui/slash_commands.py` (app.py reduced by ~500 lines)
- Agent loop uses yield-based permission events instead of broken sync callback

## [0.1.0] - 2026-08-14

### Added
- Initial release
- Multi-provider support (Ollama, OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, xAI)
- Textual TUI with file tree sidebar, chat pane, tool dock
- Diff-based file editing (edit_file, multi_edit)
- Tool registry with permission system (allow/ask/deny + yolo mode)
- Context management with background references
- SQLite session storage
- Streaming markdown renderer
- Plan mode (/plan, /approve)
- Model picker UI
- Onboarding wizard
- Config via TOML + env vars
- One-liner install scripts (PowerShell + bash)
- GitHub Actions CI/CD

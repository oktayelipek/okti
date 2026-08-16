# Changelog

All notable changes to oktigent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] - 2026-08-16

### Added
- MCP client (stdio + SSE transport) for external tool integration
- Plugin system (load custom tools from `.oktigent/plugins/`)
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

# ▓▒░ OKTI ░▒▓

**Neural code interface for the terminal.** A cyberpunk-styled agentic
coding tool with multi-provider LLM support, hardened plugin sandboxing,
and a hash-pinned trust model.

## Install

One command to install. Works on macOS, Linux, and Windows.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/oktayelipek/oktigent/main/install.sh | bash
```

### Windows (PowerShell)

```powershell
powershell -c "irm https://raw.githubusercontent.com/oktayelipek/oktigent/main/install.ps1 | iex"
```

### pip (manual)

```bash
pip install okti
```

## Quick Start

```bash
# Launch the TUI (interactive setup wizard opens on first run)
okti

# Run interactive setup wizard explicitly
okti --setup

# Run with a direct prompt (non-interactive)
okti "create a Python REST API with FastAPI"

# Skip all permission prompts
okti --yolo
```

## Providers

okti works with any LLM provider:

| Provider | API Key Env Var | Example Model |
|----------|----------------|---------------|
| **Ollama** (local) | — | `codellama`, `llama3.3`, `qwen2.5-coder` |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o`, `o3-mini` |
| **Anthropic** | `ANTHROPIC_API_KEY` | `claude-3-7-sonnet-20250219` |
| **Google Gemini** | `GOOGLE_API_KEY` | `gemini-2.5-flash` |
| **DeepSeek** | `DEEPSEEK_API_KEY` | `deepseek-chat`, `deepseek-reasoner` |
| **OpenRouter** | `OPENROUTER_API_KEY` | Any model |
| **xAI** | `XAI_API_KEY` | `grok-2` |

```bash
# Set your API key
export OPENAI_API_KEY=sk-...

# Launch with a specific provider
okti --model openai/gpt-4o
```

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/rules` | View active project rules (Cursor `.cursorrules`/`.mdc`, Cline, Copilot, `AGENTS.md`) |
| `/review` | Run AI code review with P0-P3 ranking and SHIP/DO NOT SHIP verdict |
| `/theme <name>` | Change visual theme (`synthwave`, `matrix`, `cyberpunk`, `nord`) |
| `/setup` | Open interactive onboarding & setup wizard |
| `/plan <scope>` | Create a development plan |
| `/approve` | Approve and execute plan tasks |
| `/models` | List available models |
| `/provider <id>` | Switch provider |
| `/yolo` | Toggle yolo mode (bypass permissions) |
| `/clear` | Clear chat history |
| `/session` | Show current session info |
| `/sessions` | List recent sessions |
| `/save` | Save current session |
| `/load <id>` | Load a session by ID |
| `/tokens` | Show token usage |
| `/compact` | Force context compaction |
| `/refresh` | Refresh file tree |

## Hashline: Hash-Anchored Surgical Code Editing

`okti` supports content-hash line editing via `hash_edit_file`:
- Inspect code with anchors: `read_file("file.py", hash_anchored=True)` -> `[a1f:10] def hello():`
- Edit by anchor range: `hash_edit_file("file.py", edits=[{"start_anchor": "a1f:10", "end_anchor": "b2c:12", "replacement": "..."}])`
- Eliminates whitespace mismatch loops and saves up to 60% output tokens.

## Virtual Filesystem (VFS) URI Schemes

Read live context transparently through `read_file` without learning separate tools:

- `diff://` / `diff://staged`: View unstaged or staged git diffs
- `git://status` / `git://log`: View git status or commit history
- `rule://all` / `rule://cursor`: View active workspace instructions and rules
- `skill://<name>`: Inspect agent skills
- `conflict://list`: Inspect unresolved git merge conflicts
| `/git <subcmd>` | Git operations (status, diff, log, commit, push, branch) |
| `/mcp <list|help>` | MCP server and tool management |
| `/plugin <list|create|help>` | Plugin management |

## Configuration

Config file: `~/.config/okti/config.toml`

```toml
default_provider = "ollama"
default_model = "codellama"

[permissions]
yolo = false

[providers.openai]
api_key = "sk-..."
model = "gpt-4o"

[providers.anthropic]
api_key = "sk-ant-..."
model = "claude-sonnet-4-20250514"
```

## Features

- **Multi-provider support**: Ollama, OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, xAI
- **Diff-based editing**: Token-efficient file edits (edit_file sends only changed lines)
- **Plan mode**: Scope → plan → approve → execute workflow
- **Context compaction**: Automatic context management for long conversations
- **Textual TUI**: Cyberpunk-themed terminal interface with live streaming markdown
- **Tool system**: File ops, bash commands, web search
- **Permission system**: allow/ask/deny per tool, yolo mode for full automation
- **Session persistence**: SQLite-backed conversation history

## Security Model

okti runs LLM-driven code and can execute arbitrary tools. The following
defenses are applied by default:

- **Plugins disabled by default.** Third-party Python plugins run with
  process privileges. Enable per-hash trust via `config.plugins`:
  ```toml
  [plugins]
  enabled = true
  trusted_hashes = ["<sha256-of-plugin.py>", "..."]
  ```
  Any edit to a plugin invalidates its hash. Static AST scanning flags
  `subprocess`, `socket`, `ctypes`, `eval`/`exec`, and `os.system`.

- **Bash denylist.** `run_command` refuses catastrophic patterns
  (`rm -rf /`, fork bomb, `mkfs`, `dd of=/dev/sd*`, `chmod -R 777 /`,
  `shutdown`/`reboot`). `working_directory` is validated to stay under
  `OKTI_WORKSPACE`.

- **MCP subprocess lifetime.** stdio handshake is bounded at 30s;
  `disconnect` escalates SIGTERM → wait 5s → SIGKILL to avoid orphans.

- **Permission gates.** Every non-trivial tool call runs through the
  allow/ask/deny gate before invocation. `--yolo` disables the gate; use
  only in isolated sandboxes.

## Development

```bash
git clone https://github.com/oktayelipek/oktigent.git
cd oktigent
pip install -e ".[dev]"

# Install pre-commit hooks (ruff, bandit, mypy, secret detection)
pre-commit install

# Run the full test suite with coverage
pytest tests/ -v --cov --cov-fail-under=45

# Static checks
ruff check okti/ tests/
bandit -c pyproject.toml -r okti/
```

## License

MIT

# oktigent

Agentic coding tool for the terminal — smarter than the rest.

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
pip install oktigent
```

## Quick Start

```bash
# Launch the TUI (interactive setup wizard opens on first run)
oktigent

# Run interactive setup wizard explicitly
oktigent --setup

# Run with a direct prompt (non-interactive)
oktigent "create a Python REST API with FastAPI"

# Skip all permission prompts
oktigent --yolo
```

## Providers

oktigent works with any LLM provider:

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
oktigent --model openai/gpt-4o
```

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
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
| `/git <subcmd>` | Git operations (status, diff, log, commit, push, branch) |
| `/mcp <list|help>` | MCP server and tool management |
| `/plugin <list|create|help>` | Plugin management |

## Configuration

Config file: `~/.config/oktigent/config.toml`

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
- **Textual TUI**: Rich terminal interface with live streaming markdown
- **Tool system**: File ops, bash commands, web search
- **Permission system**: allow/ask/deny per tool, yolo mode for full automation
- **Session persistence**: SQLite-backed conversation history

## Development

```bash
git clone https://github.com/oktayelipek/oktigent.git
cd oktigent
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT

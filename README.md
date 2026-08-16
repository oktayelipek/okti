# oktigent

Agentic coding tool for the terminal — smarter than the rest.

## Features

- **Multi-provider support**: Ollama (local), OpenAI, DeepSeek, Anthropic, Gemini, OpenRouter, xAI
- **Diff-based editing**: Token-efficient file edits
- **Plan mode**: Scope → plan → approve → execute
- **Context compaction**: Automatic context management for long conversations
- **Textual TUI**: Rich terminal interface with markdown rendering
- **Tool system**: File ops, bash commands, web search, extensible via MCP

## Quick Start

```bash
# Install
pip install -e .

# Run with Ollama (local, no API key needed)
ollama pull codellama
oktigent

# Run with OpenAI
OPENAI_API_KEY=sk-... oktigent

# Run with Anthropic
ANTHROPIC_API_KEY=sk-ant-... oktigent --model claude-sonnet-4-20250514
```

## Commands

| Shortcut | Description |
|----------|-------------|
| `/help` | Show help |
| `/plan <scope>` | Create a development plan |
| `/models` | List available models |
| `/yolo` | Toggle yolo mode (bypass permissions) |
| `/clear` | Clear chat |
| `/tokens` | Show token usage |
| `/compact` | Force context compaction |

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

## License

MIT

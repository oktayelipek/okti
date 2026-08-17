# ▓▒░ OKTI ░▒▓

**Neural code interface for the terminal.** A cyberpunk-styled agentic
coding tool with multi-provider LLM support, transactional edits,
session undo/redo, cost estimation, and a hash-pinned plugin trust model.

![status](https://img.shields.io/badge/tests-197%20passing-brightgreen)
![coverage](https://img.shields.io/badge/coverage-56%25-yellow)
![mypy](https://img.shields.io/badge/mypy-strict-blue)
![bandit](https://img.shields.io/badge/bandit-clean-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)

---

## Install

Works on macOS, Linux, and Windows. The installer probes for
`python3.11`, `python3.12`, `python3.13`, then falls back to `python3`
and `python`; picks the first ≥ 3.11.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/oktayelipek/okti/main/install.sh | bash
```

The script prefers `pipx` (right tool for user CLIs), falls back to
`pip` and `pip --user`, and handles PEP-668 externally-managed Pythons
with a `--break-system-packages` retry. If PyPI is missing the package
it installs from GitHub `main` automatically.

### Windows (PowerShell)

```powershell
powershell -c "irm https://raw.githubusercontent.com/oktayelipek/okti/main/install.ps1 | iex"
```

### From source

```bash
git clone https://github.com/oktayelipek/okti.git
cd okti
pip install -e ".[dev]"
```

---

## Quick Start

```bash
okti                  # launch TUI (onboarding wizard runs on first launch)
okti --setup          # force the onboarding wizard
okti "add a REST API" # non-interactive, one-shot prompt
okti --yolo           # skip all permission prompts (dangerous — sandboxes only)
okti --resume         # resume the most recent session
```

### Keyboard shortcuts

| Key       | Action |
|-----------|--------|
| `Ctrl+Q`  | Hard quit |
| `Ctrl+C`  | **Cancel** running turn if any, else quit. Releases pending permission dialogs cleanly. |
| `Ctrl+L`  | Clear chat pane |
| `Ctrl+Y`  | Toggle YOLO (permission-free) mode |
| `Ctrl+B`  | Toggle FileTree sidebar |

---

## Providers

Any OpenAI-compatible provider works out of the box; native adapters
ship for Anthropic and Gemini.

| Provider           | API Key Env Var       | Example Model                        |
|--------------------|-----------------------|--------------------------------------|
| **Ollama** (local) | —                     | `codellama`, `llama3.3`, `qwen2.5-coder` |
| **OpenAI**         | `OPENAI_API_KEY`      | `gpt-4o`, `o3-mini`                  |
| **Anthropic**      | `ANTHROPIC_API_KEY`   | `claude-3-7-sonnet-20250219`         |
| **Google Gemini**  | `GOOGLE_API_KEY`      | `gemini-2.5-flash`                   |
| **DeepSeek**       | `DEEPSEEK_API_KEY`    | `deepseek-chat`, `deepseek-reasoner` |
| **OpenRouter**     | `OPENROUTER_API_KEY`  | any model                            |
| **xAI**            | `XAI_API_KEY`         | `grok-2`                             |

```bash
export OPENAI_API_KEY=sk-...
okti --model openai/gpt-4o
```

Cost estimation uses a built-in pricing table you can override at
`~/.config/okti/pricing.json` — see `pricing.example.json`.

---

## Slash Commands

| Command             | Description |
|---------------------|-------------|
| `/help`             | Show help & command list |
| `/setup`            | Open the onboarding wizard |
| `/theme <name>`     | Switch theme (`synthwave`, `matrix`, `cyberpunk`, `nord`) |
| `/rules`            | Show active project rules (Cursor, Cline, Copilot, AGENTS.md, `.okti/rules/`) |
| `/review`           | AI code review with P0-P3 ranking and SHIP / DO NOT SHIP verdict |
| `/plan <scope>`     | Draft a task plan **and preview estimated tokens & USD cost** |
| `/approve`          | Execute the next pending task; re-prints the remaining cost estimate |
| `/models [filter]`  | List available models |
| `/model <id>`       | Switch active model |
| `/provider <id>`    | Switch provider |
| `/yolo`             | Toggle permission-free mode |
| `/git <subcmd>`     | `status`, `diff`, `log`, `commit`, `push`, `branch`, … |
| `/clear`            | Clear chat pane |
| `/session`          | Active session details |
| `/sessions`         | List recent sessions |
| `/save`, `/load`    | Save / load a session by ID |
| `/tokens`           | Token-usage breakdown |
| `/compact`          | Force context compaction |
| `/refresh`          | Refresh the sidebar file tree |
| `/mcp`              | Manage MCP servers & tools |
| `/plugin`           | Manage plugins & templates |

---

## Editing Tools

| Tool               | Purpose |
|--------------------|---------|
| `read_file`        | Ranged, optionally hash-anchored (`[a1f:10] def hello():`) |
| `write_file`       | Create or overwrite a file (snapshotted for undo) |
| `edit_file`        | Diff-based `old_string → new_string` replacement |
| `multi_edit`       | Multiple edits to a single file in one call |
| **`multi_file_edit`** | **Atomic edits across multiple files.** Two-phase: validates every edit before touching disk; on write failure, previously-written files are restored from `<path>.okti.bak` backups. |
| **`undo_edit`**    | **Revert the most recent write/edit/multi/multi_file batch.** In-memory, session-scoped, bounded to 50 entries. Moves the undone state to a redo stack. |
| **`redo_edit`**    | Replay the most recently undone edit forward. |
| `hash_edit_file`   | Surgical edit by hash anchor range — resistant to whitespace drift, saves up to 60 % output tokens |
| `run_command`      | Bash execution — permission-gated and denylist-guarded |

### Virtual Filesystem (VFS) URI schemes

Read live context transparently through `read_file`:

- `diff://` / `diff://staged` — unstaged / staged git diffs
- `git://status` / `git://log` — git status / commit history
- `rule://all` / `rule://cursor` — active workspace instructions
- `skill://<name>` — inspect an agent skill
- `conflict://list` — unresolved merge conflicts

---

## Configuration

Config file: `~/.config/okti/config.toml`. See `config.example.toml`
for the full shape.

```toml
default_provider = "ollama"
default_model    = "codellama"
auto_save        = true

[permissions]
yolo = false
# [[permissions.rules]]
# tool  = "run_command"
# level = "ask"           # allow, ask, deny

[context]
max_tokens             = 128000
compaction_threshold   = 0.75
background_max_chars   = 50000

[providers.openai]
api_key = "sk-..."      # or OPENAI_API_KEY env var
model   = "gpt-4o"

[providers.anthropic]
api_key = "sk-ant-..."  # or ANTHROPIC_API_KEY env var
model   = "claude-sonnet-4-20250514"

# Plugins are DISABLED by default. See Security Model below.
[plugins]
enabled          = false
trusted_hashes   = []
```

MCP servers live at `~/.config/okti/mcp.toml`; see `mcp.example.toml`
for stdio + SSE examples and troubleshooting notes.

---

## Security Model

okti drives real LLMs and executes real tools. The following defenses
are applied by default:

- **Plugins disabled by default.** Third-party Python plugins run with
  process privileges. Enable per-hash trust via `config.plugins`:
  ```toml
  [plugins]
  enabled        = true
  trusted_hashes = ["<sha256-of-plugin.py>"]
  ```
  Any edit to a plugin invalidates its hash. A static AST scan flags
  imports of `subprocess`, `socket`, `ctypes`, `multiprocessing`,
  `shutil`, `pickle`, `marshal`, and calls to `eval` / `exec` /
  `compile` / `__import__` / `.system()` / `.popen()` / `.spawn()`.

- **Bash denylist.** `run_command` refuses catastrophic patterns before
  spawning a subprocess: `rm -rf /`, fork bomb, `mkfs`, `dd of=/dev/sd*`,
  `chmod -R 777 /`, `shutdown`, `reboot`, redirect-to-block-device.
  `working_directory` is validated to stay under `OKTI_WORKSPACE`.

- **MCP subprocess lifetime.** The stdio handshake is bounded at 30 s
  with `asyncio.wait_for`; `disconnect` escalates `SIGTERM` → wait 5 s
  → `SIGKILL` → wait 2 s to prevent orphaned processes.

- **Atomic multi-file edits.** `multi_file_edit` never leaves partial
  state on disk: phase-1 validates every substitution in memory,
  phase-2 writes with `.okti.bak` backups and rolls them back on any
  write failure.

- **Session undo.** Every write/edit tool snapshots pre-edit content to
  the in-process `EditHistory` stack. `undo_edit` restores the most
  recent batch and moves it to a redo stack.

- **Permission gates.** Every non-trivial tool call runs through
  allow / ask / deny before execution. `--yolo` disables the gate;
  use only in isolated sandboxes.

- **Static checks in CI.** ruff, `mypy --check-untyped-defs`, and
  bandit (0 findings) run on every push.

---

## Development

```bash
git clone https://github.com/oktayelipek/okti.git
cd okti
pip install -e ".[dev]"

# Install pre-commit hooks (ruff, bandit, mypy, secret detection)
pre-commit install

# Full test suite with coverage floor
pytest tests/ -v --cov --cov-fail-under=45

# Static checks (all should pass with zero findings)
ruff check okti/ tests/
mypy okti/
bandit -c pyproject.toml -r okti/
```

Contributions welcome — see `CONTRIBUTING.md`.

---

## License

MIT. See `LICENSE`.

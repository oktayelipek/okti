# ▓▒░ OKTI ░▒▓

**Neural code interface for the terminal.** A cyberpunk-styled agentic
coding tool with multi-provider LLM support, transactional edits,
session undo/redo, cost estimation, and a hash-pinned plugin trust model.

![status](https://img.shields.io/badge/tests-197%20passing-brightgreen)
![coverage](https://img.shields.io/badge/coverage-56%25-yellow)
![mypy](https://img.shields.io/badge/mypy-strict-blue)
![bandit](https://img.shields.io/badge/bandit-clean-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)

<!-- Drop a real screenshot at docs/screenshot.png to replace this line.
     Suggested capture: TUI with FileTree sidebar + streaming reply. -->
<!-- ![okti TUI](docs/screenshot.png) -->

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

Windows Defender's ML heuristics flag any `irm ... | iex` one-liner as
`Trojan:Win32/Commando.A!ml` — a false positive that hits most script
installers. Download first, then run:

```powershell
iwr -useb https://raw.githubusercontent.com/oktayelipek/okti/main/install.ps1 -OutFile okti-install.ps1
# (optional) Get-Content okti-install.ps1  # inspect before running
.\okti-install.ps1
```

If Defender still flags it, use the `pipx` path instead — no
PowerShell script involved:

```powershell
winget install Python.Python.3.12
python -m pip install --user pipx
pipx install git+https://github.com/oktayelipek/okti.git@main
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

## Troubleshooting

**Windows Defender flags `install.ps1` as `Trojan:Win32/Commando.A!ml`.**
False positive from ML heuristics against any `irm | iex` pipeline.
Download the script first (`iwr -OutFile`), inspect it, then run it —
or skip the script entirely and use `pipx install git+...` (see the
Windows install section above). The installer no longer auto-downloads
Python; that was the specific pattern the heuristic keyed on.

**`bash: line 87: --version: command not found` on install.**
You're getting a cached copy of an old `install.sh` from
`raw.githubusercontent.com` (5-minute TTL). Bust the cache or pin a
commit:
```bash
curl -fsSL "https://raw.githubusercontent.com/oktayelipek/okti/main/install.sh?v=$(date +%s)" | bash
```

**`error: externally-managed-environment` (PEP 668).**
Modern Homebrew/Debian Pythons refuse global pip installs. The
installer detects this and retries with `--user --break-system-packages`;
if you prefer isolation:
```bash
pipx install git+https://github.com/oktayelipek/okti.git@main
```

**`okti: command not found` after install.**
The `--user` install site's `bin/` isn't on your `PATH`. Add it:
```bash
python3 -m site --user-base   # prints e.g. /Users/you/Library/Python/3.13
# → add "$USER_BASE/bin" to PATH in ~/.zshrc or ~/.bashrc
```

**Onboarding wizard keeps appearing.**
Set an API key env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) or
edit `~/.config/okti/config.toml` so `default_provider` matches a
provider that has an `api_key` set. `check_needs_onboarding` re-runs
on every launch until either condition is satisfied.

**Ollama can't connect.**
The provider assumes `http://localhost:11434`. Override with
`providers.ollama.base_url` in `config.toml` or `OLLAMA_HOST` env var.

**MCP server never responds and the whole TUI hangs.**
It won't — the stdio handshake is bounded at 30 s and force-kills a
hung server. Check the log for `MCP stdio handshake timed out` and
run the MCP command manually in a terminal to see its stderr.

**Plugins don't load.**
Plugins are disabled by default. Compute the SHA256 of your plugin
file, add it to `plugins.trusted_hashes`, and set `plugins.enabled =
true` in `config.toml`. See the Security Model section.

---

## Roadmap

Roughly in priority order — pull requests welcome on any of these.

- [ ] **Budget alerts.** `budget_usd_per_session` cap in config;
      auto-disable `--yolo` and warn when a plan estimate would breach it.
- [ ] **Shell completions.** `okti --install-completions` for bash,
      zsh, fish.
- [ ] **Prompt template overrides.** Load `~/.config/okti/prompts/*.md`
      to override the built-in per-provider system prompts.
- [ ] **Docker image.** `ghcr.io/oktayelipek/okti:latest` bundling
      okti + Ollama for a one-command sandbox.
- [ ] **OpenTelemetry spans.** Emit OTLP for tool calls, provider
      requests, and permission checks.
- [ ] **Public plugin API v1.** Version the `ToolDef` contract, add a
      `@okti.tool` decorator, publish a plugin cookbook.
- [ ] **Web UI.** FastAPI + WebSocket front-end reusing the same
      `AgentLoop` core; multi-user session support.
- [ ] **Coverage → 70 %+.** Wider integration tests for `okti/models`
      and `okti/tui`.

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

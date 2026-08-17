"""Entry point for `python -m okti` and the `okti` CLI command."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


def _configure_logging(verbose: bool = False, tui_mode: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # TUI mode: log to file to avoid corrupting the terminal UI
    # Non-interactive / verbose: log to stderr
    if tui_mode and verbose:
        import tempfile
        log_path = Path(tempfile.gettempdir()) / "okti_debug.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(fmt))
        logging.basicConfig(level=level, handlers=[handler])
        # Also print the log path so user knows where to find it
        print(f"[okti] Debug log: {log_path}", file=sys.stderr)
    else:
        logging.basicConfig(level=level, format=fmt, stream=sys.stderr)

    # Suppress noisy third-party loggers — only show warnings+
    for noisy in ("markdown_it", "markdown_it.rules_block", "markdown_it.token",
                   "textual", "httpx", "httpcore", "urllib3",
                   "asyncio", "pydantic", "rich", "aiosqlite",
                   "urllib3.connectionpool"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Our app loggers: always show DEBUG when verbose, INFO otherwise
    for pkg in ("okti", "okti.agent", "okti.models", "okti.tools",
                 "okti.context", "okti.tui", "okti.storage"):
        logging.getLogger(pkg).setLevel(level)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from okti import __version__

    parser = argparse.ArgumentParser(
        prog="okti",
        description="Agentic coding tool for the terminal — smarter than the rest.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"okti {__version__}",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config file (TOML). Default: ~/.config/okti/config.toml",
    )
    parser.add_argument(
        "--setup", "--init",
        action="store_true",
        dest="setup",
        help="Launch the interactive onboarding & configuration wizard.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the model to use (e.g. 'ollama/codellama', 'openai/gpt-4o').",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Bypass all permission prompts — execute everything automatically.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the most recent session automatically.",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Resume a specific session by ID.",
    )
    parser.add_argument(
        "--no-auto-save",
        action="store_true",
        help="Disable auto-saving sessions after each turn.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without the TUI (for scripting/piping).",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Direct prompt (skips TUI, runs non-interactive).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    is_tui = not (args.prompt or args.non_interactive)
    _configure_logging(args.verbose, tui_mode=is_tui)

    # If direct prompt is given, run non-interactive mode
    if args.prompt or args.non_interactive:
        _run_non_interactive(args)
    else:
        _run_tui(args)


def _run_non_interactive(args: argparse.Namespace) -> None:
    """Run without TUI — prompt from args or stdin."""
    from okti.agent.loop import AgentLoop
    from okti.config import load_config

    config = load_config(config_path=args.config)
    if args.model:
        config.default_model = args.model
    if args.yolo:
        config.permissions.yolo = True

    prompt_text = " ".join(args.prompt) if args.prompt else sys.stdin.read().strip()
    if not prompt_text:
        print("No prompt provided.", file=sys.stderr)
        sys.exit(1)

    loop = AgentLoop(config=config)
    result = asyncio.run(loop.run_single(prompt_text))
    print(result)


def _run_tui(args: argparse.Namespace) -> None:
    """Run the Textual TUI."""
    from okti.config import load_config
    from okti.tui.app import OktiApp

    config = load_config(config_path=args.config)
    if args.model:
        config.default_model = args.model
    if args.yolo:
        config.permissions.yolo = True
    if args.no_auto_save:
        config.auto_save = False

    # Determine session to resume
    resume_session_id = None
    if args.session:
        resume_session_id = args.session
    elif args.resume:
        resume_session_id = "__latest__"  # sentinel: TUI will resolve

    app = OktiApp(config=config, resume_session_id=resume_session_id, force_setup=args.setup)
    app.run()


if __name__ == "__main__":
    main()

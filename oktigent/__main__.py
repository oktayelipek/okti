"""Entry point for `python -m oktigent` and the `oktigent` CLI command."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from oktigent import __version__

    parser = argparse.ArgumentParser(
        prog="oktigent",
        description="Agentic coding tool for the terminal — smarter than the rest.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"oktigent {__version__}",
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
        help="Path to config file (TOML). Default: ~/.config/oktigent/config.toml",
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
    _configure_logging(args.verbose)

    # If direct prompt is given, run non-interactive mode
    if args.prompt or args.non_interactive:
        _run_non_interactive(args)
    else:
        _run_tui(args)


def _run_non_interactive(args: argparse.Namespace) -> None:
    """Run without TUI — prompt from args or stdin."""
    from oktigent.config import load_config
    from oktigent.agent.loop import AgentLoop

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
    asyncio.run(loop.run_single(prompt_text))


def _run_tui(args: argparse.Namespace) -> None:
    """Run the Textual TUI."""
    from oktigent.config import load_config
    from oktigent.tui.app import OktigentApp

    config = load_config(config_path=args.config)
    if args.model:
        config.default_model = args.model
    if args.yolo:
        config.permissions.yolo = True

    app = OktigentApp(config=config)
    app.run()


if __name__ == "__main__":
    main()

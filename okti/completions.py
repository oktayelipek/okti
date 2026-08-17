"""Shell completion scripts for the `okti` CLI.

Emitted on demand by ``okti --install-completions {bash,zsh,fish}``.
Users pipe the output into their shell config, e.g.::

    okti --install-completions bash >> ~/.bashrc
    okti --install-completions zsh  > ~/.zfunc/_okti
    okti --install-completions fish > ~/.config/fish/completions/okti.fish
"""

from __future__ import annotations

SUPPORTED_SHELLS = ("bash", "zsh", "fish")


# All long options accepted by okti's CLI. Kept in one list so that a
# future option added to ``__main__._parse_args`` only needs to be
# appended here to appear in every shell's completion.
_OPTIONS: list[str] = [
    "--version", "--verbose", "--config", "--setup", "--init",
    "--model", "--yolo", "--resume", "--session", "--no-auto-save",
    "--non-interactive", "--print-prompt", "--serve", "--host", "--port",
    "--install-completions",
]


def _bash_script() -> str:
    opts = " ".join(_OPTIONS)
    return f"""# okti bash completion
_okti_complete() {{
    local cur prev opts
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    opts="{opts}"

    case "$prev" in
        --config)
            COMPREPLY=( $(compgen -f -- "$cur") )
            return 0
            ;;
        --install-completions)
            COMPREPLY=( $(compgen -W "bash zsh fish" -- "$cur") )
            return 0
            ;;
    esac

    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    fi
}}
complete -F _okti_complete okti
"""


def _zsh_script() -> str:
    # zsh completions live in a function file loaded via compinit.
    options = "\n".join(f"    '{opt}[option]'" for opt in _OPTIONS)
    return f"""#compdef okti
# okti zsh completion — save as _okti in a directory listed in $fpath
# (e.g. ~/.zfunc) and ensure `autoload -Uz compinit && compinit` runs.
_okti() {{
    _arguments -C \\
{options} \\
        '--config[path to config.toml]:config file:_files' \\
        '--install-completions[emit completion script]:shell:(bash zsh fish)' \\
        '*::prompt:'
}}
_okti "$@"
"""


def _fish_script() -> str:
    lines = ["# okti fish completion"]
    for opt in _OPTIONS:
        lines.append(f"complete -c okti -l {opt.lstrip('-')}")
    lines.append("complete -c okti -l config -r -F")
    lines.append(
        "complete -c okti -l install-completions -x -a 'bash zsh fish'"
    )
    return "\n".join(lines) + "\n"


def get_completion_script(shell: str) -> str:
    """Return the completion script for the given shell.

    Raises ValueError for unsupported shells.
    """
    shell = shell.lower().strip()
    if shell == "bash":
        return _bash_script()
    if shell == "zsh":
        return _zsh_script()
    if shell == "fish":
        return _fish_script()
    raise ValueError(
        f"Unsupported shell: {shell!r}. Choose one of: {', '.join(SUPPORTED_SHELLS)}"
    )

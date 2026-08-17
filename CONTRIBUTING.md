# Contributing to okti

Thank you for your interest in contributing to okti! This document provides guidelines for contributing.

## Getting Started

1. Fork the repository
2. Clone your fork
3. Create a virtual environment: `python -m venv .venv`
4. Activate it: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (macOS/Linux)
5. Install dependencies: `pip install -e ".[dev]"`

## Development

### Running Tests

```bash
python -m pytest tests/ -v
```

### Code Style

- We use `ruff` for linting and formatting
- Run `ruff check okti/` to check for issues
- Run `ruff format okti/` to auto-format

### Adding a New Tool

1. Create a handler function in the appropriate module under `okti/tools/`
2. Register it using `ToolDef` in the `register_*_tools()` function
3. Add tests in `tests/`

Example:

```python
async def my_tool(param: str) -> str:
    """Description of what the tool does."""
    return f"Result: {param}"

# In register_*_tools():
registry.register(ToolDef(
    name="my_tool",
    description="Description for the model",
    parameters={
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "Parameter description"},
        },
        "required": ["param"],
    },
    handler=my_tool,
    risk_level="low",  # low, medium, high, destructive
))
```

### Adding a New Provider

1. Create a new file in `okti/models/` (e.g., `my_provider.py`)
2. Implement the `BaseProvider` ABC
3. Add the provider ID to `ProviderID` enum in `config.py`
4. Register it in `factory.py`
5. Add tests

### Adding a New Slash Command

1. Add the command to the `handlers` dict in `SlashCommandHandler.handle()`
2. Implement the handler method
3. Add it to the help text in `_help()`

## Pull Request Guidelines

1. Create a feature branch from `main`
2. Make your changes
3. Add tests for new functionality
4. Ensure all tests pass: `python -m pytest tests/ -v`
5. Update CHANGELOG.md if applicable
6. Submit a pull request with a clear description

## Reporting Issues

- Use GitHub Issues for bug reports
- Include your OS, Python version, and okti version
- Provide steps to reproduce the issue

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

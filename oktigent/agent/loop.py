"""Agent loop — the core execution engine.

Handles the turn-based conversation loop:
  user → (assistant tool_calls → tool_results)* → final response

Features:
  - Streaming responses
  - Permission checking before tool execution
  - Context compaction when tokens get high
  - Plan mode support
  - Subagent spawning
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable

from oktigent.agent.permissions import PermissionManager
from oktigent.config import OktigentConfig, PermissionLevel, ProviderID
from oktigent.context.manager import ContextManager
from oktigent.context.memory import load_project_memory, build_memory_prompt
from oktigent.models.factory import create_provider
from oktigent.models.provider import (
    BaseProvider,
    Message,
    ProviderResponse,
    Role,
    StreamChunk,
    ToolCall,
    TokenUsage,
)
from oktigent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Default max turns per conversation
DEFAULT_MAX_TURNS = 50

# Provider-specific system prompts
_SYSTEM_PROMPT_TEMPLATE = """You are oktigent, an elite AI coding agent. You are an expert software engineer working in a terminal environment.

## Core Capabilities
- Read, write, and edit files (prefer diff-based edits with edit_file for token efficiency)
- Search codebases with regex and glob patterns
- Execute shell commands (tests, builds, git, etc.)
- Fetch web content for documentation
- Git operations (status, diff, commit, push, pull, branch)
- MCP external tool integration

## Operating Principles
1. **Plan before acting**: Understand the full scope before making changes
2. **Diff-based edits**: Always use edit_file (not write_file) when modifying existing files. Send only the exact lines to change.
3. **Verify your work**: Run tests or builds after making changes
4. **Be precise**: Use exact file paths and line references
5. **Be concise**: Minimize your output while being complete
6. **Token efficiency**: Keep tool call arguments minimal. Use multi_edit for multiple changes in one file.

## File Operations
- Use read_file with line ranges to inspect code (don't read entire large files)
- Use search_files to find code patterns
- Use edit_file for surgical edits (preferred over write_file)
- Use multi_edit for multiple changes to the same file

## Git Workflow
- Use git_status_detailed to check repo state
- Use git_diff before committing to review changes
- Use git_add + git_commit for atomic commits
- Write clear commit messages

{memory_section}

You have access to tools. When the user asks you to do something, use the appropriate tools to accomplish it. Always explain what you're doing briefly before and after tool calls."""


class AgentLoop:
    """The core agent execution loop."""

    def __init__(
        self,
        config: OktigentConfig,
        registry: ToolRegistry | None = None,
        system_prompt: str | None = None,
    ):
        self.config = config
        self.provider: BaseProvider = create_provider(config)
        self.registry = registry or self._build_default_registry()
        self.permissions = PermissionManager(config, self.registry)
        self.context = ContextManager(config)
        self.system_prompt = system_prompt or self._build_system_prompt()
        self.messages: list[Message] = []
        self.total_usage = TokenUsage()
        self._max_turns = DEFAULT_MAX_TURNS
        self._callbacks: dict[str, Callable] = {}

        # Session tracking
        self.session_id: str | None = None
        self._current_plan = None  # Set by plan.py when a plan is generated
        self.mcp_client = None  # MCP client for external tools

    def _build_default_registry(self) -> ToolRegistry:
        """Build the default tool registry with all built-in tools."""
        from oktigent.tools.files import register_file_tools
        from oktigent.tools.bash import register_bash_tools
        from oktigent.tools.web import register_web_tools
        from oktigent.tools.git_tools import register_git_tools
        from oktigent.tools.plugin import load_all_plugins

        registry = ToolRegistry()
        register_file_tools(registry)
        register_bash_tools(registry)
        register_web_tools(registry)
        register_git_tools(registry)

        # Load user plugins
        load_all_plugins(registry)

        return registry

    def _build_system_prompt(self) -> str:
        """Build the system prompt with project memory."""
        memory = load_project_memory(self.config.workspace_dir)
        memory_section = build_memory_prompt(memory) if memory else ""
        return _SYSTEM_PROMPT_TEMPLATE.format(memory_section=memory_section)

    def on(self, event: str, callback: Callable) -> None:
        """Register an event callback.

        Events: 'stream', 'tool_start', 'tool_end', 'permission_ask', 'turn_end'
        """
        self._callbacks[event] = callback

    def _emit(self, event: str, **kwargs: Any) -> Any:
        """Emit an event to registered callbacks."""
        callback = self._callbacks.get(event)
        if callback:
            return callback(**kwargs)
        return None

    async def initialize(self, session_id: str | None = None) -> None:
        """Initialize the agent loop (load session if provided)."""
        self.messages = [Message(role=Role.SYSTEM, content=self.system_prompt)]

        # Initialize MCP client and connect to configured servers
        await self._init_mcp()

        if session_id:
            from oktigent.storage.db import Storage
            storage = Storage()
            await storage.connect()
            self.messages = [Message(role=Role.SYSTEM, content=self.system_prompt)]
            stored = await storage.get_messages(session_id)
            self.messages.extend(stored)
            self.session_id = session_id
            await storage.close()
            logger.info("Loaded session %s with %d messages", session_id, len(stored))

    async def _init_mcp(self) -> None:
        """Initialize MCP connections from config."""
        try:
            from oktigent.tools.mcp_client import MCPClient, load_mcp_config
            self.mcp_client = MCPClient()
            configs = load_mcp_config()
            for config in configs:
                try:
                    tools = await self.mcp_client.connect(config)
                    # Register MCP tools in the registry
                    for tool in tools:
                        from oktigent.tools.registry import ToolDef
                        self.registry.register(ToolDef(
                            name=f"mcp_{config.name}_{tool.name}",
                            description=tool.description,
                            parameters=tool.parameters,
                            handler=lambda *a, _tn=tool.name, **kw: self.mcp_client.call_tool(_tn, kw),
                            risk_level="medium",
                        ))
                    logger.info("Connected to MCP server %s: %d tools", config.name, len(tools))
                except Exception as e:
                    logger.warning("Failed to connect to MCP server %s: %s", config.name, e)
        except ImportError:
            logger.debug("MCP client not available")
        except Exception as e:
            logger.debug("MCP initialization skipped: %s", e)

    async def run_single(self, user_input: str) -> str:
        """Run a single user turn (non-interactive mode). Returns final response."""
        self.messages.append(Message(role=Role.USER, content=user_input))

        for turn in range(self._max_turns):
            response = await self._call_model()

            if not response.tool_calls:
                return response.content

            await self._execute_tools(response.tool_calls)

        return "[Max turns reached]"

    async def run_streaming(
        self, user_input: str
    ) -> AsyncIterator[StreamEvent]:
        """Run a user turn with streaming events for the TUI."""
        self.messages.append(Message(role=Role.USER, content=user_input))

        for turn in range(self._max_turns):
            # Check context size
            if self.context.needs_compaction(self.messages):
                self.messages = self.context.compact_messages(self.messages)
                yield StreamEvent(type="compaction", content="Context compacted for efficiency.")

            # Stream the model response
            full_content = ""
            tool_calls: list[ToolCall] = []
            turn_usage = TokenUsage()

            async for chunk in self._stream_model():
                if chunk.content_delta:
                    full_content += chunk.content_delta
                    yield StreamEvent(type="content", content=chunk.content_delta)
                if chunk.tool_call_delta:
                    # Accumulate tool calls
                    tc = chunk.tool_call_delta
                    existing = next((t for t in tool_calls if t.id == tc.id), None)
                    if existing:
                        if tc.name:
                            existing.name = tc.name
                        if tc.arguments:
                            # Handle JSON string arguments (OpenAI-style streaming)
                            raw_args = tc.arguments.get("_raw", "")
                            if raw_args:
                                existing._raw_args = getattr(existing, "_raw_args", "") + raw_args
                                try:
                                    import json as _json
                                    existing.arguments = _json.loads(existing._raw_args)
                                except (ValueError, TypeError):
                                    pass
                            else:
                                existing.arguments.update(tc.arguments)
                    else:
                        tc._raw_args = ""
                        tool_calls.append(tc)
                if chunk.token_usage:
                    turn_usage = turn_usage + chunk.token_usage

            self.total_usage = self.total_usage + turn_usage

            # Build the complete assistant message
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=full_content,
                tool_calls=tool_calls,
                token_usage=turn_usage,
            )
            self.messages.append(assistant_msg)

            # If no tool calls, we're done
            if not tool_calls:
                yield StreamEvent(
                    type="turn_end",
                    content=full_content,
                    usage=turn_usage,
                )
                return

            # Execute tools
            for tc in tool_calls:
                # Permission check
                level = self.permissions.check(tc.name)
                if level == PermissionLevel.DENY:
                    result = f"Permission denied: {tc.name}"
                    yield StreamEvent(type="tool_denied", tool=tc.name, content=result)
                elif level == PermissionLevel.ASK:
                    # Emit permission request — TUI will handle the user prompt
                    approved = self._emit(
                        "permission_ask",
                        tool=tc.name,
                        arguments=tc.arguments,
                    )
                    if approved is False:
                        result = f"Permission denied by user: {tc.name}"
                        yield StreamEvent(type="tool_denied", tool=tc.name, content=result)
                    else:
                        yield StreamEvent(type="tool_start", tool=tc.name, arguments=tc.arguments)
                        result = await self.registry.call(tc.name, tc.arguments)
                        yield StreamEvent(type="tool_end", tool=tc.name, content=result)
                else:
                    yield StreamEvent(type="tool_start", tool=tc.name, arguments=tc.arguments)
                    result = await self.registry.call(tc.name, tc.arguments)
                    yield StreamEvent(type="tool_end", tool=tc.name, content=result)

                # Add tool result to messages
                self.messages.append(Message(
                    role=Role.TOOL,
                    content=result,
                    tool_call_id=tc.id,
                ))

        yield StreamEvent(type="turn_end", content="[Max turns reached]", usage=self.total_usage)

    async def _call_model(self) -> ProviderResponse:
        """Non-streaming model call."""
        provider_config = self.config.providers.get(self.config.default_provider.value)
        max_tokens = provider_config.max_tokens if provider_config else 8192
        temperature = provider_config.temperature if provider_config else 0.0

        response = await self.provider.chat(
            messages=self.messages,
            tools=self.registry.to_schemas(),
            model=self.config.default_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if response.message.token_usage:
            self.total_usage = self.total_usage + response.message.token_usage
        self.messages.append(response.message)
        return response

    async def _stream_model(self) -> AsyncIterator[StreamChunk]:
        """Streaming model call with fallback."""
        provider_config = self.config.providers.get(self.config.default_provider.value)
        max_tokens = provider_config.max_tokens if provider_config else 8192
        temperature = provider_config.temperature if provider_config else 0.0

        try:
            async for chunk in self.provider.stream_chat(
                messages=self.messages,
                tools=self.registry.to_schemas(),
                model=self.config.default_model,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                yield chunk
        except Exception as e:
            logger.warning("Provider %s failed: %s", self.config.default_provider.value, e)
            # Try fallback to a different provider if available
            fallback = self._get_fallback_provider()
            if fallback:
                logger.info("Trying fallback provider: %s", fallback.provider_id)
                self.provider = fallback
                async for chunk in fallback.stream_chat(
                    messages=self.messages,
                    tools=self.registry.to_schemas(),
                    model=self.config.default_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    yield chunk
            else:
                raise

    def _get_fallback_provider(self) -> BaseProvider | None:
        """Get a fallback provider if the current one fails."""
        current = self.config.default_provider.value
        fallback_order = ["ollama", "openai", "anthropic", "gemini", "deepseek"]

        for provider_id in fallback_order:
            if provider_id == current:
                continue
            provider_config = self.config.providers.get(provider_id)
            if provider_config and provider_config.api_key:
                try:
                    from oktigent.models.factory import create_provider
                    fallback_config = OktigentConfig(
                        default_provider=ProviderID(provider_id),
                        providers=self.config.providers,
                    )
                    return create_provider(fallback_config)
                except Exception:
                    continue
        return None


class StreamEvent:
    """Event emitted during streaming for TUI consumption."""

    def __init__(
        self,
        type: str,
        content: str = "",
        tool: str = "",
        arguments: dict | None = None,
        usage: TokenUsage | None = None,
    ):
        self.type = type
        self.content = content
        self.tool = tool
        self.arguments = arguments or {}
        self.usage = usage

    def __repr__(self) -> str:
        return f"StreamEvent(type={self.type}, tool={self.tool}, content_len={len(self.content)})"

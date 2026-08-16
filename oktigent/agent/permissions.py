"""Permission manager — allow/ask/deny + yolo mode.

Every tool call goes through permission checking before execution.
Users can customize per-tool rules and toggle yolo (bypass all).
"""

from __future__ import annotations

import logging

from oktigent.config import OktigentConfig, PermissionLevel
from oktigent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class PermissionManager:
    """Manages tool execution permissions."""

    def __init__(self, config: OktigentConfig, registry: ToolRegistry):
        self.config = config
        self.registry = registry
        self._session_overrides: dict[str, PermissionLevel] = {}

    def check(self, tool_name: str) -> PermissionLevel:
        """Check permission level for a tool.

        Priority: session override > config rules > tool risk level > default (ASK)
        """
        # Yolo mode bypasses everything
        if self.config.permissions.yolo:
            return PermissionLevel.ALLOW

        # Session overrides
        if tool_name in self._session_overrides:
            return self._session_overrides[tool_name]

        # Config rules
        level = self.config.permissions.get_level(tool_name)
        if level != PermissionLevel.ASK:
            return level

        # Risk-based defaults
        risk = self.registry.get_risk_level(tool_name)
        if risk == "low":
            return PermissionLevel.ALLOW
        elif risk == "destructive":
            return PermissionLevel.ASK

        return PermissionLevel.ASK

    def is_allowed(self, tool_name: str) -> bool:
        """Quick check: is this tool allowed to run without asking?"""
        return self.check(tool_name) == PermissionLevel.ALLOW

    def is_denied(self, tool_name: str) -> bool:
        return self.check(tool_name) == PermissionLevel.DENY

    def set_session_override(self, tool_name: str, level: PermissionLevel) -> None:
        """Set a session-level permission override."""
        self._session_overrides[tool_name] = level
        logger.info("Session override: %s -> %s", tool_name, level.value)

    def clear_session_overrides(self) -> None:
        self._session_overrides.clear()

    def get_pending_requests(self, tool_name: str, arguments: dict) -> str:
        """Generate a human-readable permission request string."""
        level = self.check(tool_name)
        risk = self.registry.get_risk_level(tool_name)

        lines = [
            f"Tool: {tool_name}",
            f"Risk: {risk}",
            f"Permission: {level.value}",
        ]

        # Add relevant argument summaries
        if "path" in arguments:
            lines.append(f"Path: {arguments['path']}")
        if "command" in arguments:
            lines.append(f"Command: {arguments['command']}")
        if "content" in arguments:
            content = arguments["content"]
            lines.append(f"Content: {len(content)} chars ({content.count(chr(10)) + 1} lines)")

        return "\n".join(lines)

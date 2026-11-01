"""Centralized tool registry for NEXUS."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from nexus.tools.schema import ToolDefinition


class ToolAlreadyRegisteredError(ValueError):
    """Raised when attempting to register a tool with a name that is already in use."""


class ToolNotFoundError(KeyError):
    """Raised when attempting to access a tool that does not exist in the registry."""


class ToolRegistry:
    """Central repository storing and exposing all registered NEXUS tools.
    
    Guarantees:
    - Unique tool names (duplicate registration is strictly rejected).
    - Thread-safe mutation and lookup.
    - Export format adhering to the Ollama / OpenAI tool-calling standard.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._lock = threading.RLock()

    def register_tool(self, tool_def: ToolDefinition) -> None:
        """Register a new tool definition.
        
        Raises ToolAlreadyRegisteredError if a tool with the same name already exists.
        """
        with self._lock:
            if tool_def.name in self._tools:
                raise ToolAlreadyRegisteredError(
                    f"Cannot register duplicate tool '{tool_def.name}'. A tool with this name is already registered."
                )
            self._tools[tool_def.name] = tool_def

    def unregister_tool(self, name: str) -> bool:
        """Unregister a tool by name.
        
        Returns True if the tool was removed, False if it was not found.
        """
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                return True
            return False

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Retrieve a tool definition by name, or None if not found."""
        with self._lock:
            return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool exists in the registry."""
        with self._lock:
            return name in self._tools

    def list_tools(self) -> List[ToolDefinition]:
        """Return a list of all registered tool definitions."""
        with self._lock:
            return list(self._tools.values())

    def get_model_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return all registered tools formatted as an Ollama/OpenAI tool list."""
        with self._lock:
            return [tool.to_ollama_format() for tool in self._tools.values()]

    def count(self) -> int:
        """Return the number of registered tools."""
        with self._lock:
            return len(self._tools)

    def clear(self) -> None:
        """Unregister all tools (useful for test isolation)."""
        with self._lock:
            self._tools.clear()


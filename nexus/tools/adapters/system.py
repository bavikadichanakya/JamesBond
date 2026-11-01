"""System Adapter Interface for NEXUS.

Establishes safe, non-arbitrary Windows system integration points (telemetry, memory, uptime)
without enabling arbitrary shell execution or raw PowerShell command execution.
"""

from __future__ import annotations

import platform
import sys
import time
from typing import Any, Dict

from nexus.tools.adapters.base import BaseToolAdapter
from nexus.tools.permissions import PermissionLevel
from nexus.tools.registry import ToolRegistry
from nexus.tools.schema import ToolDefinition, ToolParameter


class SystemAdapter(BaseToolAdapter):
    """Safe Windows system integration adapter.
    
    Guarantees:
    - Never enables arbitrary shell execution.
    - Never accepts raw commands or scripts.
    - Exposes only strictly constrained, audited read-only telemetry.
    """

    ADAPTER_SOURCE = "NEXUS_SYSTEM_ADAPTER"

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register safe, constrained host telemetry tools."""
        registry.register_tool(
            ToolDefinition(
                name="get_system_telemetry",
                description="Query high-level host platform metadata and Python environment details.",
                parameters={},
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_get_system_telemetry,
                source=self.ADAPTER_SOURCE,
                simulated=False,
            )
        )

    def handle_get_system_telemetry(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Return safe, non-sensitive host telemetry."""
        return {
            "platform": platform.platform(),
            "os_name": platform.system(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "uptime_reference_seconds": round(time.time(), 2),
            "simulated": False,
        }


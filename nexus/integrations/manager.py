"""Central Integration Manager for NEXUS.

Coordinates the lifecycle, discovery, health checking, tool registration, and graceful
degradation of upstream adapters (OpenClaw, Hermes Agent, Muse Gadget SDK).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from nexus.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationMetadata,
    IntegrationStatus,
)
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import PermissionManager
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger("nexus.integrations.manager")


class IntegrationManager:
    """Manages upstream capability adapters for NEXUS.
    
    Guarantees:
    - Centralized lifecycle: initialize, register tools, probe health, and shutdown cleanly.
    - Graceful degradation: an unavailable or degraded integration never prevents other integrations
      or core NEXUS tools from functioning.
    - Conflict prevention: ensures tool names are unique and properly tracked by adapter source.
    - Unified reporting: provides a single health and status overview for all upstream components.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        permission_manager: Optional[PermissionManager] = None,
        execution_engine: Optional[ToolExecutionEngine] = None,
    ) -> None:
        self.registry = registry
        self.permission_manager = permission_manager
        self.execution_engine = execution_engine
        self._adapters: Dict[str, BaseIntegrationAdapter] = {}
        self._adapter_tools: Dict[str, List[str]] = {}

    def register_adapter(self, adapter: BaseIntegrationAdapter) -> bool:
        """Register, initialize, and wire tools for an upstream adapter.
        
        Returns True if the adapter initialized and registered successfully.
        """
        name = adapter.name
        if name in self._adapters:
            logger.warning("Integration adapter '%s' is already registered.", name)
            return False

        logger.info("Initializing upstream integration: %s", name)

        # 1. Initialize the adapter
        init_ok = False
        try:
            init_ok = adapter.initialize()
        except Exception as e:
            logger.error("Error during initialization of adapter '%s': %s", name, e, exc_info=True)
            adapter.metadata.status = IntegrationStatus.DISCONNECTED
            adapter.metadata.health_details = {"init_error": str(e)}

        self._adapters[name] = adapter
        self._adapter_tools[name] = []

        # 2. Register tools if adapter is healthy or safely simulated
        if adapter.status in (IntegrationStatus.CONNECTED, IntegrationStatus.SIMULATED, IntegrationStatus.DEGRADED):
            tools_before = {t.name for t in self.registry.list_tools()}
            try:
                adapter.register_tools(self.registry)
                tools_after = {t.name for t in self.registry.list_tools()}
                newly_registered = list(tools_after - tools_before)
                self._adapter_tools[name] = newly_registered
                logger.info("Adapter '%s' registered %d tools: %s", name, len(newly_registered), newly_registered)
            except Exception as e:
                logger.error("Failed to register tools for adapter '%s': %s", name, e, exc_info=True)
                return False

        return init_ok

    def unregister_adapter(self, name: str) -> bool:
        """Unregister an adapter, unregister its tools, and shut it down cleanly."""
        if name not in self._adapters:
            logger.warning("Adapter '%s' is not registered.", name)
            return False

        adapter = self._adapters[name]

        # 1. Unregister all tools belonging to this adapter
        registered_tools = self._adapter_tools.get(name, [])
        for tool_name in registered_tools:
            try:
                self.registry.unregister_tool(tool_name)
            except Exception as e:
                logger.warning("Error unregistering tool '%s': %s", tool_name, e)

        # 2. Shut down adapter
        try:
            adapter.shutdown()
        except Exception as e:
            logger.error("Error shutting down adapter '%s': %s", name, e)

        del self._adapters[name]
        if name in self._adapter_tools:
            del self._adapter_tools[name]

        logger.info("Unregistered adapter '%s' and cleaned up %d tools.", name, len(registered_tools))
        return True

    def get_adapter(self, name: str) -> Optional[BaseIntegrationAdapter]:
        """Retrieve an adapter by its unique identifier."""
        return self._adapters.get(name)

    def list_adapters(self) -> List[Dict[str, Any]]:
        """Return a structured overview of all registered adapters."""
        summary = []
        for name, adapter in self._adapters.items():
            meta = adapter.metadata
            summary.append({
                "name": name,
                "version": meta.version,
                "description": meta.description,
                "status": meta.status.value,
                "capabilities": adapter.get_capabilities(),
                "tools_registered": self._adapter_tools.get(name, []),
                "last_health_check": meta.last_health_check,
                "health_details": meta.health_details,
            })
        return summary

    def health_check_all(self) -> Dict[str, Any]:
        """Execute health checks across all registered adapters."""
        results: Dict[str, Any] = {}
        for name, adapter in self._adapters.items():
            try:
                details = adapter.health_check()
                results[name] = {
                    "status": adapter.status.value,
                    "details": details,
                }
            except Exception as e:
                results[name] = {
                    "status": IntegrationStatus.DISCONNECTED.value,
                    "error": str(e),
                }
        return results

    def shutdown_all(self) -> None:
        """Shut down all registered adapters."""
        for name, adapter in list(self._adapters.items()):
            try:
                adapter.shutdown()
            except Exception as e:
                logger.error("Error shutting down adapter '%s': %s", name, e)
        self._adapters.clear()
        self._adapter_tools.clear()
        logger.info("All upstream integration adapters have been shut down.")

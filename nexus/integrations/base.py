"""Unified integration contract and base adapter interface for NEXUS."""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nexus.tools.registry import ToolRegistry


class IntegrationStatus(str, Enum):
    """Lifecycle and connectivity status of an upstream integration."""

    UNINITIALIZED = "UNINITIALIZED"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    SIMULATED = "SIMULATED"


@dataclass
class IntegrationMetadata:
    """Descriptor for an upstream integration adapter."""

    name: str
    version: str
    description: str
    upstream_source_dir: str
    capabilities: List[str] = field(default_factory=list)
    status: IntegrationStatus = IntegrationStatus.UNINITIALIZED
    last_health_check: Optional[str] = None
    health_details: Dict[str, Any] = field(default_factory=dict)


class BaseIntegrationAdapter(ABC):
    """Common interface for all NEXUS upstream capability adapters.
    
    Guarantees:
    - Standardized lifecycle: initialize -> health_check -> register_tools -> shutdown.
    - Safe error containment: failures in one adapter do not crash NEXUS.
    - All exposed capabilities register into the central NEXUS ToolRegistry.
    - All invocations pass through NEXUS schema validation and permission enforcement.
    """

    def __init__(self, metadata: IntegrationMetadata) -> None:
        self.metadata = metadata

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def status(self) -> IntegrationStatus:
        return self.metadata.status

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the adapter and inspect upstream prerequisites.
        
        Returns True if successfully initialized (connected or safely simulated), False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Perform a live diagnostics probe and update status."""
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """Return the list of capabilities provided by this integration."""
        raise NotImplementedError

    @abstractmethod
    def register_tools(self, registry: ToolRegistry) -> None:
        """Register adapter-specific tools into the central NEXUS tool registry."""
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        """Cleanly release any held resources, connections, or subprocesses."""
        raise NotImplementedError


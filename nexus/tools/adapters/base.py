"""Base tool adapter interface for NEXUS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus.tools.registry import ToolRegistry


class BaseToolAdapter(ABC):
    """Abstract interface for all NEXUS tool adapters."""

    @abstractmethod
    def register_tools(self, registry: ToolRegistry) -> None:
        """Register adapter-specific tools into the central NEXUS registry."""
        raise NotImplementedError


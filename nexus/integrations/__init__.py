"""NEXUS Upstream Integrations Package.

Integrates capabilities from OpenClaw, Hermes Agent, and Muse Gadget SDK.
"""

from nexus.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationMetadata,
    IntegrationStatus,
)
from nexus.integrations.hermes.adapter import HermesAdapter
from nexus.integrations.local_system.adapter import LocalSystemAdapter
from nexus.integrations.manager import IntegrationManager
from nexus.integrations.muse.adapter import MuseAdapter
from nexus.integrations.openclaw.adapter import OpenClawAdapter

__all__ = [
    "BaseIntegrationAdapter",
    "IntegrationStatus",
    "IntegrationMetadata",
    "IntegrationManager",
    "OpenClawAdapter",
    "HermesAdapter",
    "MuseAdapter",
    "LocalSystemAdapter",
]


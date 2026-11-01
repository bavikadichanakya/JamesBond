"""Real Device Adapter Interface for NEXUS.

STUB / INTERFACE ONLY: Establishes the integration point for future physical smart hardware
without connecting to any live network, hardware, or third-party cloud.
"""

from __future__ import annotations

from typing import Any, Dict

from nexus.tools.adapters.base import BaseToolAdapter
from nexus.tools.permissions import PermissionLevel
from nexus.tools.registry import ToolRegistry
from nexus.tools.schema import ToolDefinition, ToolParameter


class RealDeviceProviderNotConfiguredError(RuntimeError):
    """Raised when an action is attempted on an unconfigured physical device provider."""


class RealDeviceAdapter(BaseToolAdapter):
    """Production interface stub for physical smart home devices.
    
    Guarantees:
    - Never connects to physical hardware during this phase.
    - Never invents mock credentials or fake endpoints.
    - Clearly demarcates live physical hardware interfaces from mock adapters.
    """

    ADAPTER_SOURCE = "NEXUS_REAL_HARDWARE"

    def __init__(self, provider_config: Dict[str, Any] | None = None) -> None:
        self.provider_config = provider_config or {}
        self.is_configured = bool(self.provider_config.get("endpoint"))

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register placeholders for real hardware integration points."""
        registry.register_tool(
            ToolDefinition(
                name="real_hardware_status",
                description="Query telemetry from physical smart home devices (Unconfigured in this phase).",
                parameters={
                    "device_id": ToolParameter(
                        name="device_id",
                        type="string",
                        description="Hardware device MAC address or unique hardware ID.",
                        required=True,
                    )
                },
                permission_level=PermissionLevel.PRIVILEGED,
                handler=self.handle_real_device_status,
                source=self.ADAPTER_SOURCE,
                simulated=False,
            )
        )

    def handle_real_device_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Placeholder handler rejecting execution until a live provider is configured."""
        raise RealDeviceProviderNotConfiguredError(
            f"Physical hardware communication is not configured in this Phase. "
            f"Cannot connect to hardware device '{args.get('device_id')}'. "
            f"Use MockDeviceAdapter for simulated operations."
        )


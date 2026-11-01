"""Mock Device Adapter for NEXUS: provides simulated IoT devices for safe local development and testing."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from nexus.tools.adapters.base import BaseToolAdapter
from nexus.tools.permissions import PermissionLevel
from nexus.tools.registry import ToolRegistry
from nexus.tools.schema import ToolDefinition, ToolParameter


class MockDeviceAdapter(BaseToolAdapter):
    """Simulated smart device controller.
    
    Guarantees:
    - All outcomes are explicitly marked as simulated (`simulated: True`).
    - Source is stamped as `NEXUS_TEST_MOCK`.
    - Never communicates with physical hardware.
    - Accurately tracks in-memory state of simulated devices across turns.
    """

    ADAPTER_SOURCE = "NEXUS_TEST_MOCK"

    def __init__(self) -> None:
        # Pre-populated in-memory simulated devices
        self._devices: Dict[str, Dict[str, Any]] = {
            "Desk Plug": {
                "device_id": "sim_plug_01",
                "device_name": "Desk Plug",
                "type": "smart_plug",
                "status": "SIMULATED_ONLINE",
                "power_state": "OFF",
                "power_draw_watts": 0.0,
                "last_seen": "2026-11-01T12:00:00Z",
                "location": "Office Desk",
            },
            "Living Room Lamp": {
                "device_id": "sim_light_02",
                "device_name": "Living Room Lamp",
                "type": "dimmable_light",
                "status": "SIMULATED_ONLINE",
                "power_state": "ON",
                "brightness_pct": 75,
                "last_seen": "2026-11-01T12:00:00Z",
                "location": "Living Room",
            },
            "Kitchen Air Monitor": {
                "device_id": "sim_sensor_03",
                "device_name": "Kitchen Air Monitor",
                "type": "air_quality_sensor",
                "status": "SIMULATED_ONLINE",
                "power_state": "ACTIVE",
                "aqi": 18,
                "temperature_c": 21.5,
                "last_seen": "2026-11-01T12:00:00Z",
                "location": "Kitchen",
            },
        }

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register get_device_status, list_devices, and control_device tools."""

        # 1. get_device_status
        registry.register_tool(
            ToolDefinition(
                name="get_device_status",
                description="Retrieve the current operating status and telemetry of a named smart device.",
                parameters={
                    "device_name": ToolParameter(
                        name="device_name",
                        type="string",
                        description="The exact name of the target smart device (e.g. 'Desk Plug').",
                        required=True,
                    ),
                    "include_last_seen": ToolParameter(
                        name="include_last_seen",
                        type="boolean",
                        description="Whether to include last communication timestamp in the telemetry.",
                        required=False,
                        default=False,
                    ),
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_get_device_status,
                source=self.ADAPTER_SOURCE,
                simulated=True,
            )
        )

        # 2. list_devices
        registry.register_tool(
            ToolDefinition(
                name="list_devices",
                description="List all available smart devices and their current basic connectivity status.",
                parameters={},
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_list_devices,
                source=self.ADAPTER_SOURCE,
                simulated=True,
            )
        )

        # 3. control_device
        registry.register_tool(
            ToolDefinition(
                name="control_device",
                description="Change the power state of a smart device. Requires explicit user confirmation.",
                parameters={
                    "device_name": ToolParameter(
                        name="device_name",
                        type="string",
                        description="The name of the target smart device to control.",
                        required=True,
                    ),
                    "action": ToolParameter(
                        name="action",
                        type="string",
                        description="The control action to execute.",
                        required=True,
                        enum=["turn_on", "turn_off"],
                    ),
                },
                permission_level=PermissionLevel.CONFIRMATION_REQUIRED,
                handler=self.handle_control_device,
                source=self.ADAPTER_SOURCE,
                simulated=True,
            )
        )

    def handle_get_device_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for get_device_status tool."""
        device_name = args["device_name"]
        include_last_seen = args.get("include_last_seen", False)

        device = self._devices.get(device_name)
        if not device:
            available = list(self._devices.keys())
            raise ValueError(
                f"Device '{device_name}' not found. Available simulated devices: {available}"
            )

        result_data = {
            "device_name": device["device_name"],
            "device_id": device["device_id"],
            "type": device["type"],
            "status": device["status"],
            "power_state": device["power_state"],
            "location": device["location"],
            "simulated": True,
            "disclaimer": "This result was generated by MockDeviceAdapter and does not represent physical hardware.",
        }

        if "power_draw_watts" in device:
            result_data["power_draw_watts"] = device["power_draw_watts"]
        if "brightness_pct" in device:
            result_data["brightness_pct"] = device["brightness_pct"]
        if "aqi" in device:
            result_data["aqi"] = device["aqi"]

        if include_last_seen:
            result_data["last_seen"] = device.get("last_seen")

        return result_data

    def handle_list_devices(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for list_devices tool."""
        device_summaries = []
        for dev in self._devices.values():
            device_summaries.append(
                {
                    "device_name": dev["device_name"],
                    "type": dev["type"],
                    "status": dev["status"],
                    "power_state": dev["power_state"],
                    "location": dev["location"],
                    "simulated": True,
                }
            )

        return {
            "count": len(device_summaries),
            "devices": device_summaries,
            "simulated": True,
            "disclaimer": "All devices listed are simulated test mocks.",
        }

    def handle_control_device(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for control_device tool."""
        device_name = args["device_name"]
        action = args["action"]

        device = self._devices.get(device_name)
        if not device:
            raise ValueError(f"Device '{device_name}' not found.")

        old_state = device["power_state"]
        new_state = "ON" if action == "turn_on" else "OFF"
        device["power_state"] = new_state

        if device["type"] == "smart_plug":
            device["power_draw_watts"] = 15.5 if new_state == "ON" else 0.0

        device["last_seen"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return {
            "device_name": device_name,
            "previous_state": old_state,
            "new_state": new_state,
            "action_executed": action,
            "status": "SIMULATED_SUCCESS",
            "simulated": True,
            "disclaimer": f"Simulated action '{action}' applied to mock device '{device_name}'.",
        }


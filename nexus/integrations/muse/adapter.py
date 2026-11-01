"""Muse Gadget SDK Integration Adapter for NEXUS.

Exposes Muse Gadget SDK IoT capabilities (LAN device discovery, 46+ smart device skills,
device protocol inspection, and safe action dispatch) to NEXUS under the central
orchestration, permission, and tool execution system.
"""

from __future__ import annotations

import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from nexus.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationMetadata,
    IntegrationStatus,
)
from nexus.tools.permissions import PermissionLevel
from nexus.tools.registry import ToolRegistry
from nexus.tools.schema import ToolDefinition, ToolParameter

logger = logging.getLogger("nexus.integrations.muse")


class MuseAdapter(BaseIntegrationAdapter):
    """Adapter for Muse Gadget SDK IoT and smart home capabilities.
    
    Guarantees:
    - Pure software execution: does not require ESP32 or Linux BlueZ for local operation.
    - Safety enforcement: all hardware actuation requires user confirmation (CONFIRMATION_REQUIRED).
    - Simulated integrity: mock and local simulation states are explicitly tagged with `simulated: True`.
    - Real-device boundary: simulated devices never claim to actuate physical hardware.
    - Catalog integration: parses and exposes all 46 device skills from upstream CATALOG.md.
    """

    def __init__(
        self,
        upstream_dir: str = "A:\\Mixer\\muse-gadget-sdk-main\\muse-gadget-sdk-main",
        force_simulated: bool = True,
    ) -> None:
        metadata = IntegrationMetadata(
            name="muse",
            version="1.0.0",
            description="Muse Gadget SDK smart home device integrations and IoT skills",
            upstream_source_dir=upstream_dir,
            capabilities=[
                "device_discovery",
                "gadget_skill_catalog",
                "skill_spec_inspection",
                "gadget_action_dispatch",
            ],
            status=IntegrationStatus.UNINITIALIZED,
        )
        super().__init__(metadata)
        self.upstream_dir = Path(upstream_dir)
        self.force_simulated = force_simulated

        # In-memory local smart devices for safe simulation and testing
        self._devices: Dict[str, Dict[str, Any]] = {
            "elgato_key_light_desk": {
                "id": "elgato_key_light_desk",
                "name": "Desk Key Light",
                "skill": "gadget-elgato-key-light",
                "category": "lights",
                "state": {"on": 1, "brightness": 65, "temperature": 250},
                "port": 9123,
                "reachable": True,
            },
            "sonos_living_room": {
                "id": "sonos_living_room",
                "name": "Living Room Sonos",
                "skill": "gadget-sonos-speakers",
                "category": "speakers",
                "state": {"playback": "paused", "volume": 25, "mute": False},
                "port": 1400,
                "reachable": True,
            },
            "roku_office_tv": {
                "id": "roku_office_tv",
                "name": "Office Roku TV",
                "skill": "gadget-roku-tvs-and-players",
                "category": "tvs",
                "state": {"power": "On", "active_app": "Home"},
                "port": 8060,
                "reachable": True,
            },
            "shelly_plug_kitchen": {
                "id": "shelly_plug_kitchen",
                "name": "Kitchen Coffee Plug",
                "skill": "gadget-shelly-plugs",
                "category": "plugs",
                "state": {"output": False, "power_watts": 0.0},
                "port": 80,
                "reachable": True,
            },
        }

    def initialize(self) -> bool:
        """Inspect upstream source and skills directory."""
        if not self.upstream_dir.exists():
            logger.warning("Muse upstream directory not found at: %s", self.upstream_dir)
            self.metadata.status = IntegrationStatus.DISCONNECTED
            return False

        skills_dir = self.upstream_dir / "skills"
        if not skills_dir.is_dir():
            logger.warning("Muse skills directory not found at: %s", skills_dir)
            self.metadata.status = IntegrationStatus.DEGRADED
            return False

        self.health_check()
        return True

    def health_check(self) -> Dict[str, Any]:
        """Probe upstream skills catalog and active devices."""
        self.metadata.last_health_check = datetime.datetime.now(datetime.timezone.utc).isoformat()
        skills_dir = self.upstream_dir / "skills"
        catalog_file = skills_dir / "CATALOG.md"

        catalog_valid = catalog_file.is_file()
        skill_folders = [p for p in skills_dir.iterdir() if p.is_dir() and p.name.startswith("gadget-")] if skills_dir.is_dir() else []

        # Unless connected to a physical Muse Hub over network, we safely operate in SIMULATED mode
        self.metadata.status = IntegrationStatus.SIMULATED
        details = {
            "mode": "software_simulated",
            "connected_to_physical_hardware": False,
            "catalog_present": catalog_valid,
            "skills_count": len(skill_folders),
            "simulated_devices_online": len(self._devices),
            "upstream_dir": str(self.upstream_dir),
        }
        self.metadata.health_details = details
        return details

    def get_capabilities(self) -> List[str]:
        return list(self.metadata.capabilities)

    def shutdown(self) -> None:
        """Release any device handles."""
        self.metadata.status = IntegrationStatus.DISCONNECTED
        logger.info("Muse integration adapter shut down cleanly.")

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register Muse tools into the central NEXUS tool registry."""

        # 1. muse_discover_devices
        registry.register_tool(
            ToolDefinition(
                name="muse_discover_devices",
                description="Discover local smart devices (lights, speakers, plugs, TVs) available on the local network or mock environment.",
                parameters={
                    "filter_category": ToolParameter(
                        name="filter_category",
                        type="string",
                        description="Optional filter by device category ('lights', 'speakers', 'tvs', 'plugs').",
                        required=False,
                    )
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_discover_devices,
                source="NEXUS_MUSE_ADAPTER",
                simulated=True,
            )
        )

        # 2. muse_list_supported_skills
        registry.register_tool(
            ToolDefinition(
                name="muse_list_supported_skills",
                description="List all 46+ IoT gadget skills supported by the Muse Gadget SDK catalog.",
                parameters={
                    "category": ToolParameter(
                        name="category",
                        type="string",
                        description="Optional category filter (e.g. 'Lights and plugs', 'Speakers', 'Printers').",
                        required=False,
                    )
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_list_supported_skills,
                source="NEXUS_MUSE_ADAPTER",
                simulated=False,
            )
        )

        # 3. muse_inspect_device_skill
        registry.register_tool(
            ToolDefinition(
                name="muse_inspect_device_skill",
                description="Inspect the full specification, endpoints, and commands for a specific device skill.",
                parameters={
                    "skill_name": ToolParameter(
                        name="skill_name",
                        type="string",
                        description="The skill name or folder name (e.g. 'gadget-elgato-key-light').",
                        required=True,
                    )
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_inspect_device_skill,
                source="NEXUS_MUSE_ADAPTER",
                simulated=False,
            )
        )

        # 4. muse_invoke_gadget_action
        registry.register_tool(
            ToolDefinition(
                name="muse_invoke_gadget_action",
                description="Execute an action on a smart device (e.g. change power, brightness, volume). Requires user confirmation.",
                parameters={
                    "device_id": ToolParameter(
                        name="device_id",
                        type="string",
                        description="The ID of the target device (e.g. 'elgato_key_light_desk').",
                        required=True,
                    ),
                    "action": ToolParameter(
                        name="action",
                        type="string",
                        description="The action command to execute (e.g. 'set_power', 'set_brightness', 'set_volume').",
                        required=True,
                    ),
                    "parameters": ToolParameter(
                        name="parameters",
                        type="object",
                        description="Key-value arguments for the action (e.g. {'state': 'on', 'brightness': 80}).",
                        required=False,
                    ),
                },
                permission_level=PermissionLevel.CONFIRMATION_REQUIRED,
                handler=self.handle_invoke_gadget_action,
                source="NEXUS_MUSE_ADAPTER",
                simulated=True,
            )
        )

    # -------------------------------------------------------------------------
    # Tool Handlers
    # -------------------------------------------------------------------------

    def handle_discover_devices(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Discover available smart devices."""
        cat_filter = args.get("filter_category")
        devices_list = list(self._devices.values())

        if cat_filter:
            devices_list = [d for d in devices_list if d.get("category", "").lower() == cat_filter.lower()]

        return {
            "count": len(devices_list),
            "devices": devices_list,
            "simulated": True,
            "disclaimer": "Retrieved from local simulated device environment. No physical hardware connected.",
        }

    def handle_list_supported_skills(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read and parse skills from upstream CATALOG.md."""
        catalog_path = self.upstream_dir / "skills" / "CATALOG.md"
        category_filter = args.get("category")

        if not catalog_path.is_file():
            return {
                "count": 0,
                "skills": [],
                "error": "CATALOG.md not found in upstream skills directory.",
                "simulated": False,
            }

        content = catalog_path.read_text(encoding="utf-8")
        skills_found: List[Dict[str, str]] = []
        current_section = "General"

        for line in content.splitlines():
            line_str = line.strip()
            if line_str.startswith("## "):
                current_section = line_str[3:].strip()
            elif line_str.startswith("- ["):
                # Parse markdown link: - [Name](path) — description
                match = re.match(r"-\s*\[(.*?)\]\((.*?)\)\s*—\s*(.*)", line_str)
                if match:
                    name, link, desc = match.groups()
                    skill_id = link.split("/")[0] if "/" in link else link.replace(".md", "")
                    if category_filter and category_filter.lower() not in current_section.lower():
                        continue
                    skills_found.append({
                        "name": name,
                        "skill_id": skill_id,
                        "category": current_section,
                        "description": desc,
                        "link": link,
                    })

        return {
            "count": len(skills_found),
            "skills": skills_found,
            "simulated": False,
        }

    def handle_inspect_device_skill(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Inspect the SKILL.md specification of a gadget skill."""
        skill_name = args.get("skill_name", "").strip()
        if not skill_name:
            raise ValueError("Parameter 'skill_name' cannot be empty.")

        skills_dir = self.upstream_dir / "skills"
        target_path = skills_dir / skill_name / "SKILL.md"

        # Check alternate directory lookup if user omitted 'gadget-'
        if not target_path.is_file() and not skill_name.startswith("gadget-"):
            target_path = skills_dir / f"gadget-{skill_name}" / "SKILL.md"

        if not target_path.is_file():
            raise FileNotFoundError(f"Skill specification not found for '{skill_name}'. Target: {target_path}")

        raw_content = target_path.read_text(encoding="utf-8")

        # Parse sections
        sections: Dict[str, str] = {}
        current_h2 = "overview"
        current_lines: List[str] = []

        for line in raw_content.splitlines():
            if line.startswith("## "):
                if current_lines:
                    sections[current_h2] = "\n".join(current_lines).strip()
                    current_lines = []
                current_h2 = line[3:].strip().lower()
            else:
                current_lines.append(line)

        if current_lines:
            sections[current_h2] = "\n".join(current_lines).strip()

        return {
            "skill_name": skill_name,
            "file_path": str(target_path),
            "sections_found": list(sections.keys()),
            "prerequisites": sections.get("prerequisites", ""),
            "workflow": sections.get("workflow", ""),
            "limits": sections.get("limits", ""),
            "simulated": False,
        }

    def handle_invoke_gadget_action(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a hardware action on a device."""
        device_id = args.get("device_id")
        action = args.get("action")
        params = args.get("parameters") or {}

        if not device_id or device_id not in self._devices:
            available = list(self._devices.keys())
            raise ValueError(f"Device '{device_id}' not found. Available devices: {available}")

        device = self._devices[device_id]
        state = device["state"]

        # Apply state updates safely in the local simulation store
        if action == "set_power":
            power_val = params.get("power", params.get("state", "on"))
            if isinstance(power_val, str):
                is_on = 1 if power_val.lower() in ("on", "1", "true") else 0
            else:
                is_on = 1 if power_val else 0
            state["on"] = is_on
            state["power"] = "On" if is_on else "Off"
            state["output"] = bool(is_on)
        elif action == "set_brightness":
            brightness = int(params.get("brightness", 50))
            brightness = max(0, min(100, brightness))
            state["brightness"] = brightness
        elif action == "set_volume":
            vol = int(params.get("volume", 30))
            vol = max(0, min(100, vol))
            state["volume"] = vol
        elif action == "pause":
            state["playback"] = "paused"
        elif action == "play":
            state["playback"] = "playing"

        return {
            "device_id": device_id,
            "action": action,
            "status": "SUCCESS",
            "updated_state": state,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "simulated": True,
            "disclaimer": "Simulated hardware action executed. No physical IoT transmission occurred.",
        }


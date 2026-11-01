"""Adapters connecting NEXUS Tool Registry to device and system providers."""

from nexus.tools.adapters.base import BaseToolAdapter
from nexus.tools.adapters.mock_device import MockDeviceAdapter
from nexus.tools.adapters.real_device import RealDeviceAdapter
from nexus.tools.adapters.system import SystemAdapter

__all__ = [
    "BaseToolAdapter",
    "MockDeviceAdapter",
    "RealDeviceAdapter",
    "SystemAdapter",
]


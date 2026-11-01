"""Local System Integration Adapter for NEXUS.

Provides safe, audited, non-arbitrary operating system capabilities:
- Validated web browser navigation (HTTP/HTTPS only).
- Whitelisted desktop application launching (no shell, no arbitrary paths).
- Local system date and time queries.
- Host platform, CPU, and memory telemetry via psutil.
- Pre-approved folder exploration (strict directory allowlist, path traversal protection).
"""

from __future__ import annotations

import datetime
import logging
import os
import platform
import subprocess
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:
    psutil = None

from nexus.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationMetadata,
    IntegrationStatus,
)
from nexus.routing.url_utils import normalize_and_validate_url
from nexus.tools.permissions import PermissionLevel
from nexus.tools.registry import ToolRegistry
from nexus.tools.schema import ToolDefinition, ToolParameter

logger = logging.getLogger("nexus.integrations.local_system")


class LocalSystemAdapter(BaseIntegrationAdapter):
    """Adapter for safe, controlled local computer capabilities.
    
    Guarantees:
    - Zero arbitrary command execution: strictly rejects raw shell commands, batch scripts, or PowerShell.
    - URL Scheme Validation: only http and https are permitted.
    - Application Allowlist: launches are restricted to known, audited executables.
    - Directory Allowlist: folder opening is restricted to predefined user folders without path traversal.
    - Permission Governance: state-changing actions (app launch, folder open) require user confirmation.
    - 100% Live: operates on real local system APIs and reports IntegrationStatus.CONNECTED.
    """

    APP_ALLOWLIST: Dict[str, List[str]] = {
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe"],
        "calc": ["calc.exe"],
        "explorer": ["explorer.exe"],
        "mspaint": ["mspaint.exe"],
        "paint": ["mspaint.exe"],
        "taskmgr": ["taskmgr.exe"],
        "edge": ["msedge.exe"],
        "chrome": ["chrome.exe"],
    }

    @classmethod
    def get_approved_folders(cls) -> Dict[str, Path]:
        """Resolve predefined allowed directories dynamically."""
        home = Path.home()
        return {
            "downloads": home / "Downloads",
            "documents": home / "Documents",
            "desktop": home / "Desktop",
            "workspace": Path("A:/Mixer"),
            "pictures": home / "Pictures",
            "videos": home / "Videos",
            "music": home / "Music",
        }

    def __init__(self) -> None:
        metadata = IntegrationMetadata(
            name="local_system",
            version="1.0.0",
            description="Safe local computer operations (browser, apps, telemetry, time, folders)",
            upstream_source_dir=platform.platform(),
            capabilities=[
                "web_navigation",
                "application_launch",
                "system_clock",
                "system_telemetry",
                "folder_access",
            ],
            status=IntegrationStatus.UNINITIALIZED,
        )
        super().__init__(metadata)

    def initialize(self) -> bool:
        """Initialize adapter and probe host environment."""
        self.health_check()
        return True

    def health_check(self) -> Dict[str, Any]:
        """Verify operating system capabilities and update status."""
        self.metadata.last_health_check = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.metadata.status = IntegrationStatus.CONNECTED

        details = {
            "mode": "live_system",
            "os_name": platform.system(),
            "os_release": platform.release(),
            "psutil_available": psutil is not None,
            "apps_allowlisted_count": len(self.APP_ALLOWLIST),
            "approved_folders_count": len(self.get_approved_folders()),
        }
        self.metadata.health_details = details
        return details

    def get_capabilities(self) -> List[str]:
        return list(self.metadata.capabilities)

    def shutdown(self) -> None:
        """Release any held handles."""
        self.metadata.status = IntegrationStatus.DISCONNECTED
        logger.info("LocalSystemAdapter shut down cleanly.")

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register local system tools into the central NEXUS tool registry."""

        # 1. open_website
        registry.register_tool(
            ToolDefinition(
                name="open_website",
                description="Open a validated HTTP or HTTPS website URL in the system's default web browser.",
                parameters={
                    "url": ToolParameter(
                        name="url",
                        type="string",
                        description="The complete web address to open (must start with http:// or https://).",
                        required=True,
                    )
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_open_website,
                source="NEXUS_LOCAL_SYSTEM_ADAPTER",
                simulated=False,
            )
        )

        # 2. launch_application
        registry.register_tool(
            ToolDefinition(
                name="launch_application",
                description="Launch a pre-approved desktop application (e.g. notepad, calculator, cmd, paint, taskmgr, edge, chrome). Requires user confirmation.",
                parameters={
                    "app_name": ToolParameter(
                        name="app_name",
                        type="string",
                        description="Application identifier from the approved list.",
                        required=True,
                        enum=list(self.APP_ALLOWLIST.keys()),
                    )
                },
                permission_level=PermissionLevel.CONFIRMATION_REQUIRED,
                handler=self.handle_launch_application,
                source="NEXUS_LOCAL_SYSTEM_ADAPTER",
                simulated=False,
            )
        )

        # 3. get_current_time
        registry.register_tool(
            ToolDefinition(
                name="get_current_time",
                description="Retrieve the current local system date, time, day of week, and timezone.",
                parameters={},
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_get_current_time,
                source="NEXUS_LOCAL_SYSTEM_ADAPTER",
                simulated=False,
            )
        )

        # 4. get_system_info
        registry.register_tool(
            ToolDefinition(
                name="get_system_info",
                description="Retrieve host system information: OS, processor architecture, CPU utilization, and available memory.",
                parameters={},
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_get_system_info,
                source="NEXUS_LOCAL_SYSTEM_ADAPTER",
                simulated=False,
            )
        )

        # 5. open_approved_folder
        registry.register_tool(
            ToolDefinition(
                name="open_approved_folder",
                description="Open an approved user directory (downloads, documents, desktop, workspace, pictures) in Windows Explorer. Requires user confirmation.",
                parameters={
                    "folder_name": ToolParameter(
                        name="folder_name",
                        type="string",
                        description="Predefined folder name to open.",
                        required=True,
                        enum=list(self.get_approved_folders().keys()),
                    )
                },
                permission_level=PermissionLevel.CONFIRMATION_REQUIRED,
                handler=self.handle_open_approved_folder,
                source="NEXUS_LOCAL_SYSTEM_ADAPTER",
                simulated=False,
            )
        )

    # -------------------------------------------------------------------------
    # Tool Handlers & OS Dispatch
    # -------------------------------------------------------------------------

    @classmethod
    def dispatch_url_os(cls, url: str) -> Tuple[bool, int, str]:
        """Dispatch a validated URL to the default operating system browser.
        
        Uses Windows ShellExecuteW API directly without spawning cmd or PowerShell.
        Returns:
            (success: bool, code: int, message: str)
            On Windows, return code > 32 denotes that Windows Shell accepted the launch request.
            Return code <= 32 denotes an OS dispatch failure with corresponding error reason.
        """
        if platform.system() == "Windows":
            try:
                import ctypes
                SW_SHOWNORMAL = 1
                # ShellExecuteW(hwnd, lpOperation, lpFile, lpParameters, lpDirectory, nShowCmd)
                code = int(ctypes.windll.shell32.ShellExecuteW(0, "open", url, None, None, SW_SHOWNORMAL))
                if code > 32:
                    return True, code, f"Windows Shell accepted browser launch request (code {code})."

                win_errors = {
                    0: "Operating system out of memory or resources",
                    2: "URL resource or target not found (ERROR_FILE_NOT_FOUND)",
                    3: "Path not found (ERROR_PATH_NOT_FOUND)",
                    5: "Access denied by Windows security policy (SE_ERR_ACCESSDENIED)",
                    8: "Out of memory (SE_ERR_OOM)",
                    26: "Sharing violation (SE_ERR_SHARE)",
                    27: "Association incomplete or invalid (SE_ERR_ASSOCINCOMPLETE)",
                    28: "DDE transaction timed out (SE_ERR_DDETIMEOUT)",
                    29: "DDE transaction failed (SE_ERR_DDEFAIL)",
                    30: "DDE busy (SE_ERR_DDEBUSY)",
                    31: "No application associated with URL protocol (SE_ERR_NOASSOC)",
                    32: "Dynamic-link library not found (SE_ERR_DLLNOTFOUND)",
                }
                err_msg = win_errors.get(code, f"Windows ShellExecute error (code {code})")
                return False, code, err_msg
            except Exception as e:
                return False, -1, f"Windows ShellExecute invocation error: {e}"
        else:
            try:
                opened = webbrowser.open(url)
                if opened:
                    return True, 1, "Dispatched URL via default browser handler."
                return False, 0, "Browser open call returned False."
            except Exception as e:
                return False, -1, f"Browser open call failed: {e}"

    def handle_open_website(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Validate, normalize, and dispatch a web URL to the system browser."""
        raw_url = str(args.get("url", "")).strip()
        if not raw_url:
            raise ValueError("Parameter 'url' cannot be empty.")

        # Strict RFC-compliant normalization and domain/scheme validation
        normalized_url = normalize_and_validate_url(raw_url)
        logger.info("[LocalSystem Observability] URL normalization succeeded: %s -> %s", raw_url, normalized_url)

        # Dispatch via OS-level Windows ShellExecute
        success, code, message = self.dispatch_url_os(normalized_url)
        if not success:
            logger.error(
                "[LocalSystem Observability] URL: '%s' | ShellExecute code: %s | Status: FAILED | Reason: %s",
                normalized_url, code, message,
            )
            raise RuntimeError(f"Browser dispatch failed: {message} (code {code})")

        logger.info(
            "[LocalSystem Observability] URL: '%s' | ShellExecute code: %s | Status: DISPATCHED | Message: %s",
            normalized_url, code, message,
        )
        return {
            "status": "DISPATCHED",
            "url": normalized_url,
            "raw_input_url": raw_url,
            "url_validated": True,
            "windows_shell_accepted": True,
            "dispatch_code": code,
            "message": message,
            "note": "Windows accepted the launch request. Actual page rendering occurs in the system default browser.",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "simulated": False,
        }

    def handle_launch_application(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Launch an approved application from the allowlist."""
        app_name = str(args.get("app_name", "")).strip().lower()
        if not app_name:
            raise ValueError("Parameter 'app_name' cannot be empty.")

        if app_name not in self.APP_ALLOWLIST:
            valid_apps = list(self.APP_ALLOWLIST.keys())
            raise ValueError(f"Application '{app_name}' is not in the approved allowlist: {valid_apps}")

        cmd = self.APP_ALLOWLIST[app_name]
        logger.info("Launching approved application: %s (cmd=%s)", app_name, cmd)

        try:
            # shell=False is strictly enforced; direct executable invocation only
            proc = subprocess.Popen(cmd, shell=False)
            return {
                "status": "LAUNCHED",
                "app_name": app_name,
                "pid": proc.pid,
                "executable": cmd[0],
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "simulated": False,
            }
        except Exception as e:
            logger.error("Failed to launch application '%s': %s", app_name, e)
            raise RuntimeError(f"Could not launch application '{app_name}': {e}") from e

    def handle_get_current_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve local system time and date."""
        now = datetime.datetime.now()
        utc_now = datetime.datetime.now(datetime.timezone.utc)

        return {
            "date": now.strftime("%A, %B %d, %Y"),
            "time": now.strftime("%I:%M:%S %p"),
            "day_of_week": now.strftime("%A"),
            "iso": now.isoformat(),
            "utc_iso": utc_now.isoformat(),
            "timezone": time.tzname[time.daylight] if hasattr(time, "tzname") else "Local",
            "simulated": False,
        }

    def handle_get_system_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve system telemetry and hardware statistics."""
        info: Dict[str, Any] = {
            "os": f"{platform.system()} {platform.release()} ({platform.version()})",
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "cpu_cores": os.cpu_count(),
            "simulated": False,
        }

        if psutil:
            try:
                mem = psutil.virtual_memory()
                info["memory"] = {
                    "total_gb": round(mem.total / (1024 ** 3), 2),
                    "available_gb": round(mem.available / (1024 ** 3), 2),
                    "used_gb": round(mem.used / (1024 ** 3), 2),
                    "percent_used": mem.percent,
                }
                cpu_p = psutil.cpu_percent(interval=0.05)
                info["cpu_utilization_percent"] = cpu_p

                # Disk usage
                disk = psutil.disk_usage(os.path.splitdrive(os.getcwd())[0] or "C:\\")
                info["disk"] = {
                    "total_gb": round(disk.total / (1024 ** 3), 2),
                    "free_gb": round(disk.free / (1024 ** 3), 2),
                    "percent_used": disk.percent,
                }
            except Exception as e:
                logger.warning("Error fetching psutil telemetry: %s", e)

        return info

    def handle_open_approved_folder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Open an approved folder in Windows Explorer."""
        folder_key = str(args.get("folder_name", "")).strip().lower()
        approved = self.get_approved_folders()

        # Reject path traversal tokens
        if ".." in folder_key or "/" in folder_key or "\\" in folder_key:
            raise ValueError(f"Path traversal characters are prohibited in folder name '{folder_key}'.")

        if folder_key not in approved:
            valid_folders = list(approved.keys())
            raise ValueError(f"Folder '{folder_key}' is not approved. Valid folders: {valid_folders}")

        target_dir = approved[folder_key].resolve()

        if not target_dir.is_dir():
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise FileNotFoundError(f"Target directory '{target_dir}' does not exist and could not be created: {e}")

        logger.info("Opening approved folder: %s (%s)", folder_key, target_dir)
        try:
            # Windows Explorer invocation with resolved directory
            subprocess.Popen(["explorer.exe", str(target_dir)], shell=False)
            return {
                "status": "OPENED",
                "folder_name": folder_key,
                "path": str(target_dir),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "simulated": False,
            }
        except Exception as e:
            logger.error("Failed to open folder '%s': %s", target_dir, e)
            raise RuntimeError(f"Could not open folder '{folder_key}': {e}") from e

"""Comprehensive Automated Test Suite for NEXUS Phase 5.1 & Phase 5.1.2.

Verifies:
1. LocalSystemAdapter initialization and tool registrations.
2. open_website: Windows OS-level ShellExecute dispatch, URL validation, malformed/non-http rejection, dispatch failure handling.
3. launch_application: allowlist validation, arbitrary commands rejected, cmd removed, confirmation enforced.
4. get_current_time: local date, time, and timezone telemetry.
5. get_system_info: OS, processor, CPU, and RAM telemetry via psutil.
6. open_approved_folder: approved folder resolution, path traversal prevention.
7. Permission denial: user rejection halts execution cleanly without spawning processes.
8. Intelligent routing: user requests automatically dispatch to LocalSystemAdapter without touching OpenClaw/Hermes/Muse.
9. Honest status telemetry: Live local system vs simulated adapters.
10. Capability-level status reporting: Granular LIVE / SIMULATED / UNAVAILABLE distinction.
11. Turn & tool call deduplication: prevents identical duplicate execution within turn, supports separate turns.
12. Favicon endpoint: serves valid icon at /favicon.ico without 404.
13. Microphone status accuracy: browser Web Speech primary path reported without false PyAudio errors.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from nexus.config import NexusConfig
from nexus.core.session import SessionManager
from nexus.integrations.base import IntegrationStatus
from nexus.integrations.hermes.adapter import HermesAdapter
from nexus.integrations.local_system.adapter import LocalSystemAdapter
from nexus.integrations.manager import IntegrationManager
from nexus.integrations.muse.adapter import MuseAdapter
from nexus.integrations.openclaw.adapter import OpenClawAdapter
from nexus.orchestrator import NexusOrchestrator
from nexus.routing.classifier import IntentClassifier
from nexus.routing.models import RoutingStatus
from nexus.routing.router import CapabilityRouter
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import (
    PermissionLevel,
    PermissionManager,
    ToolApprovalDecision,
    ToolApprovalRequest,
)
from nexus.tools.registry import ToolRegistry
from nexus.tools.result import ToolCall
from nexus.ui.app import create_app


class TestNexusPhase51LocalSystem(unittest.TestCase):
    """Test suite for Phase 5.1 & 5.1.2 Local System Capabilities and Voice/Tool Deduplication."""

    def setUp(self) -> None:
        self.config = NexusConfig()
        self.registry = ToolRegistry()
        self.permission_manager = PermissionManager(
            allow_privileged=True,
            approval_callback=lambda req: ToolApprovalDecision(
                approved=True, decided_by="AUTOMATED_TEST_HARNESS"
            ),
        )
        self.execution_engine = ToolExecutionEngine(
            registry=self.registry,
            permission_manager=self.permission_manager,
            default_timeout=2.0,
        )
        self.manager = IntegrationManager(
            registry=self.registry,
            permission_manager=self.permission_manager,
            execution_engine=self.execution_engine,
        )

        # Register all adapters
        self.local_system_adapter = LocalSystemAdapter()
        self.openclaw_adapter = OpenClawAdapter(force_simulated=True)
        self.hermes_adapter = HermesAdapter()
        self.muse_adapter = MuseAdapter(force_simulated=True)

        self.manager.register_adapter(self.local_system_adapter)
        self.manager.register_adapter(self.openclaw_adapter)
        self.manager.register_adapter(self.hermes_adapter)
        self.manager.register_adapter(self.muse_adapter)

        self.router = CapabilityRouter(
            registry=self.registry,
            manager=self.manager,
            execution_engine=self.execution_engine,
        )

        self.session_manager = SessionManager()
        self.orchestrator = NexusOrchestrator(
            config=self.config,
            registry=self.registry,
            permission_manager=self.permission_manager,
            execution_engine=self.execution_engine,
            integration_manager=self.manager,
            router=self.router,
        )

    # -------------------------------------------------------------------------
    # Test 1: Tool Registrations
    # -------------------------------------------------------------------------
    def test_01_local_system_tools_registered(self) -> None:
        registered_names = [t.name for t in self.registry.list_tools()]
        expected_tools = [
            "open_website",
            "launch_application",
            "get_current_time",
            "get_system_info",
            "open_approved_folder",
        ]
        for tool_name in expected_tools:
            self.assertIn(tool_name, registered_names)

        # Verify permissions
        app_tool = self.registry.get_tool("launch_application")
        self.assertIsNotNone(app_tool)
        self.assertEqual(app_tool.permission_level, PermissionLevel.CONFIRMATION_REQUIRED)

        folder_tool = self.registry.get_tool("open_approved_folder")
        self.assertIsNotNone(folder_tool)
        self.assertEqual(folder_tool.permission_level, PermissionLevel.CONFIRMATION_REQUIRED)

        time_tool = self.registry.get_tool("get_current_time")
        self.assertIsNotNone(time_tool)
        self.assertEqual(time_tool.permission_level, PermissionLevel.READ_ONLY)

    # -------------------------------------------------------------------------
    # Test 2: open_website tool validation & Windows ShellExecute dispatch
    # -------------------------------------------------------------------------
    def test_02_open_website_validation(self) -> None:
        with patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted browser launch request (code 42).")) as mock_dispatch:
            call = ToolCall(name="open_website", arguments={"url": "https://www.google.com"})
            result = self.execution_engine.execute_tool_call(call)
            self.assertTrue(result.success)
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data["status"], "DISPATCHED")
            self.assertTrue(result.data["windows_shell_accepted"])
            self.assertEqual(result.data["dispatch_code"], 42)
            mock_dispatch.assert_called_once_with("https://www.google.com")

        # Test implicit https:// addition for valid domain
        with patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Accepted")) as mock_dispatch:
            call2 = ToolCall(name="open_website", arguments={"url": "youtube.com"})
            result2 = self.execution_engine.execute_tool_call(call2)
            self.assertTrue(result2.success)
            self.assertIsNotNone(result2.data)
            self.assertEqual(result2.data["url"], "https://youtube.com")

        # Prohibited scheme rejected
        call_bad = ToolCall(name="open_website", arguments={"url": "file:///C:/Windows/System32"})
        result_bad = self.execution_engine.execute_tool_call(call_bad)
        self.assertFalse(result_bad.success)
        self.assertIsNotNone(result_bad.error)
        self.assertIn("Prohibited URL scheme", result_bad.error.message)

        # Script scheme rejected
        call_js = ToolCall(name="open_website", arguments={"url": "javascript:alert(1)"})
        result_js = self.execution_engine.execute_tool_call(call_js)
        self.assertFalse(result_js.success)

        # Malformed hostname rejected
        call_malformed = ToolCall(name="open_website", arguments={"url": "http://"})
        result_malformed = self.execution_engine.execute_tool_call(call_malformed)
        self.assertFalse(result_malformed.success)

        # Windows browser dispatch failure properly reported
        with patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(False, 5, "Access denied by Windows security policy (SE_ERR_ACCESSDENIED)")):
            call_fail = ToolCall(name="open_website", arguments={"url": "https://www.blocked.com"})
            result_fail = self.execution_engine.execute_tool_call(call_fail)
            self.assertFalse(result_fail.success)
            self.assertIn("Browser dispatch failed", result_fail.error.message)

    # -------------------------------------------------------------------------
    # Test 3: launch_application allowlist & arbitrary command rejection
    # -------------------------------------------------------------------------
    def test_03_launch_application_allowlist(self) -> None:
        # 1. Allowlisted app succeeds with shell=False
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            call = ToolCall(name="launch_application", arguments={"app_name": "notepad"})
            result = self.execution_engine.execute_tool_call(call)
            self.assertTrue(result.success)
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data["status"], "LAUNCHED")
            self.assertEqual(result.data["pid"], 9999)
            mock_popen.assert_called_once_with(["notepad.exe"], shell=False)

        # 2. cmd is strictly removed from allowlist and rejected
        self.assertNotIn("cmd", self.local_system_adapter.APP_ALLOWLIST)
        call_cmd = ToolCall(name="launch_application", arguments={"app_name": "cmd"})
        result_cmd = self.execution_engine.execute_tool_call(call_cmd)
        self.assertFalse(result_cmd.success)
        self.assertIsNotNone(result_cmd.error)
        self.assertIn("Allowed values are", result_cmd.error.message)

        # 3. Arbitrary executable rejected
        call_unapp = ToolCall(name="launch_application", arguments={"app_name": "powershell"})
        result_unapproved = self.execution_engine.execute_tool_call(call_unapp)
        self.assertFalse(result_unapproved.success)
        self.assertIsNotNone(result_unapproved.error)
        self.assertIn("Allowed values are", result_unapproved.error.message)

        # 4. Injected command syntax rejected
        for bad_app in ["notepad; calc", "notepad & calc", "notepad | calc", "`calc`", "$(calc)"]:
            call_inject = ToolCall(name="launch_application", arguments={"app_name": bad_app})
            result_inject = self.execution_engine.execute_tool_call(call_inject)
            self.assertFalse(result_inject.success)

        # 5. Injected unexpected arguments rejected
        call_extra = ToolCall(name="launch_application", arguments={"app_name": "notepad", "injected_flag": "-e malicious"})
        result_extra = self.execution_engine.execute_tool_call(call_extra)
        self.assertFalse(result_extra.success)
        self.assertIn("Unexpected argument", result_extra.error.message)

    # -------------------------------------------------------------------------
    # Test 4: get_current_time telemetry
    # -------------------------------------------------------------------------
    def test_04_get_current_time(self) -> None:
        call = ToolCall(name="get_current_time", arguments={})
        result = self.execution_engine.execute_tool_call(call)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data)
        self.assertIn("time", result.data)
        self.assertIn("date", result.data)
        self.assertIn("day_of_week", result.data)
        self.assertIn("iso", result.data)
        self.assertFalse(result.simulated)

    # -------------------------------------------------------------------------
    # Test 5: get_system_info telemetry
    # -------------------------------------------------------------------------
    def test_05_get_system_info(self) -> None:
        call = ToolCall(name="get_system_info", arguments={})
        result = self.execution_engine.execute_tool_call(call)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data)
        self.assertIn("os", result.data)
        self.assertIn("architecture", result.data)
        self.assertIn("cpu_cores", result.data)
        self.assertIn("memory", result.data)
        self.assertIn("total_gb", result.data["memory"])
        self.assertFalse(result.simulated)

    # -------------------------------------------------------------------------
    # Test 6: open_approved_folder & path traversal rejection
    # -------------------------------------------------------------------------
    def test_06_open_approved_folder(self) -> None:
        mock_proc = MagicMock()
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            call = ToolCall(name="open_approved_folder", arguments={"folder_name": "downloads"})
            result = self.execution_engine.execute_tool_call(call)
            self.assertTrue(result.success)
            self.assertIsNotNone(result.data)
            self.assertEqual(result.data["status"], "OPENED")
            self.assertEqual(result.data["folder_name"], "downloads")
            mock_popen.assert_called_once()

        # Path traversal rejected by schema validation
        call_trav = ToolCall(name="open_approved_folder", arguments={"folder_name": "../windows"})
        result_traversal = self.execution_engine.execute_tool_call(call_trav)
        self.assertFalse(result_traversal.success)
        self.assertIsNotNone(result_traversal.error)
        self.assertIn("Allowed values are", result_traversal.error.message)

        # Non-approved directory rejected
        call_unapp = ToolCall(name="open_approved_folder", arguments={"folder_name": "system32"})
        result_unapproved = self.execution_engine.execute_tool_call(call_unapp)
        self.assertFalse(result_unapproved.success)
        self.assertIsNotNone(result_unapproved.error)
        self.assertIn("Allowed values are", result_unapproved.error.message)

    # -------------------------------------------------------------------------
    # Test 7: Permission Denial Enforcement
    # -------------------------------------------------------------------------
    def test_07_permission_denial(self) -> None:
        denying_permission_mgr = PermissionManager(
            allow_privileged=True,
            approval_callback=lambda req: ToolApprovalDecision(
                approved=False,
                decided_by="USER_CLICKED_DENY",
                reason="User explicitly rejected execution.",
            ),
        )
        engine = ToolExecutionEngine(
            registry=self.registry,
            permission_manager=denying_permission_mgr,
        )

        with patch("subprocess.Popen") as mock_popen:
            call = ToolCall(name="launch_application", arguments={"app_name": "calc"})
            result = engine.execute_tool_call(call)
            self.assertFalse(result.success)
            self.assertIsNotNone(result.error)
            self.assertIn("rejected", result.error.message.lower())
            mock_popen.assert_not_called()

    # -------------------------------------------------------------------------
    # Test 8: Intelligent Routing to Local System Capabilities
    # -------------------------------------------------------------------------
    def test_08_intelligent_routing_local_system(self) -> None:
        # 1. "Open YouTube" -> open_website
        plan_yt = self.router.plan_task("Open YouTube in browser")
        self.assertEqual(plan_yt.status, RoutingStatus.ROUTED)
        self.assertEqual(plan_yt.steps[0].tool_name, "open_website")
        self.assertIn("youtube.com", plan_yt.steps[0].arguments.get("url", ""))

        # 2. "Open Chrome" -> launch_application
        plan_chrome = self.router.plan_task("Please open Chrome browser")
        self.assertEqual(plan_chrome.status, RoutingStatus.ROUTED)
        self.assertEqual(plan_chrome.steps[0].tool_name, "launch_application")
        self.assertEqual(plan_chrome.steps[0].arguments.get("app_name"), "chrome")

        # 3. "What time is it?" -> get_current_time
        plan_time = self.router.plan_task("What time is it right now?")
        self.assertEqual(plan_time.status, RoutingStatus.ROUTED)
        self.assertEqual(plan_time.steps[0].tool_name, "get_current_time")

        # 4. "Check my system memory" -> get_system_info
        plan_mem = self.router.plan_task("Check my system memory and CPU utilization")
        self.assertEqual(plan_mem.status, RoutingStatus.ROUTED)
        self.assertEqual(plan_mem.steps[0].tool_name, "get_system_info")

        # 5. "Open my Downloads folder" -> open_approved_folder
        plan_dl = self.router.plan_task("Open my Downloads folder")
        self.assertEqual(plan_dl.status, RoutingStatus.ROUTED)
        self.assertEqual(plan_dl.steps[0].tool_name, "open_approved_folder")
        self.assertEqual(plan_dl.steps[0].arguments.get("folder_name"), "downloads")

    # -------------------------------------------------------------------------
    # Test 9: Honest Status Reporting
    # -------------------------------------------------------------------------
    def test_09_honest_status_reporting(self) -> None:
        local_status = self.local_system_adapter.health_check()
        self.assertEqual(self.local_system_adapter.metadata.status, IntegrationStatus.CONNECTED)
        self.assertEqual(local_status["mode"], "live_system")

        openclaw_status = self.openclaw_adapter.health_check()
        self.assertEqual(self.openclaw_adapter.metadata.status, IntegrationStatus.SIMULATED)

        muse_status = self.muse_adapter.health_check()
        self.assertEqual(self.muse_adapter.metadata.status, IntegrationStatus.SIMULATED)

    # -------------------------------------------------------------------------
    # Test 10: Capability-Level Status Accuracy
    # -------------------------------------------------------------------------
    def test_10_capability_level_status(self) -> None:
        app = create_app()
        client = app.test_client()
        res = client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("capabilities", data)

        caps = {c["id"]: c["status"] for c in data["capabilities"]}

        # 1. Local System Operations: LIVE
        self.assertEqual(caps.get("local_system"), "LIVE")

        # 2. Hermes Skill Discovery: LIVE
        self.assertEqual(caps.get("hermes_skills"), "LIVE")

        # 3. Hermes Memory: SIMULATED
        self.assertEqual(caps.get("hermes_memory"), "SIMULATED")

        # 4. Hermes Subagent Execution: SIMULATED
        self.assertEqual(caps.get("hermes_subagent"), "SIMULATED")

        # 5. Muse Skill Catalog: LIVE
        self.assertEqual(caps.get("muse_catalog"), "LIVE")

        # 6. Muse Physical Device Control: UNAVAILABLE
        self.assertEqual(caps.get("muse_device_control"), "UNAVAILABLE")

        # 7. OpenClaw Gateway: SIMULATED
        self.assertEqual(caps.get("openclaw_gateway"), "SIMULATED")

    # -------------------------------------------------------------------------
    # Test 11: Turn & Tool Call Deduplication (Bug 2 Repair)
    # -------------------------------------------------------------------------
    def test_11_turn_and_tool_call_deduplication(self) -> None:
        app = create_app()
        client = app.test_client()

        # 1. Deduplication on identical request_id: cached response returned
        req_id = "req_test_dedup_001"
        payload = {"message": "What time is it?", "request_id": req_id}
        res1 = client.post("/api/chat", json=payload)
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertEqual(data1["request_id"], req_id)

        # Immediate duplicate submit with identical request_id
        res2 = client.post("/api/chat", json=payload)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2["request_id"], req_id)
        self.assertEqual(data1["response"], data2["response"])

        # 2. Legitimate repeated command in a separate user turn (different request_id) executes independently
        req_id_turn2 = "req_test_dedup_002"
        payload_turn2 = {"message": "What time is it?", "request_id": req_id_turn2}
        res3 = client.post("/api/chat", json=payload_turn2)
        self.assertEqual(res3.status_code, 200)
        data3 = res3.get_json()
        self.assertEqual(data3["request_id"], req_id_turn2)

    # -------------------------------------------------------------------------
    # Test 12: Favicon Endpoint (Bug 4 Repair)
    # -------------------------------------------------------------------------
    def test_12_favicon_endpoint(self) -> None:
        app = create_app()
        client = app.test_client()
        res = client.get("/favicon.ico")
        self.assertEqual(res.status_code, 200)
        self.assertIn("image", res.headers.get("Content-Type", ""))
        self.assertGreater(len(res.data), 0)

    # -------------------------------------------------------------------------
    # Test 13: Voice Status Accuracy (Bug 3 Repair)
    # -------------------------------------------------------------------------
    def test_13_voice_status_accuracy(self) -> None:
        app = create_app()
        client = app.test_client()
        res = client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("voice", data)
        voice = data["voice"]
        self.assertTrue(voice.get("stt_available"))
        self.assertEqual(voice.get("active_input_path"), "browser_web_speech")
        self.assertIn("Browser Web Speech API active", voice.get("microphone_status"))


if __name__ == "__main__":
    unittest.main()

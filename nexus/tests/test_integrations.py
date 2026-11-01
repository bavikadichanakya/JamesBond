"""Comprehensive Automated Integration Test Suite for NEXUS Phase 4.

Verifies the 14 critical criteria:
1. OpenClaw initializes & reports capabilities.
2. Hermes initializes & reports capabilities.
3. Muse initializes & reports capabilities.
4. All register tools in central registry.
5. Duplicate names rejected / namespaced.
6. Malformed upstream args rejected.
7. Read-only calls execute without approval.
8. State-changing calls require approval.
9. Denied calls do not execute.
10. Unavailable integrations do not crash NEXUS.
11. Timeout handling.
12. Simulated data consistently labeled.
13. Tool results return through central orchestrator.
14. AST security analysis flags dangerous patterns.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from nexus.config import NexusConfig
from nexus.integrations.base import BaseIntegrationAdapter, IntegrationMetadata, IntegrationStatus
from nexus.integrations.hermes.adapter import HermesAdapter
from nexus.integrations.manager import IntegrationManager
from nexus.integrations.muse.adapter import MuseAdapter
from nexus.integrations.openclaw.adapter import OpenClawAdapter
from nexus.model.ollama_client import OllamaChatClient, OllamaModelResponse
from nexus.orchestrator import NexusOrchestrator
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import PermissionLevel, PermissionManager, ToolApprovalDecision, ToolApprovalRequest
from nexus.tools.registry import ToolRegistry
from nexus.tools.result import StandardizedToolResult, ToolCall, ToolExecutionError
from nexus.tools.schema import ToolDefinition, ToolParameter


class TestNexusPhase4Integrations(unittest.TestCase):
    """Test suite for Phase 4 Upstream Capability Integrations."""

    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.permission_manager = PermissionManager(allow_privileged=True)
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

        # Adapters
        self.openclaw_adapter = OpenClawAdapter(force_simulated=True)
        self.hermes_adapter = HermesAdapter()
        self.muse_adapter = MuseAdapter(force_simulated=True)

    # -------------------------------------------------------------------------
    # Criterion 1: OpenClaw initializes & reports capabilities
    # -------------------------------------------------------------------------
    def test_01_openclaw_initialization_and_capabilities(self) -> None:
        init_ok = self.openclaw_adapter.initialize()
        self.assertTrue(init_ok)
        self.assertIn(self.openclaw_adapter.status, (IntegrationStatus.CONNECTED, IntegrationStatus.SIMULATED))

        capabilities = self.openclaw_adapter.get_capabilities()
        self.assertIsInstance(capabilities, list)
        self.assertIn("gateway_rpc", capabilities)
        self.assertIn("channel_dispatch", capabilities)
        self.assertIn("extension_discovery", capabilities)

        health = self.openclaw_adapter.health_check()
        self.assertIn("mode", health)

    # -------------------------------------------------------------------------
    # Criterion 2: Hermes initializes & reports capabilities
    # -------------------------------------------------------------------------
    def test_02_hermes_initialization_and_capabilities(self) -> None:
        init_ok = self.hermes_adapter.initialize()
        self.assertTrue(init_ok)
        self.assertIn(self.hermes_adapter.status, (IntegrationStatus.CONNECTED, IntegrationStatus.SIMULATED))

        capabilities = self.hermes_adapter.get_capabilities()
        self.assertIsInstance(capabilities, list)
        self.assertIn("memory_query", capabilities)
        self.assertIn("skill_discovery", capabilities)
        self.assertIn("ast_security_audit", capabilities)
        self.assertIn("subagent_delegation", capabilities)

        health = self.hermes_adapter.health_check()
        self.assertIn("skills_count", health)

    # -------------------------------------------------------------------------
    # Criterion 3: Muse initializes & reports capabilities
    # -------------------------------------------------------------------------
    def test_03_muse_initialization_and_capabilities(self) -> None:
        init_ok = self.muse_adapter.initialize()
        self.assertTrue(init_ok)
        self.assertIn(self.muse_adapter.status, (IntegrationStatus.CONNECTED, IntegrationStatus.SIMULATED))

        capabilities = self.muse_adapter.get_capabilities()
        self.assertIsInstance(capabilities, list)
        self.assertIn("device_discovery", capabilities)
        self.assertIn("gadget_skill_catalog", capabilities)
        self.assertIn("skill_spec_inspection", capabilities)
        self.assertIn("gadget_action_dispatch", capabilities)

        health = self.muse_adapter.health_check()
        self.assertIn("skills_count", health)
        self.assertTrue(health["skills_count"] >= 40)

    # -------------------------------------------------------------------------
    # Criterion 4: All register tools in central registry
    # -------------------------------------------------------------------------
    def test_04_all_register_tools_in_central_registry(self) -> None:
        self.manager.register_adapter(self.openclaw_adapter)
        self.manager.register_adapter(self.hermes_adapter)
        self.manager.register_adapter(self.muse_adapter)

        registered_tools = [t.name for t in self.registry.list_tools()]

        # OpenClaw tools
        self.assertIn("openclaw_gateway_status", registered_tools)
        self.assertIn("openclaw_list_channels", registered_tools)
        self.assertIn("openclaw_send_channel_message", registered_tools)
        self.assertIn("openclaw_list_extensions", registered_tools)

        # Hermes tools
        self.assertIn("hermes_query_memory", registered_tools)
        self.assertIn("hermes_list_skills", registered_tools)
        self.assertIn("hermes_audit_skill_code", registered_tools)
        self.assertIn("hermes_run_subagent", registered_tools)

        # Muse tools
        self.assertIn("muse_discover_devices", registered_tools)
        self.assertIn("muse_list_supported_skills", registered_tools)
        self.assertIn("muse_inspect_device_skill", registered_tools)
        self.assertIn("muse_invoke_gadget_action", registered_tools)

        self.assertGreaterEqual(len(registered_tools), 12)

    # -------------------------------------------------------------------------
    # Criterion 5: Duplicate names rejected / namespaced
    # -------------------------------------------------------------------------
    def test_05_duplicate_tool_names_rejected(self) -> None:
        self.manager.register_adapter(self.openclaw_adapter)

        # Attempt to register a duplicate tool with the same name
        duplicate_def = ToolDefinition(
            name="openclaw_gateway_status",
            description="Duplicate definition attempt",
            parameters={},
            permission_level=PermissionLevel.READ_ONLY,
            handler=lambda args: {},
            source="DUPLICATE_SOURCE",
        )
        with self.assertRaises(ValueError) as ctx:
            self.registry.register_tool(duplicate_def)
        self.assertIn("already registered", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Criterion 6: Malformed upstream args rejected
    # -------------------------------------------------------------------------
    def test_06_malformed_upstream_args_rejected(self) -> None:
        self.manager.register_adapter(self.openclaw_adapter)
        self.manager.register_adapter(self.muse_adapter)

        # Missing required parameter: 'channel_id' and 'message' are required for openclaw_send_channel_message
        call_missing = ToolCall(name="openclaw_send_channel_message", arguments={}, tool_call_id="call_err_1")
        result_missing = self.execution_engine.execute_tool_call(call_missing)
        self.assertFalse(result_missing.success)
        self.assertIsNotNone(result_missing.error)
        self.assertIn("Missing required parameter", result_missing.error.message)

        # Wrong type: int passed where string expected
        call_bad_type = ToolCall(
            name="openclaw_send_channel_message",
            arguments={"channel_id": 12345, "message": "hello"},
            tool_call_id="call_err_2",
        )
        result_bad_type = self.execution_engine.execute_tool_call(call_bad_type)
        self.assertFalse(result_bad_type.success)
        self.assertIsNotNone(result_bad_type.error)
        self.assertIn("expected string", result_bad_type.error.message.lower())

        # Unknown unexpected parameter
        call_unexpected = ToolCall(
            name="muse_inspect_device_skill",
            arguments={"skill_name": "gadget-elgato-key-light", "unexpected_arg": "invalid"},
            tool_call_id="call_err_3",
        )
        result_unexpected = self.execution_engine.execute_tool_call(call_unexpected)
        self.assertFalse(result_unexpected.success)
        self.assertIsNotNone(result_unexpected.error)
        self.assertIn("Unexpected argument", result_unexpected.error.message)

    # -------------------------------------------------------------------------
    # Criterion 7: Read-only calls execute without approval
    # -------------------------------------------------------------------------
    def test_07_readonly_calls_execute_without_approval(self) -> None:
        self.manager.register_adapter(self.openclaw_adapter)
        self.manager.register_adapter(self.hermes_adapter)
        self.manager.register_adapter(self.muse_adapter)

        # Mock approval callback to verify it is NEVER called for READ_ONLY
        approval_cb = MagicMock()
        self.permission_manager.set_approval_callback(approval_cb)

        # 1. OpenClaw status
        res1 = self.execution_engine.execute_tool_call(ToolCall(name="openclaw_gateway_status", arguments={}, tool_call_id="c1"))
        self.assertTrue(res1.success)
        approval_cb.assert_not_called()

        # 2. Hermes list skills
        res2 = self.execution_engine.execute_tool_call(ToolCall(name="hermes_list_skills", arguments={"category": "productivity"}, tool_call_id="c2"))
        self.assertTrue(res2.success)
        approval_cb.assert_not_called()

        # 3. Muse discover devices
        res3 = self.execution_engine.execute_tool_call(ToolCall(name="muse_discover_devices", arguments={}, tool_call_id="c3"))
        self.assertTrue(res3.success)
        approval_cb.assert_not_called()

        # 4. Hermes AST code audit
        safe_code = "def add(a, b):\n    return a + b\n"
        res4 = self.execution_engine.execute_tool_call(ToolCall(name="hermes_audit_skill_code", arguments={"code": safe_code}, tool_call_id="c4"))
        self.assertTrue(res4.success)
        self.assertTrue(res4.data["safe"])
        approval_cb.assert_not_called()

    # -------------------------------------------------------------------------
    # Criterion 8: State-changing calls require approval and execute when approved
    # -------------------------------------------------------------------------
    def test_08_state_changing_calls_require_approval_and_execute(self) -> None:
        self.manager.register_adapter(self.openclaw_adapter)
        self.manager.register_adapter(self.hermes_adapter)
        self.manager.register_adapter(self.muse_adapter)

        def approve_cb(req: ToolApprovalRequest) -> ToolApprovalDecision:
            return ToolApprovalDecision(approved=True, decided_by="USER_CONFIRMED", reason="User verified action")

        self.permission_manager.set_approval_callback(approve_cb)

        # 1. OpenClaw send message (CONFIRMATION_REQUIRED)
        res_openclaw = self.execution_engine.execute_tool_call(
            ToolCall(
                name="openclaw_send_channel_message",
                arguments={"channel_id": "telegram_general", "message": "Test announcement"},
                tool_call_id="c_send",
            )
        )
        self.assertTrue(res_openclaw.success)
        self.assertEqual(res_openclaw.data.get("delivery_status"), "SIMULATED_DELIVERED")

        # 2. Hermes run subagent (CONFIRMATION_REQUIRED)
        res_hermes = self.execution_engine.execute_tool_call(
            ToolCall(
                name="hermes_run_subagent",
                arguments={"task_description": "Review codebase for AST safety", "role": "Security Auditor"},
                tool_call_id="c_subagent",
            )
        )
        self.assertTrue(res_hermes.success)
        self.assertEqual(res_hermes.data.get("status"), "COMPLETED")

        # 3. Muse invoke gadget action (CONFIRMATION_REQUIRED)
        res_muse = self.execution_engine.execute_tool_call(
            ToolCall(
                name="muse_invoke_gadget_action",
                arguments={
                    "device_id": "elgato_key_light_desk",
                    "action": "set_brightness",
                    "parameters": {"brightness": 85},
                },
                tool_call_id="c_gadget",
            )
        )
        self.assertTrue(res_muse.success)
        self.assertEqual(res_muse.data.get("status"), "SUCCESS")
        self.assertEqual(res_muse.data["updated_state"]["brightness"], 85)

    # -------------------------------------------------------------------------
    # Criterion 9: Denied calls do not execute
    # -------------------------------------------------------------------------
    def test_09_denied_calls_do_not_execute(self) -> None:
        self.manager.register_adapter(self.muse_adapter)

        def deny_cb(req: ToolApprovalRequest) -> ToolApprovalDecision:
            return ToolApprovalDecision(approved=False, decided_by="USER_DENIED", reason="User rejected device modification")

        self.permission_manager.set_approval_callback(deny_cb)

        # Attempt to change device power when denied
        call = ToolCall(
            name="muse_invoke_gadget_action",
            arguments={"device_id": "elgato_key_light_desk", "action": "set_power", "parameters": {"state": "off"}},
            tool_call_id="c_denied",
        )
        res = self.execution_engine.execute_tool_call(call)
        self.assertFalse(res.success)
        self.assertIsNotNone(res.error)
        self.assertIn("rejected", res.error.message.lower())

        # Verify device state remains unchanged
        dev = self.muse_adapter._devices["elgato_key_light_desk"]
        self.assertEqual(dev["state"]["on"], 1)

    # -------------------------------------------------------------------------
    # Criterion 10: Unavailable integrations do not crash NEXUS
    # -------------------------------------------------------------------------
    def test_10_unavailable_integrations_do_not_crash_nexus(self) -> None:
        # Create a broken adapter pointing to a non-existent path
        broken_openclaw = OpenClawAdapter(upstream_dir="A:\\NonExistent\\Path", force_simulated=False)
        registered = self.manager.register_adapter(broken_openclaw)
        # Even if broken, it should not throw unhandled exception
        self.assertIn(broken_openclaw.status, (IntegrationStatus.DISCONNECTED, IntegrationStatus.SIMULATED))

        # Core functionality and other adapters should continue working seamlessly
        self.manager.register_adapter(self.muse_adapter)
        res = self.execution_engine.execute_tool_call(ToolCall(name="muse_discover_devices", arguments={}, tool_call_id="c_ok"))
        self.assertTrue(res.success)

    # -------------------------------------------------------------------------
    # Criterion 11: Timeout handling
    # -------------------------------------------------------------------------
    def test_11_timeout_handling(self) -> None:
        import time

        def slow_handler(args: Dict[str, Any]) -> Dict[str, Any]:
            time.sleep(1.0)
            return {"status": "done"}

        slow_tool = ToolDefinition(
            name="mock_slow_integration_tool",
            description="Tool that exceeds execution timeout",
            parameters={},
            permission_level=PermissionLevel.READ_ONLY,
            handler=slow_handler,
            source="TEST",
        )
        self.registry.register_tool(slow_tool)

        # Call with tight 0.1s timeout
        call = ToolCall(name="mock_slow_integration_tool", arguments={}, tool_call_id="c_slow")
        res = self.execution_engine.execute_tool_call(call, timeout_seconds=0.1)
        self.assertFalse(res.success)
        self.assertIsNotNone(res.error)
        self.assertIn("timed out", res.error.message.lower())

    # -------------------------------------------------------------------------
    # Criterion 12: Simulated data consistently labeled
    # -------------------------------------------------------------------------
    def test_12_simulated_data_consistently_labeled(self) -> None:
        self.manager.register_adapter(self.openclaw_adapter)
        self.manager.register_adapter(self.hermes_adapter)
        self.manager.register_adapter(self.muse_adapter)

        # Simulated tool results MUST have simulated: True and disclaimers
        r_gw = self.execution_engine.execute_tool_call(ToolCall(name="openclaw_gateway_status", arguments={}, tool_call_id="s1"))
        self.assertTrue(r_gw.simulated)
        self.assertIn("simulated", r_gw.data)
        self.assertTrue(r_gw.data["simulated"])
        self.assertIsNotNone(r_gw.data.get("disclaimer"))

        r_muse = self.execution_engine.execute_tool_call(ToolCall(name="muse_discover_devices", arguments={}, tool_call_id="s2"))
        self.assertTrue(r_muse.simulated)
        self.assertTrue(r_muse.data["simulated"])
        self.assertIsNotNone(r_muse.data.get("disclaimer"))

        # Real disk inspection tools MUST have simulated: False
        r_ext = self.execution_engine.execute_tool_call(ToolCall(name="openclaw_list_extensions", arguments={}, tool_call_id="s3"))
        self.assertFalse(r_ext.simulated)

        r_muse_skills = self.execution_engine.execute_tool_call(ToolCall(name="muse_list_supported_skills", arguments={}, tool_call_id="s4"))
        self.assertFalse(r_muse_skills.simulated)

    # -------------------------------------------------------------------------
    # Criterion 13: Tool results return through central orchestrator
    # -------------------------------------------------------------------------
    def test_13_tool_results_return_through_central_orchestrator(self) -> None:
        self.manager.register_adapter(self.openclaw_adapter)
        self.manager.register_adapter(self.hermes_adapter)
        self.manager.register_adapter(self.muse_adapter)

        # Mock model client returning tool call on first turn and final answer on second
        mock_model = MagicMock(spec=OllamaChatClient)
        mock_model.chat.side_effect = [
            OllamaModelResponse(
                role="assistant",
                content="",
                tool_calls=[ToolCall(name="muse_discover_devices", arguments={}, tool_call_id="call_orch_1")],
                done=True,
            ),
            OllamaModelResponse(
                role="assistant",
                content="I discovered 4 local smart devices on your network, including your Desk Key Light and Living Room Sonos.",
                tool_calls=[],
                done=True,
            ),
        ]

        orchestrator = NexusOrchestrator(
            registry=self.registry,
            permission_manager=self.permission_manager,
            execution_engine=self.execution_engine,
            model_client=mock_model,
        )

        turn_result = orchestrator.run_turn("What smart devices are available?")
        self.assertEqual(turn_result.rounds, 2)
        self.assertEqual(len(turn_result.tool_calls_executed), 1)
        self.assertEqual(turn_result.tool_calls_executed[0].name, "muse_discover_devices")
        self.assertTrue(turn_result.has_simulated_data)
        self.assertIn("Desk Key Light", turn_result.final_response)

    # -------------------------------------------------------------------------
    # Criterion 14: AST Security Audit verifies dangerous patterns
    # -------------------------------------------------------------------------
    def test_14_hermes_ast_audit_flags_dangerous_patterns(self) -> None:
        # Check unsafe code
        unsafe_code = """
import os
import importlib

def run_hack(cmd):
    os.system(cmd)
    eval("print('pwned')")
    getattr(obj, dynamic_var)()
"""
        res = self.hermes_adapter.handle_audit_skill_code({"code": unsafe_code})
        self.assertTrue(res["valid_syntax"])
        self.assertFalse(res["safe"])
        self.assertGreaterEqual(res["findings_count"], 3)
        pattern_ids = [f["pattern_id"] for f in res["findings"]]
        self.assertIn("os_system", pattern_ids)
        self.assertIn("call_eval", pattern_ids)
        self.assertIn("dynamic_getattr", pattern_ids)


if __name__ == "__main__":
    unittest.main()

"""Comprehensive Automated Test Suite for NEXUS Phase 5.

Verifies the 14 critical criteria:
1. Text input to OpenClaw routing.
2. Text input to Hermes routing.
3. Text input to Muse routing.
4. Voice transcription entering the same routing pipeline.
5. Unsupported request handling.
6. Ambiguous request handling.
7. Integration unavailable fallback.
8. Multi-integration orchestration.
9. Confirmation-required operations.
10. Permission denial.
11. Simulated versus real execution distinction.
12. Failed execution reporting.
13. Conversation history and session management.
14. Model unavailable handling.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from nexus.config import NexusConfig
from nexus.core.session import SessionManager
from nexus.integrations.base import IntegrationMetadata, IntegrationStatus
from nexus.integrations.hermes.adapter import HermesAdapter
from nexus.integrations.manager import IntegrationManager
from nexus.integrations.muse.adapter import MuseAdapter
from nexus.integrations.openclaw.adapter import OpenClawAdapter
from nexus.model.ollama_client import OllamaChatClient, OllamaModelResponse
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
from nexus.tools.result import StandardizedToolResult, ToolCall
from nexus.voice.stt import SpeechToTextEngine
from nexus.voice.tts import TextToSpeechEngine


class TestNexusPhase5RoutingAndInterface(unittest.TestCase):
    """Test suite for Phase 5 Intelligent Routing and Unified Voice/Chat Interface."""

    def setUp(self) -> None:
        self.config = NexusConfig()
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
    # Criterion 1: Text input to OpenClaw routing
    # -------------------------------------------------------------------------
    def test_01_text_input_to_openclaw_routing(self) -> None:
        plan = self.router.plan_task("Please check OpenClaw gateway status and active channels")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].integration_name, "openclaw")
        self.assertEqual(plan.steps[0].tool_name, "openclaw_gateway_status")

        outcome = self.router.execute_query("Please check OpenClaw gateway status")
        self.assertTrue(outcome.success)
        self.assertIn("openclaw_gateway_status", [s["step"].tool_name for s in outcome.executed_steps])
        self.assertIn("OpenClaw Gateway status", outcome.final_response)

    # -------------------------------------------------------------------------
    # Criterion 2: Text input to Hermes routing
    # -------------------------------------------------------------------------
    def test_02_text_input_to_hermes_routing(self) -> None:
        plan = self.router.plan_task("What do you remember in persistent memory about my preferences?")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].integration_name, "hermes")
        self.assertEqual(plan.steps[0].tool_name, "hermes_query_memory")

        outcome = self.router.execute_query("What do you remember in persistent memory about my preferences?")
        self.assertTrue(outcome.success)
        self.assertIn("hermes_query_memory", [s["step"].tool_name for s in outcome.executed_steps])
        self.assertIn("memory", outcome.final_response.lower())

    # -------------------------------------------------------------------------
    # Criterion 3: Text input to Muse routing
    # -------------------------------------------------------------------------
    def test_03_text_input_to_muse_routing(self) -> None:
        plan = self.router.plan_task("Please discover all smart devices available on the network")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].integration_name, "muse")
        self.assertEqual(plan.steps[0].tool_name, "muse_discover_devices")

        outcome = self.router.execute_query("Please discover all smart devices available on the network")
        self.assertTrue(outcome.success)
        self.assertIn("muse_discover_devices", [s["step"].tool_name for s in outcome.executed_steps])
        self.assertIn("smart devices", outcome.final_response.lower())

    # -------------------------------------------------------------------------
    # Criterion 4: Voice transcription entering same routing pipeline
    # -------------------------------------------------------------------------
    def test_04_voice_transcription_entering_same_pipeline(self) -> None:
        # Configure approval so execution succeeds
        self.permission_manager.set_approval_callback(
            lambda req: ToolApprovalDecision(approved=True, decided_by="USER_CONFIRMED", reason="Approved")
        )

        # Simulate voice transcription output
        simulated_voice_text = "Turn off the desk key light"

        # Verify it enters route_and_run exactly like typed text
        activity_events = []
        turn = self.orchestrator.route_and_run(
            user_prompt=simulated_voice_text,
            activity_callback=lambda act: activity_events.append(act),
        )

        self.assertTrue(len(activity_events) > 0)
        self.assertIn("Understanding your request...", activity_events)
        self.assertEqual(len(turn.tool_calls_executed), 1)
        self.assertEqual(turn.tool_calls_executed[0].name, "muse_invoke_gadget_action")
        self.assertIn("Successfully executed", turn.final_response)

    # -------------------------------------------------------------------------
    # Criterion 5: Unsupported request handling
    # -------------------------------------------------------------------------
    def test_05_unsupported_request_handling(self) -> None:
        outcome = self.router.execute_query("Please book a flight to New York and order pizza")
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.plan.status, RoutingStatus.UNSUPPORTED)
        self.assertIn("cannot fulfill", outcome.final_response.lower())
        self.assertIn("none of the available integrations", outcome.final_response.lower())

    # -------------------------------------------------------------------------
    # Criterion 6: Ambiguous request handling
    # -------------------------------------------------------------------------
    def test_06_ambiguous_request_handling(self) -> None:
        outcome = self.router.execute_query("Send it")
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.plan.status, RoutingStatus.AMBIGUOUS)
        self.assertIn("clarification", outcome.final_response.lower())

    # -------------------------------------------------------------------------
    # Criterion 7: Integration unavailable fallback
    # -------------------------------------------------------------------------
    def test_07_integration_unavailable_fallback(self) -> None:
        # Temporarily shut down Muse adapter
        self.muse_adapter.shutdown()
        self.assertEqual(self.muse_adapter.status, IntegrationStatus.DISCONNECTED)

        # Plan smart device query
        plan = self.router.plan_task("Discover smart devices")
        self.assertEqual(plan.status, RoutingStatus.UNAVAILABLE)

        outcome = self.router.execute_query("Discover smart devices")
        self.assertFalse(outcome.success)
        self.assertIn("unavailable", outcome.final_response.lower())

        # Restore Muse adapter for subsequent tests
        self.muse_adapter.initialize()

    # -------------------------------------------------------------------------
    # Criterion 8: Multi-integration orchestration
    # -------------------------------------------------------------------------
    def test_08_multi_integration_orchestration(self) -> None:
        multi_query = "Check my smart devices and summarize which ones were offline recently"
        plan = self.router.plan_task(multi_query)

        self.assertEqual(plan.status, RoutingStatus.MULTI_ROUTED)
        self.assertGreaterEqual(len(plan.steps), 2)

        # First step: Muse (devices)
        self.assertEqual(plan.steps[0].integration_name, "muse")
        self.assertEqual(plan.steps[0].tool_name, "muse_discover_devices")

        # Second step: Hermes (memory)
        self.assertEqual(plan.steps[1].integration_name, "hermes")
        self.assertEqual(plan.steps[1].tool_name, "hermes_query_memory")
        self.assertEqual(plan.steps[1].depends_on, 1)

        outcome = self.router.execute_query(multi_query)
        self.assertTrue(outcome.success)
        executed_tools = [s["step"].tool_name for s in outcome.executed_steps]
        self.assertIn("muse_discover_devices", executed_tools)
        self.assertIn("hermes_query_memory", executed_tools)

    # -------------------------------------------------------------------------
    # Criterion 9: Confirmation-required operations
    # -------------------------------------------------------------------------
    def test_09_confirmation_required_operations(self) -> None:
        # Check plan flags confirmation
        plan = self.router.plan_task("Send message 'Server alerts' to telegram")
        self.assertTrue(plan.requires_confirmation)

        approval_called = []

        def tracking_approval_cb(req: ToolApprovalRequest) -> ToolApprovalDecision:
            approval_called.append(req.tool_name)
            return ToolApprovalDecision(approved=True, decided_by="USER_ALLOW", reason="Confirmed")

        self.permission_manager.set_approval_callback(tracking_approval_cb)
        outcome = self.router.execute_query("Send message 'Server alerts' to telegram")

        self.assertTrue(outcome.success)
        self.assertIn("openclaw_send_channel_message", approval_called)

    # -------------------------------------------------------------------------
    # Criterion 10: Permission denial
    # -------------------------------------------------------------------------
    def test_10_permission_denial(self) -> None:
        def deny_cb(req: ToolApprovalRequest) -> ToolApprovalDecision:
            return ToolApprovalDecision(approved=False, decided_by="USER_REFUSED", reason="User cancelled device action")

        self.permission_manager.set_approval_callback(deny_cb)
        outcome = self.router.execute_query("Turn off the desk key light")

        self.assertFalse(outcome.success)
        self.assertIn("unable to complete", outcome.final_response.lower())
        self.assertIn("user cancelled", outcome.final_response.lower())

    # -------------------------------------------------------------------------
    # Criterion 11: Simulated versus real execution distinction
    # -------------------------------------------------------------------------
    def test_11_simulated_versus_real_execution_distinction(self) -> None:
        # Simulated device query
        sim_outcome = self.router.execute_query("Check smart devices")
        self.assertTrue(sim_outcome.has_simulated_data)
        self.assertIn("simulated data", sim_outcome.final_response.lower())

        # Real on-disk extension list
        real_outcome = self.router.execute_query("List openclaw extensions")
        self.assertFalse(real_outcome.has_simulated_data)
        self.assertNotIn("simulated data", real_outcome.final_response.lower())

    # -------------------------------------------------------------------------
    # Criterion 12: Failed execution reporting
    # -------------------------------------------------------------------------
    def test_12_failed_execution_reporting(self) -> None:
        # Configure approval so execution reaches handler
        self.permission_manager.set_approval_callback(
            lambda req: ToolApprovalDecision(approved=True, decided_by="TEST_HARNESS", reason="Allow")
        )
        # Dispatch with a non-existent device ID
        bad_call = ToolCall(
            name="muse_invoke_gadget_action",
            arguments={"device_id": "non_existent_device_id", "action": "set_power"},
        )
        res = self.execution_engine.execute_tool_call(bad_call)
        self.assertFalse(res.success)
        self.assertIsNotNone(res.error)
        self.assertIn("not found", res.error.message.lower())

    # -------------------------------------------------------------------------
    # Criterion 13: Conversation history and session management
    # -------------------------------------------------------------------------
    def test_13_conversation_history_and_session_management(self) -> None:
        self.permission_manager.set_approval_callback(
            lambda req: ToolApprovalDecision(approved=True, decided_by="TEST_HARNESS", reason="Allow")
        )
        sess = self.session_manager.get_active_session()
        self.assertEqual(len(sess.messages), 0)

        # First turn
        turn1 = self.orchestrator.route_and_run("Discover smart devices")
        sess.add_message(role="user", content="Discover smart devices")
        sess.add_message(role="assistant", content=turn1.final_response)

        # Second turn (contextual follow-up)
        turn2 = self.orchestrator.route_and_run(
            user_prompt="Turn off the desk key light",
            conversation_history=sess.get_context_messages(),
        )
        sess.add_message(role="user", content="Turn off the desk key light")
        sess.add_message(role="assistant", content=turn2.final_response)

        self.assertEqual(len(sess.messages), 4)
        self.assertEqual(sess.messages[0].role, "user")
        self.assertEqual(sess.messages[1].role, "assistant")
        self.assertEqual(sess.messages[2].role, "user")
        self.assertEqual(sess.messages[3].role, "assistant")

    # -------------------------------------------------------------------------
    # Criterion 14: Model unavailable handling
    # -------------------------------------------------------------------------
    def test_14_model_unavailable_handling(self) -> None:
        # Point client to an invalid endpoint
        failing_client = OllamaChatClient(endpoint="http://localhost:9999", timeout=0.5)
        offline_orchestrator = NexusOrchestrator(
            config=self.config,
            registry=self.registry,
            permission_manager=self.permission_manager,
            execution_engine=self.execution_engine,
            model_client=failing_client,
            # Note: with no router attached, it falls back to model client
        )

        with self.assertRaises(ConnectionError) as ctx:
            offline_orchestrator.run_turn("Hello, can you hear me?")
        self.assertIn("Cannot connect to Ollama", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

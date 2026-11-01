"""Comprehensive automated test suite for NEXUS Tool Registry and Execution Engine.

Covers all 20 required verification criteria using deterministic mock transports.
"""

from __future__ import annotations

import json
import time
import unittest
from typing import Any, Dict, List

from nexus.config import NexusConfig
from nexus.model.ollama_client import OllamaChatClient
from nexus.orchestrator import NexusOrchestrator
from nexus.tools.adapters.mock_device import MockDeviceAdapter
from nexus.tools.adapters.real_device import RealDeviceAdapter, RealDeviceProviderNotConfiguredError
from nexus.tools.adapters.system import SystemAdapter
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import (
    PermissionLevel,
    PermissionManager,
    ToolApprovalDecision,
    ToolApprovalRequest,
)
from nexus.tools.registry import ToolAlreadyRegisteredError, ToolRegistry
from nexus.tools.result import StandardizedToolResult, ToolCall
from nexus.tools.schema import ToolDefinition, ToolParameter, ToolSchemaValidator


class TestNexusToolRegistryAndEngine(unittest.TestCase):
    """Test suite covering the 20 required verification points for NEXUS Phase 3."""

    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.permission_manager = PermissionManager()
        self.execution_engine = ToolExecutionEngine(
            registry=self.registry,
            permission_manager=self.permission_manager,
            default_timeout=2.0,
        )
        self.mock_adapter = MockDeviceAdapter()
        self.mock_adapter.register_tools(self.registry)

    # 1. Tool Registration
    def test_01_tool_registration(self) -> None:
        """Verify tool registration correctly registers tools."""
        self.assertTrue(self.registry.has_tool("get_device_status"))
        self.assertTrue(self.registry.has_tool("list_devices"))
        self.assertTrue(self.registry.has_tool("control_device"))
        self.assertEqual(self.registry.count(), 3)

    # 2. Duplicate Registration Rejection
    def test_02_duplicate_registration_rejection(self) -> None:
        """Verify duplicate tool registration is rejected with ValueError."""
        duplicate_def = ToolDefinition(
            name="get_device_status",
            description="Duplicate tool",
            parameters={},
            permission_level=PermissionLevel.READ_ONLY,
            handler=lambda args: {},
        )
        with self.assertRaises(ToolAlreadyRegisteredError):
            self.registry.register_tool(duplicate_def)

    # 3. Tool Lookup
    def test_03_tool_lookup(self) -> None:
        """Verify tool definition lookup and properties."""
        tool = self.registry.get_tool("get_device_status")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "get_device_status")
        self.assertEqual(tool.permission_level, PermissionLevel.READ_ONLY)
        self.assertTrue(tool.simulated)

        non_existent = self.registry.get_tool("non_existent_tool")
        self.assertIsNone(non_existent)

    # 4. Tool Schema Generation
    def test_04_tool_schema_generation(self) -> None:
        """Verify schema formats match Ollama function specifications."""
        definitions = self.registry.get_model_tool_definitions()
        self.assertEqual(len(definitions), 3)

        tool_map = {d["function"]["name"]: d for d in definitions}
        self.assertIn("get_device_status", tool_map)

        get_status_fn = tool_map["get_device_status"]["function"]
        self.assertEqual(get_status_fn["parameters"]["type"], "object")
        self.assertIn("device_name", get_status_fn["parameters"]["properties"])
        self.assertIn("device_name", get_status_fn["parameters"]["required"])

        control_fn = tool_map["control_device"]["function"]
        self.assertIn("action", control_fn["parameters"]["properties"])
        self.assertEqual(
            control_fn["parameters"]["properties"]["action"]["enum"],
            ["turn_on", "turn_off"],
        )

    # 5. Valid Arguments
    def test_05_valid_arguments(self) -> None:
        """Verify argument validation succeeds on conforming input."""
        tool_def = self.registry.get_tool("get_device_status")
        args = {"device_name": "Desk Plug", "include_last_seen": True}
        validated = ToolSchemaValidator.validate(tool_def, args)
        self.assertEqual(validated["device_name"], "Desk Plug")
        self.assertTrue(validated["include_last_seen"])

    # 6. Invalid Arguments
    def test_06_invalid_arguments(self) -> None:
        """Verify validation rejects missing required args, bad types, unexpected args, and bad enums."""
        tool_def = self.registry.get_tool("get_device_status")

        # Missing required parameter
        with self.assertRaises(ValueError) as ctx:
            ToolSchemaValidator.validate(tool_def, {})
        self.assertIn("Missing required parameter 'device_name'", str(ctx.exception))

        # Invalid type
        with self.assertRaises(ValueError) as ctx:
            ToolSchemaValidator.validate(tool_def, {"device_name": 12345})
        self.assertIn("Invalid type for argument 'device_name'", str(ctx.exception))

        # Unexpected parameter
        with self.assertRaises(ValueError) as ctx:
            ToolSchemaValidator.validate(
                tool_def, {"device_name": "Desk Plug", "unsupported_extra": True}
            )
        self.assertIn("Unexpected argument(s)", str(ctx.exception))

        # Invalid enum value on control_device
        control_def = self.registry.get_tool("control_device")
        with self.assertRaises(ValueError) as ctx:
            ToolSchemaValidator.validate(
                control_def, {"device_name": "Desk Plug", "action": "explode"}
            )
        self.assertIn("Allowed values are: ['turn_on', 'turn_off']", str(ctx.exception))

    # 7. Unknown Tool Rejection
    def test_07_unknown_tool_rejection(self) -> None:
        """Verify execution engine returns a structured error for unknown tools."""
        call = ToolCall(name="arbitrary_system_execute", arguments={"cmd": "whoami"})
        result = self.execution_engine.execute_tool_call(call)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.code, "TOOL_NOT_FOUND")
        self.assertIn("is not registered", result.error.message)

    # 8. Mock Device Status Execution
    def test_08_mock_device_status_execution(self) -> None:
        """Verify successful get_device_status execution."""
        call = ToolCall(name="get_device_status", arguments={"device_name": "Desk Plug"})
        result = self.execution_engine.execute_tool_call(call)
        self.assertTrue(result.success)
        self.assertTrue(result.simulated)
        self.assertEqual(result.source, "NEXUS_TEST_MOCK")
        self.assertEqual(result.data["device_name"], "Desk Plug")
        self.assertEqual(result.data["status"], "SIMULATED_ONLINE")

    # 9. Mock Device Listing
    def test_09_mock_device_listing(self) -> None:
        """Verify list_devices execution returns all simulated devices."""
        call = ToolCall(name="list_devices", arguments={})
        result = self.execution_engine.execute_tool_call(call)
        self.assertTrue(result.success)
        self.assertTrue(result.simulated)
        self.assertGreaterEqual(result.data["count"], 3)
        device_names = [d["device_name"] for d in result.data["devices"]]
        self.assertIn("Desk Plug", device_names)
        self.assertIn("Living Room Lamp", device_names)

    # 10. Confirmation-Required Execution (Approved)
    def test_10_confirmation_required_execution_approved(self) -> None:
        """Verify CONFIRMATION_REQUIRED tools execute when approved."""
        # Set approval callback to approve
        self.permission_manager.set_approval_callback(
            lambda req: ToolApprovalDecision(approved=True, decided_by="USER_TEST_APPROVED")
        )
        call = ToolCall(
            name="control_device",
            arguments={"device_name": "Desk Plug", "action": "turn_on"},
        )
        result = self.execution_engine.execute_tool_call(call)
        self.assertTrue(result.success)
        self.assertEqual(result.data["new_state"], "ON")

    # 11. Permission Denial
    def test_11_permission_denial(self) -> None:
        """Verify CONFIRMATION_REQUIRED tools are blocked when denied."""
        # Set approval callback to deny
        self.permission_manager.set_approval_callback(
            lambda req: ToolApprovalDecision(
                approved=False,
                decided_by="USER_TEST_DENIED",
                reason="User refused state modification",
            )
        )
        call = ToolCall(
            name="control_device",
            arguments={"device_name": "Desk Plug", "action": "turn_on"},
        )
        result = self.execution_engine.execute_tool_call(call)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.code, "PERMISSION_DENIED")
        self.assertIn("User refused", result.error.message)

    # 12. Tool Execution Failure
    def test_12_tool_execution_failure(self) -> None:
        """Verify safe exception handling when handler raises an exception."""
        def failing_handler(args: Dict[str, Any]) -> Dict[str, Any]:
            raise RuntimeError("Database connection reset by peer")

        self.registry.register_tool(
            ToolDefinition(
                name="failing_tool",
                description="A tool that throws an exception",
                parameters={},
                permission_level=PermissionLevel.READ_ONLY,
                handler=failing_handler,
            )
        )
        call = ToolCall(name="failing_tool", arguments={})
        result = self.execution_engine.execute_tool_call(call)
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "EXECUTION_FAILED")
        self.assertIn("Database connection reset", result.error.message)

    # 13. Execution Timeout
    def test_13_execution_timeout(self) -> None:
        """Verify long-running tool execution is safely terminated on timeout."""
        def hanging_handler(args: Dict[str, Any]) -> Dict[str, Any]:
            time.sleep(2.0)
            return {"status": "finished"}

        self.registry.register_tool(
            ToolDefinition(
                name="hanging_tool",
                description="A tool that hangs",
                parameters={},
                permission_level=PermissionLevel.READ_ONLY,
                handler=hanging_handler,
            )
        )
        call = ToolCall(name="hanging_tool", arguments={})
        result = self.execution_engine.execute_tool_call(call, timeout_seconds=0.2)
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "EXECUTION_TIMEOUT")
        self.assertIn("timed out after 0.2", result.error.message)

    # 14. Model-Generated Structured Tool Calls
    def test_14_model_generated_structured_tool_calls(self) -> None:
        """Verify client correctly parses model-generated tool calls from Ollama response."""
        # Simulated Ollama response with standard tool_calls
        mock_raw = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_12345",
                        "type": "function",
                        "function": {
                            "name": "get_device_status",
                            "arguments": {"device_name": "Desk Plug"},
                        },
                    }
                ],
            }
        }
        client = OllamaChatClient(transport=lambda endpoint, payload, to: mock_raw)
        res = client.chat(messages=[{"role": "user", "content": "Status?"}])
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].name, "get_device_status")
        self.assertEqual(res.tool_calls[0].arguments["device_name"], "Desk Plug")

    # 15. Assistant Tool-Call Message Preservation
    # 16. Tool-Result Message Preservation
    # 17. Final Model Response After Tool Execution
    def test_15_16_17_full_tool_turn_lifecycle(self) -> None:
        """Verify assistant message, tool calls, tool results, and final response preservation."""
        turn_step = 0

        def mock_two_step_transport(endpoint: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
            nonlocal turn_step
            turn_step += 1
            if turn_step == 1:
                # Step 1: Model requests tool call
                return {
                    "message": {
                        "role": "assistant",
                        "content": "Let me check the status of Desk Plug for you.",
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "get_device_status",
                                    "arguments": {"device_name": "Desk Plug"},
                                },
                            }
                        ],
                    }
                }
            else:
                # Step 2: Model provides final response using tool result
                return {
                    "message": {
                        "role": "assistant",
                        "content": "The Desk Plug is currently SIMULATED_ONLINE and turned OFF.",
                    }
                }

        client = OllamaChatClient(transport=mock_two_step_transport)
        orchestrator = NexusOrchestrator(
            registry=self.registry,
            permission_manager=self.permission_manager,
            execution_engine=self.execution_engine,
            model_client=client,
        )

        turn_result = orchestrator.run_turn("What is the status of Desk Plug?")

        # 17. Final model response verified
        self.assertEqual(turn_result.final_response, "The Desk Plug is currently SIMULATED_ONLINE and turned OFF.")
        self.assertEqual(len(turn_result.tool_calls_executed), 1)
        self.assertEqual(len(turn_result.tool_results), 1)
        self.assertEqual(turn_result.rounds, 2)

        # Inspect conversation history
        history = turn_result.conversation_history
        self.assertEqual(len(history), 5)

        # System message
        self.assertEqual(history[0]["role"], "system")

        # User message
        self.assertEqual(history[1]["role"], "user")

        # 15. Assistant message with tool_calls preserved
        self.assertEqual(history[2]["role"], "assistant")
        self.assertIn("tool_calls", history[2])
        self.assertEqual(history[2]["tool_calls"][0]["function"]["name"], "get_device_status")

        # 16. Tool result message preserved
        self.assertEqual(history[3]["role"], "tool")
        self.assertEqual(history[3]["name"], "get_device_status")
        self.assertEqual(history[3]["tool_call_id"], "call_abc123")
        tool_payload = json.loads(history[3]["content"])
        self.assertTrue(tool_payload["success"])
        self.assertEqual(tool_payload["data"]["device_name"], "Desk Plug")

        # Final assistant message
        self.assertEqual(history[4]["role"], "assistant")

    # 18. Multiple Tool Calls
    def test_18_multiple_tool_calls(self) -> None:
        """Verify multiple tool calls in a single turn round are all executed."""
        mock_raw = {
            "message": {
                "role": "assistant",
                "content": "Checking both devices...",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_device_status",
                            "arguments": {"device_name": "Desk Plug"},
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "get_device_status",
                            "arguments": {"device_name": "Living Room Lamp"},
                        },
                    },
                ],
            }
        }
        step = 0
        def transport(endpoint, payload, to):
            nonlocal step
            step += 1
            if step == 1:
                return mock_raw
            return {"message": {"role": "assistant", "content": "Both devices checked."}}

        client = OllamaChatClient(transport=transport)
        orchestrator = NexusOrchestrator(
            registry=self.registry,
            permission_manager=self.permission_manager,
            execution_engine=self.execution_engine,
            model_client=client,
        )

        result = orchestrator.run_turn("Check both desk plug and living room lamp")
        self.assertEqual(len(result.tool_calls_executed), 2)
        self.assertEqual(len(result.tool_results), 2)
        self.assertEqual(result.tool_results[0].data["device_name"], "Desk Plug")
        self.assertEqual(result.tool_results[1].data["device_name"], "Living Room Lamp")

    # 19. Bounded Tool Execution Rounds
    def test_19_bounded_tool_execution_rounds(self) -> None:
        """Verify that infinite tool calling loops are terminated at max_rounds."""
        # Always emits a tool call indefinitely
        def looping_transport(endpoint, payload, to):
            return {
                "message": {
                    "role": "assistant",
                    "content": "Looping...",
                    "tool_calls": [
                        {
                            "id": "call_loop",
                            "type": "function",
                            "function": {
                                "name": "get_device_status",
                                "arguments": {"device_name": "Desk Plug"},
                            },
                        }
                    ],
                }
            }

        client = OllamaChatClient(transport=looping_transport)
        orchestrator = NexusOrchestrator(
            registry=self.registry,
            permission_manager=self.permission_manager,
            execution_engine=self.execution_engine,
            model_client=client,
        )

        # Run with max_rounds=3
        result = orchestrator.run_turn("Loop test", max_rounds=3)
        self.assertEqual(result.rounds, 3)
        self.assertIn("Bounded tool execution limit reached", result.final_response)

    # 20. Simulated-Data Labeling
    def test_20_simulated_data_labeling(self) -> None:
        """Verify simulated mock results are explicitly tagged as simulated."""
        call = ToolCall(name="list_devices", arguments={})
        result = self.execution_engine.execute_tool_call(call)
        self.assertTrue(result.simulated)
        self.assertEqual(result.source, "NEXUS_TEST_MOCK")
        self.assertIn("simulated", result.data)
        self.assertTrue(result.data["simulated"])
        self.assertIn("disclaimer", result.data)


if __name__ == "__main__":
    unittest.main()

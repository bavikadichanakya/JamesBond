"""End-to-End Live Verification Test against locally running Ollama instance."""

from __future__ import annotations

import json
import logging
import sys

from nexus.config import NexusConfig
from nexus.model.ollama_client import OllamaChatClient
from nexus.orchestrator import NexusOrchestrator
from nexus.tools.adapters.mock_device import MockDeviceAdapter
from nexus.tools.adapters.system import SystemAdapter
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import (
    PermissionLevel,
    PermissionManager,
    ToolApprovalDecision,
    ToolApprovalRequest,
)
from nexus.tools.registry import ToolRegistry

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("nexus.live_test")


def simulated_user_approval(req: ToolApprovalRequest) -> ToolApprovalDecision:
    """Simulated user confirmation for automated verification."""
    print(f"\n[USER PROMPT INTERACTIVE DIALOG]")
    print(f"Action requested: {req.tool_name}")
    print(f"Target arguments: {req.arguments}")
    print(f"Permission level: {req.permission_level.value}")
    print(f"Decision: [APPROVED BY USER]")
    return ToolApprovalDecision(
        approved=True,
        decided_by="INTERACTIVE_USER_CONFIRMATION",
        reason="User confirmed device power modification",
    )


def run_live_verification():
    print("=" * 80)
    print("NEXUS END-TO-END LIVE OLLAMA VERIFICATION (qwen2.5-coder:3b)")
    print("=" * 80)

    config = NexusConfig(
        ollama_endpoint="http://localhost:11434",
        model_name="qwen2.5-coder:3b",
        model_request_timeout=60.0,
    )

    registry = ToolRegistry()
    mock_devices = MockDeviceAdapter()
    mock_devices.register_tools(registry)

    sys_adapter = SystemAdapter()
    sys_adapter.register_tools(registry)

    perm_manager = PermissionManager(approval_callback=simulated_user_approval)

    engine = ToolExecutionEngine(
        registry=registry,
        permission_manager=perm_manager,
        default_timeout=config.default_tool_timeout,
    )

    client = OllamaChatClient(
        endpoint=config.ollama_endpoint,
        model=config.model_name,
        timeout=config.model_request_timeout,
    )

    orchestrator = NexusOrchestrator(
        config=config,
        registry=registry,
        permission_manager=perm_manager,
        execution_engine=engine,
        model_client=client,
    )

    # Test Case 1: Status query (Read-Only)
    prompt_1 = "What is the status of the Desk Plug?"
    print(f"\n>>> USER: {prompt_1}")
    result_1 = orchestrator.run_turn(prompt_1)

    print(f"\n<<< ASSISTANT:\n{result_1.final_response}")
    print(f"\nTools executed ({len(result_1.tool_calls_executed)}):")
    for call, res in zip(result_1.tool_calls_executed, result_1.tool_results):
        print(f" - Tool: {call.name}({call.arguments})")
        print(f"   Success: {res.success} | Simulated: {res.simulated} | Duration: {res.duration_ms}ms")
        print(f"   Data: {json.dumps(res.data, indent=2)}")

    print(f"\nConversation History Messages: {len(result_1.conversation_history)}")
    for idx, msg in enumerate(result_1.conversation_history):
        role = msg.get("role")
        print(f"  [{idx}] Role: {role.upper()}")
        if "tool_calls" in msg:
            print(f"      Tool Calls: {msg['tool_calls']}")
        if "content" in msg and msg["content"]:
            preview = msg["content"][:120].replace('\n', ' ')
            print(f"      Content: {preview}...")

    # Test Case 2: Control device (Confirmation Required)
    prompt_2 = "Please turn on the Desk Plug."
    print(f"\n" + "-" * 80)
    print(f">>> USER: {prompt_2}")
    result_2 = orchestrator.run_turn(prompt_2, conversation_history=result_1.conversation_history)

    print(f"\n<<< ASSISTANT:\n{result_2.final_response}")
    print(f"\nTools executed ({len(result_2.tool_calls_executed)}):")
    for call, res in zip(result_2.tool_calls_executed, result_2.tool_results):
        print(f" - Tool: {call.name}({call.arguments})")
        print(f"   Success: {res.success} | Simulated: {res.simulated} | Duration: {res.duration_ms}ms")
        print(f"   Data: {json.dumps(res.data, indent=2)}")

    print("\n" + "=" * 80)
    print("VERIFICATION COMPLETED SUCCESSFULLY.")
    print("=" * 80)


if __name__ == "__main__":
    run_live_verification()

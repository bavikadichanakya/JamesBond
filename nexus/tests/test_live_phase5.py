"""End-to-End Live Model Verification Test for NEXUS Phase 5.

Verifies live natural-language intent understanding, intelligent capability routing,
and response synthesis with Ollama (qwen2.5-coder:3b).
"""

from __future__ import annotations

import logging
import sys

from nexus.config import NexusConfig
from nexus.core.session import SessionManager
from nexus.integrations.hermes.adapter import HermesAdapter
from nexus.integrations.manager import IntegrationManager
from nexus.integrations.muse.adapter import MuseAdapter
from nexus.integrations.openclaw.adapter import OpenClawAdapter
from nexus.orchestrator import NexusOrchestrator
from nexus.routing.router import CapabilityRouter
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import (
    PermissionManager,
    ToolApprovalDecision,
    ToolApprovalRequest,
)
from nexus.tools.registry import ToolRegistry

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("nexus.live_phase5")


def live_approval_cb(req: ToolApprovalRequest) -> ToolApprovalDecision:
    """Automatic approval for automated verification run."""
    print(f"\n[LIVE APPROVAL DIALOG] Action '{req.tool_name}' ({req.permission_level.value}) - APPROVED")
    return ToolApprovalDecision(approved=True, decided_by="LIVE_TEST_HARNESS", reason="Automated verification")


def run_live_phase5_verification() -> bool:
    print("=" * 80)
    print("NEXUS PHASE 5: LIVE MODEL INTELLIGENT ROUTING & CONVERSATION TEST")
    print("Local Model: qwen2.5-coder:3b on http://localhost:11434")
    print("=" * 80)

    cfg = NexusConfig(model_request_timeout=120.0)
    registry = ToolRegistry()
    perm_mgr = PermissionManager(approval_callback=live_approval_cb, allow_privileged=True)
    engine = ToolExecutionEngine(registry=registry, permission_manager=perm_mgr)

    mgr = IntegrationManager(registry=registry, permission_manager=perm_mgr, execution_engine=engine)
    mgr.register_adapter(OpenClawAdapter(force_simulated=True))
    mgr.register_adapter(HermesAdapter())
    mgr.register_adapter(MuseAdapter(force_simulated=True))

    router = CapabilityRouter(registry=registry, manager=mgr, execution_engine=engine)
    session_mgr = SessionManager()

    orchestrator = NexusOrchestrator(
        config=cfg,
        registry=registry,
        permission_manager=perm_mgr,
        execution_engine=engine,
        integration_manager=mgr,
        router=router,
    )

    # Turn 1: Device Discovery via Muse Routing
    print("\n--- TURN 1: Smart Home Device Discovery (Intelligent Routing to Muse) ---")
    prompt_1 = "Please check all smart devices currently discovered on the network."
    activity_log_1: list[str] = []
    turn_1 = orchestrator.route_and_run(
        user_prompt=prompt_1,
        activity_callback=lambda act: activity_log_1.append(act),
    )

    print(f"Activity Sequence: {activity_log_1}")
    print(f"Tool Executed: {[c.name for c in turn_1.tool_calls_executed]}")
    print(f"Has Simulated Data: {turn_1.has_simulated_data}")
    print(f"Response:\n{turn_1.final_response.strip()}\n")

    assert len(turn_1.tool_calls_executed) >= 1
    assert "muse_discover_devices" in [c.name for c in turn_1.tool_calls_executed]

    # Turn 2: OpenClaw Status
    print("\n--- TURN 2: Gateway Status (Intelligent Routing to OpenClaw) ---")
    prompt_2 = "What is the status of the OpenClaw gateway and messaging channels?"
    activity_log_2: list[str] = []
    turn_2 = orchestrator.route_and_run(
        user_prompt=prompt_2,
        activity_callback=lambda act: activity_log_2.append(act),
    )

    print(f"Activity Sequence: {activity_log_2}")
    print(f"Tool Executed: {[c.name for c in turn_2.tool_calls_executed]}")
    print(f"Response:\n{turn_2.final_response.strip()}\n")

    assert len(turn_2.tool_calls_executed) >= 1
    assert "openclaw_gateway_status" in [c.name for c in turn_2.tool_calls_executed]

    print("=" * 80)
    print("ALL LIVE PHASE 5 VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = run_live_phase5_verification()
    sys.exit(0 if success else 1)


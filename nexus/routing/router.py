"""NEXUS Dedicated Intelligent Capability Router.

Implements the 9-stage evaluation, scoring, multi-integration sequencing,
and execution pipeline across OpenClaw, Hermes, and Muse adapters.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from nexus.integrations.base import IntegrationStatus
from nexus.integrations.manager import IntegrationManager
from nexus.routing.classifier import IntentClassifier
from nexus.routing.models import (
    CandidateScore,
    IntentClassification,
    RoutingExecutionOutcome,
    RoutingPlan,
    RoutingStatus,
    RoutingStep,
)
from nexus.routing.response_manager import ResponseManager
from nexus.routing.url_utils import extract_website_target_from_query
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import PermissionLevel
from nexus.tools.registry import ToolRegistry
from nexus.tools.result import StandardizedToolResult, ToolCall

logger = logging.getLogger("nexus.routing.router")

ActivityCallback = Callable[[str], None]


class CapabilityRouter:
    """The central intelligence and capability routing engine for NEXUS.
    
    Guarantees:
    - Never assumes an integration supports a task without actual registered capability match.
    - Accurately identifies multi-integration dependencies.
    - Discloses simulation state and handles missing integrations with explicit limitation notices.
    - Strictly preserves the central permission and execution engine.
    """

    # Static capability-to-tool mappings
    CAPABILITY_TOOL_MAP: Dict[str, Dict[str, Any]] = {
        # Muse
        "device_discovery": {"tool": "muse_discover_devices", "default_args": {}, "integration": "muse"},
        "gadget_action_dispatch": {"tool": "muse_invoke_gadget_action", "default_args": {}, "integration": "muse"},
        "gadget_skill_catalog": {"tool": "muse_list_supported_skills", "default_args": {}, "integration": "muse"},
        "skill_spec_inspection": {"tool": "muse_inspect_device_skill", "default_args": {"skill_name": "gadget-elgato-key-light"}, "integration": "muse"},

        # OpenClaw
        "gateway_rpc": {"tool": "openclaw_gateway_status", "default_args": {}, "integration": "openclaw"},
        "channel_dispatch": {"tool": "openclaw_send_channel_message", "default_args": {"channel_id": "telegram_general", "message": "Notification"}, "integration": "openclaw"},
        "extension_discovery": {"tool": "openclaw_list_extensions", "default_args": {}, "integration": "openclaw"},

        # Hermes
        "memory_query": {"tool": "hermes_query_memory", "default_args": {"query": "", "target": "all"}, "integration": "hermes"},
        "skill_discovery": {"tool": "hermes_list_skills", "default_args": {}, "integration": "hermes"},
        "ast_security_audit": {"tool": "hermes_audit_skill_code", "default_args": {"code": "def check(): pass"}, "integration": "hermes"},
        "subagent_delegation": {"tool": "hermes_run_subagent", "default_args": {"task_description": "Analyze context", "role": "Assistant"}, "integration": "hermes"},

        # Local System
        "web_navigation": {"tool": "open_website", "default_args": {"url": "https://www.google.com"}, "integration": "local_system"},
        "application_launch": {"tool": "launch_application", "default_args": {"app_name": "notepad"}, "integration": "local_system"},
        "system_clock": {"tool": "get_current_time", "default_args": {}, "integration": "local_system"},
        "system_telemetry": {"tool": "get_system_info", "default_args": {}, "integration": "local_system"},
        "folder_access": {"tool": "open_approved_folder", "default_args": {"folder_name": "downloads"}, "integration": "local_system"},
    }

    def __init__(
        self,
        registry: ToolRegistry,
        manager: IntegrationManager,
        execution_engine: ToolExecutionEngine,
        classifier: Optional[IntentClassifier] = None,
        response_manager: Optional[ResponseManager] = None,
    ) -> None:
        self.registry = registry
        self.manager = manager
        self.execution_engine = execution_engine
        self.classifier = classifier or IntentClassifier()
        self.response_manager = response_manager or ResponseManager()

    # -------------------------------------------------------------------------
    # Stage 1-6: Planning & Scoring
    # -------------------------------------------------------------------------

    def plan_task(self, query: str) -> RoutingPlan:
        """Execute stages 1 through 6 to formulate an execution plan."""
        # Stage 1 & 2: Understand Intent and Identify Required Capabilities
        intent = self.classifier.classify(query)

        if intent.is_ambiguous:
            return RoutingPlan(
                query=query,
                status=RoutingStatus.AMBIGUOUS,
                intent=intent,
                explanation=intent.ambiguity_reason,
            )

        if intent.primary_intent == "unsupported" or not intent.required_capabilities:
            return RoutingPlan(
                query=query,
                status=RoutingStatus.UNSUPPORTED,
                intent=intent,
                explanation=(
                    f"I cannot fulfill the request '{query}'. "
                    "None of the available integrations support this operation."
                ),
            )

        # Stage 3-5: Retrieve Candidates, Check Health, and Score
        all_scores: List[CandidateScore] = []
        steps: List[RoutingStep] = []
        step_idx = 1
        requires_confirm = False

        for cap in intent.required_capabilities:
            score = self._score_capability(cap)
            all_scores.append(score)

            if score.total_score <= 0.0:
                # Target integration is unavailable
                return RoutingPlan(
                    query=query,
                    status=RoutingStatus.UNAVAILABLE,
                    intent=intent,
                    scores=all_scores,
                    explanation=f"Required capability '{cap}' is currently unavailable: {score.reason}",
                )

            tool_meta = self.CAPABILITY_TOOL_MAP.get(cap)
            if not tool_meta or not score.matched_tool_name:
                continue

            tool_def = self.registry.get_tool(score.matched_tool_name)
            is_confirm = tool_def.permission_level == PermissionLevel.CONFIRMATION_REQUIRED if tool_def else False
            if is_confirm:
                requires_confirm = True

            # Extract arguments tailored to query
            args = self._extract_arguments(cap, query, tool_meta["default_args"])

            steps.append(
                RoutingStep(
                    step_index=step_idx,
                    integration_name=score.integration_name,
                    tool_name=score.matched_tool_name,
                    arguments=args,
                    capability=cap,
                    description=f"Execute {cap} via {score.integration_name.capitalize()}",
                    depends_on=step_idx - 1 if step_idx > 1 else None,
                )
            )
            step_idx += 1

        status = RoutingStatus.MULTI_ROUTED if len(steps) > 1 else RoutingStatus.ROUTED
        return RoutingPlan(
            query=query,
            status=status,
            intent=intent,
            steps=steps,
            scores=all_scores,
            requires_confirmation=requires_confirm,
        )

    def _score_capability(self, capability: str) -> CandidateScore:
        """Score candidate integration for a required capability."""
        mapping = self.CAPABILITY_TOOL_MAP.get(capability)
        if not mapping:
            return CandidateScore(
                integration_name="unknown",
                capability=capability,
                matched_tool_name=None,
                capability_match_score=0.0,
                availability_score=0.0,
                permission_score=0.0,
                total_score=0.0,
                reason=f"No integration in the catalog supports '{capability}'.",
            )

        target_integration = mapping["integration"]
        tool_name = mapping["tool"]

        # Check if tool is registered
        if not self.registry.has_tool(tool_name):
            return CandidateScore(
                integration_name=target_integration,
                capability=capability,
                matched_tool_name=tool_name,
                capability_match_score=1.0,
                availability_score=0.0,
                permission_score=0.0,
                total_score=0.0,
                reason=f"Tool '{tool_name}' is not registered in central registry.",
            )

        # Check adapter health
        adapter = self.manager.get_adapter(target_integration)
        if not adapter:
            return CandidateScore(
                integration_name=target_integration,
                capability=capability,
                matched_tool_name=tool_name,
                capability_match_score=1.0,
                availability_score=0.0,
                permission_score=0.0,
                total_score=0.0,
                reason=f"Adapter for '{target_integration}' is not registered with manager.",
            )

        # Availability scoring
        status = adapter.status
        if status == IntegrationStatus.CONNECTED:
            avail_score = 1.0
        elif status == IntegrationStatus.SIMULATED:
            avail_score = 0.8
        elif status == IntegrationStatus.DEGRADED:
            avail_score = 0.5
        else:
            avail_score = 0.0

        if avail_score <= 0.0:
            return CandidateScore(
                integration_name=target_integration,
                capability=capability,
                matched_tool_name=tool_name,
                capability_match_score=1.0,
                availability_score=0.0,
                permission_score=0.0,
                total_score=0.0,
                reason=f"Integration '{target_integration}' is disconnected or unavailable.",
            )

        # Permission scoring
        tool_def = self.registry.get_tool(tool_name)
        perm_score = 1.0 if tool_def and tool_def.permission_level == PermissionLevel.READ_ONLY else 0.8

        total = 0.5 * 1.0 + 0.3 * avail_score + 0.2 * perm_score

        return CandidateScore(
            integration_name=target_integration,
            capability=capability,
            matched_tool_name=tool_name,
            capability_match_score=1.0,
            availability_score=avail_score,
            permission_score=perm_score,
            total_score=total,
            reason=f"Verified candidate '{target_integration}' (status: {status.value})",
        )

    def _extract_arguments(self, capability: str, query: str, default_args: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameter arguments from query text for given capability."""
        args = dict(default_args)
        q_lower = query.lower()

        if capability == "channel_dispatch":
            # Extract channel target if mentioned
            if "discord" in q_lower:
                args["channel_id"] = "discord_alerts"
            elif "slack" in q_lower:
                args["channel_id"] = "slack_dev"
            else:
                args["channel_id"] = "telegram_general"
            # Extract message content or default
            msg_match = re.search(r"message\s*['\"](.*?)['\"]", query, re.IGNORECASE)
            if msg_match:
                args["message"] = msg_match.group(1)
            else:
                args["message"] = query

        elif capability == "memory_query":
            # Pass query as keyword filter
            for word in ["offline", "preference", "recent", "devices"]:
                if word in q_lower:
                    args["query"] = word
                    break

        elif capability == "gadget_action_dispatch":
            # Identify target device
            if "key light" in q_lower or "light" in q_lower:
                args["device_id"] = "elgato_key_light_desk"
            elif "sonos" in q_lower or "speaker" in q_lower:
                args["device_id"] = "sonos_living_room"
            elif "roku" in q_lower or "tv" in q_lower:
                args["device_id"] = "roku_office_tv"
            else:
                args["device_id"] = "shelly_plug_kitchen"

            # Identify action
            if "turn off" in q_lower or "power off" in q_lower:
                args["action"] = "set_power"
                args["parameters"] = {"state": "off"}
            elif "turn on" in q_lower or "power on" in q_lower:
                args["action"] = "set_power"
                args["parameters"] = {"state": "on"}
            elif "brightness" in q_lower:
                num = re.search(r"\b(\d+)\b", query)
                b_val = int(num.group(1)) if num else 70
                args["action"] = "set_brightness"
                args["parameters"] = {"brightness": b_val}
            elif "volume" in q_lower:
                num = re.search(r"\b(\d+)\b", query)
                v_val = int(num.group(1)) if num else 40
                args["action"] = "set_volume"
                args["parameters"] = {"volume": v_val}
            else:
                args["action"] = "set_power"
                args["parameters"] = {"state": "on"}

        elif capability == "web_navigation":
            extracted = extract_website_target_from_query(query)
            if extracted:
                args["url"] = extracted
            else:
                # Dynamic fallback for explicit URLs or domains
                url_match = re.search(r"https?://\S+|www\.\S+|\b[a-zA-Z0-9-]+\.(?:com|org|io|net|edu|ai|gov|co|uk|de|me)\b", query)
                if url_match:
                    found_url = url_match.group(0)
                    if not found_url.startswith("http"):
                        found_url = "https://" + found_url
                    args["url"] = found_url

        elif capability == "application_launch":
            if "notepad" in q_lower:
                args["app_name"] = "notepad"
            elif "chrome" in q_lower:
                args["app_name"] = "chrome"
            elif "calculator" in q_lower or "calc" in q_lower:
                args["app_name"] = "calculator"
            elif "paint" in q_lower or "mspaint" in q_lower:
                args["app_name"] = "mspaint"
            elif "taskmgr" in q_lower or "task manager" in q_lower:
                args["app_name"] = "taskmgr"
            elif "edge" in q_lower:
                args["app_name"] = "edge"

        elif capability == "folder_access":
            if "download" in q_lower:
                args["folder_name"] = "downloads"
            elif "document" in q_lower:
                args["folder_name"] = "documents"
            elif "desktop" in q_lower:
                args["folder_name"] = "desktop"
            elif "workspace" in q_lower or "mixer" in q_lower:
                args["folder_name"] = "workspace"
            elif "picture" in q_lower:
                args["folder_name"] = "pictures"
            elif "video" in q_lower:
                args["folder_name"] = "videos"
            elif "music" in q_lower:
                args["folder_name"] = "music"

        return args

    # -------------------------------------------------------------------------
    # Stage 7-9: Execution, Verification & Consolidation
    # -------------------------------------------------------------------------

    def execute_query(
        self,
        query: str,
        activity_callback: Optional[ActivityCallback] = None,
    ) -> RoutingExecutionOutcome:
        """Full end-to-end routing pipeline execution."""
        activity_log: List[str] = []

        def log_act(msg: str) -> None:
            activity_log.append(msg)
            if activity_callback:
                activity_callback(msg)

        log_act("Understanding your request...")
        plan = self.plan_task(query)

        # Handle non-executable plans
        if plan.status == RoutingStatus.AMBIGUOUS:
            return RoutingExecutionOutcome(
                plan=plan,
                success=False,
                final_response=f"I need clarification: {plan.intent.suggested_clarification}",
                activity_log=activity_log,
                error_message="Ambiguous request",
            )

        if plan.status == RoutingStatus.UNSUPPORTED:
            return RoutingExecutionOutcome(
                plan=plan,
                success=False,
                final_response=plan.explanation or "This request is not supported.",
                activity_log=activity_log,
                error_message="Unsupported request",
            )

        if plan.status == RoutingStatus.UNAVAILABLE:
            return RoutingExecutionOutcome(
                plan=plan,
                success=False,
                final_response=plan.explanation or "The required integration is currently unavailable.",
                activity_log=activity_log,
                error_message="Integration unavailable",
            )

        log_act("Checking available capabilities...")
        executed_records: List[Dict[str, Any]] = []
        has_simulated = False
        all_success = True

        executed_signatures: set = set()

        for step in plan.steps:
            # Prevent identical tool calls from executing twice within the same turn
            sig = f"{step.tool_name}:{json.dumps(step.arguments, sort_keys=True)}"
            if sig in executed_signatures:
                logger.info("[Router Deduplication] Skipping duplicate identical tool call in turn: %s", sig)
                continue
            executed_signatures.add(sig)

            log_act(f"Routing to {step.integration_name.capitalize()}...")
            log_act(f"Retrieving information via {step.tool_name}...")

            call = ToolCall(
                name=step.tool_name,
                arguments=step.arguments,
            )
            result = self.execution_engine.execute_tool_call(call)
            executed_records.append({"step": step, "result": result})

            # Stage 8 Observability Logging
            norm_url = step.arguments.get("url", "N/A")
            if result.data and isinstance(result.data, dict) and "url" in result.data:
                norm_url = result.data.get("url")
            shell_res = result.data.get("dispatch_code", "N/A") if (result.data and isinstance(result.data, dict)) else (f"ERROR: {result.error.message}" if result.error else "N/A")
            op_status = "SUCCESS" if result.success else "FAILED"
            logger.info(
                "[NEXUS Execution Observability] Request: '%s' | Intent: %s | Adapter: %s | Tool: %s | "
                "Normalized URL: %s | Tool Invocation ID: %s | Windows ShellExecute Result: %s | Status: %s",
                query,
                step.capability,
                step.integration_name,
                step.tool_name,
                norm_url,
                result.execution_id,
                shell_res,
                op_status,
            )

            if result.simulated:
                has_simulated = True

            if not result.success:
                all_success = False
                logger.warning("Step %d (%s) failed: %s", step.step_index, step.tool_name, result.error)
                break

        log_act("Preparing your response...")
        final_text = self.response_manager.consolidate(
            plan=plan,
            results=executed_records,
            has_simulated=has_simulated,
        )

        return RoutingExecutionOutcome(
            plan=plan,
            success=all_success,
            final_response=final_text,
            executed_steps=executed_records,
            has_simulated_data=has_simulated,
            activity_log=activity_log,
        )

"""NEXUS Central Orchestrator: Combines Tool Registry, Execution Engine, and Model Client."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from nexus.config import NexusConfig
from nexus.model.ollama_client import OllamaChatClient, OllamaModelResponse
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import PermissionManager
from nexus.tools.registry import ToolRegistry
from nexus.tools.result import StandardizedToolResult, ToolCall

# Forward typing imports for Phase 5 integration
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from nexus.integrations.manager import IntegrationManager
    from nexus.routing.models import RoutingExecutionOutcome, RoutingPlan
    from nexus.routing.router import CapabilityRouter

logger = logging.getLogger("nexus.orchestrator")


@dataclass
class NexusTurnResult:
    """The complete outcome of an end-to-end conversation turn."""

    user_prompt: str
    final_response: str
    tool_calls_executed: List[ToolCall] = field(default_factory=list)
    tool_results: List[StandardizedToolResult] = field(default_factory=list)
    rounds: int = 1
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    has_simulated_data: bool = False
    routing_plan: Optional[Any] = None
    activity_log: List[str] = field(default_factory=list)


class NexusOrchestrator:
    """The unified cognitive orchestration engine for NEXUS.
    
    Coordinates the full turn lifecycle:
    User request -> Model tool call -> Tool execution -> Tool result -> Model final response.
    """

    def __init__(
        self,
        config: Optional[NexusConfig] = None,
        registry: Optional[ToolRegistry] = None,
        permission_manager: Optional[PermissionManager] = None,
        execution_engine: Optional[ToolExecutionEngine] = None,
        model_client: Optional[OllamaChatClient] = None,
        integration_manager: Optional[Any] = None,
        router: Optional[Any] = None,
    ) -> None:
        self.config = config or NexusConfig()
        self.registry = registry or ToolRegistry()
        self.permission_manager = permission_manager or PermissionManager(
            allow_privileged=self.config.allow_privileged_execution
        )
        self.execution_engine = execution_engine or ToolExecutionEngine(
            registry=self.registry,
            permission_manager=self.permission_manager,
            default_timeout=self.config.default_tool_timeout,
            redact_patterns=self.config.redact_sensitive_patterns,
        )
        self.model_client = model_client or OllamaChatClient(
            endpoint=self.config.ollama_endpoint,
            model=self.config.model_name,
            timeout=self.config.model_request_timeout,
        )
        self.integration_manager = integration_manager
        self.router = router
        if self.router is None and self.integration_manager is not None:
            from nexus.routing.router import CapabilityRouter
            self.router = CapabilityRouter(
                registry=self.registry,
                manager=self.integration_manager,
                execution_engine=self.execution_engine,
            )

    DEFAULT_SYSTEM_PROMPT = (
        "You are NEXUS, a privacy-first local AI assistant with access to tools. "
        "When you need to inspect or control devices or system state, call the appropriate registered tool. "
        "When tool results are provided, synthesize a clear, helpful natural language answer for the user, "
        "and clearly disclose when the data is simulated."
    )

    def run_turn(
        self,
        user_prompt: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        max_rounds: Optional[int] = None,
    ) -> NexusTurnResult:
        """Execute a full multi-turn conversation turn with bounded tool execution."""
        messages: List[Dict[str, Any]] = list(conversation_history or [])

        # Ensure system prompt is present at root of conversation
        if not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": self.DEFAULT_SYSTEM_PROMPT})

        messages.append({"role": "user", "content": user_prompt})

        executed_calls: List[ToolCall] = []
        executed_results: List[StandardizedToolResult] = []
        limit_rounds = max_rounds if max_rounds is not None else self.config.max_tool_rounds
        current_round = 0
        final_text = ""
        has_simulated = False

        while current_round < limit_rounds:
            current_round += 1
            tool_definitions = self.registry.get_model_tool_definitions()

            logger.info("Starting turn round %d/%d (tools registered: %d)", current_round, limit_rounds, len(tool_definitions))
            response = self.model_client.chat(messages=messages, tools=tool_definitions)

            # If no tool calls were generated by model, we have the final assistant response
            if not response.tool_calls:
                final_text = response.content
                messages.append({"role": "assistant", "content": final_text})
                break

            # Preserve assistant message with tool calls in history
            # Note: For Ollama template compatibility (e.g. Qwen2.5-Coder), if tool_calls
            # are present, content must be empty so the template renders <tool_call> blocks.
            assistant_history_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": "",
            }
            # Add tool_calls structure to assistant message for compliance
            assistant_history_msg["tool_calls"] = [
                {
                    "id": call.tool_call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in response.tool_calls
            ]
            messages.append(assistant_history_msg)

            # Execute tool calls emitted in this round (prevent identical duplicate execution in turn)
            round_signatures: set = set()
            for call in response.tool_calls:
                sig = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
                if sig in round_signatures:
                    logger.info("[Orchestrator Deduplication] Skipping duplicate identical tool call in round: %s", sig)
                    continue
                round_signatures.add(sig)

                executed_calls.append(call)
                result = self.execution_engine.execute_tool_call(call)
                executed_results.append(result)
                if result.simulated:
                    has_simulated = True

                # Append tool result to conversation history matching call id
                tool_msg: Dict[str, Any] = {
                    "role": "tool",
                    "name": result.tool_name,
                    "tool_call_id": result.tool_call_id,
                    "content": result.to_json(),
                }
                messages.append(tool_msg)

        else:
            # Reached max_rounds boundary without model concluding
            warning_msg = (
                f"[NEXUS Execution Warning: Bounded tool execution limit reached ({limit_rounds} rounds). "
                f"Halting tool execution loop for safety.]"
            )
            logger.warning(warning_msg)
            final_text = warning_msg
            messages.append({"role": "assistant", "content": final_text})

        return NexusTurnResult(
            user_prompt=user_prompt,
            final_response=final_text,
            tool_calls_executed=executed_calls,
            tool_results=executed_results,
            rounds=current_round,
            conversation_history=messages,
            has_simulated_data=has_simulated,
        )

    def route_and_run(
        self,
        user_prompt: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        activity_callback: Optional[Callable[[str], None]] = None,
    ) -> NexusTurnResult:
        """Route user prompt through the CapabilityRouter if available, falling back to LLM turn.
        
        Guarantees:
        - Automatically detects whether the prompt matches OpenClaw, Hermes, or Muse capabilities.
        - Emits real-time activity updates to activity_callback.
        - Returns a unified NexusTurnResult with activity log and routing provenance.
        """
        if self.router is not None:
            # Plan with router
            plan = self.router.plan_task(user_prompt)
            from nexus.routing.models import RoutingStatus

            if plan.status in (RoutingStatus.ROUTED, RoutingStatus.MULTI_ROUTED):
                outcome = self.router.execute_query(user_prompt, activity_callback=activity_callback)
                tool_calls = [
                    ToolCall(name=step["step"].tool_name, arguments=step["step"].arguments)
                    for step in outcome.executed_steps
                ]
                tool_results = [step["result"] for step in outcome.executed_steps]

                history = list(conversation_history) if conversation_history else []
                history.append({"role": "user", "content": user_prompt})
                history.append({"role": "assistant", "content": outcome.final_response})

                return NexusTurnResult(
                    user_prompt=user_prompt,
                    final_response=outcome.final_response,
                    tool_calls_executed=tool_calls,
                    tool_results=tool_results,
                    rounds=len(outcome.executed_steps) + 1,
                    conversation_history=history,
                    has_simulated_data=outcome.has_simulated_data,
                    routing_plan=plan,
                    activity_log=outcome.activity_log,
                )
            elif plan.status in (RoutingStatus.AMBIGUOUS, RoutingStatus.UNSUPPORTED, RoutingStatus.UNAVAILABLE):
                outcome = self.router.execute_query(user_prompt, activity_callback=activity_callback)
                history = list(conversation_history) if conversation_history else []
                history.append({"role": "user", "content": user_prompt})
                history.append({"role": "assistant", "content": outcome.final_response})

                return NexusTurnResult(
                    user_prompt=user_prompt,
                    final_response=outcome.final_response,
                    tool_calls_executed=[],
                    tool_results=[],
                    rounds=1,
                    conversation_history=history,
                    has_simulated_data=False,
                    routing_plan=plan,
                    activity_log=outcome.activity_log,
                )

        # Fallback to model turn
        if activity_callback:
            activity_callback("Understanding your request via local model...")
        turn = self.run_turn(user_prompt, conversation_history=conversation_history)
        if activity_callback:
            activity_callback("Preparing your response...")
        return turn


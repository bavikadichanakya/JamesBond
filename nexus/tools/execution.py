"""Tool Execution Engine for NEXUS."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from nexus.tools.permissions import PermissionManager
from nexus.tools.registry import ToolRegistry
from nexus.tools.result import StandardizedToolResult, ToolCall
from nexus.tools.schema import ToolDefinition, ToolSchemaValidator

logger = logging.getLogger("nexus.tools.execution")


class ToolExecutionEngine:
    """Executes validated tool calls with strict permission enforcement, timeouts, and structured error handling.
    
    Guarantees:
    - Independent argument validation before execution.
    - Strict permission checking outside LLM control.
    - Hard timeouts preventing runaway execution.
    - Sensitive token redaction in all logging.
    - Canonical `StandardizedToolResult` return contract.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        permission_manager: PermissionManager,
        default_timeout: float = 10.0,
        redact_patterns: Optional[List[str]] = None,
    ) -> None:
        self.registry = registry
        self.permission_manager = permission_manager
        self.default_timeout = default_timeout
        self.redact_patterns = [
            p.lower()
            for p in (
                redact_patterns
                or [
                    "password",
                    "secret",
                    "token",
                    "api_key",
                    "authorization",
                    "bearer",
                    "private_key",
                ]
            )
        ]

    def _redact_dict(self, data: Any) -> Any:
        """Recursively redact sensitive keys in nested data structures for logging."""
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if any(pat in k.lower() for pat in self.redact_patterns):
                    redacted[k] = "[REDACTED]"
                else:
                    redacted[k] = self._redact_dict(v)
            return redacted
        elif isinstance(data, list):
            return [self._redact_dict(item) for item in data]
        return data

    def execute_tool_call(
        self,
        tool_call: Union[ToolCall, Dict[str, Any]],
        timeout_seconds: Optional[float] = None,
    ) -> StandardizedToolResult:
        """Execute a single structured tool call."""
        start_time = time.perf_counter()
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"

        # Parse tool call
        if isinstance(tool_call, ToolCall):
            tool_name = tool_call.name
            raw_args = tool_call.arguments
            tool_call_id = tool_call.tool_call_id
        elif isinstance(tool_call, dict):
            tool_name = str(tool_call.get("name") or "")
            raw_args = tool_call.get("arguments", {})
            tool_call_id = str(tool_call.get("tool_call_id") or tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}")
        else:
            duration = (time.perf_counter() - start_time) * 1000.0
            return StandardizedToolResult.create_failure(
                execution_id=execution_id,
                tool_call_id="unknown",
                tool_name="unknown",
                source="NEXUS_EXECUTION_ENGINE",
                simulated=True,
                error_code="INVALID_CALL_FORMAT",
                error_message=f"Expected ToolCall or dict, received {type(tool_call).__name__}",
                duration_ms=duration,
            )

        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout

        logger.info(
            "Initiating tool execution: id=%s tool=%s call_id=%s args=%s",
            execution_id,
            tool_name,
            tool_call_id,
            self._redact_dict(raw_args),
        )

        # 1. Lookup Tool
        tool_def = self.registry.get_tool(tool_name)
        if tool_def is None:
            duration = (time.perf_counter() - start_time) * 1000.0
            logger.warning("Tool not found: %s", tool_name)
            return StandardizedToolResult.create_failure(
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                source="NEXUS_EXECUTION_ENGINE",
                simulated=True,
                error_code="TOOL_NOT_FOUND",
                error_message=f"Tool '{tool_name}' is not registered in the NEXUS Tool Registry.",
                duration_ms=duration,
            )

        # 2. Sanitize and Validate Arguments
        try:
            sanitized_args = ToolSchemaValidator.sanitize_arguments(raw_args)
            validated_args = ToolSchemaValidator.validate(tool_def, sanitized_args)
        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000.0
            logger.warning("Argument validation failed for tool '%s': %s", tool_name, exc)
            return StandardizedToolResult.create_failure(
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                source=tool_def.source,
                simulated=tool_def.simulated,
                error_code="VALIDATION_ERROR",
                error_message=str(exc),
                duration_ms=duration,
            )

        # 3. Check and Authorize Permissions
        auth_decision = self.permission_manager.check_and_authorize(
            tool_name=tool_name,
            permission_level=tool_def.permission_level,
            execution_id=execution_id,
            tool_call_id=tool_call_id,
            arguments=self._redact_dict(validated_args),
            source=tool_def.source,
        )

        if not auth_decision.approved:
            duration = (time.perf_counter() - start_time) * 1000.0
            logger.warning(
                "Execution denied for tool '%s' by %s: %s",
                tool_name,
                auth_decision.decided_by,
                auth_decision.reason,
            )
            return StandardizedToolResult.create_failure(
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                source=tool_def.source,
                simulated=tool_def.simulated,
                error_code="PERMISSION_DENIED",
                error_message=auth_decision.reason or "Permission denied by security policy.",
                error_details={"decided_by": auth_decision.decided_by},
                duration_ms=duration,
            )

        # 4. Execute Handler with Timeout
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(tool_def.handler, validated_args)
                result_data = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            duration = (time.perf_counter() - start_time) * 1000.0
            logger.error("Execution timed out for tool '%s' after %.2fs", tool_name, timeout)
            return StandardizedToolResult.create_failure(
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                source=tool_def.source,
                simulated=tool_def.simulated,
                error_code="EXECUTION_TIMEOUT",
                error_message=f"Tool '{tool_name}' timed out after {timeout} seconds.",
                duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000.0
            logger.exception("Execution failed for tool '%s': %s", tool_name, exc)
            return StandardizedToolResult.create_failure(
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                source=tool_def.source,
                simulated=tool_def.simulated,
                error_code="EXECUTION_FAILED",
                error_message=f"Tool handler raised exception: {str(exc)}",
                duration_ms=duration,
            )

        duration = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "Tool execution successful: tool=%s duration=%.2fms",
            tool_name,
            duration,
        )

        if not isinstance(result_data, dict):
            result_data = {"result": result_data}

        return StandardizedToolResult.create_success(
            execution_id=execution_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            source=tool_def.source,
            simulated=tool_def.simulated,
            data=result_data,
            duration_ms=duration,
        )


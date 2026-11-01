"""Standardized tool result contracts and data structures for NEXUS."""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolCall:
    """Represents a structured tool call requested by the model."""

    name: str
    arguments: Dict[str, Any]
    tool_call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")


@dataclass
class ToolExecutionError:
    """Structured error descriptor returned upon tool execution failure."""

    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details or {},
        }


@dataclass
class StandardizedToolResult:
    """The canonical tool execution outcome returned to the model and caller.
    
    Guarantees:
    - Clear distinction between real and simulated results via `simulated` and `source`.
    - Strict provenance tracking via `execution_id` and `tool_call_id`.
    - Predictable serialization schema.
    """

    success: bool
    execution_id: str
    tool_call_id: str
    tool_name: str
    source: str
    simulated: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[ToolExecutionError] = None
    started_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    duration_ms: float = 0.0

    @classmethod
    def create_success(
        cls,
        execution_id: str,
        tool_call_id: str,
        tool_name: str,
        source: str,
        simulated: bool,
        data: Dict[str, Any],
        duration_ms: float = 0.0,
    ) -> StandardizedToolResult:
        return cls(
            success=True,
            execution_id=execution_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            source=source,
            simulated=simulated,
            data=data,
            error=None,
            duration_ms=duration_ms,
        )

    @classmethod
    def create_failure(
        cls,
        execution_id: str,
        tool_call_id: str,
        tool_name: str,
        source: str,
        simulated: bool,
        error_code: str,
        error_message: str,
        error_details: Optional[Dict[str, Any]] = None,
        duration_ms: float = 0.0,
    ) -> StandardizedToolResult:
        return cls(
            success=False,
            execution_id=execution_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            source=source,
            simulated=simulated,
            data=None,
            error=ToolExecutionError(
                code=error_code,
                message=error_message,
                details=error_details,
            ),
            duration_ms=duration_ms,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "execution_id": self.execution_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "source": self.source,
            "simulated": self.simulated,
            "data": self.data,
            "error": self.error.to_dict() if self.error else None,
            "started_at": self.started_at,
            "duration_ms": round(self.duration_ms, 2),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


"""Permission management and human-in-the-loop authorization for NEXUS tools."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class PermissionLevel(str, Enum):
    """Permission categories for tool execution."""

    READ_ONLY = "READ_ONLY"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    PRIVILEGED = "PRIVILEGED"
    DISABLED = "DISABLED"


@dataclass
class ToolApprovalRequest:
    """Request payload provided to an approval callback."""

    execution_id: str
    tool_name: str
    tool_call_id: str
    arguments: Dict[str, Any]
    permission_level: PermissionLevel
    source: str
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


@dataclass
class ToolApprovalDecision:
    """Decision produced by an approval callback."""

    approved: bool
    decided_by: str  # e.g. "USER_CONFIRMED", "POLICY_AUTO_ALLOW", "POLICY_DENIED", "USER_DENIED"
    reason: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


ApprovalCallback = Callable[[ToolApprovalRequest], ToolApprovalDecision]


class PermissionManager:
    """Enforces execution permissions outside LLM control.
    
    The model cannot grant itself permissions. Every tool with CONFIRMATION_REQUIRED
    or PRIVILEGED must obtain an explicit approval decision through the registered callback.
    All decisions are permanently recorded in an in-memory audit log.
    """

    def __init__(
        self,
        approval_callback: Optional[ApprovalCallback] = None,
        allow_privileged: bool = False,
    ) -> None:
        self.approval_callback = approval_callback or self._default_interactive_or_deny_callback
        self.allow_privileged = allow_privileged
        self._audit_log: List[Dict[str, Any]] = []

    @staticmethod
    def _default_interactive_or_deny_callback(request: ToolApprovalRequest) -> ToolApprovalDecision:
        """Default fallback if no interactive UI/channel callback is bound. Denies by default for safety."""
        return ToolApprovalDecision(
            approved=False,
            decided_by="DEFAULT_POLICY_DENIED",
            reason=f"Action '{request.tool_name}' requires explicit confirmation, but no approval handler was configured.",
        )

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        """Set or update the approval callback (e.g., interactive CLI prompt, web UI button, or test mock)."""
        self.approval_callback = callback

    def check_and_authorize(
        self,
        tool_name: str,
        permission_level: PermissionLevel,
        execution_id: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
        source: str = "NEXUS_CORE",
    ) -> ToolApprovalDecision:
        """Evaluate permission for a tool execution request."""
        # Hard disabled tools can never run
        if permission_level == PermissionLevel.DISABLED:
            decision = ToolApprovalDecision(
                approved=False,
                decided_by="POLICY_DISABLED",
                reason=f"Tool '{tool_name}' is disabled by security policy.",
            )
            self._record_audit(tool_name, arguments, permission_level, decision)
            return decision

        # READ_ONLY tools are automatically authorized
        if permission_level == PermissionLevel.READ_ONLY:
            decision = ToolApprovalDecision(
                approved=True,
                decided_by="POLICY_AUTO_READ_ONLY",
                reason="Read-only operations do not modify external state.",
            )
            self._record_audit(tool_name, arguments, permission_level, decision)
            return decision

        # PRIVILEGED tools require global privileged permission flag AND approval callback
        if permission_level == PermissionLevel.PRIVILEGED and not self.allow_privileged:
            decision = ToolApprovalDecision(
                approved=False,
                decided_by="POLICY_PRIVILEGED_LOCKED",
                reason=f"Tool '{tool_name}' requires PRIVILEGED mode, which is currently disabled on this NEXUS host.",
            )
            self._record_audit(tool_name, arguments, permission_level, decision)
            return decision

        # Request user / client approval for CONFIRMATION_REQUIRED and PRIVILEGED
        req = ToolApprovalRequest(
            execution_id=execution_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            arguments=arguments,
            permission_level=permission_level,
            source=source,
        )

        try:
            decision = self.approval_callback(req)
        except Exception as exc:
            decision = ToolApprovalDecision(
                approved=False,
                decided_by="APPROVAL_HANDLER_EXCEPTION",
                reason=f"Approval callback failed with exception: {exc}",
            )

        self._record_audit(tool_name, arguments, permission_level, decision)
        return decision

    def _record_audit(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        permission_level: PermissionLevel,
        decision: ToolApprovalDecision,
    ) -> None:
        self._audit_log.append(
            {
                "tool_name": tool_name,
                "permission_level": permission_level.value,
                "approved": decision.approved,
                "decided_by": decision.decided_by,
                "reason": decision.reason,
                "timestamp": decision.timestamp,
            }
        )

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Return a copy of the recorded permission audit log."""
        return list(self._audit_log)


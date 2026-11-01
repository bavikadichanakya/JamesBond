"""Data models for NEXUS Intelligent Capability Routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RoutingStatus(str, Enum):
    """Status of a task routing operation."""

    ROUTED = "ROUTED"
    MULTI_ROUTED = "MULTI_ROUTED"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


@dataclass
class IntentClassification:
    """Classified user intent and associated capabilities."""

    raw_query: str
    primary_intent: str
    required_capabilities: List[str]
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    suggested_clarification: Optional[str] = None
    confidence: float = 1.0


@dataclass
class CandidateScore:
    """Evaluation score for an integration candidate."""

    integration_name: str
    capability: str
    matched_tool_name: Optional[str]
    capability_match_score: float  # 0.0 to 1.0
    availability_score: float      # 1.0 = CONNECTED, 0.7 = SIMULATED, 0.4 = DEGRADED, 0.0 = DISCONNECTED
    permission_score: float        # 1.0 = READ_ONLY, 0.8 = CONFIRMATION_REQUIRED
    total_score: float
    reason: str


@dataclass
class RoutingStep:
    """A discrete execution step in a routing plan."""

    step_index: int
    integration_name: str
    tool_name: str
    arguments: Dict[str, Any]
    capability: str
    description: str
    depends_on: Optional[int] = None  # Step index this step depends on


@dataclass
class RoutingPlan:
    """The formulated execution plan for a user query."""

    query: str
    status: RoutingStatus
    intent: IntentClassification
    steps: List[RoutingStep] = field(default_factory=list)
    scores: List[CandidateScore] = field(default_factory=list)
    explanation: Optional[str] = None
    requires_confirmation: bool = False


@dataclass
class RoutingExecutionOutcome:
    """The complete outcome of routing and executing a task."""

    plan: RoutingPlan
    success: bool
    final_response: str
    executed_steps: List[Dict[str, Any]] = field(default_factory=list)
    has_simulated_data: bool = False
    activity_log: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


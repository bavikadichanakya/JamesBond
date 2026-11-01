"""Intent Classifier for NEXUS Intelligent Routing.

Classifies natural language input into required capabilities, detects ambiguities,
and flags unsupported tasks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from nexus.routing.models import IntentClassification
from nexus.routing.url_utils import (
    DEFAULT_APP_NAMES,
    DEFAULT_FOLDER_NAMES,
    is_website_navigation_query,
)


class IntentClassifier:
    """Classifies user requests into standardized capability requirements.
    
    Guarantees:
    - Never hallucinates capabilities not supported by the ecosystem.
    - Explicitly flags ambiguous requests for user clarification.
    - Accurately identifies multi-integration dependencies.
    """

    # Keyword mappings to capabilities
    CAPABILITY_KEYWORDS: Dict[str, List[str]] = {
        # Muse capabilities
        "device_discovery": [
            "device", "devices", "smart home", "lights", "light", "plug", "plugs",
            "speaker", "speakers", "tv", "tvs", "sonos", "elgato", "roku", "shelly",
            "discover devices", "scan network", "find devices", "list devices",
        ],
        "gadget_action_dispatch": [
            "turn on", "turn off", "set brightness", "dim", "brighten", "set volume",
            "mute", "unmute", "power on", "power off", "switch on", "switch off",
            "change light", "play music", "pause music",
        ],
        "gadget_skill_catalog": [
            "device skills", "gadget skills", "supported devices", "supported hardware",
            "device catalog", "iot catalog", "list device skills",
        ],
        "skill_spec_inspection": [
            "device spec", "device specification", "how to control", "device commands",
            "inspect skill", "elgato spec", "sonos spec",
        ],

        # OpenClaw capabilities
        "gateway_rpc": [
            "gateway", "gateway status", "gateway health", "openclaw status",
            "control plane", "gateway online",
        ],
        "channel_dispatch": [
            "send message", "send a message", "post to", "notify channel",
            "telegram", "discord", "slack", "message channel", "dispatch message",
            "broadcast", "alert team",
        ],
        "extension_discovery": [
            "extensions", "plugins", "openclaw extensions", "list extensions",
            "openclaw plugins",
        ],

        # Hermes capabilities
        "memory_query": [
            "remember", "memory", "memories", "user profile", "agent notes",
            "my preferences", "what do you know about me", "recall", "stored context",
            "previously noted", "offline recently",
        ],
        "skill_discovery": [
            "hermes skills", "agent skills", "reasoning skills", "workflow skills",
            "list agent skills", "list hermes skills",
        ],
        "ast_security_audit": [
            "audit code", "ast audit", "code safety", "security audit", "inspect python",
            "is this code safe", "check code for vulnerabilities",
        ],
        "subagent_delegation": [
            "subagent", "delegate", "delegate task", "run subagent", "agent delegation",
            "autonomous task", "background agent",
        ],

        # Local System capabilities
        "web_navigation": [
            "open website", "open url", "open web", "go to", "browse to",
            "open youtube", "youtube", "open google", "open github", "open reddit",
            "visit site", "visit website",
        ],
        "application_launch": [
            "open chrome", "launch chrome", "open notepad", "launch notepad",
            "open calculator", "launch calculator", "open calc", "open paint",
            "open taskmgr", "open task manager", "open edge",
            "launch application", "start application",
        ],
        "system_clock": [
            "what time is it", "current time", "what's the time", "tell me the time",
            "what is the time", "what is the date", "current date", "what day is it",
            "time right now", "system time", "local time", "clock",
        ],
        "system_telemetry": [
            "system memory", "check memory", "check my memory", "system ram",
            "check my system", "system info", "system information", "host specs",
            "system specs", "cpu usage", "ram usage", "available memory",
        ],
        "folder_access": [
            "downloads folder", "open downloads", "my downloads", "open my downloads",
            "documents folder", "open documents", "my documents", "open my documents",
            "desktop folder", "open desktop", "open workspace", "pictures folder",
            "open folder", "browse folder",
        ],
    }

    # Ambiguous phrases that lack sufficient context
    AMBIGUOUS_PATTERNS = [
        r"^(send|send it|dispatch)$",
        r"^(status|check status)$",
        r"^(check|check it|look at it)$",
        r"^(run|execute|do it)$",
        r"^(start|stop)$",
        r"^(help me)$",
    ]

    # Explicitly unsupported topics outside assistant scope
    UNSUPPORTED_KEYWORDS = [
        "book a flight", "hotel reservation", "order pizza", "buy bitcoin",
        "crypto trading", "uber ride", "food delivery", "stock purchase",
    ]

    def classify(self, user_query: str) -> IntentClassification:
        """Classify a user query into primary intent and required capabilities."""
        query_norm = user_query.strip().lower()

        # 1. Check for Ambiguous Queries
        for pat in self.AMBIGUOUS_PATTERNS:
            if re.match(pat, query_norm):
                return IntentClassification(
                    raw_query=user_query,
                    primary_intent="ambiguous",
                    required_capabilities=[],
                    is_ambiguous=True,
                    ambiguity_reason=f"The request '{user_query}' is too brief or ambiguous to determine the target capability.",
                    suggested_clarification="Could you please specify whether you want to check smart devices, send a channel message, or query memory?",
                    confidence=0.2,
                )

        # 2. Check for Explicitly Unsupported Queries
        for unsupp in self.UNSUPPORTED_KEYWORDS:
            if unsupp in query_norm:
                return IntentClassification(
                    raw_query=user_query,
                    primary_intent="unsupported",
                    required_capabilities=[],
                    is_ambiguous=False,
                    confidence=0.9,
                )

        # 3. Detect Capabilities
        detected_caps: List[str] = []

        # Website intent detection (Dynamic domain and brand recognition before fallback)
        if is_website_navigation_query(user_query):
            detected_caps.append("web_navigation")

        for cap, keywords in self.CAPABILITY_KEYWORDS.items():
            if cap == "web_navigation" and "web_navigation" in detected_caps:
                continue
            if any(kw in query_norm for kw in keywords):
                detected_caps.append(cap)

        # Disambiguation: Distinguish application launches from website navigation
        if "web_navigation" in detected_caps and "application_launch" in detected_caps:
            if any(re.search(rf"\b{re.escape(app)}\b", query_norm) for app in DEFAULT_APP_NAMES):
                detected_caps.remove("web_navigation")
            else:
                detected_caps.remove("application_launch")

        # Disambiguation: Distinguish folder opening from website navigation
        if "web_navigation" in detected_caps and "folder_access" in detected_caps:
            if any(re.search(rf"\b{re.escape(fld)}\b", query_norm) for fld in DEFAULT_FOLDER_NAMES):
                detected_caps.remove("web_navigation")
            else:
                detected_caps.remove("folder_access")

        # Prioritize website navigation for single-intent website directives
        if "web_navigation" in detected_caps and len(detected_caps) > 1:
            if is_website_navigation_query(user_query):
                if not any(sep in query_norm for sep in (" and ", " & ", " then ", " also ")):
                    detected_caps = ["web_navigation"]

        # Refinement: If action dispatch is requested without explicit discovery terms,
        # prioritize action dispatch over general discovery
        if "gadget_action_dispatch" in detected_caps and "device_discovery" in detected_caps:
            if not any(term in query_norm for term in ["discover", "find", "list", "scan", "check all"]):
                detected_caps.remove("device_discovery")

        # Refinement: If system hardware telemetry is requested, distinguish system RAM from cognitive memory
        if "system_telemetry" in detected_caps and "memory_query" in detected_caps:
            if not any(term in query_norm for term in ["remember", "profile", "preference", "notes", "stored", "recall"]):
                detected_caps.remove("memory_query")

        # Disambiguate / refine multi-intent combinations
        # Example: "Check my smart devices and summarize which ones have been offline recently"
        # -> device_discovery (Muse) + memory_query (Hermes)
        if ("device" in query_norm or "devices" in query_norm or "smart" in query_norm) and (
            "offline" in query_norm or "history" in query_norm or "recently" in query_norm or "remember" in query_norm
        ):
            if "device_discovery" not in detected_caps:
                detected_caps.append("device_discovery")
            if "memory_query" not in detected_caps:
                detected_caps.append("memory_query")

        # Fallback if no specific keyword matched
        if not detected_caps:
            # Check general questions
            if query_norm.startswith(("what", "who", "where", "when", "how", "why", "can you", "tell me")):
                primary = "general_knowledge"
            else:
                primary = "unsupported"
            return IntentClassification(
                raw_query=user_query,
                primary_intent=primary,
                required_capabilities=[],
                is_ambiguous=False,
                confidence=0.5,
            )

        # Primary intent determination
        if len(detected_caps) > 1:
            primary = "multi_integration"
        else:
            primary = detected_caps[0]

        return IntentClassification(
            raw_query=user_query,
            primary_intent=primary,
            required_capabilities=detected_caps,
            is_ambiguous=False,
            confidence=0.9,
        )

"""NEXUS Desktop UI Server and API Backend.

Serves the unified desktop interface and provides REST/JSON endpoints for chat,
voice recording, text-to-speech, capability routing, and interactive permission approvals.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_from_directory

from nexus.config import NexusConfig
from nexus.core.session import SessionManager
from nexus.integrations.base import IntegrationStatus
from nexus.integrations.hermes.adapter import HermesAdapter
from nexus.integrations.local_system.adapter import LocalSystemAdapter
from nexus.integrations.manager import IntegrationManager
from nexus.integrations.muse.adapter import MuseAdapter
from nexus.integrations.openclaw.adapter import OpenClawAdapter
from nexus.model.ollama_client import OllamaChatClient
from nexus.orchestrator import NexusOrchestrator
from nexus.routing.router import CapabilityRouter
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import (
    PermissionLevel,
    PermissionManager,
    ToolApprovalDecision,
    ToolApprovalRequest,
)
from nexus.tools.registry import ToolRegistry
from nexus.voice.stt import SpeechToTextEngine
from nexus.voice.tts import TextToSpeechEngine

logger = logging.getLogger("nexus.ui.app")

# Global interactive approval event & response holder for web UI
_pending_approvals: Dict[str, Dict[str, Any]] = {}
_approval_events: Dict[str, threading.Event] = {}
_approval_decisions: Dict[str, ToolApprovalDecision] = {}
_processed_turns: Dict[str, Dict[str, Any]] = {}
_processed_turns_lock = threading.Lock()


def interactive_web_approval_callback(req: ToolApprovalRequest) -> ToolApprovalDecision:
    """Approval callback that blocks until user confirms or denies via UI."""
    request_id = req.execution_id
    event = threading.Event()
    _approval_events[request_id] = event
    _pending_approvals[request_id] = {
        "execution_id": req.execution_id,
        "tool_name": req.tool_name,
        "arguments": req.arguments,
        "permission_level": req.permission_level.value,
        "source": req.source,
        "requested_at": getattr(req, "timestamp", ""),
    }

    logger.info("Awaiting user approval for action '%s' (req_id=%s)", req.tool_name, request_id)
    # Wait up to 30 seconds for user approval from UI
    event_set = event.wait(timeout=30.0)

    # Cleanup
    if request_id in _pending_approvals:
        del _pending_approvals[request_id]
    if request_id in _approval_events:
        del _approval_events[request_id]

    if not event_set or request_id not in _approval_decisions:
        return ToolApprovalDecision(
            approved=False,
            decided_by="TIMEOUT_USER_UNRESPONSIVE",
            reason="User confirmation timed out after 30 seconds.",
        )

    decision = _approval_decisions.pop(request_id)
    return decision


def create_app(config: Optional[NexusConfig] = None) -> Flask:
    """Application factory for NEXUS Desktop."""
    template_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"

    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
    )

    # 1. Initialize Core
    cfg = config or NexusConfig.from_json_file(Path("A:/Mixer/nexus/nexus_config.json"))
    registry = ToolRegistry()
    perm_mgr = PermissionManager(
        approval_callback=interactive_web_approval_callback,
        allow_privileged=cfg.allow_privileged_execution,
    )
    exec_engine = ToolExecutionEngine(
        registry=registry,
        permission_manager=perm_mgr,
        default_timeout=cfg.default_tool_timeout,
        redact_patterns=cfg.redact_sensitive_patterns,
    )

    # 2. Initialize Integrations
    int_mgr = IntegrationManager(
        registry=registry,
        permission_manager=perm_mgr,
        execution_engine=exec_engine,
    )
    int_mgr.register_adapter(LocalSystemAdapter())
    int_mgr.register_adapter(OpenClawAdapter(force_simulated=True))
    int_mgr.register_adapter(HermesAdapter())
    int_mgr.register_adapter(MuseAdapter(force_simulated=True))

    # 3. Initialize Router & Sessions
    router = CapabilityRouter(
        registry=registry,
        manager=int_mgr,
        execution_engine=exec_engine,
    )
    session_mgr = SessionManager()

    # 4. Initialize Voice Engines
    stt_engine = SpeechToTextEngine()
    tts_engine = TextToSpeechEngine()

    # 5. Initialize Orchestrator
    orchestrator = NexusOrchestrator(
        config=cfg,
        registry=registry,
        permission_manager=perm_mgr,
        execution_engine=exec_engine,
        integration_manager=int_mgr,
        router=router,
    )

    # Attach instances to app context
    app.nexus_config = cfg
    app.registry = registry
    app.permission_manager = perm_mgr
    app.integration_manager = int_mgr
    app.router = router
    app.session_manager = session_mgr
    app.stt_engine = stt_engine
    app.tts_engine = tts_engine
    app.orchestrator = orchestrator

    # -------------------------------------------------------------------------
    # UI Web Routes & Anti-Caching Headers
    # -------------------------------------------------------------------------

    @app.after_request
    def set_cache_headers(response):
        """Prevent browser from serving stale cached HTML, CSS, or JS during live interaction."""
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
        return response

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            str(static_dir),
            "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
        )

    # -------------------------------------------------------------------------
    # REST API Routes
    # -------------------------------------------------------------------------

    @app.route("/api/status", methods=["GET"])
    def get_status():
        """Retrieve system status, registered adapters, and tool counts with honest verification states."""
        adapters = int_mgr.list_adapters()
        for a in adapters:
            raw_st = a.get("status", "UNINITIALIZED")
            # Map into honest status labels: LIVE, SIMULATED, UNAVAILABLE, ERROR
            if a.get("name") == "local_system" and raw_st == "CONNECTED":
                a["display_state"] = "LIVE"
            elif raw_st == "CONNECTED":
                # For openclaw/hermes, check if live probe truly succeeded
                mode = a.get("health_details", {}).get("mode", "")
                if "simulated" in mode:
                    a["display_state"] = "SIMULATED"
                else:
                    a["display_state"] = "LIVE"
            elif raw_st in ("SIMULATED", "DEGRADED"):
                a["display_state"] = "SIMULATED"
            elif raw_st in ("DISCONNECTED", "UNINITIALIZED"):
                a["display_state"] = "UNAVAILABLE"
            else:
                a["display_state"] = "ERROR"

        # Determine capability-level statuses
        openclaw_adapter = int_mgr.get_adapter("openclaw")
        openclaw_gw_status = "SIMULATED"
        if openclaw_adapter:
            h = openclaw_adapter.metadata.health_details or {}
            if h.get("mode") == "live_gateway":
                openclaw_gw_status = "LIVE"
            elif openclaw_adapter.metadata.status == IntegrationStatus.DISCONNECTED:
                openclaw_gw_status = "UNAVAILABLE"

        capabilities = [
            {
                "id": "local_system",
                "name": "Local System Operations",
                "integration": "Local OS",
                "status": "LIVE",
                "description": "Browser navigation, allowlisted applications, system time & psutil telemetry",
            },
            {
                "id": "hermes_skills",
                "name": "Hermes Skill Discovery",
                "integration": "Hermes",
                "status": "LIVE",
                "description": "AST audit & skill catalog directly from hermes-agent-main",
            },
            {
                "id": "hermes_memory",
                "name": "Hermes Memory",
                "integration": "Hermes",
                "status": "SIMULATED",
                "description": "Simulated profile & preference memory retrieval",
            },
            {
                "id": "hermes_subagent",
                "name": "Hermes Subagents",
                "integration": "Hermes",
                "status": "SIMULATED",
                "description": "Simulated background task delegation",
            },
            {
                "id": "muse_catalog",
                "name": "Muse Skill Catalog",
                "integration": "Muse",
                "status": "LIVE",
                "description": "Specs and manifests directly from muse-gadget-sdk-main",
            },
            {
                "id": "muse_device_control",
                "name": "Muse Device Control",
                "integration": "Muse",
                "status": "UNAVAILABLE",
                "description": "Physical IoT transport disconnected; real hardware offline",
            },
            {
                "id": "openclaw_gateway",
                "name": "OpenClaw Gateway",
                "integration": "OpenClaw",
                "status": openclaw_gw_status,
                "description": "Gateway RPC & multi-channel messaging",
            },
        ]

        tools = registry.list_tools()
        active_sess = session_mgr.get_active_session()
        mic_ok, mic_msg = stt_engine.check_microphone()

        return jsonify({
            "status": "ONLINE",
            "model": cfg.model_name,
            "ollama_endpoint": cfg.ollama_endpoint,
            "active_session_id": active_sess.session_id,
            "adapters": adapters,
            "capabilities": capabilities,
            "tools_count": len(tools),
            "tools": [t.name for t in tools],
            "voice": {
                "active_input_path": "browser_web_speech",
                "stt_available": True,
                "tts_available": tts_engine.is_available(),
                "browser_speech_supported": True,
                "backend_pyaudio_available": mic_ok,
                "microphone_status": "Browser Web Speech API active (Client audio capture)",
            },
            "pending_approvals": list(_pending_approvals.values()),
        })

    @app.route("/api/sessions", methods=["GET", "POST"])
    def handle_sessions():
        """List sessions or create a new session."""
        if request.method == "POST":
            data = request.get_json() or {}
            title = data.get("title")
            sess = session_mgr.create_session(title=title)
            return jsonify({
                "status": "CREATED",
                "session": {
                    "session_id": sess.session_id,
                    "title": sess.title,
                    "created_at": sess.created_at,
                },
            })

        return jsonify({
            "sessions": session_mgr.list_sessions(),
            "active_session_id": session_mgr.get_active_session().session_id,
        })

    @app.route("/api/sessions/<session_id>/select", methods=["POST"])
    def select_session(session_id):
        """Switch active conversation session."""
        ok = session_mgr.set_active_session(session_id)
        if not ok:
            return jsonify({"error": "Session not found"}), 404
        sess = session_mgr.get_active_session()
        return jsonify({
            "status": "SWITCHED",
            "session_id": sess.session_id,
            "messages": [m.to_dict() for m in sess.messages],
        })

    @app.route("/api/chat", methods=["POST"])
    def chat_turn():
        """Process an incoming user message through intelligent routing and execution."""
        data = request.get_json() or {}
        user_text = data.get("message", "").strip()
        request_id = data.get("request_id") or f"req_{uuid.uuid4().hex[:12]}"
        voice_session_id = data.get("voice_session_id")

        if not user_text:
            return jsonify({"error": "Message text cannot be empty"}), 400

        # Turn-level deduplication: Return cached turn outcome if identical request_id arrives
        with _processed_turns_lock:
            if request_id in _processed_turns:
                logger.info("[NEXUS Chat Deduplication] Retransmitting cached response for request_id=%s", request_id)
                return jsonify(_processed_turns[request_id])

        sess = session_mgr.get_active_session()
        sess.add_message(role="user", content=user_text)

        activity_events: List[str] = []

        def capture_activity(act: str):
            activity_events.append(act)

        # Execute turn via orchestrator with capability routing
        turn_result = orchestrator.route_and_run(
            user_prompt=user_text,
            conversation_history=sess.get_context_messages(),
            activity_callback=capture_activity,
        )

        tool_calls_names = [c.name for c in turn_result.tool_calls_executed]
        tool_results_info = [
            {
                "execution_id": r.execution_id,
                "tool_name": r.tool_name,
                "dispatch_status": r.data.get("status") if r.data else (r.error.code if r.error else "SUCCESS"),
            }
            for r in turn_result.tool_results
        ]

        logger.info(
            "[NEXUS Turn Debug] request_id=%s voice_session_id=%s final_transcript=%r tool_calls_count=%d tool_invocations=%r",
            request_id,
            voice_session_id,
            user_text,
            len(tool_calls_names),
            tool_results_info,
        )

        # Record assistant reply in session
        sess.add_message(
            role="assistant",
            content=turn_result.final_response,
            metadata={
                "has_simulated_data": turn_result.has_simulated_data,
                "tool_calls": tool_calls_names,
                "activity_log": turn_result.activity_log or activity_events,
                "request_id": request_id,
                "voice_session_id": voice_session_id,
            },
        )

        resp_payload = {
            "status": "SUCCESS",
            "request_id": request_id,
            "voice_session_id": voice_session_id,
            "response": turn_result.final_response,
            "has_simulated_data": turn_result.has_simulated_data,
            "tool_calls_executed": tool_calls_names,
            "tool_invocations": tool_results_info,
            "rounds": turn_result.rounds,
            "activity_log": turn_result.activity_log or activity_events,
            "session_id": sess.session_id,
        }

        with _processed_turns_lock:
            if len(_processed_turns) > 100:
                oldest_key = next(iter(_processed_turns))
                del _processed_turns[oldest_key]
            _processed_turns[request_id] = resp_payload

        return jsonify(resp_payload)

    @app.route("/api/voice/transcribe", methods=["POST"])
    def transcribe_audio():
        """Transcribe uploaded audio file/blob from microphone."""
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        audio_file = request.files["audio"]
        audio_bytes = audio_file.read()

        ok, text = stt_engine.transcribe_audio_bytes(audio_bytes)
        if not ok:
            return jsonify({"status": "FAILED", "error": text}), 400

        return jsonify({"status": "SUCCESS", "text": text})

    @app.route("/api/voice/speak", methods=["POST"])
    def speak_text():
        """Speak response text using Text-to-Speech."""
        data = request.get_json() or {}
        text = data.get("text", "").strip()
        if not text:
            return jsonify({"error": "No text provided"}), 400

        success = tts_engine.speak(text, async_mode=True)
        return jsonify({"status": "SPEAKING" if success else "FALLBACK", "text": text})

    @app.route("/api/voice/stop", methods=["POST"])
    def stop_speaking():
        """Interrupt and stop current speech output."""
        tts_engine.stop()
        return jsonify({"status": "STOPPED"})

    @app.route("/api/permission/decision", methods=["POST"])
    def submit_permission_decision():
        """Submit user approval or denial for a pending tool confirmation."""
        data = request.get_json() or {}
        request_id = data.get("execution_id") or data.get("request_id")
        approved = bool(data.get("approved", False))
        reason = data.get("reason", "Interactive user confirmation via NEXUS UI")

        if not request_id or request_id not in _approval_events:
            return jsonify({"error": "Invalid or expired execution ID"}), 404

        _approval_decisions[request_id] = ToolApprovalDecision(
            approved=approved,
            decided_by="INTERACTIVE_WEB_USER",
            reason=reason,
        )
        _approval_events[request_id].set()

        return jsonify({"status": "DECISION_RECORDED", "approved": approved})

    return app


if __name__ == "__main__":
    app = create_app()
    print("=" * 70)
    print("NEXUS DESKTOP INTERFACE SERVER")
    print("Access the interface at: http://localhost:5000")
    print("=" * 70)
    app.run(host="127.0.0.1", port=5000, debug=False)


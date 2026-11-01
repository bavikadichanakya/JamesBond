/**
 * NEXUS // J.A.R.V.I.S. Client Controller
 * Reactive Kinetic Orb, Robust Speech IO, Deduplicated Messaging & Tactical HUD
 */

let activeSessionId = null;
let isRecording = false;
let isSubmittingTurn = false;
let currentVoiceSession = null;
let mediaRecorder = null;
let audioChunks = [];
let speechRecognizer = null;
let pendingApprovalResolver = null;

document.addEventListener("DOMContentLoaded", () => {
  initSystem();
  setupEventListeners();
  initSpeechRecognition();
  setOrbState("idle");
});

// -----------------------------------------------------------------------------
// System Initialization & Honest Status Telemetry
// -----------------------------------------------------------------------------

async function initSystem() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    console.log("[NEXUS System Status]", data);

    // Update Voice Status Pill based on actual client recognition path
    const voiceStatusText = document.getElementById("voiceStatusText");
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (voiceStatusText) {
      if (SpeechRecognition) {
        voiceStatusText.textContent = "VOICE READY (Web Speech)";
        voiceStatusText.title = "Client Web Speech API active for high-accuracy local transcription";
      } else if (data.voice && data.voice.stt_available) {
        voiceStatusText.textContent = "AUDIO UPLOAD READY";
        voiceStatusText.title = "Server audio upload fallback active";
      } else {
        voiceStatusText.textContent = "VOICE INPUT DISABLED";
      }
    }

    // Update Honest Capability Badges
    const statusContainer = document.getElementById("adapterStatusList");
    const items = data.capabilities || data.adapters;
    if (statusContainer && items) {
      statusContainer.innerHTML = "";
      items.forEach(item => {
        const row = document.createElement("div");
        row.className = "subsystem-row";

        const nameSpan = document.createElement("span");
        nameSpan.className = "subsystem-name";
        nameSpan.textContent = item.name || "Capability";
        if (item.description) {
          nameSpan.title = item.description;
        }

        const badge = document.createElement("span");
        const state = (item.status || item.display_state || "UNAVAILABLE").toUpperCase();
        badge.textContent = state;

        if (state === "LIVE") {
          badge.className = "status-badge badge-live";
        } else if (state === "SIMULATED") {
          badge.className = "status-badge badge-simulated";
        } else if (state === "ERROR") {
          badge.className = "status-badge badge-error";
        } else {
          badge.className = "status-badge badge-unavailable";
        }

        row.appendChild(nameSpan);
        row.appendChild(badge);
        statusContainer.appendChild(row);
      });
    }

    loadSessions();
  } catch (err) {
    console.error("Failed to connect to NEXUS server:", err);
    setOrbState("error");
  }
}

function setupEventListeners() {
  const btnSend = document.getElementById("btnSend");
  const txtPrompt = document.getElementById("txtPrompt");
  const btnMic = document.getElementById("btnMic");
  const btnNewChat = document.getElementById("btnNewChat");
  const btnStopSpeaking = document.getElementById("btnStopSpeaking");
  const jarvisOrb = document.getElementById("jarvisOrb");

  btnSend.addEventListener("click", () => handleSendMessage());
  txtPrompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  });

  // Attach microphone toggles once
  btnMic.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleVoiceRecording();
  });

  if (jarvisOrb) {
    jarvisOrb.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleVoiceRecording();
    });
  }

  btnNewChat.addEventListener("click", createNewSession);
  btnStopSpeaking.addEventListener("click", stopSpeaking);

  // Approval modal buttons
  const btnApprove = document.getElementById("btnApproveAction");
  const btnDeny = document.getElementById("btnDenyAction");
  if (btnApprove && btnDeny) {
    btnApprove.addEventListener("click", () => resolveApproval(true));
    btnDeny.addEventListener("click", () => resolveApproval(false));
  }
}

// -----------------------------------------------------------------------------
// Kinetic Reactive Orb State Machine
// -----------------------------------------------------------------------------

function setOrbState(state) {
  const orb = document.getElementById("jarvisOrb");
  const label = document.getElementById("orbStateLabel");
  const subtext = document.getElementById("orbSubtext");
  if (!orb) return;

  // Clear previous state classes
  orb.classList.remove("state-idle", "state-listening", "state-processing", "state-speaking", "state-error");
  orb.classList.add(`state-${state}`);

  switch (state) {
    case "listening":
      if (label) label.textContent = "AUDIO STREAM ACTIVE // LISTENING";
      if (subtext) subtext.textContent = "Speak clearly into your microphone...";
      break;
    case "processing":
      if (label) label.textContent = "COGNITIVE SYNAPSE // PROCESSING";
      if (subtext) subtext.textContent = "Analyzing directive & routing capabilities...";
      break;
    case "speaking":
      if (label) label.textContent = "TRANSMITTING RESPONSE // SPEAKING";
      if (subtext) subtext.textContent = "Synthesizing vocal response...";
      break;
    case "error":
      if (label) label.textContent = "SECURITY ALERT // MALFUNCTION";
      if (subtext) subtext.textContent = "Directive rejected or communication failed.";
      break;
    case "idle":
    default:
      if (label) label.textContent = "STANDBY // READY";
      if (subtext) subtext.textContent = "Click the orb or press microphone to speak";
      break;
  }
}

// -----------------------------------------------------------------------------
// Deduplicated Chat & Messaging Engine
// -----------------------------------------------------------------------------

async function handleSendMessage(textOverride = null, options = {}) {
  const txtPrompt = document.getElementById("txtPrompt");
  const messageText = (textOverride !== null ? textOverride : txtPrompt.value).trim();
  if (!messageText) return;

  // Prevent multiple simultaneous submissions from one microphone session or rapid clicks
  if (isSubmittingTurn) {
    console.warn("[NEXUS Debug] Turn submission currently in progress; duplicate trigger ignored.");
    return;
  }

  isSubmittingTurn = true;
  if (textOverride === null) txtPrompt.value = "";

  // Unique Request ID for every distinct user turn
  const requestId = "req_" + Date.now() + "_" + Math.random().toString(36).substring(2, 8);
  const voiceSessionId = options.voiceSessionId || null;

  console.log(`[NEXUS Turn Debug] >>> SUBMITTING TURN:`, {
    requestId: requestId,
    voiceSessionId: voiceSessionId,
    message: messageText,
  });

  appendMessage("user", messageText);
  setOrbState("processing");
  showActivity("Analyzing directive with local neural engine...");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: messageText,
        request_id: requestId,
        voice_session_id: voiceSessionId,
      }),
    });

    const data = await res.json();
    hideActivity();

    console.log(`[NEXUS Turn Debug] <<< RECEIVED RESPONSE for requestId=${requestId}:`, {
      status: data.status,
      toolCallsCount: data.tool_calls_executed ? data.tool_calls_executed.length : 0,
      tools: data.tool_calls_executed,
      toolInvocations: data.tool_invocations,
    });

    if (data.status === "SUCCESS") {
      appendMessage("assistant", data.response, {
        simulated: data.has_simulated_data,
        tools: data.tool_calls_executed,
      });

      // Vocalize response
      speakResponse(data.response);
    } else {
      setOrbState("error");
      appendMessage("assistant", `Error: ${data.error || "Execution failed"}`);
      setTimeout(() => setOrbState("idle"), 3000);
    }
  } catch (err) {
    hideActivity();
    setOrbState("error");
    appendMessage("assistant", `System fault: ${err.message}`);
    setTimeout(() => setOrbState("idle"), 3000);
  } finally {
    isSubmittingTurn = false;
  }
}

function sendQuickPrompt(promptText) {
  handleSendMessage(promptText);
}

function appendMessage(role, content, meta = {}) {
  const container = document.getElementById("chatContainer");
  const welcome = container.querySelector(".welcome-hud-card");
  if (welcome) welcome.remove();

  const row = document.createElement("div");
  row.className = `message-row ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = content;
  row.appendChild(bubble);

  // Metadata tags
  if (meta.simulated || (meta.tools && meta.tools.length > 0)) {
    const metaDiv = document.createElement("div");
    metaDiv.className = "message-meta";

    if (meta.simulated) {
      const simTag = document.createElement("span");
      simTag.className = "simulated-tag";
      simTag.textContent = "SIMULATED";
      metaDiv.appendChild(simTag);
    }

    if (meta.tools && meta.tools.length > 0) {
      const toolTag = document.createElement("span");
      toolTag.className = "tool-tag";
      toolTag.textContent = `[Via: ${meta.tools.join(", ")}]`;
      metaDiv.appendChild(toolTag);
    }

    row.appendChild(metaDiv);
  }

  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

// -----------------------------------------------------------------------------
// Real-Time Activity Banner
// -----------------------------------------------------------------------------

function showActivity(text) {
  const banner = document.getElementById("activityBanner");
  const label = document.getElementById("activityText");
  if (label) label.textContent = text;
  if (banner) banner.style.display = "flex";
}

function updateActivity(text) {
  const label = document.getElementById("activityText");
  if (label) label.textContent = text;
}

function hideActivity() {
  const banner = document.getElementById("activityBanner");
  if (banner) banner.style.display = "none";
}

// -----------------------------------------------------------------------------
// Voice Subsystem: Clean Session Buffer & Deduplicated Recognition
// -----------------------------------------------------------------------------

function createFreshVoiceSession() {
  return {
    sessionId: "voice_sess_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
    finalTranscriptBuffer: "",
    submitted: false,
    startedAt: Date.now(),
  };
}

function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.log("[NEXUS Voice Debug] Web Speech API not supported natively in this browser.");
    return;
  }
}

function toggleVoiceRecording() {
  if (isRecording) {
    stopRecording();
  } else {
    startRecording();
  }
}

function startRecording() {
  if (isRecording) {
    console.log("[NEXUS Voice Debug] Recording already in progress; ignoring duplicate start.");
    return;
  }

  // 1. Create a fresh transcript buffer for this recognition session
  currentVoiceSession = createFreshVoiceSession();
  const sessionRef = currentVoiceSession;
  console.log(`[NEXUS Voice Debug] Initialized new recognition session: ${sessionRef.sessionId}`);

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    // Re-instantiate recognition engine fresh per session to prevent any state leakage
    if (speechRecognizer) {
      try { speechRecognizer.abort(); } catch(e) {}
    }

    speechRecognizer = new SpeechRecognition();
    speechRecognizer.continuous = false;
    speechRecognizer.interimResults = false; // Strictly final results to avoid interim duplication
    speechRecognizer.maxAlternatives = 1;
    speechRecognizer.lang = "en-US";

    speechRecognizer.onstart = () => {
      isRecording = true;
      updateMicUI(true);
      setOrbState("listening");
      showActivity("Awaiting vocal directive...");
      console.log(`[NEXUS Voice Debug] [${sessionRef.sessionId}] Speech recognition active.`);
    };

    speechRecognizer.onresult = (event) => {
      // 5. Prevent multiple simultaneous submissions from one microphone session
      if (sessionRef.submitted) {
        console.log(`[NEXUS Voice Debug] [${sessionRef.sessionId}] Already submitted, skipping late result.`);
        return;
      }

      // 2 & 3. Accumulate final recognition segments only once
      let capturedTranscript = "";
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const res = event.results[i];
        if (res.isFinal) {
          const phrase = res[0].transcript.trim();
          if (phrase) {
            capturedTranscript = phrase;
          }
        }
      }

      // Fallback for browsers returning single final array without explicit isFinal flag
      if (!capturedTranscript && event.results.length > 0 && event.results[0].length > 0) {
        capturedTranscript = event.results[0][0].transcript.trim();
      }

      if (capturedTranscript) {
        sessionRef.finalTranscriptBuffer = capturedTranscript;
        console.log(`[NEXUS Voice Debug] [${sessionRef.sessionId}] Final Transcript: "${capturedTranscript}"`);

        // 4. Submit recognized command exactly once
        sessionRef.submitted = true;
        stopRecording();
        handleSendMessage(capturedTranscript, { voiceSessionId: sessionRef.sessionId });
      }
    };

    speechRecognizer.onerror = (event) => {
      console.warn(`[NEXUS Voice Debug] [${sessionRef.sessionId}] Speech recognition error:`, event.error);
      hideActivity();
      updateMicUI(false);
      isRecording = false;
      setOrbState("error");
      setTimeout(() => setOrbState("idle"), 2000);
    };

    speechRecognizer.onend = () => {
      console.log(`[NEXUS Voice Debug] [${sessionRef.sessionId}] Recognition session ended.`);
      isRecording = false;
      updateMicUI(false);

      // If speech ended with buffer ready but onresult did not trigger submission
      if (!sessionRef.submitted && sessionRef.finalTranscriptBuffer) {
        sessionRef.submitted = true;
        handleSendMessage(sessionRef.finalTranscriptBuffer, { voiceSessionId: sessionRef.sessionId });
      } else if (!sessionRef.submitted) {
        setOrbState("idle");
        hideActivity();
      }
    };

    try {
      speechRecognizer.start();
      return;
    } catch (e) {
      console.warn("Web Speech start failed, falling back to MediaRecorder", e);
    }
  }

  // Fallback: MediaRecorder audio capture
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert("Audio input device is not supported in this environment.");
    return;
  }

  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
      mediaRecorder.onstop = () => uploadAudioForTranscription(sessionRef);
      mediaRecorder.start();
      isRecording = true;
      updateMicUI(true);
      setOrbState("listening");
      showActivity("Listening to vocal frequency...");
    })
    .catch(err => {
      alert("Microphone permission denied: " + err.message);
      setOrbState("error");
      setTimeout(() => setOrbState("idle"), 2000);
      isRecording = false;
    });
}

function stopRecording() {
  if (speechRecognizer) {
    try { speechRecognizer.stop(); } catch(e) {}
  }
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  isRecording = false;
  updateMicUI(false);
  setOrbState("processing");
}

function updateMicUI(recording) {
  const btnMic = document.getElementById("btnMic");
  if (btnMic) {
    if (recording) btnMic.classList.add("recording");
    else btnMic.classList.remove("recording");
  }
}

async function uploadAudioForTranscription(sessionRef) {
  hideActivity();
  const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.wav");

  showActivity("Transcribing acoustic pattern...");
  try {
    const res = await fetch("/api/voice/transcribe", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    hideActivity();

    if (data.status === "SUCCESS" && data.text) {
      if (sessionRef && !sessionRef.submitted) {
        sessionRef.submitted = true;
        handleSendMessage(data.text, { voiceSessionId: sessionRef.sessionId });
      }
    } else {
      setOrbState("idle");
      appendMessage("assistant", "Could not transcribe audio. Please enter text directive.");
    }
  } catch (e) {
    hideActivity();
    setOrbState("idle");
    console.error("Audio upload error:", e);
  }
}

function speakResponse(text) {
  const cleanText = text.replace(/[*_#`]/g, "").replace(/\n/g, " ");
  const banner = document.getElementById("speakingBanner");
  if (banner) banner.style.display = "flex";

  setOrbState("speaking");

  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 1.05;
    utterance.pitch = 0.95;
    utterance.onend = () => {
      if (banner) banner.style.display = "none";
      setOrbState("idle");
    };
    utterance.onerror = () => {
      if (banner) banner.style.display = "none";
      setOrbState("idle");
    };
    window.speechSynthesis.speak(utterance);
  } else {
    // SAPI trigger fallback
    fetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: cleanText }),
    })
      .then(() => setTimeout(() => {
        if (banner) banner.style.display = "none";
        setOrbState("idle");
      }, 3000))
      .catch(e => {
        console.warn(e);
        if (banner) banner.style.display = "none";
        setOrbState("idle");
      });
  }
}

function stopSpeaking() {
  const banner = document.getElementById("speakingBanner");
  if (banner) banner.style.display = "none";
  setOrbState("idle");

  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
  fetch("/api/voice/stop", { method: "POST" }).catch(e => console.warn(e));
}

// -----------------------------------------------------------------------------
// Tactical Confirmation Modal
// -----------------------------------------------------------------------------

let activeApprovalExecutionId = null;

async function checkPendingApprovals() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    const pending = data.pending_approvals || [];
    const modal = document.getElementById("approvalModal");
    if (pending.length > 0) {
      const appReq = pending[0];
      activeApprovalExecutionId = appReq.execution_id;
      const nameEl = document.getElementById("modalToolName");
      const argsEl = document.getElementById("modalArgs");
      if (nameEl) nameEl.textContent = appReq.tool_name;
      if (argsEl) argsEl.textContent = JSON.stringify(appReq.arguments || {}, null, 2);
      if (modal && modal.style.display === "none") {
        modal.style.display = "flex";
      }
    } else if (modal && modal.style.display !== "none" && !pendingApprovalResolver) {
      modal.style.display = "none";
      activeApprovalExecutionId = null;
    }
  } catch (e) {
    // Non-blocking telemetry poll
  }
}

setInterval(checkPendingApprovals, 600);

function requestUserApproval(toolName, args) {
  return new Promise((resolve) => {
    const modal = document.getElementById("approvalModal");
    const nameEl = document.getElementById("modalToolName");
    const argsEl = document.getElementById("modalArgs");

    if (nameEl) nameEl.textContent = toolName;
    if (argsEl) argsEl.textContent = JSON.stringify(args, null, 2);

    if (modal) modal.style.display = "flex";
    pendingApprovalResolver = resolve;
  });
}

async function resolveApproval(isApproved) {
  const modal = document.getElementById("approvalModal");
  if (modal) modal.style.display = "none";

  if (activeApprovalExecutionId) {
    const execId = activeApprovalExecutionId;
    activeApprovalExecutionId = null;
    try {
      await fetch("/api/permission/decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          execution_id: execId,
          approved: isApproved,
        }),
      });
    } catch (e) {
      console.error("Failed to submit approval decision:", e);
    }
  }

  if (pendingApprovalResolver) {
    pendingApprovalResolver(isApproved);
    pendingApprovalResolver = null;
  }
}

// -----------------------------------------------------------------------------
// Sessions Management
// -----------------------------------------------------------------------------

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    const data = await res.json();
    const list = document.getElementById("sessionList");
    if (!list) return;
    list.innerHTML = "";

    data.sessions.forEach(s => {
      const item = document.createElement("div");
      item.className = `session-item ${s.is_active ? "active" : ""}`;
      item.textContent = s.title;
      item.addEventListener("click", () => switchSession(s.session_id));
      list.appendChild(item);
    });

    activeSessionId = data.active_session_id;
  } catch (e) {
    console.error("Failed to load sessions:", e);
  }
}

async function createNewSession() {
  try {
    const res = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: `Session ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` }),
    });
    const data = await res.json();
    if (data.status === "CREATED") {
      loadSessions();
      location.reload();
    }
  } catch (e) {
    console.error("Failed to create session:", e);
  }
}

async function switchSession(sessionId) {
  try {
    const res = await fetch(`/api/sessions/${sessionId}/select`, { method: "POST" });
    const data = await res.json();
    if (data.status === "SWITCHED") {
      loadSessions();
      const container = document.getElementById("chatContainer");
      container.innerHTML = "";
      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(m => {
          if (m.role === "user" || m.role === "assistant") {
            appendMessage(m.role, m.content, m.metadata);
          }
        });
      }
    }
  } catch (e) {
    console.error("Failed to switch session:", e);
  }
}

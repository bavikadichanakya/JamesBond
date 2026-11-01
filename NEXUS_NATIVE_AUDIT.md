# NEXUS — Phase A: Native Windows Desktop Application Architecture & Feasibility Audit

**Document Version:** 1.0.0  
**Date:** November 1, 2026  
**Status:** Audit & Architecture Specification Complete  
**Target Environment:** Windows 11 / Local Ollama (`qwen2.5-coder:3b`) / Tauri 2 + Python Backend  
**Workspace Root:** `A:\Mixer\`  

---

## 1. Executive Summary & Objective

The objective of this project phase is to transform **NEXUS** from its current browser-based execution model (`http://127.0.0.1:5000` inside Google Chrome) into a genuine, standalone **Native Windows Desktop Application**.

### Guiding Principles:
1. **Preserve Existing Intelligence:** All existing intelligence—including the dedicated 9-stage capability router, central tool registry, AST code auditing, permission manager, session tracking, turn deduplication, and RFC-compliant URL dispatch—remains intact in Python.
2. **Native Windows Shell:** Tauri 2 serves as the desktop shell, providing an independent application window, system tray integration, native Windows notifications, startup options, and window lifecycle management.
3. **No Web Browser Dependency:** The user launches NEXUS like normal Windows desktop software; no manual browser opening or navigation to `localhost:5000` is required.
4. **Localhost Process Supervision:** Tauri manages the local Python backend as a supervised background child process. Closing the application terminates the backend cleanly, unless the user chooses to keep NEXUS running in the system tray.

---

## 2. Comprehensive Workspace & Subsystem Audit

### 2.1 Core Subsystems (`A:\Mixer\nexus\`)

| Subsystem | Primary Module(s) | Operational State | Role in Native Desktop App |
| :--- | :--- | :--- | :--- |
| **Tool Registry & Schema** | `nexus/tools/registry.py`, `schema.py` | **LIVE (Verified)** | Manages 16 tools with typed parameters and JSON schema generation. Preserved in Python. |
| **Permission Governance** | `nexus/tools/permissions.py` | **LIVE (Verified)** | Enforces `READ_ONLY` vs `CONFIRMATION_REQUIRED` policies. Intercepts state-altering actions via interactive UI modals. |
| **Tool Execution Engine** | `nexus/tools/execution.py` | **LIVE (Verified)** | Bounded threadpool execution, timeout enforcement (30s), sensitive pattern redaction, standardized error structures. |
| **Capability Router** | `nexus/routing/router.py`, `classifier.py` | **LIVE (Verified)** | 9-stage capability evaluation, dynamic website intent extraction, brand name normalization, turn-level tool deduplication. |
| **URL Utilities** | `nexus/routing/url_utils.py` | **LIVE (Verified)** | Strict RFC-compliant URL normalization, domain validation, prohibited scheme rejection (`file:`, `javascript:`, `powershell:`). |
| **Response Synthesis** | `nexus/routing/response_manager.py` | **LIVE (Verified)** | Generates unified natural-language responses with transparent simulation disclosures and error provenance. |
| **Model Client** | `nexus/model/ollama_client.py` | **LIVE (Verified)** | Interacts with local Ollama (`qwen2.5-coder:3b` at `http://localhost:11434`). Preserved as single-model runtime. |
| **Session Manager** | `nexus/core/session.py` | **LIVE (Verified)** | Multi-turn conversation tracking, active session switching, disk persistence. |
| **Orchestrator** | `nexus/orchestrator.py` | **LIVE (Verified)** | Coordinates full multi-turn conversational loop, tool rounds, and fallback routing. |
| **Voice Engine** | `nexus/voice/stt.py`, `tts.py` | **LIVE (Verified)** | Offline Windows SAPI `SpVoice` speech synthesis and speech-to-text pipeline. |
| **Desktop UI Server** | `nexus/ui/app.py` | **LIVE (Verified)** | Flask backend serving REST API, interactive approval callback events, turn caching. |

### 2.2 Integration Adapters (`A:\Mixer\nexus\integrations\`)

| Adapter | Capabilities Provided | Mode & Reality State | Status |
| :--- | :--- | :--- | :--- |
| **`local_system`** | `open_website`, `launch_application`, `get_current_time`, `get_system_info`, `open_approved_folder` | **LIVE_VERIFIED** (Windows ShellExecuteW return code 42, psutil hardware telemetry, allowlisted application spawning) | **Connected & Operational** |
| **`openclaw`** | `openclaw_gateway_status`, `openclaw_send_channel_message`, `openclaw_list_extensions` | **SIMULATED** (Gateway transport offline; extensions discovered from disk) | **Operational with Transparency** |
| **`hermes`** | `hermes_list_skills`, `hermes_audit_skill_code`, `hermes_query_memory`, `hermes_run_subagent` | **LIVE_VERIFIED** (Skill discovery & AST audit from on-disk files); **SIMULATED** (Memory store, subagents) | **Operational with Transparency** |
| **`muse`** | `muse_list_supported_skills`, `muse_inspect_device_skill`, `muse_discover_devices`, `muse_invoke_gadget_action` | **LIVE_VERIFIED** (Skill catalog & specs from on-disk manifests); **UNAVAILABLE** (Physical IoT hardware transport disconnected) | **Operational with Transparency** |

---

## 3. Entry Point, Startup & Lifecycle Management

### 3.1 Existing Python Entry Point (`A:\Mixer\launch_nexus.py`)
Currently:
```python
def main():
    app = create_app()
    # Opens default browser automatically
    try:
        webbrowser.open("http://127.0.0.1:5000")
    except Exception:
        pass
    app.run(host="127.0.0.1", port=5000, debug=False)
```

### 3.2 Required Desktop Backend Entry Point (`A:\Mixer\nexus\desktop_backend.py`)
For the native desktop application:
1. **Headless Execution:** Eliminate `webbrowser.open()`. The window is managed entirely by Tauri's WebView2.
2. **Dedicated CLI Arguments:** Accept `--port`, `--host`, `--auth-token`, and `--parent-pid` flags.
3. **Parent Process Heartbeat/Supervisor:** If Tauri crashes or terminates unexpectedly, the Python process detects that its parent PID is dead and terminates automatically within 2 seconds, preventing orphan background processes.
4. **Clean API Shutdown Route (`POST /api/system/shutdown`):** Allows Tauri to gracefully request backend shutdown before exiting.
5. **Readiness Probe (`GET /api/status`):** Tauri polls `http://127.0.0.1:5000/api/status` on startup. Once HTTP 200 is returned, Tauri displays the window.

---

## 4. API Routes & Desktop Communication Contracts

| Route | Method | Purpose | Desktop Integration |
| :--- | :--- | :--- | :--- |
| `GET /api/status` | GET | System telemetry, model health, adapter states | Polled by Tauri on boot for readiness detection; displayed in HUD. |
| `GET /api/sessions` | GET | List saved conversation sessions | Displayed in sidebar navigation. |
| `POST /api/sessions` | POST | Create new conversation session | Triggered by "INITIALIZE NEW SESSION" button. |
| `POST /api/sessions/<id>/select` | POST | Switch active session | Switches buffer view. |
| `POST /api/chat` | POST | Submit text or voice directive | Primary conversation and routing pipeline. |
| `POST /api/permission/decision` | POST | Approve or deny privileged action | Triggered by native/HUD authorization modal. |
| `POST /api/voice/transcribe` | POST | Audio byte transcription fallback | Client audio byte processing. |
| `POST /api/voice/speak` | POST | Trigger Windows SAPI speech synthesis | Invokes Windows host speech engine. |
| `POST /api/voice/stop` | POST | Halt ongoing speech playback | Immediate audio interruption. |
| `POST /api/system/shutdown` | POST | Request clean backend termination | Triggered on Tauri application exit. |

---

## 5. Frontend & WebView2 Compatibility

### 5.1 Frontend Asset Inventory
- **HTML:** `nexus/ui/templates/index.html` (11.1 KB)
- **CSS:** `nexus/ui/static/css/styles.css` (25.6 KB)
- **JavaScript:** `nexus/ui/static/js/app.js` (21.7 KB)
- **Icons:** `nexus/ui/static/favicon.ico` (1.1 KB)

### 5.2 WebView2 Runtime Compatibility
- **Host WebView2 Version:** `156.0.4314.50` (Verified present in Windows 11).
- **Vanilla ES6+ Architecture:** The frontend uses standard DOM APIs, CSS custom variables, and Web APIs (`SpeechRecognition`, `speechSynthesis`, `fetch`), without any external JavaScript framework dependencies (no React, Vue, Angular, or Tailwind CDN).
- **Audio Capture:** Microsoft Edge WebView2 natively supports microphone media capture and speech recognition.
- **Glassmorphic Rendering:** Hardware-accelerated CSS filters (`backdrop-filter: blur()`, glowing borders, kinetic animations) run smoothly on Intel Iris Xe graphics.

---

## 6. Host Toolchain & Dependency Audit

| Tool / Dependency | Version on Host | Location | Status for Tauri 2 |
| :--- | :--- | :--- | :--- |
| **Node.js** | `v24.18.0` | `C:\Program Files\nodejs\node.exe` | **READY** |
| **npm** | `11.16.0` | `C:\Program Files\nodejs\npm.ps1` | **READY** |
| **Python** | `3.14.3` | `C:\Users\bavik\AppData\Local\Python\pythoncore-3.14-64\python.exe` | **READY** |
| **Git** | `2.49.0.windows.1` | `C:\Program Files\Git\cmd\git.exe` | **READY** |
| **WebView2** | `156.0.4314.50` | Windows System Runtime | **READY** |
| **winget** | Windows 11 default | `C:\Users\bavik\AppData\Local\Microsoft\WindowsApps\winget.exe` | **READY** |
| **Rust (`rustc`, `cargo`)** | *Not currently on PATH* | Missing | **REQUIRED FOR TAURI COMPILATION** |
| **MSVC C++ Build Tools** | *vswhere not found* | Missing | **REQUIRED FOR RUST NATIVE LINKING** |

### Toolchain Recommendation:
To build the native Tauri 2 application binary on Windows:
1. Install Rust via `winget install Rustlang.Rustup` or `rustup-init.exe`.
2. Install Microsoft C++ Build Tools via `winget install Microsoft.VisualStudio.2022.BuildTools --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"`.
3. Alternatively, or during intermediate development, run the desktop shell in development mode with `@tauri-apps/cli`.

---

## 7. Proposed Native Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                   NEXUS Native Windows Desktop App                     │
│                        (Tauri 2 / WebView2)                            │
│                                                                        │
│  ┌──────────────────────┐  ┌─────────────────┐  ┌───────────────────┐  │
│  │ Native Windows Shell │  │ System Tray     │  │ Windows Startup   │  │
│  │ • Minimize/Maximize  │  │ • Show / Hide   │  │ • Registry Run    │  │
│  │ • Frameless HUD Title│  │ • Status Pill   │  │   Key (Opt-in)    │  │
│  │ • Window State Save  │  │ • Exit Action   │  │ • Tray Launch     │  │
│  └──────────┬───────────┘  └────────┬────────┘  └───────────────────┘  │
│             │                       │                                  │
│             ▼                       ▼                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                  NEXUS J.A.R.V.I.S. Frontend                     │  │
│  │     (Graphite #05080E | Electric Cyan #00F5FF | Ice Blue)        │  │
│  │                                                                  │  │
│  │  [Tactical Sidebar]  [Kinetic Voice Orb]  [Chat Stream Buffer]   │  │
│  │  [Telemetry HUD]     [Approval Modal]     [Input Controller]     │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
└─────────────────────────────────────┼──────────────────────────────────┘
                                      │ Localhost REST / JSON (127.0.0.1)
                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Managed NEXUS Python Backend                        │
│                   (`nexus/desktop_backend.py`)                         │
│                                                                        │
│  • Process Supervision (Parent PID Heartbeat & Clean Shutdown API)     │
│  • Capability Router & URL Normalizer (RFC-Compliant Scheme Filter)    │
│  • Central Tool Registry (16 Registered Tools across 4 Adapters)       │
│  • Permission Manager (Interactive Confirmation Callbacks)             │
│  • Local System Adapter (ShellExecuteW, Allowlisted App Execution)     │
│  • Ollama Client (Local qwen2.5-coder:3b at http://localhost:11434)    │
│  • Offline Windows SAPI SpVoice TTS Engine                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Native Windows Features Implementation Plan

### 8.1 Native Window & Window State Persistence
- Window title: `NEXUS`
- Min dimensions: `900 x 650` (ideal for JARVIS sidebar and orb layout).
- Default dimensions: `1200 x 800`.
- Position and dimension persistence using `tauri-plugin-window-state`.

### 8.2 System Tray
- Tray icon using NEXUS branded cyan reactor ring icon.
- Context menu:
  - `Show NEXUS`
  - `Hide NEXUS`
  - `Status: Core Ready`
  - `---`
  - `Exit NEXUS`
- Minimize to tray behavior: Closing the main window hides it instead of terminating the process when enabled in preferences.

### 8.3 Windows Startup (Opt-In)
- Managed via `tauri-plugin-autostart` (or Windows Registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- User can toggle "Launch at Windows startup" in settings. Defaults to `false` (strictly opt-in).

### 8.4 Native Notifications
- System tray notifications via `tauri-plugin-notification` for:
  - System authorization required (for `CONFIRMATION_REQUIRED` actions when minimized).
  - Background task completion.
  - Critical subsystem disconnection alerts.

---

## 9. Security, Local-First Operation & Performance

1. **Localhost-Only Binding:** The backend strictly binds to `127.0.0.1`. Remote network interfaces (`0.0.0.0`) are forbidden.
2. **Local AI & Privacy:** The local model (`qwen2.5-coder:3b`) runs on the user's host via Ollama. No prompt data, credentials, or session history are transmitted to any third-party SaaS cloud.
3. **Permission Integrity:** State-altering operations (`launch_application`, `open_approved_folder`, `openclaw_send_channel_message`, `hermes_run_subagent`, `muse_invoke_gadget_action`) require explicit human confirmation. The model is barred from self-approving actions.
4. **Subprocess Isolation:** `shell=False` is strictly enforced across all process execution paths.
5. **Resource Budgeting:** Reuses the existing Ollama instance; total RAM footprint remains ~2.0 GB, perfectly calibrated for the host's 8 GB RAM and Intel Iris Xe graphics.

---

## 10. Implementation Roadmap

- **Phase A (Complete):** Workspace & toolchain audit (`NEXUS_NATIVE_AUDIT.md`).
- **Phase B (Desktop Shell):**
  - Create `nexus/desktop_backend.py` with process supervision and clean shutdown.
  - Set up the Tauri 2 desktop project (`src-tauri/`) with WebView2 integration.
  - Implement backend readiness probing and automatic startup.
- **Phase C (Native Features):**
  - Implement system tray, window minimize-to-tray, and native notifications.
  - Implement opt-in Windows startup integration.
- **Phase D (UI Polish):**
  - Refine JARVIS HUD window controls and responsive sidebar.
  - Verify Web Speech STT and Windows SAPI TTS inside WebView2.
- **Phase E & F (Packaging & Verification):**
  - Build standalone desktop executable and Windows installer.
  - Full end-to-end verification across all 18 lifecycle scenarios.
  - Generate `NEXUS_NATIVE_IMPLEMENTATION_REPORT.md`.


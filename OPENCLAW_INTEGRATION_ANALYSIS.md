# NEXUS Integration Analysis: OpenClaw Architecture & Upstream Reuse

**Project:** OpenClaw (`openclaw-main\openclaw-main`)  
**Version:** `2026.10.9`  
**License:** MIT  
**Analysis Date:** November 1, 2026  
**Auditor:** Senior Software Architect & Repository Analysis Engineer  

---

## 1. Executive Summary

OpenClaw is a modular, multi-channel AI gateway and execution platform written in TypeScript (ESM) targeting Node.js `>=24.16.0`. It acts as a local control plane orchestrating sessions, multi-platform messaging (Discord, Telegram, Slack, WhatsApp, Signal, iMessage, etc.), tool execution with human-in-the-loop approvals, skills, and sandboxed runtimes.

Crucially for NEXUS, OpenClaw **already provides first-class extension hooks and migration layers for both Hermes and Muse**, as well as an extensible Plugin SDK (`packages/plugin-sdk`) and an Agent Client Protocol (`acp-core`, `extensions/acpx`) runtime engine.

This document analyzes OpenClaw's internal architecture from source to determine precisely which components can be reused **without modifying any upstream OpenClaw source code**.

---

## 2. Upstream Component Analysis

### 2.1. `extensions/migrate-hermes` (Existing Hermes Importer)

Located at `openclaw-main\openclaw-main\extensions\migrate-hermes`, this extension implements a complete migration provider that understands Hermes Agent's on-disk configuration, storage, and runtime state.

#### Grounded Source Findings:
- **Discovery Mechanism (`source.ts`):**
  Discovers Hermes installations by inspecting `%LOCALAPPDATA%\hermes`, `~/.hermes`, or custom paths. It detects:
  - Configuration: `config.yaml`, `.env`, `auth.json`, `active_profile`
  - Personas: `SOUL.md`, `AGENTS.md`
  - State Databases: `state.db`, `hermes_state.db`, `projects.db`, `response_store.db`, `memory_store.db`, `kanban.db`
  - Directories: `skills`, `memories`, `plugins`, `sessions`, `cron`, `mcp-tokens`
- **Memory Ingestion (`memory.ts`):**
  Functions `isMemoryOnlyMigration` and `buildHermesMemoryPlan` import Hermes memory files (`MEMORY.md`, `USER.md`) into OpenClaw's indexed storage at `<workspaceDir>/memory/imports/hermes/`.
- **Skill Ingestion (`skills.ts`):**
  Discovers `SKILL.md` skill roots across Hermes org trees (`_org/`), filtering out virtual environments and test caches, mapping them into OpenClaw's skill registry.
- **MCP Configuration Mapping (`config-mcp.ts`):**
  Converts Hermes MCP definitions into OpenClaw plugin configurations, preserving command, arguments, environment variables, timeouts, and TLS client certificates (`mapHermesClientCertificate`).
- **Credential Handling (`secrets.ts`, `auth.ts`):**
  Provides explicit user-consent gated extraction (`includeSecrets`) of API keys and bearer tokens for OpenAI, Anthropic, OpenRouter, and custom endpoints.

#### NEXUS Reuse Assessment:
- **Reuse As-Is:** Can be invoked programmatically or via CLI (`openclaw migrate hermes --dry-run`) during NEXUS bootstrapping to sync Hermes profiles and configurations into OpenClaw without any manual porting.

---

### 2.2. `extensions/muse` (Existing Muse Code Integration)

Located at `openclaw-main\openclaw-main\extensions\muse`, this extension registers an external agent harness backed by Meta's Muse Code CLI (`muse serve`) and `@muse-code/sdk`.

#### Grounded Source Findings:
- **Plugin Registration (`index.ts`):**
  Calls `definePluginEntry` and registers an `AgentHarnessV2` via `api.registerAgentHarness(harness)`.
- **Harness Lifecycle (`harness.ts`):**
  Implements `createMuseAgentHarness`:
  - Maintains session bindings in `msp-sessions` keyed store (`MuseSessionBinding: { sessionId, compatibility }`).
  - Implements `APPROVAL_TIMEOUT_MS = 120_000` for human-in-the-loop tool approvals.
  - Integrates with OpenClaw's `createAgentHarnessAttemptLifecycle` and `emitAgentHarnessAttemptEvent`.
- **Event Streaming (`src/events.ts`):**
  Consumes turn events from the agent process, translating reasoning deltas, tool starts/finishes, and message chunks into OpenClaw session events.
- **Mock/Test Implementation (`src/test-support/fake-muse.mjs`):**
  Provides a standalone Node.js script implementing the JSON-RPC 2.0 stdio protocol used by Muse, emitting `item/started`, `item/delta`, `item/completed`, `toolCall`, and `turn/completed`.

#### NEXUS Reuse Assessment:
- **Reuse Pattern:** Demonstrates the exact pattern NEXUS should follow to register Hermes Agent as an external `AgentHarness` within OpenClaw without touching core files.
- **Mock Utility:** `fake-muse.mjs` provides a template for mocking agent turns in automated integration testing.

---

### 2.3. Gateway Architecture (`src/gateway/`)

The OpenClaw Gateway is the central local control plane.

#### Grounded Source Findings:
- **Role:** Handles incoming message ingress, session dispatching, tool policy enforcement, WebSocket client connections, and Web UI hosting.
- **Multi-Channel Ingress:** Bridges Discord, Slack, Telegram, WhatsApp, Google Chat, Teams, IRC, Signal, and Matrix via unified abstractions in `packages/gateway-protocol`.
- **Session Dispatching:** Resolves routing rules from `src/gateway/` to pair incoming chat threads with dedicated agent sessions.
- **Sandboxing & Permissions:** Enforces host execution boundaries (`packages/net-policy`, `crates/crabbox`), maintaining an audit log of every tool execution.

#### NEXUS Reuse Assessment:
- **Primary Role in NEXUS:** OpenClaw Gateway serves as the **External Communication & Channel Hub**. It handles user identity, messaging channels, and client UIs, freeing Hermes from needing to manage redundant chat protocol drivers.

---

### 2.4. Agent Runtime Architecture & Plugin SDK (`packages/agent-core/`, `packages/plugin-sdk/`)

OpenClaw cleanly separates agent orchestration from agent execution.

#### Grounded Source Findings:
- **Contract Interface (`AgentHarnessV2`):**
  Defined in `packages/plugin-sdk/agent-harness-runtime.ts`. Any external runtime can register as an execution engine if it accepts `AgentHarnessAttemptParamsV2` and emits lifecycle events via `emitAgentHarnessAttemptEvent`.
- **Plugin Lifecycle Hooks (`plugin-entry.ts`):**
  Plugins declare activation modes (`onStartup`, `onDemand`), register tools (`api.registerTool`), register channels, register migrations, and register runtime lifecycles (`api.lifecycle.registerRuntimeLifecycle`).
- **Keyed State Stores (`plugin-state-runtime.ts`):**
  Provides isolated persistent key-value/document storage for plugins with TTL and namespace isolation.

#### NEXUS Reuse Assessment:
- **100% Upstream Unmodified:** A dedicated NEXUS bridge plugin (`@openclaw/nexus-bridge`) can be dropped into `extensions/` or installed via standard `openclaw plugins install`, utilizing official public Plugin SDK APIs.

---

### 2.5. ACP (Agent Client Protocol) Implementation (`packages/acp-core/`, `extensions/acpx/`)

OpenClaw includes built-in support for the Agent Client Protocol.

#### Grounded Source Findings:
- **ACP Core (`packages/acp-core`):**
  Implements typed session identities (`SessionAcpIdentity`), session modes (`AcpSessionRuntimeOptions`: `model`, `thinking`, `cwd`, `runtimeMode`), and provenance tracking (`normalizeAcpProvenanceMode`).
- **ACPX Runtime (`extensions/acpx`):**
  Allows OpenClaw to spawn and manage external coding agents (Copilot, Pi, Qwen, OpenCode, Grok Build) over ACP JSON-RPC streams. OpenClaw owns channels, sessions, and permissions, while the external agent executes the reasoning loop.

#### NEXUS Reuse Assessment:
- **Critical Architectural Link:** Because Hermes Agent *also* implements ACP (`acp_adapter/server.py`), **ACP represents an immediate, zero-modification bridge between OpenClaw and Hermes**.

---

### 2.6. MCP (Model Context Protocol) Implementation

OpenClaw provides bi-directional MCP support:
- **MCP Client (`extensions/mcp-relay`):** Connects to external MCP servers to ingest tools and prompt templates into OpenClaw's catalog.
- **MCP Projection (`packages/plugin-sdk/codex-mcp-projection.d.ts`):** Projects OpenClaw tools as MCP endpoints for external consumption.

#### NEXUS Reuse Assessment:
- Tools exposed by Muse or Hermes can be registered into OpenClaw via standard MCP configurations (`config.yaml`).

---

### 2.7. Model Routing & Session Management

- **Model Routing (`packages/model-catalog-core`, `packages/llm-core`):**
  Maps model strings (`provider/model-id`) to backend providers (OpenAI, Anthropic, Bedrock, Ollama, vLLM, SGLang, local GGUF). Models can be directed to specific agent harnesses by setting `agentRuntime.id`.
- **Session Management (`packages/agent-core`, `packages/plugin-sdk/agent-sessions`):**
  Manages session persistence in SQLite (`state.db`, schema version 38/39), session branching, compaction, transcript history, and ephemeral run IDs.

---

### 2.8. Skill Loading & Device Connectivity

- **Skill Loading (`skills/`, `src/skills/`):**
  Loads directory-based skills containing `SKILL.md` (YAML frontmatter + markdown instructions).
- **Device Connectivity (`apps/`, `extensions/device-pair`):**
  Supports pairing mobile device nodes (iOS, Android) and desktop companion nodes over encrypted WebSocket/Bonjour tunnels to capture audio, screenshots, and camera input.

---

## 3. Summary of Upstream Reusability

| Component | Upstream Reusability | Modification Needed? | NEXUS Role |
| :--- | :--- | :--- | :--- |
| **OpenClaw Gateway** | **100% Reusable As-Is** | None | Primary communication gateway, chat ingress, UI host |
| **Control UI (SolidJS)** | **100% Reusable As-Is** | None | User dashboard, session control, model configuration |
| **Plugin SDK** | **100% Reusable As-Is** | None | Extension host for NEXUS orchestration |
| **`extensions/migrate-hermes`**| **100% Reusable As-Is** | None | Cold-start state/memory synchronization from Hermes |
| **`extensions/acpx` & `acp-core`**| **100% Reusable As-Is** | None | Protocol bridge to Hermes `acp_adapter` |
| **Tool Approval Subsystem** | **100% Reusable As-Is** | None | Interactive human authorization for sensitive tools |
| **Skills Engine** | **100% Reusable As-Is** | None | Hosts common `SKILL.md` library |


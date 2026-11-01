# NEXUS Security Architecture: Cross-Service Hardening & Defense-in-Depth

**Context:** NEXUS Multi-Repository Architecture Evaluation  
**Projects Analyzed:** OpenClaw, Hermes Agent, Muse Gadget SDK  
**Analysis Date:** November 1, 2026  
**Auditor:** Senior Software Architect & Repository Analysis Engineer  

---

## 1. Executive Summary

Combining multi-channel messaging (OpenClaw), an autonomous self-improving agent with shell access (Hermes), and edge device control (Muse) produces a system with significant potential blast radius if improperly configured.

A comprehensive source review reveals robust individual security subsystems across all three repositories:
- OpenClaw enforces strict execution policies (`execPolicy`), paired DM authorization, secret redaction, and container sandboxing (`crabbox`).
- Hermes enforces AST syntax audits on learned skills (`tools/skills_ast_audit.py`), command blacklists, directory ACLs (`hermes_dir_acl.py`), and interactive approval callbacks.
- Muse implements Noise XX mutual cryptographic handshakes and strict account isolation (`executor.py`).

This document defines the **Unified NEXUS Security Architecture**, establishing strict defense-in-depth policies across service authentication, credential storage, network exposure, shell execution, filesystem access, and audit logging.

---

## 2. Threat Modeling & Attack Surface Analysis

```text
Potential Attack Vectors:
1. Inbound Channel Injection: Malicious user inputs via Discord/Telegram trying to prompt-inject Hermes.
2. Tool Hijacking: LLM hallucinating destructive shell commands (`rm -rf`, format, credential exfiltration).
3. Localhost Sniffing: Malicious local apps or web browsers attempting to probe open ports on 127.0.0.1.
4. Credential Leakage: API keys or bearer tokens being printed into transcripts or logs.
5. Skill Poisoning: Learned or imported skills containing malicious Python code.
```

---

## 3. Defense-in-Depth Security Controls

### 3.1. Authentication Between Services

#### Grounded Findings:
- OpenClaw Gateway uses token and password authorization (`gatewayToken`, `gatewayPassword`, or bearer headers) to protect WebSocket and HTTP endpoints.
- Hermes Gateway supports per-session bearer tokens (`auth.py`).
- Muse uses Noise XX mutual authentication where the device and VM exchange cryptographically verified tokens.

#### NEXUS Policy:
1. **Zero Open Ports for Hermes:**
   Hermes does not expose any listening TCP port. It is invoked purely as a **subprocess over standard I/O (stdio)** by OpenClaw's ACP manager. No local network authentication is required because the operating system kernel enforces pipe privacy.
2. **Localhost Loopback Guards for OpenClaw:**
   When OpenClaw Gateway runs, it binds strictly to `127.0.0.1` (never `0.0.0.0` unless explicitly configured for Docker). All HTTP/WS requests require an HMAC-signed bearer token generated at session initialization.
3. **Noise XX for IoT Gadgets:**
   Any external edge gadget (ESP32 or Raspberry Pi) connecting to the NEXUS Virtual Hub must complete the Noise XX handshake with pinned pre-shared keys or developer pairing tokens.

---

### 3.2. API Credential Storage & Secret Redaction

#### Grounded Findings:
- **OpenClaw (`structured-auth-redaction.ts`, `provider-auth-runtime.ts`):**
  Features a runtime redaction engine that automatically intercepts logs, error traces, and transcripts to mask detected API keys, bearer tokens, and private keys.
- **Hermes (`auth.json`, `secrets_*.py`):**
  Stores credentials in `auth.json` (mode `0600` on POSIX; protected user folder `%LOCALAPPDATA%\hermes` on Windows).
- **OpenClaw Hermes Importer (`extensions/migrate-hermes/secrets.ts`):**
  Enforces a mandatory `includeSecrets` consent check before reading any credential from Hermes.

#### NEXUS Policy:
1. **Single Vault Rule:** OpenClaw acts as the primary secrets broker. Hermes receives transient, scoped credentials for each turn via ACP session parameters (`SessionRuntimeOptions`), eliminating duplicate stored secrets.
2. **Redaction Pipeline:** All output streaming from Hermes back to OpenClaw passes through OpenClaw's `structured-auth-redaction` before being persisted to transcripts or rendered on chat channels.

---

### 3.3. Localhost Network Exposure & Web Isolation

#### Risks:
Local web browsers visiting malicious sites can attempt DNS rebinding or CSRF attacks against open `http://localhost:<port>` services.

#### NEXUS Policy:
1. **CORS & Origin Verification:** OpenClaw Gateway enforces strict Origin verification on all incoming WebSocket connections. Connections with non-whitelisted Origin headers are rejected immediately.
2. **CSRF Tokens:** All state-changing Gateway operations require a session-bound CSRF token header (`X-OpenClaw-CSRF`).

---

### 3.4. Shell Execution Permissions & Tool Approval Mechanisms

#### Grounded Findings:
- **Hermes Approval Framework (`acp_adapter/permissions.py`, `tools/terminal_tool.py`):**
  Hermes categorizes tools into safe (read-only) and sensitive (write, execute). Sensitive commands invoke `make_approval_callback`, pausing execution until approved.
- **OpenClaw Approval Framework (`packages/plugin-sdk/exec-approvals-runtime.ts`):**
  Enforces `execPolicy`, supporting interactive approvals in the Control UI, channel interactive buttons (e.g., Telegram inline buttons), or CLI prompts.

#### NEXUS Policy:
1. **Unified Human-in-the-Loop (HITL) Gate:**
   When Hermes attempts to execute a shell command or destructive file modification, its ACP adapter forwards the permission request to OpenClaw:
   ```text
   Hermes (Tool Call) ──► ACP Permission Request ──► OpenClaw Channel ──► User Approves ──► Execution
   ```
2. **Command Blacklisting & Sandboxing:**
   - Both Hermes (`hermes_constants.py`) and OpenClaw enforce hard command blacklists blocking destructive disk commands, privilege escalation attempts (`sudo -i`), or raw network sniffing.
   - On Windows, Hermes commands run within the restricted user security context without administrator elevation.

---

### 3.5. Filesystem Access & Worktree Isolation

#### Grounded Findings:
- Hermes implements `tools/subagent_worktree.py` and `hermes_dir_acl.py` to constrain subagents to dedicated directory trees.
- OpenClaw enforces path containment checks (`packages/plugin-sdk/file-access-runtime.ts`: `isPathInside`).

#### NEXUS Policy:
1. **Workspace Boundary Enforcement:** All agent file reading and writing is constrained to the workspace root (`A:\Mixer\workspace` or active project root). Attempts to access parent directories (`..`) or Windows system directories (`C:\Windows`, `C:\Program Files`) trigger an immediate access violation.
2. **Subagent Worktree Segregation:** Subagents spawned by Hermes operate in temporary isolated directories (`A:\Mixer\workspace\.nexus-worktrees\<task_id>`). Changes are merged only upon explicit parent task approval.

---

### 3.6. Audit Logging & Forensic Traceability

#### Grounded Findings:
- OpenClaw Gateway maintains structured event logs in `dist/` and session logs.
- Hermes maintains a transaction ledger in `delivery_ledger.py` and `lifecycle_ledger.py`.

#### NEXUS Policy:
1. **Immutable Audit Ledger:** Every incoming channel prompt, model generation, tool invocation, human approval, and edge device command is recorded with ISO-8601 timestamps, user IDs, and unique turn IDs.
2. **Fail-Closed Policy:** If the audit log cannot be written (e.g., disk full), all shell execution tools immediately pause until storage is restored.


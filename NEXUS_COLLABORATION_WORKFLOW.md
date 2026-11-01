# NEXUS Shared AI Engineering Workflow

**Repository:** `A:\Mixer` (`bavikadichanakya/JamesBond`)  
**Primary implementer:** Codex  
**Architecture and review partner:** ChatGPT

## Responsibilities

- **Codex** owns repository inspection, routine implementation, debugging, tests, documentation, and Git changes. It may create task branches, commit its work, and prepare pull requests. High autonomy does not waive the approval gates below.
- **ChatGPT** provides architecture, research, implementation specifications, test plans, and independent security/code review. It reviews concrete GitHub issues, pull requests, diffs, and handoff reports; it does not assume local state that is not included in those records.
- **Project owner** decides product behavior and approves gated actions. GitHub issues and pull requests are the shared durable record; concise reports link decisions and verification to the relevant issue/PR.

## Branches and worktrees

- Keep `main` stable and based on the current `origin/main`. Do not develop directly on `main` for substantial work.
- Use a focused branch per task, named `codex/<issue-number>-<short-topic>` where practical. Use a separate worktree when tasks must proceed concurrently; never let two agents edit one working tree at the same time.
- Before editing, inspect `git status`, branch/upstream, recent history, and the exact target files. If the tree has unrelated changes, preserve them and avoid overlapping files; do not reset, clean, stash, or overwrite them without explicit direction.
- Integrate by pull request. Do not force-push, amend published commits, or rewrite history. Never stage upstream source directories or broad path globs.
- Preserve `openclaw-main/`, `hermes-agent-main/`, and `muse-gadget-sdk-main/` as local upstream source checkouts. Do not edit, delete, or stage their contents as part of ordinary NEXUS work. Changes needed upstream require explicit owner approval and a separately scoped plan.

## Task handoff format

Create or update a GitHub issue for substantial work. Include:

```text
Objective:
Acceptance criteria:
Scope / files expected:
Out of scope:
Dependencies and constraints:
Security or approval gates:
Verification plan:
Owner decision needed (if any):
```

For completion or review, add a concise report to the issue or PR containing:

```text
Outcome and implementation decisions:
Files changed:
Verification (commands and actual results):
Status labels: LIVE_VERIFIED | TESTED | IMPLEMENTED_NOT_TESTED | MOCKED | BLOCKED | NOT_IMPLEMENTED
Risks, limitations, and remaining work:
Next recommended task:
```

Link the issue, PR, and report to one another. For ChatGPT review, provide the exact PR/commit, changed-file list, relevant diff or GitHub compare link, actual test output/summary, and questions needing review. Share evidence, not private reasoning or claims unsupported by artifacts.

## Verification requirements

- Inspect existing code, tests, dependencies, and side effects before changing behavior. Make the smallest reliable change and document material decisions.
- Run focused tests for affected behavior and broader regression checks when practical. Record exact commands and outcomes; distinguish skipped, blocked, mocked, and live checks. Never claim tests passed unless they ran and passed.
- Review the final diff and `git status`; confirm only intended paths are staged or committed. Check that no upstream directory, credential, build output, or unrelated user change entered the change.
- For security-sensitive behavior, include relevant negative/denial cases and ask ChatGPT for independent review before merge. Native desktop acceptance requires a real Windows build and launch; source inspection or backend tests alone do not satisfy it.

## Security boundaries and approval gates

- Keep NEXUS permission controls enabled. Do not weaken authentication, authorization, allowlists, sandboxing, or audit behavior to make a task pass.
- Do not expose, print, commit, or transmit credentials. Avoid secrets in logs, reports, issue bodies, and test fixtures; use safe placeholders.
- Codex may perform ordinary, reversible project edits and diagnostics autonomously. Stop for project-owner approval before deleting important files/directories, modifying upstream repositories, changing system-wide security settings, installing system-level software, exposing/changing credentials, or taking other irreversible actions.
- Never force-push or rewrite Git history. Do not publish, merge, release, or deploy without the owner’s explicit approval for that action.
- If a requested action crosses a gate, finish independent safe work first, then present the concrete proposed action, scope, and impact for approval.

## Current verified starting point

- Repository is `A:\Mixer`, on `main` tracking `origin/main`. At workflow setup, the working tree already contained newline-only modifications in `NEXUS_PHASE_B_REPORT.md`, `nexus/desktop_backend.py`, and `nexus/tests/test_desktop_backend.py`, plus an untracked `vs_BuildTools.exe`. Preserve and review these separately; do not include them in this workflow change.
- The three upstream directories are present and ignored by Git.
- `NEXUS_PHASE_B_REPORT.md` reports 79/79 tests passing and live supervised-backend/Ollama/shutdown checks. These are claims recorded by that report, not rerun in this workflow setup.
- The same report marks native Tauri compilation **BLOCKED** because MSVC (`cl.exe`/`link.exe`) and the Windows SDK were missing at report time. Verify the current toolchain before Phase B.1; do not infer that the old environment check is still current.
- Immediate milestone is **Phase B.1**: compile, launch, and validate the Windows desktop application against documented acceptance criteria. Do not start Phase C until those checks pass. No product features are authorized by this setup assignment.

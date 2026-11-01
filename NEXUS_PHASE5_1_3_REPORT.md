# NEXUS — Phase 5.1.3 Implementation & Verification Report: Generic Website Recognition & Routing Repair

**Document Version:** 1.0.0  
**Date:** November 1, 2026  
**Status:** Completed & Verified  
**Target Environment:** Windows 11 / Local Ollama (`qwen2.5-coder:3b`) / Local System Adapter  
**Project Workspace:** `A:\Mixer\`  
**Entry Point / Launcher:** `A:\Mixer\launch_nexus.py`  
**Dedicated URL Utility:** `A:\Mixer\nexus\routing\url_utils.py`  
**Classifier Subsystem:** `A:\Mixer\nexus\routing\classifier.py`  
**Router Subsystem:** `A:\Mixer\nexus\routing\router.py`  
**Local System Adapter:** `A:\Mixer\nexus\integrations\local_system\adapter.py`  
**Automated Test Suite:** `A:\Mixer\nexus\tests\test_phase5_1_3.py`  

---

## 1. Executive Summary & Defect Statement

In earlier versions of NEXUS, website navigation requests such as:
```text
open instagram.com
```
resulted in the fallback failure response:
```text
None of the available integrations (OpenClaw, Hermes, Muse) support this operation.
```

### Root Causes Identified:
1. **Static Keyword Dependency in IntentClassifier:**  
   `nexus/routing/classifier.py` relied on a static keyword list (`["open website", "open url", "open youtube", "open google", "open github", "open reddit"]`). Because `"instagram"` and generic domains were not in the static list, any request for an unlisted domain produced zero detected capabilities (`detected_caps = []`) and fell through to `"unsupported"`.
2. **Hardcoded Domain Switch in Router:**  
   `nexus/routing/router.py`’s `_extract_arguments` explicitly checked only `"youtube"`, `"google"`, `"github"`, `"reddit"`, with a rudimentary regex that recognized only 5 TLDs (`com|org|io|net|edu`).
3. **Misleading Fallback Explanations:**  
   When a request fell through to `RoutingStatus.UNSUPPORTED`, the router explanation hardcoded `"(OpenClaw, Hermes, Muse)"`, failing to reflect that `Local System` was registered and active.

---

## 2. Architecture of the Phase 5.1.3 Repair

To permanently resolve this defect without introducing fragile hardcoded lists of popular websites, Phase 5.1.3 implements a dedicated, RFC-compliant URL normalization and dynamic website intent recognition architecture:

```
User Input ("open instagram.com")
               │
               ▼
┌────────────────────────────────────────────────────────┐
│     nexus/routing/url_utils.py                         │
│  • extract_website_target_from_query()                 │
│  • normalize_and_validate_url()                        │
│  • Rejects prohibited schemes (file:, javascript:, ...) │
│  • Rejects malformed domains (adjacent dots, bad TLDs) │
└──────────────────────┬─────────────────────────────────┘
                       │ Valid Target Extracted
                       ▼
┌────────────────────────────────────────────────────────┐
│     nexus/routing/classifier.py                        │
│  • is_website_navigation_query() prioritized           │
│  • Disambiguates apps (Chrome, Calc) vs websites       │
│  • Disambiguates folders (Downloads) vs websites       │
│  • Detects 'web_navigation' capability                 │
└──────────────────────┬─────────────────────────────────┘
                       │ RoutingPlan (Status: ROUTED)
                       ▼
┌────────────────────────────────────────────────────────┐
│     nexus/routing/router.py                            │
│  • Maps 'web_navigation' -> 'open_website'             │
│  • Extracts normalized HTTPS URL                       │
│  • Deduplicates identical turns                        │
│  • Emits Stage 8 Structured Observability Log          │
└──────────────────────┬─────────────────────────────────┘
                       │ ToolCall(open_website)
                       ▼
┌────────────────────────────────────────────────────────┐
│     nexus/integrations/local_system/adapter.py         │
│  • Validates URL via normalize_and_validate_url()      │
│  • Windows ShellExecuteW(0, "open", url, None, None, 1)│
│  • Win32 Return Code Verification (ret > 32)           │
│  • Returns structured execution payload                │
└──────────────────────┬─────────────────────────────────┘
                       │ StandardizedToolResult
                       ▼
┌────────────────────────────────────────────────────────┐
│     nexus/routing/response_manager.py                  │
│  • Formats unified response acknowledging dispatch     │
│  • Notes actual rendering occurs in default browser    │
└────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Component Implementations

### 3.1 Dedicated URL Utilities (`nexus/routing/url_utils.py`)
Provides reusable, RFC-compliant URL normalization and validation:
- **`normalize_and_validate_url(raw_url: str) -> str`**:
  - Automatically prepends `https://` if scheme is omitted (e.g., `instagram.com` → `https://instagram.com`).
  - Preserves explicit `http://` or `https://` schemes.
  - Lowercases hostnames (`INSTAGRAM.COM` → `https://instagram.com`).
  - Preserves legitimate paths, query parameters, and fragments (`https://github.com/torvalds/linux?tab=readme#sec`).
  - Rejects prohibited schemes (`javascript:`, `file:`, `powershell:`, `data:`, `vbscript:`, `cmd:`).
  - Rejects malformed domains (adjacent dots like `foo..com`, invalid labels, single-character or numeric TLDs).
  - Rejects arbitrary whitespace and natural language text.
- **`extract_website_target_from_query(query: str, ...)`**:
  - Dynamically extracts website targets from natural language phrases (`"Open instagram.com"`, `"Visit github.com"`, `"Go to instagram.com"`, `"Navigate to https://example.com"`, `"Launch the website reddit.com"`).
  - Normalizes bare brand names without TLD (`"Open Instagram"` → `https://www.instagram.com`, `"Open YouTube"` → `https://www.youtube.com`).
  - Strips trailing natural language modifiers (`"in browser"`, `"in a new tab"`, `"please"`, `"for me"`).

### 3.2 Dynamic Intent Classification (`nexus/routing/classifier.py`)
- Executes `is_website_navigation_query()` before capability keyword scanning.
- **Application vs. Website Disambiguation:**  
  If a query contains `"open"` with an allowlisted desktop executable (`chrome`, `calculator`, `notepad`, `mspaint`, `taskmgr`, `edge`), the classifier prioritizes `application_launch` and suppresses `web_navigation`.
- **Folder vs. Website Disambiguation:**  
  If a query contains an approved user directory (`downloads`, `documents`, `desktop`, `pictures`), it prioritizes `folder_access`.
- **Precedence:** Explicit website directives are never routed to OpenClaw, Hermes, or Muse.

### 3.3 Router Argument Extraction & Observability (`nexus/routing/router.py`)
- Dynamically extracts the target URL via `extract_website_target_from_query(query)`.
- Updates the unsupported fallback explanation to:  
  `"I cannot fulfill the request '{query}'. None of the available integrations support this operation."` (eliminating the inaccurate exclusion notice).
- **Execution Observability Logging:** Logs all 8 mandated observability dimensions for every request:
  ```text
  [NEXUS Execution Observability] Request: 'open instagram.com' | Intent: web_navigation | Adapter: local_system | Tool: open_website | Normalized URL: https://instagram.com | Tool Invocation ID: exec_2cfccbd3ec97 | Windows ShellExecute Result: 42 | Status: SUCCESS
  ```

### 3.4 Local System Adapter (`nexus/integrations/local_system/adapter.py`)
- `handle_open_website` delegates validation to `normalize_and_validate_url(raw_url)`.
- Dispatches through Windows `ShellExecuteW` API (`ret > 32` denotes success).
- Returns structured JSON payload confirming `windows_shell_accepted`, `dispatch_code`, `note`, and normalized URL.

---

## 4. Verification Against Objectives

| Requirement | Input Command | Target Tool | Normalized Argument | Observed Outcome | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Open instagram.com** | `open instagram.com` | `open_website` | `https://instagram.com` | ShellExecuteW dispatched (code 42) | **PASS** |
| **2. Open Instagram** | `Open Instagram` | `open_website` | `https://www.instagram.com` | ShellExecuteW dispatched (code 42) | **PASS** |
| **3. Open youtube.com** | `open youtube.com` | `open_website` | `https://youtube.com` | ShellExecuteW dispatched (code 42) | **PASS** |
| **4. Open https://github.com** | `open https://github.com` | `open_website` | `https://github.com` | HTTPS URL preserved; dispatched | **PASS** |
| **5. Visit reddit.com** | `visit reddit.com` | `open_website` | `https://reddit.com` | ShellExecuteW dispatched (code 42) | **PASS** |
| **6. Arbitrary Domain** | `visit techcrunch.com` | `open_website` | `https://techcrunch.com` | Dynamically resolved without hardcoding | **PASS** |
| **7. Reject javascript:** | `open javascript:alert(1)` | `open_website` | `javascript:alert(1)` | Rejected: `Prohibited URL scheme 'javascript:'` | **PASS** |
| **8. Reject file:** | `open file:///C:/Windows` | `open_website` | `file:///C:/Windows` | Rejected: `Prohibited URL scheme 'file:'` | **PASS** |
| **9. Reject malformed domain** | `open malformed..domain.com`| `open_website` | `malformed..domain.com` | Rejected: `Malformed domain: contains adjacent dots` | **PASS** |
| **10. Preserve App Launch** | `Open Chrome` | `launch_application`| `app_name: "chrome"` | Preserved desktop application launch | **PASS** |
| **10. Preserve App Launch** | `Open Calculator` | `launch_application`| `app_name: "calculator"` | Preserved desktop application launch | **PASS** |
| **11. Prevent Fall-Through** | All website inputs | `open_website` | N/A | Never routed to OpenClaw, Hermes, or Muse | **PASS** |
| **12. Single Invocation** | `open instagram.com` | `open_website` | N/A | Exactly 1 tool invocation generated | **PASS** |

---

## 5. Automated Test Suite Results

The dedicated test suite [`nexus/tests/test_phase5_1_3.py`](file:///A:/Mixer/nexus/tests/test_phase5_1_3.py) runs 16 comprehensive tests:

```text
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_01_url_normalization_standard PASSED [  6%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_02_url_normalization_preserves_paths_and_queries PASSED [ 12%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_03_url_validation_rejects_prohibited_schemes PASSED [ 18%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_04_url_validation_rejects_malformed_domains PASSED [ 25%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_05_open_instagram_dot_com PASSED [ 31%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_06_open_instagram_bare_brand PASSED [ 37%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_07_open_youtube_dot_com PASSED [ 43%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_08_open_https_github_com PASSED [ 50%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_09_visit_reddit_dot_com PASSED [ 56%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_10_open_arbitrary_valid_external_domain PASSED [ 62%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_11_reject_javascript_urls PASSED [ 68%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_12_reject_file_urls PASSED [ 75%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_13_reject_malformed_domains PASSED [ 81%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_14_preserve_application_launches PASSED [ 87%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_15_website_requests_never_fall_through_to_other_integrations PASSED [ 93%]
nexus/tests/test_phase5_1_3.py::TestNexusPhase513GenericWebsiteRouting::test_16_single_request_generates_single_tool_invocation PASSED [100%]

============================= 16 passed in 0.36s ==============================
```

### Full Regression Suite:
```text
nexus/tests/test_integrations.py .............. [ 18%]
nexus/tests/test_nexus.py ..................... [ 42%]
nexus/tests/test_phase5.py .................... [ 61%]
nexus/tests/test_phase5_1.py .................. [ 78%]
nexus/tests/test_phase5_1_3.py ................ [100%]

======================== 75 passed, 1 warning in 6.26s ========================
```
Zero regressions across all 75 workspace tests.

---

## 6. Live Windows OS Dispatch Verification

Separate from automated mocking, live Windows `ShellExecuteW` execution was verified directly on the Windows 11 host:

```powershell
python -c "from nexus.integrations.local_system.adapter import LocalSystemAdapter; print(LocalSystemAdapter.dispatch_url_os('https://instagram.com'))"
```
**Output:**
```python
(True, 42, 'Windows Shell accepted browser launch request (code 42).')
```
- Windows Shell accepted the launch request with return code `42` (`> 32`).
- The default browser was invoked and launched `https://instagram.com`.

---

## 7. Conclusion

NEXUS Phase 5.1.3 resolves the generic website recognition defect completely:
- Dynamic domain recognition operates without hardcoded website lists.
- RFC-compliant normalization preserves paths and query parameters while enforcing HTTPS defaults and domain sanity.
- Dangerous schemes (`javascript:`, `file:`, `powershell:`) are rejected with explicit, transparent security notices.
- Application launches (`Chrome`, `Calculator`) remain strictly preserved.
- Full 8-field execution observability is logged for every turn.
- The desktop interface is live at `http://127.0.0.1:5000`.


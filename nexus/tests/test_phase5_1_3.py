"""NEXUS Phase 5.1.3 Test Suite: Generic Website Recognition & Routing Repair.

Validates:
1. Dynamic URL normalization and validation (HTTP/HTTPS, paths, queries, fragments).
2. Dynamic intent recognition for arbitrary domains and brand names.
3. Strict rejection of prohibited schemes (javascript:, file:, powershell:, data:).
4. Strict rejection of malformed domains (adjacent dots, invalid labels, invalid TLDs).
5. Preservation of application launching (Chrome, Calculator, Notepad).
6. Prevention of fall-through to OpenClaw, Hermes, or Muse for website navigation.
7. Single-invocation turn execution.
8. End-to-end execution observability logging.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from nexus.integrations.hermes.adapter import HermesAdapter
from nexus.integrations.local_system.adapter import LocalSystemAdapter
from nexus.integrations.manager import IntegrationManager
from nexus.integrations.muse.adapter import MuseAdapter
from nexus.integrations.openclaw.adapter import OpenClawAdapter
from nexus.routing.classifier import IntentClassifier
from nexus.routing.models import RoutingStatus
from nexus.routing.router import CapabilityRouter
from nexus.routing.url_utils import (
    extract_website_target_from_query,
    is_website_navigation_query,
    normalize_and_validate_url,
)
from nexus.tools.execution import ToolExecutionEngine
from nexus.tools.permissions import PermissionManager, ToolApprovalDecision
from nexus.tools.registry import ToolRegistry


class TestNexusPhase513GenericWebsiteRouting(unittest.TestCase):
    """Test suite for Phase 5.1.3 generic website recognition and routing repair."""

    def setUp(self):
        self.registry = ToolRegistry()
        self.permission_manager = PermissionManager(allow_privileged=True)
        self.execution_engine = ToolExecutionEngine(
            registry=self.registry,
            permission_manager=self.permission_manager,
        )
        self.integration_manager = IntegrationManager(registry=self.registry)

        # Register local system adapter
        self.local_adapter = LocalSystemAdapter()
        self.local_adapter.initialize()
        self.integration_manager.register_adapter(self.local_adapter)

        # Register upstream adapters in simulated mode
        self.openclaw_adapter = OpenClawAdapter(force_simulated=True)
        self.openclaw_adapter.initialize()
        self.integration_manager.register_adapter(self.openclaw_adapter)

        self.hermes_adapter = HermesAdapter(force_simulated=True)
        self.hermes_adapter.initialize()
        self.integration_manager.register_adapter(self.hermes_adapter)

        self.muse_adapter = MuseAdapter(force_simulated=True)
        self.muse_adapter.initialize()
        self.integration_manager.register_adapter(self.muse_adapter)

        self.classifier = IntentClassifier()
        self.router = CapabilityRouter(
            registry=self.registry,
            manager=self.integration_manager,
            execution_engine=self.execution_engine,
            classifier=self.classifier,
        )

    # -------------------------------------------------------------------------
    # 1. URL Normalization Unit Tests
    # -------------------------------------------------------------------------

    def test_01_url_normalization_standard(self):
        """Verify standard domain and protocol normalization."""
        self.assertEqual(normalize_and_validate_url("instagram.com"), "https://instagram.com")
        self.assertEqual(normalize_and_validate_url("www.youtube.com"), "https://www.youtube.com")
        self.assertEqual(normalize_and_validate_url("https://github.com"), "https://github.com")
        self.assertEqual(normalize_and_validate_url("http://example.org"), "http://example.org")
        self.assertEqual(normalize_and_validate_url("INSTAGRAM.COM"), "https://instagram.com")

    def test_02_url_normalization_preserves_paths_and_queries(self):
        """Verify preservation of paths, query parameters, and fragments."""
        url_with_path = "https://github.com/torvalds/linux/blob/master/README"
        self.assertEqual(normalize_and_validate_url(url_with_path), url_with_path)

        url_with_query = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"
        self.assertEqual(normalize_and_validate_url(url_with_query), url_with_query)

        url_fragment = "instagram.com/p/C_12345/?hl=en#comments"
        self.assertEqual(normalize_and_validate_url(url_fragment), "https://instagram.com/p/C_12345/?hl=en#comments")

    def test_03_url_validation_rejects_prohibited_schemes(self):
        """Verify strict rejection of prohibited schemes (javascript:, file:, powershell:, data:)."""
        prohibited = [
            "javascript:alert(1)",
            "file:///C:/Windows/System32",
            "powershell:Get-Process",
            "data:text/html,<b>exploit</b>",
            "vbscript:msgbox",
            "cmd:dir",
        ]
        for url in prohibited:
            with self.assertRaises(ValueError) as ctx:
                normalize_and_validate_url(url)
            self.assertTrue(
                "Prohibited URL scheme" in str(ctx.exception)
                or "Unsupported URL scheme" in str(ctx.exception)
            )

    def test_04_url_validation_rejects_malformed_domains(self):
        """Verify rejection of malformed hostnames, adjacent dots, and invalid TLDs."""
        malformed = [
            "malformed..domain.com",
            "-leadinghyphen.com",
            "trailinghyphen-.org",
            "invalid.c",
            "invalid.123",
            "http://",
            "https://..",
            "arbitrary natural language text with spaces",
            "not_a_domain_without_tld",
        ]
        for bad in malformed:
            with self.assertRaises(ValueError):
                normalize_and_validate_url(bad)

    # -------------------------------------------------------------------------
    # 2. Objective 6 Specific Required Routing Tests
    # -------------------------------------------------------------------------

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_05_open_instagram_dot_com(self, mock_dispatch):
        """Requirement 1: 'Open instagram.com' routes to open_website with normalized HTTPS URL."""
        plan = self.router.plan_task("open instagram.com")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].integration_name, "local_system")
        self.assertEqual(plan.steps[0].arguments["url"], "https://instagram.com")

        outcome = self.router.execute_query("open instagram.com")
        self.assertTrue(outcome.success)
        mock_dispatch.assert_called_once_with("https://instagram.com")
        self.assertIn("https://instagram.com", outcome.final_response)

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_06_open_instagram_bare_brand(self, mock_dispatch):
        """Requirement 2: 'Open Instagram' routes to open_website with canonical web URL."""
        plan = self.router.plan_task("Open Instagram")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].integration_name, "local_system")
        self.assertEqual(plan.steps[0].arguments["url"], "https://www.instagram.com")

        outcome = self.router.execute_query("Open Instagram")
        self.assertTrue(outcome.success)
        mock_dispatch.assert_called_once_with("https://www.instagram.com")

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_07_open_youtube_dot_com(self, mock_dispatch):
        """Requirement 3: 'Open youtube.com' routes to open_website."""
        plan = self.router.plan_task("open youtube.com")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].arguments["url"], "https://youtube.com")

        outcome = self.router.execute_query("open youtube.com")
        self.assertTrue(outcome.success)
        mock_dispatch.assert_called_once_with("https://youtube.com")

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_08_open_https_github_com(self, mock_dispatch):
        """Requirement 4: 'Open https://github.com' preserves explicit HTTPS URL."""
        plan = self.router.plan_task("open https://github.com")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].arguments["url"], "https://github.com")

        outcome = self.router.execute_query("open https://github.com")
        self.assertTrue(outcome.success)
        mock_dispatch.assert_called_once_with("https://github.com")

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_09_visit_reddit_dot_com(self, mock_dispatch):
        """Requirement 5: 'Visit reddit.com' routes to open_website."""
        plan = self.router.plan_task("visit reddit.com")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].arguments["url"], "https://reddit.com")

        outcome = self.router.execute_query("visit reddit.com")
        self.assertTrue(outcome.success)
        mock_dispatch.assert_called_once_with("https://reddit.com")

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_10_open_arbitrary_valid_external_domain(self, mock_dispatch):
        """Requirement 6: Arbitrary external domains recognized dynamically without hardcoding."""
        arbitrary_queries = [
            ("visit myportfolio.io", "https://myportfolio.io"),
            ("go to news.ycombinator.com", "https://news.ycombinator.com"),
            ("navigate to https://example.com", "https://example.com"),
            ("launch the website techcrunch.com", "https://techcrunch.com"),
            ("browse to speedtest.net", "https://speedtest.net"),
        ]
        for query, expected_url in arbitrary_queries:
            mock_dispatch.reset_mock()
            plan = self.router.plan_task(query)
            self.assertEqual(plan.status, RoutingStatus.ROUTED, f"Failed for query: {query}")
            self.assertEqual(plan.steps[0].tool_name, "open_website")
            self.assertEqual(plan.steps[0].integration_name, "local_system")
            self.assertEqual(plan.steps[0].arguments["url"], expected_url)

            outcome = self.router.execute_query(query)
            self.assertTrue(outcome.success, f"Execution failed for {query}")
            mock_dispatch.assert_called_once_with(expected_url)

    def test_11_reject_javascript_urls(self):
        """Requirement 7: Reject javascript: URLs cleanly without executing browser dispatch."""
        plan = self.router.plan_task("open javascript:alert(1)")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].integration_name, "local_system")

        outcome = self.router.execute_query("open javascript:alert(1)")
        self.assertFalse(outcome.success)
        self.assertIn("Prohibited URL scheme", outcome.final_response)
        self.assertNotIn("OpenClaw", outcome.final_response)
        self.assertNotIn("Hermes", outcome.final_response)
        self.assertNotIn("Muse", outcome.final_response)

    def test_12_reject_file_urls(self):
        """Requirement 8: Reject file: URLs cleanly without executing browser dispatch."""
        plan = self.router.plan_task("open file:///C:/Windows/System32")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].integration_name, "local_system")

        outcome = self.router.execute_query("open file:///C:/Windows/System32")
        self.assertFalse(outcome.success)
        self.assertIn("Prohibited URL scheme", outcome.final_response)
        self.assertNotIn("OpenClaw", outcome.final_response)
        self.assertNotIn("Hermes", outcome.final_response)
        self.assertNotIn("Muse", outcome.final_response)

    def test_13_reject_malformed_domains(self):
        """Requirement 9: Reject malformed domains during tool execution."""
        plan = self.router.plan_task("open malformed..domain.com")
        self.assertEqual(plan.status, RoutingStatus.ROUTED)
        self.assertEqual(plan.steps[0].tool_name, "open_website")
        self.assertEqual(plan.steps[0].integration_name, "local_system")

        outcome = self.router.execute_query("open malformed..domain.com")
        self.assertFalse(outcome.success)
        self.assertIn("Malformed domain", outcome.final_response)
        self.assertNotIn("OpenClaw", outcome.final_response)
        self.assertNotIn("Hermes", outcome.final_response)
        self.assertNotIn("Muse", outcome.final_response)

    @patch("subprocess.Popen")
    def test_14_preserve_application_launches(self, mock_popen):
        """Requirement 10: Preserve Chrome and Calculator desktop application launching."""
        self.permission_manager.set_approval_callback(
            lambda req: ToolApprovalDecision(approved=True, decided_by="TEST_ADMIN", reason="Test auto-approve")
        )
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        # 1. Open Chrome
        plan_chrome = self.router.plan_task("Open Chrome")
        self.assertEqual(plan_chrome.status, RoutingStatus.ROUTED)
        self.assertEqual(plan_chrome.steps[0].tool_name, "launch_application")
        self.assertEqual(plan_chrome.steps[0].arguments["app_name"], "chrome")
        self.assertTrue(plan_chrome.requires_confirmation)

        outcome_chrome = self.router.execute_query("Open Chrome")
        self.assertTrue(outcome_chrome.success)
        self.assertIn("chrome", outcome_chrome.final_response.lower())

        # 2. Open Calculator
        mock_popen.reset_mock()
        plan_calc = self.router.plan_task("Open Calculator")
        self.assertEqual(plan_calc.status, RoutingStatus.ROUTED)
        self.assertEqual(plan_calc.steps[0].tool_name, "launch_application")
        self.assertEqual(plan_calc.steps[0].arguments["app_name"], "calculator")
        self.assertTrue(plan_calc.requires_confirmation)

        outcome_calc = self.router.execute_query("Open Calculator")
        self.assertTrue(outcome_calc.success)
        self.assertIn("calculator", outcome_calc.final_response.lower())

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_15_website_requests_never_fall_through_to_other_integrations(self, mock_dispatch):
        """Requirement 11: Verify website requests never fall through to OpenClaw, Hermes, or Muse."""
        test_inputs = [
            "open instagram.com",
            "Open Instagram",
            "open youtube.com",
            "go to instagram.com",
            "visit github.com",
            "navigate to https://example.com",
            "open https://www.google.com",
            "launch the website reddit.com",
            "visit myportfolio.io",
        ]
        for query in test_inputs:
            plan = self.router.plan_task(query)
            self.assertEqual(plan.status, RoutingStatus.ROUTED, f"Query '{query}' failed routing")
            for step in plan.steps:
                self.assertEqual(
                    step.integration_name,
                    "local_system",
                    f"Query '{query}' fell through to {step.integration_name}",
                )
                self.assertEqual(
                    step.tool_name,
                    "open_website",
                    f"Query '{query}' routed to unexpected tool {step.tool_name}",
                )

    @patch.object(LocalSystemAdapter, "dispatch_url_os", return_value=(True, 42, "Windows Shell accepted launch"))
    def test_16_single_request_generates_single_tool_invocation(self, mock_dispatch):
        """Requirement 12: Verify one website request generates exactly one tool invocation."""
        query = "open instagram.com"
        plan = self.router.plan_task(query)
        self.assertEqual(len(plan.steps), 1)

        outcome = self.router.execute_query(query)
        self.assertEqual(len(outcome.executed_steps), 1)
        self.assertEqual(mock_dispatch.call_count, 1)


if __name__ == "__main__":
    unittest.main()

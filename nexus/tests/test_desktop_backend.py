"""Automated tests for NEXUS Desktop Backend Supervisor (Phase B)."""

import json
import os
import signal
import sys
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path

# Add workspace to path
workspace_root = Path(__file__).parent.parent.parent.resolve()
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from nexus.desktop_backend import DesktopBackendSupervisor, INSTANCE_FILE_NAME


class TestDesktopBackendSupervisor(unittest.TestCase):
    """Test suite for desktop backend supervisor lifecycle and security."""

    TEST_PORT = 5098

    def setUp(self):
        self.supervisor = DesktopBackendSupervisor(
            host="127.0.0.1",
            port=self.TEST_PORT,
            auth_token="test_secret_token_12345",
        )

    def tearDown(self):
        self.supervisor.stop()
        meta_file = workspace_root / INSTANCE_FILE_NAME
        if meta_file.exists():
            try:
                meta_file.unlink()
            except Exception:
                pass

    def test_01_instance_metadata_creation_and_removal(self):
        """Verify instance metadata file creation and cleanup."""
        self.supervisor.write_instance_metadata()
        meta_file = workspace_root / INSTANCE_FILE_NAME
        self.assertTrue(meta_file.exists())

        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["instance_id"], self.supervisor.instance_id)
        self.assertEqual(data["port"], self.TEST_PORT)
        self.assertEqual(data["auth_token"], "test_secret_token_12345")
        self.assertEqual(data["host"], "127.0.0.1")

        self.supervisor.remove_instance_metadata()
        self.assertFalse(meta_file.exists())

    def test_02_port_availability_probe(self):
        """Verify probe correctly identifies an available port."""
        res = self.supervisor.verify_port_availability()
        self.assertEqual(res["status"], "AVAILABLE")

    def test_03_app_creation_and_routes(self):
        """Verify supervisor enhances Flask app with shutdown and supervisor telemetry."""
        app = self.supervisor.build_application()
        client = app.test_client()

        # 1. Status route contains supervisor telemetry
        resp = client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("supervisor", data)
        self.assertEqual(data["supervisor"]["instance_id"], self.supervisor.instance_id)
        self.assertEqual(data["supervisor"]["supervised"], True)

        # 2. Unauthorized shutdown rejected
        unauth_resp = client.post("/api/system/shutdown")
        self.assertEqual(unauth_resp.status_code, 403)

        bad_token_resp = client.post(
            "/api/system/shutdown",
            headers={"X-Nexus-Auth-Token": "wrong_token"},
        )
        self.assertEqual(bad_token_resp.status_code, 403)

        # 3. Authorized shutdown accepted
        auth_resp = client.post(
            "/api/system/shutdown",
            headers={"X-Nexus-Auth-Token": "test_secret_token_12345"},
        )
        self.assertEqual(auth_resp.status_code, 200)
        auth_data = auth_resp.get_json()
        self.assertEqual(auth_data["status"], "SHUTTING_DOWN")
        self.assertEqual(auth_data["instance_id"], self.supervisor.instance_id)

    def test_04_parent_pid_detection(self):
        """Verify PID existence check for parent process monitoring."""
        current_pid = os.getpid()
        self.assertTrue(DesktopBackendSupervisor._is_pid_alive(current_pid))
        self.assertFalse(DesktopBackendSupervisor._is_pid_alive(-99999))
        self.assertFalse(DesktopBackendSupervisor._is_pid_alive(9999999))


if __name__ == "__main__":
    unittest.main()


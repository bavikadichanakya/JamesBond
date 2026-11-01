"""NEXUS Desktop Backend Supervisor.

Manages the headless lifecycle of the NEXUS Flask backend for desktop environments
(such as Tauri 2). Provides exclusive 127.0.0.1 binding, instance identification,
authenticated shutdown, parent process tracking, and duplicate prevention.
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import secrets
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.request
import urllib.error

# Ensure workspace root is in sys.path
workspace_root = Path(__file__).parent.parent.resolve()
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from nexus.config import NexusConfig
from nexus.ui.app import create_app

INSTANCE_FILE_NAME = ".nexus_desktop_instance.json"
LOG_FILE_NAME = "desktop_backend.log"


class DesktopBackendSupervisor:
    """Supervises the local Flask backend lifecycle for desktop integration."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        parent_pid: Optional[int] = None,
        auth_token: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.parent_pid = parent_pid
        self.instance_id = f"inst_{uuid.uuid4().hex[:12]}"
        self.auth_token = auth_token or secrets.token_hex(16)
        self.workspace_dir = workspace_dir or workspace_root
        self.instance_file_path = self.workspace_dir / INSTANCE_FILE_NAME
        self.log_file_path = self.workspace_dir / "nexus" / LOG_FILE_NAME

        self._shutdown_requested = False
        self._server_thread: Optional[threading.Thread] = None
        self._parent_monitor_thread: Optional[threading.Thread] = None
        self._setup_logger()

    def _setup_logger(self) -> None:
        """Configure structured file and stream logger."""
        self.logger = logging.getLogger("nexus.desktop_backend")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [instance=" + self.instance_id + "] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # File Handler
        try:
            fh = logging.FileHandler(str(self.log_file_path), encoding="utf-8")
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
        except Exception as e:
            sys.stderr.write(f"Warning: Could not open log file {self.log_file_path}: {e}\n")

        # Console Handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

    def verify_port_availability(self) -> Dict[str, Any]:
        """Probe the target host:port to prevent duplicate instances or port conflicts.

        Returns:
            dict indicating whether the port is available, occupied by another NEXUS,
            or occupied by an unrelated foreign service.
        """
        probe_url = f"http://{self.host}:{self.port}/api/status"
        try:
            req = urllib.request.Request(probe_url, headers={"User-Agent": "NEXUS-Supervisor-Probe"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    # Validate NEXUS signature
                    if data.get("status") == "ONLINE" and "adapters" in data and "capabilities" in data:
                        return {
                            "status": "OCCUPIED_BY_NEXUS",
                            "message": f"An existing NEXUS backend is already active on {self.host}:{self.port}.",
                            "details": data,
                        }
                    else:
                        return {
                            "status": "OCCUPIED_BY_FOREIGN_SERVICE",
                            "message": f"Port {self.port} is occupied by an unrelated foreign service. Aborting.",
                        }
        except urllib.error.URLError:
            # Connection refused or host unreachable -> Port is clean
            return {"status": "AVAILABLE", "message": f"Port {self.port} is available."}
        except Exception as exc:
            return {
                "status": "UNKNOWN_OCCUPIED",
                "message": f"Port {self.port} returned an unexpected error on probe: {exc}",
            }

        return {"status": "AVAILABLE", "message": f"Port {self.port} is available."}

    def write_instance_metadata(self) -> None:
        """Write runtime state file for desktop shell discovery and authenticated access."""
        meta = {
            "instance_id": self.instance_id,
            "pid": os.getpid(),
            "parent_pid": self.parent_pid,
            "host": self.host,
            "port": self.port,
            "base_url": f"http://{self.host}:{self.port}",
            "auth_token": self.auth_token,
            "started_at": time.time(),
        }
        try:
            with open(self.instance_file_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            self.logger.info("Instance metadata saved to %s", self.instance_file_path)
        except Exception as exc:
            self.logger.error("Failed to write instance metadata: %s", exc)

    def remove_instance_metadata(self) -> None:
        """Clean up runtime state file on exit."""
        try:
            if self.instance_file_path.exists():
                self.instance_file_path.unlink()
                self.logger.info("Instance metadata removed.")
        except Exception as exc:
            self.logger.warning("Error cleaning instance metadata: %s", exc)

    def _monitor_parent_process(self) -> None:
        """Daemon thread watching parent PID; terminates backend cleanly if parent dies."""
        if not self.parent_pid:
            return

        self.logger.info("Parent process watcher active for PID: %d", self.parent_pid)
        while not self._shutdown_requested:
            time.sleep(1.0)
            if not self._is_pid_alive(self.parent_pid):
                self.logger.warning(
                    "Parent process (PID %d) terminated unexpectedly. Initiating supervisor shutdown.",
                    self.parent_pid,
                )
                self.stop()
                os._exit(0)

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check whether a given PID is still running on Windows/POSIX."""
        if pid <= 0:
            return False
        try:
            if sys.platform == "win32":
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                SYNCHRONIZE = 0x00100000
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
                    False,
                    pid,
                )
                if not handle:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            else:
                os.kill(pid, 0)
                return True
        except Exception:
            return False

    def build_application(self):
        """Build and configure the Flask app with supervisor extensions."""
        cfg = NexusConfig.from_json_file(self.workspace_dir / "nexus" / "nexus_config.json")
        app = create_app(config=cfg)

        # Extend /api/status with supervisor telemetry
        original_get_status = app.view_functions.get("get_status")

        def enhanced_status():
            from flask import jsonify
            resp = original_get_status()
            data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp.data)
            data["supervisor"] = {
                "instance_id": self.instance_id,
                "supervised": True,
                "parent_pid": self.parent_pid,
                "host": self.host,
                "port": self.port,
            }
            return jsonify(data)

        app.view_functions["get_status"] = enhanced_status

        # Authenticated Shutdown Endpoint
        @app.route("/api/system/shutdown", methods=["POST"])
        def shutdown_endpoint():
            from flask import jsonify, request

            token = request.headers.get("X-Nexus-Auth-Token")
            if not token and request.is_json:
                token = (request.get_json() or {}).get("token")

            if not token or not secrets.compare_digest(token, self.auth_token):
                self.logger.warning("Unauthorized shutdown attempt rejected (token mismatch)")
                return jsonify({"error": "Unauthorized: invalid shutdown token"}), 403

            self.logger.info("Authenticated shutdown request received from authorized desktop client.")

            def delayed_kill():
                time.sleep(0.5)
                self.stop()
                os._exit(0)

            threading.Thread(target=delayed_kill, daemon=True).start()
            return jsonify({
                "status": "SHUTTING_DOWN",
                "instance_id": self.instance_id,
                "message": "NEXUS supervisor terminating cleanly.",
            })

        return app

    def start(self, block: bool = True) -> None:
        """Start the supervised backend."""
        self.logger.info("Initializing NEXUS Desktop Supervisor [instance=%s]...", self.instance_id)

        # 1. Port Verification
        port_check = self.verify_port_availability()
        if port_check["status"] == "OCCUPIED_BY_NEXUS":
            self.logger.info("Existing NEXUS backend detected on %s:%d. Reusing instance.", self.host, self.port)
            # Write instance metadata pointing to the running service if needed
            print(f"ALREADY_RUNNING:{self.host}:{self.port}")
            return
        elif port_check["status"] != "AVAILABLE":
            self.logger.error("Port conflict error: %s", port_check["message"])
            raise RuntimeError(port_check["message"])

        # 2. Setup cleanup hooks
        atexit.register(self.remove_instance_metadata)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # 3. Write metadata file
        self.write_instance_metadata()

        # 4. Start Parent Process Watcher
        if self.parent_pid:
            self._parent_monitor_thread = threading.Thread(
                target=self._monitor_parent_process,
                daemon=True,
                name="nexus-parent-monitor",
            )
            self._parent_monitor_thread.start()

        # 5. Build Flask App
        app = self.build_application()

        self.logger.info(
            "Starting Flask application headless on http://%s:%d (auth_token=%s...)",
            self.host,
            self.port,
            self.auth_token[:6],
        )

        # Print ready signal to stdout for desktop shell consumption
        print(f"NEXUS_BACKEND_READY:{self.instance_id}:{self.host}:{self.port}:{self.auth_token}", flush=True)

        if block:
            app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        else:
            self._server_thread = threading.Thread(
                target=lambda: app.run(host=self.host, port=self.port, debug=False, use_reloader=False),
                daemon=True,
                name="nexus-flask-server",
            )
            self._server_thread.start()

    def stop(self) -> None:
        """Clean shutdown of supervisor and instance metadata."""
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        self.logger.info("Stopping NEXUS Desktop Supervisor [instance=%s]...", self.instance_id)
        self.remove_instance_metadata()

    def _signal_handler(self, signum, frame):
        self.logger.info("Signal %d received. Exiting.", signum)
        self.stop()
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="NEXUS Desktop Backend Supervisor")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    parser.add_argument("--parent-pid", type=int, default=None, help="PID of the parent desktop process to monitor")
    parser.add_argument("--auth-token", default=None, help="Secret authentication token for control/shutdown")
    args = parser.parse_args()

    supervisor = DesktopBackendSupervisor(
        host=args.host,
        port=args.port,
        parent_pid=args.parent_pid,
        auth_token=args.auth_token,
    )
    try:
        supervisor.start(block=True)
    except Exception as exc:
        supervisor.logger.error("Supervisor startup failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

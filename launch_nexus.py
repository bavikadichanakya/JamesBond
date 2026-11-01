"""NEXUS Desktop Application Launcher.

Starts the unified NEXUS Desktop Assistant on http://127.0.0.1:5000.
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path

# Add workspace to path
workspace_root = Path(__file__).parent.resolve()
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from nexus.ui.app import create_app


def main():
    print("=" * 75)
    print("               NEXUS UNIFIED DESKTOP AI ASSISTANT")
    print("  Integrating: OpenClaw (Gateway) | Hermes (Agent) | Muse (Smart IoT)")
    print("  Local Model: qwen2.5-coder:3b (Ollama)")
    print("=" * 75)
    print("\nStarting local server on http://127.0.0.1:5000 ...")

    app = create_app()

    # Open browser automatically
    try:
        webbrowser.open("http://127.0.0.1:5000")
    except Exception:
        pass

    print("\n[NEXUS READY] Interface accessible at http://127.0.0.1:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()


"""Configuration management for NEXUS."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class NexusConfig:
    """Runtime configuration for NEXUS engine and model integrations."""

    # Model settings
    ollama_endpoint: str = "http://localhost:11434"
    model_name: str = "qwen2.5-coder:3b"
    model_request_timeout: float = 120.0

    # Tool execution limits
    default_tool_timeout: float = 10.0
    max_tool_rounds: int = 5
    allow_privileged_execution: bool = False

    # Security & Redaction
    redact_sensitive_patterns: List[str] = field(
        default_factory=lambda: [
            "password",
            "secret",
            "token",
            "api_key",
            "authorization",
            "bearer",
        ]
    )

    # Persistence
    workspace_root: str = "A:\\Mixer"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NexusConfig:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_json_file(cls, path: str | Path) -> NexusConfig:
        file_path = Path(path)
        if not file_path.is_file():
            return cls()
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ollama_endpoint": self.ollama_endpoint,
            "model_name": self.model_name,
            "model_request_timeout": self.model_request_timeout,
            "default_tool_timeout": self.default_tool_timeout,
            "max_tool_rounds": self.max_tool_rounds,
            "allow_privileged_execution": self.allow_privileged_execution,
            "redact_sensitive_patterns": list(self.redact_sensitive_patterns),
            "workspace_root": self.workspace_root,
        }


"""Ollama client integration with structured tool-calling support for NEXUS."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from nexus.tools.result import ToolCall

logger = logging.getLogger("nexus.model.ollama")

TransportFunction = Callable[[str, Dict[str, Any], float], Dict[str, Any]]


@dataclass
class OllamaModelResponse:
    """Parsed response from the Ollama chat endpoint."""

    role: str
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw_message: Dict[str, Any] = field(default_factory=dict)
    done: bool = True
    total_duration_ns: int = 0


def default_http_transport(endpoint: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """Default HTTP transport using Python standard library urllib.request."""
    url = f"{endpoint.rstrip('/')}/api/chat"
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP error {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Cannot connect to Ollama at {endpoint}: {exc.reason}") from exc


class OllamaChatClient:
    """Client for communicating with Ollama's /api/chat endpoint with tool-calling capabilities."""

    def __init__(
        self,
        endpoint: str = "http://localhost:11434",
        model: str = "qwen2.5-coder:3b",
        timeout: float = 60.0,
        transport: Optional[TransportFunction] = None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.transport = transport or default_http_transport

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> OllamaModelResponse:
        """Send chat messages and tool definitions to Ollama and parse response."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        logger.debug("Dispatching request to Ollama model=%s message_count=%d", self.model, len(messages))
        raw_response = self.transport(self.endpoint, payload, self.timeout)

        msg = raw_response.get("message", {})
        content = msg.get("content") or ""
        role = msg.get("role") or "assistant"
        total_duration = raw_response.get("total_duration") or 0

        # Parse tool calls
        tool_calls = self._extract_tool_calls(msg)

        return OllamaModelResponse(
            role=role,
            content=content,
            tool_calls=tool_calls,
            raw_message=msg,
            done=raw_response.get("done", True),
            total_duration_ns=total_duration,
        )

    def _extract_tool_calls(self, message: Dict[str, Any]) -> List[ToolCall]:
        """Extract tool calls from standard tool_calls field or structured JSON in content."""
        extracted: List[ToolCall] = []

        # 1. Standard Ollama/OpenAI tool_calls list
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, list) and raw_tool_calls:
            for item in raw_tool_calls:
                fn = item.get("function") or item
                name = fn.get("name")
                raw_args = fn.get("arguments", {})
                call_id = item.get("id") or f"call_{uuid.uuid4().hex[:12]}"

                # Parse arguments if string
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {"raw_arguments": raw_args}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}

                if name:
                    extracted.append(ToolCall(name=name, arguments=args, tool_call_id=call_id))

        # 2. Fallback: Parse structured tool call JSON emitted directly in assistant content
        if not extracted:
            content = (message.get("content") or "").strip()
            
            # Strip markdown code blocks if model wrapped JSON in ```json ... ```
            if content.startswith("```"):
                lines = content.splitlines()
                # Remove first line if it starts with ```
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                # Remove last line if it starts with ```
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            # Also check if wrapped in <tool_call> ... </tool_call>
            if "<tool_call>" in content and "</tool_call>" in content:
                match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", content, re.DOTALL)
                if match:
                    content = match.group(1).strip()

            if content.startswith("{") and content.endswith("}"):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        # Pattern A: {"name": "...", "arguments": {...}}
                        if "name" in parsed and ("arguments" in parsed or "parameters" in parsed):
                            name = parsed["name"]
                            args = parsed.get("arguments", parsed.get("parameters", {}))
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    args = {"raw": args}
                            extracted.append(
                                ToolCall(
                                    name=name,
                                    arguments=args if isinstance(args, dict) else {},
                                    tool_call_id=f"call_{uuid.uuid4().hex[:12]}",
                                )
                            )
                        # Pattern B: {"tool": "...", "parameters": {...}}
                        elif "tool" in parsed and ("parameters" in parsed or "arguments" in parsed):
                            name = parsed["tool"]
                            args = parsed.get("parameters", parsed.get("arguments", {}))
                            extracted.append(
                                ToolCall(
                                    name=name,
                                    arguments=args if isinstance(args, dict) else {},
                                    tool_call_id=f"call_{uuid.uuid4().hex[:12]}",
                                )
                            )
                except json.JSONDecodeError:
                    pass

        return extracted

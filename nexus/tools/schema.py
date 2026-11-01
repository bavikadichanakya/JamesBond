"""Schema definitions and strict validation for NEXUS tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from nexus.tools.permissions import PermissionLevel


@dataclass
class ToolParameter:
    """Specification of a single tool parameter."""

    name: str
    type: str  # "string", "boolean", "integer", "number", "array", "object"
    description: str
    required: bool = True
    enum: Optional[List[str]] = None
    default: Any = None
    properties: Optional[Dict[str, ToolParameter]] = None
    items: Optional[Dict[str, Any]] = None

    def to_json_schema(self) -> Dict[str, Any]:
        schema: Dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum is not None:
            schema["enum"] = list(self.enum)
        if self.properties is not None:
            schema["properties"] = {k: v.to_json_schema() for k, v in self.properties.items()}
        if self.items is not None:
            schema["items"] = self.items
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass
class ToolDefinition:
    """Complete specification of a registered NEXUS tool."""

    name: str
    description: str
    parameters: Dict[str, ToolParameter]
    permission_level: PermissionLevel
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    source: str = "NEXUS_CORE"
    simulated: bool = False
    allow_additional_properties: bool = False

    def get_required_parameter_names(self) -> List[str]:
        return [name for name, p in self.parameters.items() if p.required]

    def to_ollama_format(self) -> Dict[str, Any]:
        """Convert tool specification to standard Ollama/OpenAI tool definition format."""
        properties = {name: p.to_json_schema() for name, p in self.parameters.items()}
        required = self.get_required_parameter_names()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": self.allow_additional_properties,
                },
            },
        }


class ToolSchemaValidator:
    """Validates model-generated tool arguments against registered schemas with strict type and boundary checking."""

    TYPE_CHECKERS: Dict[str, Callable[[Any], bool]] = {
        "string": lambda val: isinstance(val, str),
        "boolean": lambda val: isinstance(val, bool),
        "integer": lambda val: isinstance(val, int) and not isinstance(val, bool),
        "number": lambda val: (isinstance(val, (int, float)) and not isinstance(val, bool)),
        "array": lambda val: isinstance(val, list),
        "object": lambda val: isinstance(val, dict),
    }

    @classmethod
    def sanitize_arguments(cls, raw_arguments: Union[str, Dict[str, Any], None]) -> Dict[str, Any]:
        """Safely parse arguments into a dictionary, handling JSON strings or None."""
        if raw_arguments is None:
            return {}
        if isinstance(raw_arguments, dict):
            return dict(raw_arguments)
        if isinstance(raw_arguments, str):
            clean_str = raw_arguments.strip()
            if not clean_str:
                return {}
            try:
                parsed = json.loads(clean_str)
                if isinstance(parsed, dict):
                    return parsed
                raise ValueError(f"Tool arguments must be a JSON object, but parsed {type(parsed).__name__}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON in tool arguments: {exc.msg} at line {exc.lineno} col {exc.colno}")
        raise ValueError(f"Unsupported tool arguments type: {type(raw_arguments).__name__}")

    @classmethod
    def validate(cls, tool_def: ToolDefinition, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate arguments against tool definition.
        
        Returns normalized arguments with defaults filled in, or raises ValueError.
        """
        validated_args: Dict[str, Any] = {}

        # 1. Reject unexpected parameters unless explicitly permitted
        if not tool_def.allow_additional_properties:
            unexpected = set(arguments.keys()) - set(tool_def.parameters.keys())
            if unexpected:
                unexpected_list = ", ".join(f"'{k}'" for k in sorted(unexpected))
                raise ValueError(
                    f"Unexpected argument(s) {unexpected_list} for tool '{tool_def.name}'. "
                    f"Allowed parameters are: {', '.join(sorted(tool_def.parameters.keys()))}"
                )

        # 2. Check required parameters
        for param_name, param_spec in tool_def.parameters.items():
            if param_name in arguments:
                val = arguments[param_name]

                # Type checking
                expected_type = param_spec.type
                checker = cls.TYPE_CHECKERS.get(expected_type)
                if checker and not checker(val):
                    raise ValueError(
                        f"Invalid type for argument '{param_name}' in tool '{tool_def.name}'. "
                        f"Expected {expected_type}, received {type(val).__name__} ({repr(val)})."
                    )

                # Enum checking
                if param_spec.enum is not None:
                    if val not in param_spec.enum:
                        raise ValueError(
                            f"Invalid value for '{param_name}' in tool '{tool_def.name}'. "
                            f"Received '{val}'. Allowed values are: {param_spec.enum}."
                        )

                validated_args[param_name] = val
            else:
                if param_spec.required:
                    raise ValueError(
                        f"Missing required parameter '{param_name}' for tool '{tool_def.name}'."
                    )
                # Assign default if specified
                if param_spec.default is not None:
                    validated_args[param_name] = param_spec.default

        # Copy any permitted additional properties
        if tool_def.allow_additional_properties:
            for k, v in arguments.items():
                if k not in validated_args:
                    validated_args[k] = v

        return validated_args


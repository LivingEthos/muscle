"""OpenAI-compatible function schema boundary normalization.

Architecture Decision Record (ADR):
- Keep schema compatibility at provider/API boundaries so MUSCLE feature
  handlers keep their internal argument contracts.
- Normalize generated JSON Schemas into OpenAI-compatible function
  ``parameters`` objects before network I/O.
- Return an explicit unwrap registry keyed by function name so dispatch can
  recover the original handler argument shape after a provider tool call.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

FORBIDDEN_ROOT_SCHEMA_KEYS = frozenset({"oneOf", "anyOf", "allOf", "enum", "const", "not"})
COMBINATOR_ROOT_SCHEMA_KEYS = frozenset({"oneOf", "anyOf", "allOf", "not"})
SCALAR_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "null"})


class ToolSchemaCompatibilityError(ValueError):
    """Raised when a function schema cannot be made provider-compatible."""


class ArgumentUnwrapKey(str, Enum):
    """Provider-boundary wrapper keys for non-object root schemas."""

    ITEMS = "items"
    VALUE = "value"
    PAYLOAD = "payload"


@dataclass(frozen=True)
class FunctionSchemaCompatibility:
    """Normalized function ``parameters`` schema plus dispatch unwrap metadata."""

    provider_schema: dict[str, Any]
    unwrap_key: ArgumentUnwrapKey | None = None


@dataclass(frozen=True)
class PayloadSchemaCompatibility:
    """Normalized OpenAI-compatible payload and per-function unwrap registry."""

    payload: dict[str, Any]
    argument_wrappers: Mapping[str, ArgumentUnwrapKey] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "argument_wrappers",
            MappingProxyType(dict(self.argument_wrappers)),
        )


def normalize_function_parameters_schema(
    schema: Mapping[str, Any] | None,
    *,
    function_name: str | None = None,
) -> FunctionSchemaCompatibility:
    """Normalize a generated JSON Schema into OpenAI function ``parameters``.

    Args:
        schema: Source JSON Schema. ``None`` is treated as an empty object
            parameter schema, matching OpenAI's no-argument function shape.
        function_name: Optional name used only in error messages.

    Returns:
        The provider-facing object-root schema and an optional unwrap key.

    Raises:
        ToolSchemaCompatibilityError: If ``schema`` is not a JSON object schema
            mapping or the normalized provider schema is still invalid.
    """
    label = _function_label(function_name)
    if schema is None:
        provider_schema: dict[str, Any] = {"type": "object", "properties": {}}
        validate_openai_function_parameters_schema(provider_schema, function_name=function_name)
        return FunctionSchemaCompatibility(provider_schema=provider_schema)
    if not isinstance(schema, Mapping):
        raise ToolSchemaCompatibilityError(
            f"{label} parameters schema must be a JSON object mapping before provider "
            f"serialization; got {type(schema).__name__}."
        )

    source = copy.deepcopy(dict(schema))
    unwrap_key = _choose_unwrap_key(source)
    if unwrap_key is None:
        provider_schema = _normalize_object_root_schema(source)
    else:
        provider_schema = _wrap_schema(source, unwrap_key)

    validate_openai_function_parameters_schema(provider_schema, function_name=function_name)
    return FunctionSchemaCompatibility(
        provider_schema=provider_schema,
        unwrap_key=unwrap_key,
    )


def validate_openai_function_parameters_schema(
    schema: Mapping[str, Any],
    *,
    function_name: str | None = None,
) -> None:
    """Validate a provider-facing OpenAI function ``parameters`` schema.

    The OpenAI-compatible contract enforced here is intentionally narrow: the
    root must be ``type: object`` and must not carry top-level combinators or
    scalar restrictions that some OpenAI-compatible providers reject.
    """
    label = _function_label(function_name)
    if not isinstance(schema, Mapping):
        raise ToolSchemaCompatibilityError(
            f"{label} provider-facing parameters schema must be a JSON object mapping; "
            f"got {type(schema).__name__}."
        )
    root_type = schema.get("type")
    forbidden = sorted(FORBIDDEN_ROOT_SCHEMA_KEYS.intersection(schema))
    if root_type != "object" or forbidden:
        forbidden_text = ", ".join(f"'{key}'" for key in sorted(FORBIDDEN_ROOT_SCHEMA_KEYS))
        detail = f"; found top-level {', '.join(forbidden)}" if forbidden else ""
        raise ToolSchemaCompatibilityError(
            f"{label} provider-facing parameters schema must have type 'object' and "
            f"not have {forbidden_text} at the top level{detail}. Wrap the source "
            "schema with normalize_function_parameters_schema() before network I/O."
        )
    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, Mapping):
        raise ToolSchemaCompatibilityError(
            f"{label} provider-facing parameters schema has non-object 'properties'; "
            "expected a JSON object mapping."
        )


def normalize_openai_compatible_payload(payload: Mapping[str, Any]) -> PayloadSchemaCompatibility:
    """Normalize ``tools`` and ``functions`` entries in an OpenAI-compatible payload."""
    normalized_payload = copy.deepcopy(dict(payload))
    wrappers: dict[str, ArgumentUnwrapKey] = {}

    if "tools" in normalized_payload:
        normalized_payload["tools"] = _normalize_tools_list(normalized_payload["tools"], wrappers)
    if "functions" in normalized_payload:
        normalized_payload["functions"] = _normalize_functions_list(
            normalized_payload["functions"],
            wrappers,
        )

    return PayloadSchemaCompatibility(payload=normalized_payload, argument_wrappers=wrappers)


def unwrap_openai_tool_arguments(
    function_name: str,
    arguments: Any,
    argument_wrappers: Mapping[str, ArgumentUnwrapKey | str],
) -> Any:
    """Unwrap provider tool-call arguments back to the original handler shape."""
    unwrap_key = argument_wrappers.get(function_name)
    if unwrap_key is None:
        return arguments
    key = unwrap_key.value if isinstance(unwrap_key, ArgumentUnwrapKey) else str(unwrap_key)
    if not isinstance(arguments, Mapping):
        raise ToolSchemaCompatibilityError(
            f"Tool call arguments for {function_name!r} must be an object containing "
            f"{key!r}; got {type(arguments).__name__}."
        )
    if key not in arguments:
        raise ToolSchemaCompatibilityError(
            f"Tool call arguments for {function_name!r} are missing wrapper key {key!r}."
        )
    return arguments[key]


def _normalize_tools_list(tools: Any, wrappers: dict[str, ArgumentUnwrapKey]) -> list[Any]:
    if not isinstance(tools, list):
        raise ToolSchemaCompatibilityError(
            f"OpenAI-compatible payload 'tools' must be a list before provider "
            f"serialization; got {type(tools).__name__}."
        )
    normalized_tools: list[Any] = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            raise ToolSchemaCompatibilityError(
                f"OpenAI-compatible tool at index {index} must be an object; "
                f"got {type(tool).__name__}."
            )
        tool_copy = copy.deepcopy(dict(tool))
        if tool_copy.get("type") != "function" and "function" not in tool_copy:
            normalized_tools.append(tool_copy)
            continue
        function_def = tool_copy.get("function")
        if not isinstance(function_def, Mapping):
            raise ToolSchemaCompatibilityError(
                f"OpenAI-compatible function tool at index {index} must contain a "
                "'function' object."
            )
        normalized_function, unwrap_key = _normalize_function_definition(function_def)
        if unwrap_key is not None:
            wrappers[_function_name(normalized_function)] = unwrap_key
        tool_copy["type"] = "function"
        tool_copy["function"] = normalized_function
        normalized_tools.append(tool_copy)
    return normalized_tools


def _normalize_functions_list(
    functions: Any,
    wrappers: dict[str, ArgumentUnwrapKey],
) -> list[Any]:
    if not isinstance(functions, list):
        raise ToolSchemaCompatibilityError(
            f"OpenAI-compatible payload 'functions' must be a list before provider "
            f"serialization; got {type(functions).__name__}."
        )
    normalized_functions: list[Any] = []
    for index, function_def in enumerate(functions):
        if not isinstance(function_def, Mapping):
            raise ToolSchemaCompatibilityError(
                f"OpenAI-compatible function at index {index} must be an object; "
                f"got {type(function_def).__name__}."
            )
        normalized_function, unwrap_key = _normalize_function_definition(function_def)
        if unwrap_key is not None:
            wrappers[_function_name(normalized_function)] = unwrap_key
        normalized_functions.append(normalized_function)
    return normalized_functions


def _normalize_function_definition(
    function_def: Mapping[str, Any],
) -> tuple[dict[str, Any], ArgumentUnwrapKey | None]:
    function_copy = copy.deepcopy(dict(function_def))
    name = _function_name(function_copy)
    compatibility = normalize_function_parameters_schema(
        function_copy.get("parameters"),
        function_name=name,
    )
    function_copy["parameters"] = compatibility.provider_schema
    return function_copy, compatibility.unwrap_key


def _choose_unwrap_key(schema: Mapping[str, Any]) -> ArgumentUnwrapKey | None:
    root_type = schema.get("type")
    if root_type == "object" and not FORBIDDEN_ROOT_SCHEMA_KEYS.intersection(schema):
        return None
    if COMBINATOR_ROOT_SCHEMA_KEYS.intersection(schema):
        return ArgumentUnwrapKey.PAYLOAD
    if root_type == "array":
        return ArgumentUnwrapKey.ITEMS
    if "enum" in schema or "const" in schema or root_type in SCALAR_JSON_TYPES:
        return ArgumentUnwrapKey.VALUE
    if "properties" in schema and not FORBIDDEN_ROOT_SCHEMA_KEYS.intersection(schema):
        return None
    return ArgumentUnwrapKey.PAYLOAD


def _normalize_object_root_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if schema.get("type") == "object":
        return schema
    normalized = copy.deepcopy(schema)
    normalized["type"] = "object"
    normalized.setdefault("properties", {})
    return normalized


def _wrap_schema(schema: dict[str, Any], unwrap_key: ArgumentUnwrapKey) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {unwrap_key.value: schema},
        "required": [unwrap_key.value],
    }


def _function_name(function_def: Mapping[str, Any]) -> str:
    name = function_def.get("name")
    return name if isinstance(name, str) and name else "<unnamed>"


def _function_label(function_name: str | None) -> str:
    return f"Function {function_name!r}" if function_name else "Function"

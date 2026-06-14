"""Regression tests for OpenAI-compatible tool schema normalization."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from muscle.llm.tool_schema_compat import (
    ArgumentUnwrapKey,
    ToolSchemaCompatibilityError,
    normalize_function_parameters_schema,
    normalize_openai_compatible_payload,
    unwrap_openai_tool_arguments,
    validate_openai_function_parameters_schema,
)
from muscle.m27_client import M27Client
from muscle.openrouter_api_client import OpenRouterApiClient


def test_top_level_array_schema_wraps_under_items_and_unwraps() -> None:
    compatibility = normalize_function_parameters_schema(
        {"type": "array", "items": {"type": "string"}},
        function_name="collect_names",
    )

    assert compatibility.unwrap_key == ArgumentUnwrapKey.ITEMS
    assert compatibility.provider_schema == {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
        "required": ["items"],
    }
    assert (
        unwrap_openai_tool_arguments(
            "collect_names",
            {"items": ["alpha", "beta"]},
            {"collect_names": ArgumentUnwrapKey.ITEMS},
        )
        == ["alpha", "beta"]
    )


def test_top_level_enum_scalar_schema_wraps_under_value_and_unwraps() -> None:
    compatibility = normalize_function_parameters_schema(
        {"type": "string", "enum": ["small", "large"]},
        function_name="choose_size",
    )

    assert compatibility.unwrap_key == ArgumentUnwrapKey.VALUE
    assert compatibility.provider_schema["type"] == "object"
    assert compatibility.provider_schema["properties"] == {
        "value": {"type": "string", "enum": ["small", "large"]}
    }
    assert (
        unwrap_openai_tool_arguments(
            "choose_size",
            {"value": "large"},
            {"choose_size": ArgumentUnwrapKey.VALUE},
        )
        == "large"
    )


@pytest.mark.parametrize("keyword", ["oneOf", "anyOf", "allOf", "not"])
def test_top_level_union_combinator_schema_wraps_under_payload(keyword: str) -> None:
    source_schema: dict[str, Any] = {
        keyword: [
            {"type": "object", "properties": {"query": {"type": "string"}}},
            {"type": "array", "items": {"type": "string"}},
        ]
    }

    compatibility = normalize_function_parameters_schema(
        source_schema,
        function_name="search",
    )

    assert compatibility.unwrap_key == ArgumentUnwrapKey.PAYLOAD
    assert compatibility.provider_schema == {
        "type": "object",
        "properties": {"payload": source_schema},
        "required": ["payload"],
    }
    assert (
        unwrap_openai_tool_arguments(
            "search",
            {"payload": {"query": "cache"}},
            {"search": ArgumentUnwrapKey.PAYLOAD},
        )
        == {"query": "cache"}
    )


def test_valid_object_root_schema_stays_stable() -> None:
    source_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    compatibility = normalize_function_parameters_schema(source_schema, function_name="search")

    assert compatibility.unwrap_key is None
    assert compatibility.provider_schema == source_schema


def test_multicategorysearchitems_validates_as_object_root_and_dispatches_same_behavior() -> None:
    def handler(categories: list[str]) -> str:
        return ",".join(category.upper() for category in categories)

    payload = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "_multicategorysearchitems",
                    "description": "Search across multiple item categories.",
                    "parameters": {"type": "array", "items": {"type": "string"}},
                },
            }
        ]
    }

    compatibility = normalize_openai_compatible_payload(payload)
    function_def = compatibility.payload["tools"][0]["function"]

    assert function_def["name"] == "_multicategorysearchitems"
    validate_openai_function_parameters_schema(
        function_def["parameters"],
        function_name=function_def["name"],
    )
    assert function_def["parameters"]["type"] == "object"
    assert "items" in function_def["parameters"]["properties"]
    original_arguments = ["books", "games"]
    unwrapped = unwrap_openai_tool_arguments(
        "_multicategorysearchitems",
        {"items": original_arguments},
        compatibility.argument_wrappers,
    )
    assert handler(unwrapped) == handler(original_arguments)


def test_legacy_functions_payload_uses_same_schema_compatibility_registry() -> None:
    compatibility = normalize_openai_compatible_payload(
        {
            "functions": [
                {
                    "name": "choose",
                    "parameters": {"enum": ["one", "two"]},
                }
            ]
        }
    )

    assert compatibility.payload["functions"][0]["parameters"]["type"] == "object"
    assert compatibility.argument_wrappers["choose"] == ArgumentUnwrapKey.VALUE
    assert (
        unwrap_openai_tool_arguments(
            "choose",
            {"value": "two"},
            compatibility.argument_wrappers,
        )
        == "two"
    )


def test_provider_facing_validator_rejects_invalid_top_level_schema() -> None:
    with pytest.raises(ToolSchemaCompatibilityError, match="must have type 'object'"):
        validate_openai_function_parameters_schema(
            {"type": "array", "items": {"type": "string"}},
            function_name="bad_tool",
        )


def test_openai_compatible_chat_rejects_invalid_schema_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = Mock()
    monkeypatch.setattr(M27Client, "_get_session", staticmethod(lambda: fake_session))
    client = OpenRouterApiClient(api_key="sk-or-test")

    with pytest.raises(ToolSchemaCompatibilityError, match="parameters schema"):
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "bad_tool",
                        "parameters": ["not", "a", "schema"],
                    },
                }
            ],
        )

    fake_session.post.assert_not_called()

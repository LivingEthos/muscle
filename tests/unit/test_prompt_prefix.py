"""Unit tests for cache-aware prompt prefix planning."""

from __future__ import annotations

from muscle.optimization.prompt_prefix import PromptPrefixPlanner, estimate_prefix_cost


def test_prompt_prefix_plan_is_byte_stable_for_same_inputs() -> None:
    planner = PromptPrefixPlanner()

    plan_a = planner.plan(
        system_instructions="You are MUSCLE.",
        methodology="Generate, evaluate, evolve.",
        stable_project_summary="Python review tool.",
        model_pack_lessons="Run host-risk preflight first.",
        tool_schemas='{"tool": "review"}',
        dynamic_task_payload="Review src/a.py",
    )
    plan_b = planner.plan(
        system_instructions="You are MUSCLE.",
        methodology="Generate, evaluate, evolve.",
        stable_project_summary="Python review tool.",
        model_pack_lessons="Run host-risk preflight first.",
        tool_schemas='{"tool": "review"}',
        dynamic_task_payload="Review src/a.py",
    )

    assert plan_a.stable_prefix == plan_b.stable_prefix
    assert plan_a.cache_prefix_digest == plan_b.cache_prefix_digest
    assert [section.name for section in plan_a.sections] == [
        "system_instructions",
        "methodology",
        "stable_project_summary",
        "model_pack_lessons",
        "tool_schemas",
        "dynamic_task_payload",
    ]


def test_dynamic_payload_change_does_not_change_stable_prefix_digest() -> None:
    planner = PromptPrefixPlanner()

    stable_kwargs = {
        "system_instructions": "You are MUSCLE.",
        "methodology": "Plan, delegate, verify.",
        "stable_project_summary": "Stable repo summary.",
        "model_pack_lessons": "Typed claims require evidence.",
        "tool_schemas": '{"schema": "stable"}',
    }
    plan_a = planner.plan(**stable_kwargs, dynamic_task_payload="Review tests/a.py")
    plan_b = planner.plan(**stable_kwargs, dynamic_task_payload="Review tests/b.py")

    assert plan_a.cache_prefix_digest == plan_b.cache_prefix_digest
    assert plan_a.dynamic_payload != plan_b.dynamic_payload


def test_rendered_prompt_uses_first_untrusted_content_marker_as_dynamic_boundary() -> None:
    planner = PromptPrefixPlanner()
    prompt = (
        "Stable host rubric\n"
        "No timestamps here.\n\n"
        "===== BEGIN MUSCLE UNTRUSTED CONTENT =====\n"
        "Source-Kind: file\n"
        "----- BEGIN DATA -----\n"
        "dynamic user code\n"
        "----- END DATA -----\n"
        "===== END MUSCLE UNTRUSTED CONTENT ====="
    )

    plan = planner.plan_rendered_prompt(prompt)

    assert plan.stable_prefix == "Stable host rubric\nNo timestamps here."
    assert plan.dynamic_payload.startswith("===== BEGIN MUSCLE UNTRUSTED CONTENT =====")


def test_prefix_linter_flags_unstable_stable_content() -> None:
    planner = PromptPrefixPlanner()

    plan = planner.plan(
        system_instructions=(
            "Generated at 2026-06-12T10:30:00\n"
            "run id abcdef1234567890abcdef\n"
            "running status\n"
            "scanned /Users/ryan/project/src/file.py\n"
            "1234 tokens used\n"
            "pytest collected 5 items\n"
        ),
        dynamic_task_payload="Dynamic content may contain 2026-06-12 without warning.",
    )

    codes = {warning.code for warning in plan.lint_warnings}
    assert {
        "timestamp",
        "random_id",
        "transient_status",
        "path_list",
        "token_counter",
        "command_output",
    } <= codes


def test_prefix_cost_estimate_labels_fable_cache_read_as_estimated() -> None:
    estimate = estimate_prefix_cost(4000)

    assert estimate.prefix_chars == 4000
    assert estimate.estimated_cache_fresh_cost > estimate.estimated_cache_read_cost > 0
    assert estimate.confidence == "estimated"

from __future__ import annotations

from tools.muscle.optimization.context_budgeter import (
    DEFAULT_ESCALATION_LINE_BUDGET,
    LARGE_WINDOW_ESCALATION_LINE_BUDGET,
    ContextBudgeter,
)


def test_escalation_budget_defaults_to_compact_ceiling() -> None:
    assert ContextBudgeter().escalation_line_budget == DEFAULT_ESCALATION_LINE_BUDGET


def test_escalation_budget_never_below_base_budget() -> None:
    # A base budget larger than the escalation ceiling raises the floor.
    budgeter = ContextBudgeter(line_budget=600, escalation_line_budget=420)
    assert budgeter.escalation_line_budget == 600


def test_large_window_escalation_pulls_more_lines() -> None:
    code = "\n".join(f"line_{idx} = {idx}" for idx in range(2000))
    small = ContextBudgeter(escalation_line_budget=DEFAULT_ESCALATION_LINE_BUDGET)
    large = ContextBudgeter(escalation_line_budget=LARGE_WINDOW_ESCALATION_LINE_BUDGET)
    small_pb = small.build_semantic_review_budget("f.py", code, [], escalate=True)
    large_pb = large.build_semantic_review_budget("f.py", code, [], escalate=True)
    assert len(large_pb.content.splitlines()) == LARGE_WINDOW_ESCALATION_LINE_BUDGET
    assert len(large_pb.content.splitlines()) > len(small_pb.content.splitlines())


def test_semantic_review_budget_prefers_issue_windows() -> None:
    code = "\n".join(
        [
            "import os",
            "import requests",
            "",
            "def fetch_data(url):",
            "    token = os.environ.get('TOKEN')",
            "    response = requests.get(url)",
            "    return response.json()",
        ]
        + [f"value_{idx} = {idx}" for idx in range(8, 80)]
    )
    budgeter = ContextBudgeter()

    budget = budgeter.build_semantic_review_budget(
        file_path="service.py",
        code_content=code,
        issues=[{"line_number": 6, "rule_id": "REQ001"}],
    )

    assert budget.strategy == "issue_windows"
    assert "0006:     response = requests.get(url)" in budget.content
    assert "0001: import os" in budget.content
    assert "REQ001" in budget.signals


def test_semantic_review_budget_escalates_to_expanded_slice() -> None:
    code = "\n".join(f"line_{idx}" for idx in range(1, 600))
    budgeter = ContextBudgeter()

    budget = budgeter.build_semantic_review_budget(
        file_path="large.py",
        code_content=code,
        issues=[{"line_number": 400, "rule_id": "JSON"}],
        escalate=True,
    )

    assert budget.strategy == "expanded_file_slice"
    assert budget.escalated is True
    assert "line_1" in budget.content


def test_fix_budget_prefers_patch_hunk_context() -> None:
    code = "\n".join(
        ["import os", "", "def save(path, payload):"]
        + [f"    line_{idx} = {idx}" for idx in range(4, 60)]
        + ["    open(path, 'w').write(payload)"]
    )
    budgeter = ContextBudgeter(fix_strategy="patch_hunk_context")

    budget = budgeter.build_fix_budget(issue_line=60, file_content=code)

    assert budget.strategy == "patch_hunk_context"
    assert "0060:     open(path, 'w').write(payload)" in budget.content
    assert "0001: import os" in budget.content

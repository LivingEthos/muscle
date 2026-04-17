"""Pydantic schemas for M2.7 response shapes — harness-wide I/O contract.

Use via M27Client.chat_structured() for automatic validation,
fence-stripping, and schema-corrective retries.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReviewFinding(BaseModel):
    file_path: str
    line_number: int = Field(ge=1)
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: Literal[
        "security", "correctness", "performance", "style", "docs", "best_practice"
    ]
    title: str
    description: str
    code_snippet: str = ""
    auto_fixable: bool = False
    suggested_fix: str | None = None
    reasoning: str


class ReviewFindings(BaseModel):
    reviews: list[ReviewFinding]


class FixCandidate(BaseModel):
    file_path: str
    original_snippet: str
    fixed_snippet: str
    rationale: str


class PatternScanResult(BaseModel):
    patterns_found: list[str]
    occurrences_by_pattern: dict[str, int]


class VerificationReport(BaseModel):
    passed: bool
    tests_run: int = 0
    tests_failed: int = 0
    lint_passed: bool | None = None
    type_check_passed: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class RouteDecisionSchema(BaseModel):
    tier: Literal["mechanical", "reasoning", "architectural"]
    recommended: Literal["m27", "m27_with_verify", "escalate_to_host"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str

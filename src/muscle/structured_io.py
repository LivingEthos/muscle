"""Pydantic schemas for M2.7 response shapes — harness-wide I/O contract.

Use via M27Client.chat_structured() for automatic validation,
fence-stripping, and schema-corrective retries.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_REVIEW_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_REVIEW_CATEGORIES = {
    "security",
    "correctness",
    "performance",
    "style",
    "documentation",
    "docs",
    "best_practice",
}


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_path: str = ""
    line_number: int = Field(default=1, ge=1)
    severity: str
    category: str = "best_practice"
    title: str = "Code issue"
    description: str = ""
    valid: bool = True
    cwe_id: str | None = None
    code_snippet: str = ""
    auto_fixable: bool = False
    suggested_fix: str | None = None
    reasoning: str = ""

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in _REVIEW_SEVERITIES:
            raise ValueError(f"Unsupported severity: {value}")
        return normalized

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in _REVIEW_CATEGORIES:
            raise ValueError(f"Unsupported category: {value}")
        return "documentation" if normalized == "docs" else normalized


class ReviewSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_reviewed: int = 0
    valid_issues: int = 0
    false_positives: int = 0
    intentional: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class ReviewFindings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reviews: list[ReviewFinding] = Field(default_factory=list)
    summary: ReviewSummary = Field(default_factory=ReviewSummary)


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

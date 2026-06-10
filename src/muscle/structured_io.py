"""Pydantic schemas for M2.7 response shapes — harness-wide I/O contract.

Use via M27Client.chat_structured() for automatic validation,
fence-stripping, and schema-corrective retries.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # ``None`` means the model did not report a line. We deliberately do NOT
    # default to 1: fabricating line 1 makes a line-less finding indistinguishable
    # from one genuinely on line 1. Downstream emitters surface this as JSON null.
    line_number: int | None = Field(default=None, ge=0)
    severity: str
    category: str = "best_practice"
    # Empty by default so the finding parser can derive a real title from the
    # description instead of stamping a constant "Code issue" placeholder.
    title: str = ""
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


# Inner-finding line keys that hold a LIST of line numbers (M3 emits both a scalar
# ``line``/``line_number`` and these list forms); we take the first element.
_INNER_LINE_LIST_KEYS = ("lines", "line_numbers")
# Inner-item aliases → canonical ReviewFinding field name (observed in real M3
# captures: ``cwe``→``cwe_id``, ``message``→``description``; ``fix``/``suggestion``
# accepted defensively as suggested_fix synonyms).
_INNER_FIELD_ALIASES: dict[str, str] = {
    "cwe": "cwe_id",
    "message": "description",
    "fix": "suggested_fix",
    "suggestion": "suggested_fix",
}
# Container-level keys that describe the group, not an individual finding. These
# are never copied onto flattened inner findings.
_CONTAINER_ONLY_KEYS = {"issues", "findings", "summary"}


def _flatten_review_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand one ``reviews[]`` entry into zero or more flat finding dicts.

    Handles MiniMax-M3's nondeterministic *nested* review shape, where a
    per-file container carries an ``issues`` (or ``findings``) list of inner
    findings, e.g.::

        {"file_path": "auth.py", "severity": "CRITICAL", "summary": "...",
         "issues": [{"title": "...", "line": 9, "cwe": "CWE-798", ...}]}

    Each inner item becomes one flat ``ReviewFinding`` dict that:

    * inherits ``file_path`` from the container when the inner item lacks it;
    * normalizes line fields (``line``→``line_number``; ``lines``/``line_numbers``
      list→first element);
    * applies inner aliases (``cwe``→``cwe_id``, ``message``→``description``,
      ``fix``/``suggestion``→``suggested_fix``);
    * uses the inner ``severity`` when present, falling back to the container's.

    Container-only keys (``summary``) are dropped.

    Decision on "both shapes": in every real captured payload, a container that
    carries an ``issues`` list has no standalone finding content of its own
    (only ``file_path``/``severity``/``summary``). We therefore emit ONLY the
    inner findings for such containers and do not also keep the container as a
    finding — keeping it would fabricate a contentless duplicate. Containers
    without an inner list pass through unchanged (the legacy flat shape).
    """
    if not isinstance(item, dict):
        return [item]

    inner_list: Any = None
    for key in ("issues", "findings"):
        candidate = item.get(key)
        if isinstance(candidate, list):
            inner_list = candidate
            break

    if not inner_list:
        # Legacy flat finding (no nested list). Pass through untouched.
        return [item]

    container_file = item.get("file_path")
    container_severity = item.get("severity")

    flattened: list[dict[str, Any]] = []
    for inner in inner_list:
        if not isinstance(inner, dict):
            continue
        finding: dict[str, Any] = {}

        # Carry the container file_path so each inner finding is self-describing.
        if container_file is not None:
            finding["file_path"] = container_file

        for raw_key, value in inner.items():
            canonical = _INNER_FIELD_ALIASES.get(str(raw_key), str(raw_key))
            if canonical in _CONTAINER_ONLY_KEYS:
                continue
            if canonical in _INNER_LINE_LIST_KEYS:
                if isinstance(value, list) and value:
                    finding["line_number"] = value[0]
                continue
            if canonical == "line_number" or str(raw_key) == "line":
                finding["line_number"] = value
                continue
            # Inner file_path (if any) wins over the inherited container value.
            finding[canonical] = value

        # Inner severity wins; fall back to the container's when absent.
        if not finding.get("severity") and container_severity is not None:
            finding["severity"] = container_severity

        flattened.append(finding)

    return flattened


class ReviewFindings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Appended to chat_structured's schema hint when this schema is the target.
    # Steers MiniMax-M3 toward the flat array shape this model expects, reducing
    # how often the parse-side salvage in ``_normalize_nested_reviews`` must fire.
    schema_hint_suffix: ClassVar[str] = (
        'Emit a FLAT array under "reviews": one object per individual issue. '
        'Do not group issues by file and do not nest an "issues"/"findings" '
        "list inside a review object."
    )

    reviews: list[ReviewFinding] = Field(default_factory=list)
    summary: ReviewSummary = Field(default_factory=ReviewSummary)

    @model_validator(mode="before")
    @classmethod
    def _normalize_nested_reviews(cls, data: Any) -> Any:
        """Flatten any nested ``reviews[]`` entries before field validation.

        MiniMax-M3 sometimes returns per-file containers with an inner
        ``issues``/``findings`` list instead of the flat finding list this
        schema expects. Without this step the container validates (thanks to
        ``extra="ignore"`` and field defaults) while the entire inner list is
        silently discarded. Runs for every call site (live, retry, and cached
        re-validation).
        """
        if not isinstance(data, dict):
            return data
        reviews = data.get("reviews")
        if not isinstance(reviews, list):
            return data
        flattened: list[Any] = []
        for item in reviews:
            flattened.extend(_flatten_review_item(item))
        # Return a shallow copy so we never mutate the caller's dict in place.
        return {**data, "reviews": flattened}


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

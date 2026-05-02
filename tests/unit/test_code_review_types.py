"""
Unit tests for code_review types.
"""

from tools.muscle.code_review.types import (
    HandoffIssue,
    HandoffPlan,
    IssueCategory,
    ReviewConfig,
    ReviewEvent,
    ReviewIssue,
    ReviewMode,
    ReviewResult,
    ReviewStats,
    Severity,
    StaticAnalysisResult,
    StaticIssue,
)


def test_severity_levels():
    assert Severity.CRITICAL.value == 5
    assert Severity.HIGH.value == 4
    assert Severity.MEDIUM.value == 3
    assert Severity.LOW.value == 2
    assert Severity.INFO.value == 1


def test_severity_comparison():
    assert Severity.CRITICAL.value > Severity.HIGH.value
    assert Severity.HIGH.value > Severity.MEDIUM.value
    assert Severity.MEDIUM.value > Severity.LOW.value
    assert Severity.LOW.value > Severity.INFO.value


def test_issue_category_values():
    assert IssueCategory.SECURITY.value == "security"
    assert IssueCategory.CORRECTNESS.value == "correctness"
    assert IssueCategory.PERFORMANCE.value == "performance"
    assert IssueCategory.STYLE.value == "style"
    assert IssueCategory.DOCUMENTATION.value == "documentation"
    assert IssueCategory.BEST_PRACTICE.value == "best_practice"


def test_review_issue_creation():
    issue = ReviewIssue(
        file_path="src/auth.py",
        line_number=42,
        severity=Severity.HIGH,
        category=IssueCategory.SECURITY,
        cwe_id="CWE-89",
        title="SQL Injection vulnerability",
        description="User input directly interpolated into SQL query",
        code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
        suggested_fix="query = 'SELECT * FROM users WHERE id = ?'",
        auto_fixable=True,
    )

    assert issue.file_path == "src/auth.py"
    assert issue.line_number == 42
    assert issue.severity == Severity.HIGH
    assert issue.category == IssueCategory.SECURITY
    assert issue.cwe_id == "CWE-89"
    assert issue.auto_fixable is True


def test_review_issue_auto_fixable_defaults_false():
    issue = ReviewIssue(
        file_path="src/main.py",
        line_number=10,
        severity=Severity.INFO,
        category=IssueCategory.STYLE,
        cwe_id=None,
        title="Missing docstring",
        description="Function lacks docstring",
        code_snippet="def foo(): pass",
        suggested_fix=None,
    )

    assert issue.auto_fixable is False


def test_review_config_defaults():
    config = ReviewConfig(target_path="./src")

    assert config.target_path == "./src"
    assert config.language is None
    assert config.mode == ReviewMode.REVIEW
    assert config.severity_threshold == Severity.LOW
    assert config.max_iterations == 10
    assert config.max_fixes_per_round == 5
    assert config.timeout_seconds == 3600
    assert config.pressure_challenge is None


def test_review_config_custom():
    config = ReviewConfig(
        target_path="./src",
        language="python",
        mode=ReviewMode.AUTO_FIX,
        severity_threshold=Severity.HIGH,
        max_iterations=20,
        max_fixes_per_round=10,
        timeout_seconds=7200,
        include_patterns=["*.py"],
        exclude_patterns=["test_*.py"],
        pressure_challenge="fragility",
    )

    assert config.language == "python"
    assert config.mode == ReviewMode.AUTO_FIX
    assert config.severity_threshold == Severity.HIGH
    assert config.max_iterations == 20
    assert config.max_fixes_per_round == 10
    assert config.include_patterns == ["*.py"]
    assert config.exclude_patterns == ["test_*.py"]
    assert config.pressure_challenge == "fragility"


def test_review_mode_values():
    assert ReviewMode.REVIEW.value == "review"
    assert ReviewMode.AUTO_FIX.value == "auto_fix"
    assert ReviewMode.PLAN.value == "plan"
    assert ReviewMode.HYBRID.value == "hybrid"


def test_review_result_initialization():
    result = ReviewResult(
        session_id="abc123",
        target_path="./src",
    )

    assert result.session_id == "abc123"
    assert result.target_path == "./src"
    assert result.issues == []
    assert result.files_reviewed == 0
    assert result.lines_reviewed == 0
    assert result.critical_count == 0
    assert result.high_count == 0
    assert result.medium_count == 0
    assert result.low_count == 0
    assert result.info_count == 0


def test_review_result_with_issues():
    issues = [
        ReviewIssue(
            file_path="src/a.py",
            line_number=1,
            severity=Severity.CRITICAL,
            category=IssueCategory.SECURITY,
            cwe_id="CWE-78",
            title="RCE vulnerability",
            description="Remote code execution via eval",
            code_snippet="eval(user_input)",
            auto_fixable=False,
        ),
        ReviewIssue(
            file_path="src/b.py",
            line_number=10,
            severity=Severity.MEDIUM,
            category=IssueCategory.STYLE,
            cwe_id=None,
            title="Line too long",
            description="Line exceeds 100 characters",
            code_snippet="x = 1; y = 2; z = 3",
            auto_fixable=True,
        ),
    ]

    result = ReviewResult(
        session_id="xyz789",
        target_path="./src",
        issues=issues,
        critical_count=1,
        medium_count=1,
    )

    assert len(result.issues) == 2
    assert result.critical_count == 1
    assert result.medium_count == 1


def test_static_issue():
    issue = StaticIssue(
        file_path="src/app.py",
        line_number=55,
        severity="HIGH",
        rule_id="S001",
        message="Line too long",
        category="style",
    )

    assert issue.file_path == "src/app.py"
    assert issue.line_number == 55
    assert issue.severity == "HIGH"
    assert issue.rule_id == "S001"


def test_static_analysis_result():
    issues = [
        StaticIssue(
            file_path="src/main.py",
            line_number=10,
            severity="MEDIUM",
            rule_id="E501",
            message="Line too long",
            category="style",
        ),
    ]

    result = StaticAnalysisResult(
        tool_name="ruff",
        language="python",
        issues=issues,
        duration_seconds=1.5,
    )

    assert result.tool_name == "ruff"
    assert result.language == "python"
    assert len(result.issues) == 1
    assert result.duration_seconds == 1.5


def test_review_event_values():
    assert ReviewEvent.REVIEW_START.value == "review_start"
    assert ReviewEvent.STATIC_ANALYSIS_COMPLETE.value == "static_analysis_complete"
    assert ReviewEvent.SEMANTIC_REVIEW_COMPLETE.value == "semantic_review_complete"
    assert ReviewEvent.FIX_APPLIED.value == "fix_applied"
    assert ReviewEvent.FIX_VERIFIED.value == "fix_verified"
    assert ReviewEvent.FIX_ROLLBACK.value == "fix_rollback"
    assert ReviewEvent.HANDOFF_GENERATED.value == "handoff_generated"
    assert ReviewEvent.REVIEW_COMPLETE.value == "review_complete"
    assert ReviewEvent.REVIEW_ABORT.value == "review_abort"


def test_review_stats_defaults():
    stats = ReviewStats()

    assert stats.total_issues == 0
    assert stats.valid_issues == 0
    assert stats.fixed_issues == 0
    assert stats.auto_fixed == 0
    assert stats.failed_fixes == 0
    assert stats.handoffs_generated == 0
    assert stats.tokens_used == 0
    assert stats.duration_seconds == 0.0


def test_review_stats_custom():
    stats = ReviewStats(
        total_issues=10,
        valid_issues=8,
        fixed_issues=5,
        auto_fixed=3,
        failed_fixes=1,
        handoffs_generated=2,
        tokens_used=50000,
        duration_seconds=120.5,
    )

    assert stats.total_issues == 10
    assert stats.valid_issues == 8
    assert stats.fixed_issues == 5
    assert stats.auto_fixed == 3
    assert stats.handoffs_generated == 2


def test_handoff_issue():
    issue = ReviewIssue(
        file_path="src/db.py",
        line_number=100,
        severity=Severity.HIGH,
        category=IssueCategory.SECURITY,
        cwe_id="CWE-89",
        title="SQL Injection",
        description="SQL injection vulnerability",
        code_snippet="query = f'SELECT * FROM {table}'",
        auto_fixable=False,
    )

    handoff = HandoffIssue(
        issue=issue,
        root_cause="User input directly concatenated into SQL",
        verification_steps=[
            "Verify the fix compiles",
            "Run security tests",
            "Check for similar patterns elsewhere",
        ],
        effort_estimate="High",
        related_files=["src/auth.py", "src/models.py"],
    )

    assert handoff.issue == issue
    assert handoff.root_cause == "User input directly concatenated into SQL"
    assert len(handoff.verification_steps) == 3
    assert handoff.effort_estimate == "High"
    assert len(handoff.related_files) == 2


def test_handoff_plan():
    issue = ReviewIssue(
        file_path="src/main.py",
        line_number=1,
        severity=Severity.CRITICAL,
        category=IssueCategory.SECURITY,
        cwe_id="CWE-78",
        title="RCE",
        description="Remote code execution",
        code_snippet="eval(input())",
        auto_fixable=False,
    )

    handoff_issue = HandoffIssue(
        issue=issue,
        root_cause="eval with user input",
        verification_steps=["Test fix"],
        effort_estimate="Medium",
        related_files=[],
    )

    plan = HandoffPlan(
        session_id="plan-001",
        target_path="./src",
        issues=[handoff_issue],
        generated_at="2026-03-30T10:00:00Z",
        markdown="# Handoff Plan\n\n## Issue\n\n...",
    )

    assert plan.session_id == "plan-001"
    assert len(plan.issues) == 1
    assert plan.markdown.startswith("# Handoff Plan")


# ---------------------------------------------------------------------------
# [TY-CR] Enum .name / .value convention tests
# ---------------------------------------------------------------------------


def test_severity_value_is_int_for_persistence():
    """[TY-CR] Severity.value must be an int — used for JSON persistence and comparisons."""
    for member in Severity:
        assert isinstance(member.value, int), (
            f"Severity.{member.name}.value should be int, got {type(member.value)}"
        )


def test_severity_name_is_upper_str_for_logs():
    """[TY-CR] Severity.name is the upper-case string used in log messages."""
    assert Severity.HIGH.name == "HIGH"
    assert Severity.CRITICAL.name == "CRITICAL"
    assert Severity.INFO.name == "INFO"


def test_issue_category_value_is_lowercase_str_for_persistence():
    """[TY-CR] IssueCategory.value must be a lowercase str — used for JSON persistence."""
    for member in IssueCategory:
        assert isinstance(member.value, str), (
            f"IssueCategory.{member.name}.value should be str, got {type(member.value)}"
        )
        assert member.value == member.value.lower(), (
            f"IssueCategory.{member.name}.value '{member.value}' must be lowercase"
        )


def test_issue_category_name_is_upper_str_for_logs():
    """[TY-CR] IssueCategory.name is the upper-case string used in log messages."""
    assert IssueCategory.SECURITY.name == "SECURITY"
    assert IssueCategory.BEST_PRACTICE.name == "BEST_PRACTICE"


def test_review_mode_value_is_lowercase_str():
    """[TY-CR] ReviewMode.value is a lowercase str — used for persistence/JSON."""
    from tools.muscle.code_review.types import ReviewMode

    for member in ReviewMode:
        assert isinstance(member.value, str), f"ReviewMode.{member.name}.value should be str"


# ---------------------------------------------------------------------------
# [CR-05] ReviewConfig.max_issues_per_batch is present and documented
# ---------------------------------------------------------------------------


def test_review_config_has_max_issues_per_batch():
    """[CR-05] ReviewConfig must expose max_issues_per_batch (default 20)."""
    config = ReviewConfig(target_path="./src")
    assert hasattr(config, "max_issues_per_batch")
    assert config.max_issues_per_batch == 20


def test_review_config_max_issues_per_batch_overridable():
    """[CR-05] ReviewConfig.max_issues_per_batch must be overridable."""
    config = ReviewConfig(target_path="./src", max_issues_per_batch=10)
    assert config.max_issues_per_batch == 10

# Learning Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire MUSCLE's existing MemoryManager, SkillGenerator, and PatternDetector into a self-learning pipeline that dynamically updates CLAUDE.md, MEMORY.md, and project-specific skills after every review.

**Architecture:** New `LearningPipeline` class orchestrates existing components. Called from CLI layer after `ReviewController.run()` completes. Validates past rules, promotes recurring patterns, archives stale rules.

**Tech Stack:** Python 3.10+, existing M2.7 client, existing MemoryManager/PatternDetector/SkillGenerator

---

### Task 1: Fix MemoryManager Markers and Add Structured Section Support

**Files:**
- Modify: `tools/muscle/code_review/memory_manager.py`
- Modify: `tools/muscle/tui/project_manager.py:147-166`
- Test: `tests/unit/test_memory_manager.py`

- [ ] **Step 1: Write failing test for new CLAUDE.md structured sections**

```python
# In tests/unit/test_memory_manager.py — add at end of file

class TestStructuredClaudeMd:
    def test_write_do_rule(self, tmp_path):
        mm = MemoryManager(str(tmp_path))
        mm.write_rule(
            rule_text="Use logger.getLogger(__name__) for all logging",
            rule_type="do",
            severity="high",
            confidence="high",
            validated_count=3,
        )
        content = (tmp_path / ".muscle" / "CLAUDE.md").read_text()
        assert "### Do" in content
        assert "logger.getLogger" in content
        assert "confidence: high" in content
        assert "validated: 3x" in content

    def test_write_dont_rule(self, tmp_path):
        mm = MemoryManager(str(tmp_path))
        mm.write_rule(
            rule_text="Never catch bare except: without specifying exception type",
            rule_type="dont",
            severity="high",
            confidence="medium",
            validated_count=1,
        )
        content = (tmp_path / ".muscle" / "CLAUDE.md").read_text()
        assert "### Don't" in content
        assert "bare except" in content

    def test_write_skill_reference(self, tmp_path):
        mm = MemoryManager(str(tmp_path))
        mm.write_rule(
            rule_text="Use logger.getLogger(__name__) for all logging",
            rule_type="do",
            severity="high",
            confidence="high",
            validated_count=3,
        )
        mm.write_skill_ref("auth-validation", ".muscle/skills/auth-validation.md")
        content = (tmp_path / ".muscle" / "CLAUDE.md").read_text()
        assert "### Project Skills" in content
        assert "auth-validation" in content

    def test_dedup_rules(self, tmp_path):
        mm = MemoryManager(str(tmp_path))
        mm.write_rule(
            rule_text="Use logger for logging",
            rule_type="do",
            severity="high",
            confidence="high",
            validated_count=1,
        )
        mm.write_rule(
            rule_text="Use logger for logging",
            rule_type="do",
            severity="high",
            confidence="high",
            validated_count=2,
        )
        content = (tmp_path / ".muscle" / "CLAUDE.md").read_text()
        assert content.count("Use logger for logging") == 1

    def test_read_rules(self, tmp_path):
        mm = MemoryManager(str(tmp_path))
        mm.write_rule(
            rule_text="Use logger",
            rule_type="do",
            severity="high",
            confidence="high",
            validated_count=3,
        )
        rules = mm.read_rules()
        assert len(rules) == 1
        assert rules[0]["text"] == "Use logger"
        assert rules[0]["type"] == "do"
        assert rules[0]["validated_count"] == 3

    def test_update_rule_validated_count(self, tmp_path):
        mm = MemoryManager(str(tmp_path))
        mm.write_rule(
            rule_text="Use logger",
            rule_type="do",
            severity="high",
            confidence="low",
            validated_count=1,
        )
        mm.update_rule_validation("Use logger", validated_count=4, confidence="high")
        rules = mm.read_rules()
        assert rules[0]["validated_count"] == 4
        assert rules[0]["confidence"] == "high"

    def test_archive_rule(self, tmp_path):
        mm = MemoryManager(str(tmp_path))
        mm.write_rule(
            rule_text="Old rule",
            rule_type="do",
            severity="low",
            confidence="high",
            validated_count=10,
        )
        mm.archive_rule("Old rule", reason="not seen in 12 reviews")
        claude_content = (tmp_path / ".muscle" / "CLAUDE.md").read_text()
        assert "Old rule" not in claude_content
        memory_content = (tmp_path / ".muscle" / "MEMORY.md").read_text()
        assert "Old rule" in memory_content
        assert "not seen in 12 reviews" in memory_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/unit/test_memory_manager.py::TestStructuredClaudeMd -v`
Expected: FAIL — methods `write_rule`, `read_rules`, `update_rule_validation`, `archive_rule`, `write_skill_ref` don't exist

- [ ] **Step 3: Fix project_manager.py marker mismatch**

In `tools/muscle/tui/project_manager.py`, change lines 154-158:

```python
        agent_md = muscle_dir / AGENT_MEMORY
        if not agent_md.exists():
            agent_md.write_text("""<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE_LEARNED_END -->
""")
```

- [ ] **Step 4: Add new markers and structured methods to MemoryManager**

In `tools/muscle/code_review/memory_manager.py`, add new markers and methods:

```python
RULES_START = "<!-- MUSCLE_RULES_START -->"
RULES_END = "<!-- MUSCLE_RULES_END -->"
MEMORY_START = "<!-- MUSCLE_MEMORY_START -->"
MEMORY_END = "<!-- MUSCLE_MEMORY_END -->"
```

Add to the `MemoryManager` class:

```python
    def _ensure_claude_md_structure(self) -> Path:
        """Ensure CLAUDE.md exists with structured rules section."""
        filepath = self.muscle_dir / "CLAUDE.md"
        if not filepath.exists():
            filepath.write_text(
                f"## MUSCLE Learned Rules\n"
                f"{RULES_START}\n\n"
                f"### Do\n\n"
                f"### Don't\n\n"
                f"### Project Skills\n\n"
                f"{RULES_END}\n"
            )
        else:
            content = filepath.read_text()
            if RULES_START not in content:
                content += (
                    f"\n## MUSCLE Learned Rules\n"
                    f"{RULES_START}\n\n"
                    f"### Do\n\n"
                    f"### Don't\n\n"
                    f"### Project Skills\n\n"
                    f"{RULES_END}\n"
                )
                filepath.write_text(content)
        return filepath

    def _ensure_memory_md_structure(self) -> Path:
        """Ensure MEMORY.md exists with structured sections."""
        filepath = self.muscle_dir / "MEMORY.md"
        if not filepath.exists():
            filepath.write_text(
                f"# MUSCLE Memory\n"
                f"{MEMORY_START}\n\n"
                f"## Pattern History\n\n"
                f"## Archived Rules\n\n"
                f"## Fix History\n\n"
                f"## Review Sessions\n\n"
                f"{MEMORY_END}\n"
            )
        return filepath

    def _extract_rules_section(self, content: str) -> str:
        match = re.search(
            rf"{re.escape(RULES_START)}(.*?){re.escape(RULES_END)}",
            content,
            re.DOTALL,
        )
        return match.group(1) if match else ""

    def write_rule(
        self,
        rule_text: str,
        rule_type: str,
        severity: str,
        confidence: str,
        validated_count: int,
    ) -> bool:
        """Write a rule to the appropriate section of CLAUDE.md."""
        filepath = self._ensure_claude_md_structure()
        content = filepath.read_text()
        section = self._extract_rules_section(content)

        if rule_text.lower().strip() in section.lower():
            return False

        entry = f"- {rule_text} (confidence: {confidence}, validated: {validated_count}x)"
        header = "### Do" if rule_type == "do" else "### Don't"

        lines = section.split("\n")
        insert_idx = None
        for i, line in enumerate(lines):
            if line.strip() == header:
                # Find the next header or end
                for j in range(i + 1, len(lines)):
                    if lines[j].strip().startswith("### "):
                        insert_idx = j
                        break
                else:
                    insert_idx = len(lines)
                break

        if insert_idx is not None:
            lines.insert(insert_idx, entry)
            new_section = "\n".join(lines)
            new_content = content.replace(section, new_section)
            filepath.write_text(new_content)
            return True
        return False

    def write_skill_ref(self, skill_name: str, skill_path: str) -> bool:
        """Register a skill reference in the Project Skills section of CLAUDE.md."""
        filepath = self._ensure_claude_md_structure()
        content = filepath.read_text()
        section = self._extract_rules_section(content)

        if skill_name in section:
            return False

        entry = f"- `{skill_path}` — {skill_name}"
        lines = section.split("\n")
        for i, line in enumerate(lines):
            if line.strip() == "### Project Skills":
                lines.insert(i + 1, entry)
                break

        new_section = "\n".join(lines)
        new_content = content.replace(section, new_section)
        filepath.write_text(new_content)
        return True

    def read_rules(self) -> list[dict]:
        """Parse all rules from CLAUDE.md into structured dicts."""
        filepath = self.muscle_dir / "CLAUDE.md"
        if not filepath.exists():
            return []

        content = filepath.read_text()
        section = self._extract_rules_section(content)
        rules = []
        current_type = None

        for line in section.split("\n"):
            stripped = line.strip()
            if stripped == "### Do":
                current_type = "do"
            elif stripped == "### Don't":
                current_type = "dont"
            elif stripped == "### Project Skills":
                current_type = None
            elif stripped.startswith("- ") and current_type:
                text, confidence, validated = self._parse_rule_line(stripped)
                if text:
                    rules.append({
                        "text": text,
                        "type": current_type,
                        "confidence": confidence,
                        "validated_count": validated,
                    })
        return rules

    def _parse_rule_line(self, line: str) -> tuple[str, str, int]:
        """Parse '- Rule text (confidence: X, validated: Nx)' into components."""
        line = line.lstrip("- ").strip()
        match = re.search(r'\(confidence:\s*(\w+),\s*validated:\s*(\d+)x\)', line)
        if match:
            text = line[:match.start()].strip()
            confidence = match.group(1)
            validated = int(match.group(2))
            return text, confidence, validated
        return line, "low", 0

    def update_rule_validation(
        self, rule_text: str, validated_count: int, confidence: str
    ) -> bool:
        """Update a rule's validation count and confidence in CLAUDE.md."""
        filepath = self.muscle_dir / "CLAUDE.md"
        if not filepath.exists():
            return False

        content = filepath.read_text()
        rules = self.read_rules()
        for rule in rules:
            if rule["text"] == rule_text:
                old_entry = f"- {rule['text']} (confidence: {rule['confidence']}, validated: {rule['validated_count']}x)"
                new_entry = f"- {rule_text} (confidence: {confidence}, validated: {validated_count}x)"
                content = content.replace(old_entry, new_entry)
                filepath.write_text(content)
                return True
        return False

    def archive_rule(self, rule_text: str, reason: str) -> bool:
        """Move a rule from CLAUDE.md to MEMORY.md archived section."""
        filepath = self.muscle_dir / "CLAUDE.md"
        if not filepath.exists():
            return False

        content = filepath.read_text()
        rules = self.read_rules()
        for rule in rules:
            if rule["text"] == rule_text:
                old_entry = f"- {rule['text']} (confidence: {rule['confidence']}, validated: {rule['validated_count']}x)"
                content = content.replace(old_entry + "\n", "")
                content = content.replace(old_entry, "")
                filepath.write_text(content)

                self._ensure_memory_md_structure()
                mem_path = self.muscle_dir / "MEMORY.md"
                mem_content = mem_path.read_text()
                timestamp = datetime.now().strftime("%Y-%m-%d")
                archive_entry = f"- [{timestamp}] \"{rule_text}\" — {reason}"
                mem_content = mem_content.replace(
                    "## Archived Rules\n",
                    f"## Archived Rules\n{archive_entry}\n",
                )
                mem_path.write_text(mem_content)
                return True
        return False

    def log_review_session(self, critical: int, high: int, medium: int, low: int, actions: str) -> bool:
        """Log a review session summary to MEMORY.md."""
        self._ensure_memory_md_structure()
        mem_path = self.muscle_dir / "MEMORY.md"
        mem_content = mem_path.read_text()
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"- {timestamp}: {critical} critical, {high} high, {medium} medium, {low} low — {actions}"
        mem_content = mem_content.replace(
            "## Review Sessions\n",
            f"## Review Sessions\n{entry}\n",
        )
        mem_path.write_text(mem_content)
        return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/unit/test_memory_manager.py::TestStructuredClaudeMd -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite for regressions**

Run: `python3 -m pytest tests/unit/test_memory_manager.py -v`
Expected: All PASS (existing + new)

- [ ] **Step 7: Commit**

```bash
git add tools/muscle/code_review/memory_manager.py tools/muscle/tui/project_manager.py tests/unit/test_memory_manager.py
git commit -m "feat: add structured CLAUDE.md rules and validation tracking to MemoryManager"
```

---

### Task 2: Create LearningPipeline

**Files:**
- Create: `tools/muscle/code_review/learning_pipeline.py`
- Test: `tests/unit/test_learning_pipeline.py`

- [ ] **Step 1: Write failing tests for LearningPipeline**

```python
"""Tests for LearningPipeline — the self-learning orchestrator."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from tools.muscle.code_review.learning_pipeline import LearningPipeline
from tools.muscle.code_review.types import (
    ReviewResult,
    ReviewIssue,
    Severity,
    IssueCategory,
)


def _make_issue(
    title="Test issue",
    severity=Severity.HIGH,
    category=IssueCategory.CORRECTNESS,
    file_path="src/foo.py",
    line_number=10,
):
    return ReviewIssue(
        file_path=file_path,
        line_number=line_number,
        severity=severity,
        category=category,
        cwe_id=None,
        title=title,
        description="Test description",
        code_snippet="x = 1",
        suggested_fix="Fix it",
    )


def _make_review_result(issues=None):
    return ReviewResult(
        session_id="test-session",
        target_path="./src",
        issues=issues or [],
        critical_count=sum(1 for i in (issues or []) if i.severity == Severity.CRITICAL),
        high_count=sum(1 for i in (issues or []) if i.severity == Severity.HIGH),
        medium_count=sum(1 for i in (issues or []) if i.severity == Severity.MEDIUM),
        low_count=sum(1 for i in (issues or []) if i.severity == Severity.LOW),
    )


class TestLearningPipelineCategorize:
    def test_high_critical_promoted_immediately(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        issues = [
            _make_issue(title="Critical bug", severity=Severity.CRITICAL),
            _make_issue(title="High bug", severity=Severity.HIGH),
            _make_issue(title="Medium bug", severity=Severity.MEDIUM),
        ]
        result = _make_review_result(issues)
        immediate, tracked = pipeline._categorize_findings(result)
        assert len(immediate) == 2
        assert len(tracked) == 1

    def test_empty_review_returns_empty(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        result = _make_review_result([])
        immediate, tracked = pipeline._categorize_findings(result)
        assert immediate == []
        assert tracked == []


class TestLearningPipelineUpdateClaudeMd:
    def test_high_issue_creates_dont_rule(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        issues = [_make_issue(title="Bare except clause found", severity=Severity.HIGH)]
        result = _make_review_result(issues)
        pipeline.learn_from_review(result)

        claude_md = tmp_path / ".muscle" / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "Bare except clause found" in content

    def test_no_issues_no_update(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        result = _make_review_result([])
        pipeline.learn_from_review(result)

        claude_md = tmp_path / ".muscle" / "CLAUDE.md"
        if claude_md.exists():
            content = claude_md.read_text()
            assert "### Do" not in content or content.count("- ") == 0


class TestLearningPipelineValidation:
    def test_rule_validated_when_pattern_absent(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        pipeline.memory_manager.write_rule(
            rule_text="Use logger instead of print",
            rule_type="do",
            severity="high",
            confidence="low",
            validated_count=1,
        )
        result = _make_review_result([])
        pipeline._validate_existing_rules(result)

        rules = pipeline.memory_manager.read_rules()
        assert rules[0]["validated_count"] == 2

    def test_confidence_upgrades(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        pipeline.memory_manager.write_rule(
            rule_text="Use logger",
            rule_type="do",
            severity="high",
            confidence="low",
            validated_count=1,
        )
        result = _make_review_result([])
        pipeline._validate_existing_rules(result)

        rules = pipeline.memory_manager.read_rules()
        assert rules[0]["confidence"] == "medium"

    def test_stale_rule_archived(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        pipeline.memory_manager.write_rule(
            rule_text="Old stale rule",
            rule_type="do",
            severity="low",
            confidence="high",
            validated_count=12,
        )
        result = _make_review_result([])
        pipeline._validate_existing_rules(result)

        rules = pipeline.memory_manager.read_rules()
        assert len(rules) == 0 or rules[0]["text"] != "Old stale rule"

        memory_md = tmp_path / ".muscle" / "MEMORY.md"
        content = memory_md.read_text()
        assert "Old stale rule" in content


class TestLearningPipelineMemoryMd:
    def test_review_session_logged(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        issues = [_make_issue(severity=Severity.HIGH)]
        result = _make_review_result(issues)
        pipeline.learn_from_review(result)

        memory_md = tmp_path / ".muscle" / "MEMORY.md"
        assert memory_md.exists()
        content = memory_md.read_text()
        assert "Review Sessions" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/unit/test_learning_pipeline.py -v`
Expected: FAIL — `learning_pipeline` module doesn't exist

- [ ] **Step 3: Implement LearningPipeline**

Create `tools/muscle/code_review/learning_pipeline.py`:

```python
"""
Learning Pipeline - Orchestrates the self-learning cycle after reviews.

Wires together MemoryManager, PatternDetector, and SkillGenerator to:
1. Categorize findings by severity
2. Update CLAUDE.md with rules + anti-patterns (high/critical immediately)
3. Update MEMORY.md with pattern history and review sessions
4. Detect recurring patterns and generate skills
5. Validate existing rules and archive stale ones
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .memory_manager import MemoryManager
from .pattern_detector import PatternDetector
from .skill_generator import SkillGenerator
from .types import ReviewResult, Severity

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLDS = {
    1: "low",
    2: "medium",
    4: "high",
}

ARCHIVE_VALIDATED_THRESHOLD = 10
REWRITE_FAILURE_THRESHOLD = 3


class LearningPipeline:
    """Orchestrates the full self-learning cycle after a review."""

    def __init__(
        self,
        project_path: str,
        m27_client: Any | None = None,
        kb_path: str | None = None,
    ):
        self.project_path = Path(project_path)
        self.memory_manager = MemoryManager(project_path, m27_client)
        self.m27 = m27_client
        self._kb_path = kb_path

    def learn_from_review(self, review_result: ReviewResult) -> dict:
        """Main entry point — called after every review completes.

        Returns a summary dict of actions taken.
        """
        actions = {
            "rules_added": 0,
            "rules_validated": 0,
            "rules_archived": 0,
            "skills_generated": 0,
            "session_logged": False,
        }

        if not review_result.issues:
            self._validate_existing_rules(review_result)
            self._log_review_session(review_result, actions)
            return actions

        immediate, tracked = self._categorize_findings(review_result)

        for issue in immediate:
            rule_type = "dont"
            rule_text = f"{issue.title} in `{issue.file_path}`"
            if issue.suggested_fix:
                rule_text = f"{issue.title} — {issue.suggested_fix}"

            added = self.memory_manager.write_rule(
                rule_text=rule_text,
                rule_type=rule_type,
                severity=issue.severity.name.lower(),
                confidence="low",
                validated_count=0,
            )
            if added:
                actions["rules_added"] += 1

        for issue in tracked:
            self.memory_manager.update_memory_md(
                f"{issue.severity.name}: {issue.title} in `{issue.file_path}`",
                category="pattern",
            )

        self._validate_existing_rules(review_result)
        actions["rules_validated"] = self._last_validated_count
        actions["rules_archived"] = self._last_archived_count

        skills = self._detect_and_generate_skills()
        actions["skills_generated"] = skills

        self._log_review_session(review_result, actions)
        actions["session_logged"] = True

        return actions

    def _categorize_findings(
        self, review_result: ReviewResult
    ) -> tuple[list, list]:
        """Split findings: high/critical → immediate, medium/low → tracked."""
        immediate = []
        tracked = []

        for issue in review_result.issues:
            if issue.severity in (Severity.CRITICAL, Severity.HIGH):
                immediate.append(issue)
            else:
                tracked.append(issue)

        return immediate, tracked

    _last_validated_count: int = 0
    _last_archived_count: int = 0

    def _validate_existing_rules(self, review_result: ReviewResult) -> None:
        """Check each rule: was the pattern found? Strengthen or archive."""
        self._last_validated_count = 0
        self._last_archived_count = 0

        rules = self.memory_manager.read_rules()
        issue_titles_lower = {i.title.lower() for i in review_result.issues}

        for rule in rules:
            rule_text_lower = rule["text"].lower()

            pattern_found = any(
                title in rule_text_lower or rule_text_lower in title
                for title in issue_titles_lower
            )

            if not pattern_found:
                new_count = rule["validated_count"] + 1
                new_confidence = self._compute_confidence(new_count)

                if new_count >= ARCHIVE_VALIDATED_THRESHOLD and new_confidence == "high":
                    self.memory_manager.archive_rule(
                        rule["text"],
                        reason=f"not seen in {new_count}+ clean reviews",
                    )
                    self._last_archived_count += 1
                else:
                    self.memory_manager.update_rule_validation(
                        rule["text"],
                        validated_count=new_count,
                        confidence=new_confidence,
                    )
                    self._last_validated_count += 1

    def _compute_confidence(self, validated_count: int) -> str:
        """Compute confidence level from validation count."""
        if validated_count >= 4:
            return "high"
        if validated_count >= 2:
            return "medium"
        return "low"

    def _detect_and_generate_skills(self) -> int:
        """Run pattern detection and generate skills for recurring patterns."""
        try:
            detector = PatternDetector(kb_path=self._kb_path, m27_client=self.m27)
            patterns = detector.detect_patterns()
            candidates = detector.get_skill_candidates()

            if not candidates:
                return 0

            generator = SkillGenerator(str(self.project_path), self.m27)
            count = 0

            for pattern in candidates:
                if detector.should_create_skill(pattern):
                    skill_path = generator.generate_skill(
                        pattern,
                        pattern.semantically_related_issues,
                    )
                    if skill_path:
                        self.memory_manager.write_skill_ref(
                            pattern.pattern[:40],
                            skill_path,
                        )
                        count += 1

            return count
        except Exception as e:
            logger.warning(f"Skill generation failed: {e}")
            return 0

    def _log_review_session(self, review_result: ReviewResult, actions: dict) -> None:
        """Log review session summary to MEMORY.md."""
        action_parts = []
        if actions.get("rules_added"):
            action_parts.append(f"added {actions['rules_added']} rules")
        if actions.get("rules_validated"):
            action_parts.append(f"validated {actions['rules_validated']} rules")
        if actions.get("rules_archived"):
            action_parts.append(f"archived {actions['rules_archived']} rules")
        if actions.get("skills_generated"):
            action_parts.append(f"generated {actions['skills_generated']} skills")

        actions_str = ", ".join(action_parts) if action_parts else "no actions"

        self.memory_manager.log_review_session(
            critical=review_result.critical_count,
            high=review_result.high_count,
            medium=review_result.medium_count,
            low=review_result.low_count,
            actions=actions_str,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/unit/test_learning_pipeline.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tools/muscle/code_review/learning_pipeline.py tests/unit/test_learning_pipeline.py
git commit -m "feat: add LearningPipeline orchestrator for self-learning after reviews"
```

---

### Task 3: Wire LearningPipeline into CLI Review Command

**Files:**
- Modify: `tools/muscle/cli.py:1367-1417`
- Test: `tests/unit/test_cli_review.py`

- [ ] **Step 1: Write failing test for post-review learning**

```python
# Add to tests/unit/test_cli_review.py

class TestReviewLearningIntegration:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_review_calls_learning_pipeline(self, runner, tmp_path):
        with patch("tools.muscle.cli.M27Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.api_key = "test-key"
            mock_client_cls.return_value = mock_client

            with patch("tools.muscle.cli.ReviewController") as mock_ctrl_cls:
                mock_ctrl = MagicMock()
                mock_result = MagicMock()
                mock_result.handoff_plan = None
                mock_ctrl.run.return_value = mock_result
                mock_ctrl.get_review_result.return_value = MagicMock(
                    session_id="test",
                    target_path=str(tmp_path),
                    issues=[],
                    critical_count=0,
                    high_count=0,
                    medium_count=0,
                    low_count=0,
                    info_count=0,
                )
                mock_ctrl_cls.return_value = mock_ctrl

                with patch("tools.muscle.cli.LearningPipeline") as mock_pipeline_cls:
                    mock_pipeline = MagicMock()
                    mock_pipeline.learn_from_review.return_value = {"rules_added": 0}
                    mock_pipeline_cls.return_value = mock_pipeline

                    with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}):
                        result = runner.invoke(
                            review,
                            ["--target", str(tmp_path)],
                            catch_exceptions=False,
                        )

                    mock_pipeline.learn_from_review.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_cli_review.py::TestReviewLearningIntegration -v`
Expected: FAIL — LearningPipeline not imported or called in cli.py

- [ ] **Step 3: Wire LearningPipeline into cli.py review command**

In `tools/muscle/cli.py`, add import near top (after existing imports):

```python
from .code_review.learning_pipeline import LearningPipeline
```

In the `review` function, after line 1369 (`review_result = controller.get_review_result()`), add:

```python
        # Self-learning: update CLAUDE.md, MEMORY.md, and skills
        if review_result:
            try:
                pipeline = LearningPipeline(
                    project_path=str(Path(target).resolve().parent) if Path(target).is_file() else target,
                    m27_client=m27_client,
                )
                learn_result = pipeline.learn_from_review(review_result)
                if learn_result.get("rules_added"):
                    console.print(
                        f"[cyan]Learned {learn_result['rules_added']} new rules[/cyan]"
                    )
                if learn_result.get("skills_generated"):
                    console.print(
                        f"[cyan]Generated {learn_result['skills_generated']} new skills[/cyan]"
                    )
            except Exception as e:
                logger.warning(f"Learning pipeline failed: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_cli_review.py::TestReviewLearningIntegration -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/unit/ -q`
Expected: All pass, no regressions

- [ ] **Step 6: Commit**

```bash
git add tools/muscle/cli.py tests/unit/test_cli_review.py
git commit -m "feat: wire LearningPipeline into review command for automatic learning"
```

---

### Task 4: Wire LearningPipeline into Nightly Runner

**Files:**
- Modify: `tools/muscle/code_review/nightly_runner.py:84-88`
- Test: `tests/unit/test_nightly_runner.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/unit/test_nightly_runner.py

class TestNightlyLearningIntegration:
    def test_nightly_run_calls_learning_pipeline(self, tmp_path):
        config = NightlyConfig(
            enabled=True,
            target_paths=[str(tmp_path)],
        )
        runner = NightlyRunner(str(tmp_path), config)

        with patch.object(runner, "_run_review") as mock_review:
            mock_review.return_value = {
                "issues": [],
                "critical_issues": [],
                "high_issues": [],
                "total_issues": 0,
            }
            with patch("tools.muscle.code_review.nightly_runner.LearningPipeline") as mock_pl:
                mock_pipeline = MagicMock()
                mock_pipeline.learn_from_review.return_value = {}
                mock_pl.return_value = mock_pipeline

                runner.run_nightly()

                mock_pl.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_nightly_runner.py::TestNightlyLearningIntegration -v`
Expected: FAIL

- [ ] **Step 3: Add LearningPipeline call to nightly_runner.py**

In `tools/muscle/code_review/nightly_runner.py`, add import:

```python
from .learning_pipeline import LearningPipeline
from .types import ReviewResult
```

After line 84 (`self._save_report(results)`), add:

```python
        # Self-learning from nightly review
        try:
            pipeline = LearningPipeline(str(self.project_path))
            review_result = ReviewResult(
                session_id=f"nightly-{start_time.strftime('%Y%m%d')}",
                target_path=str(self.project_path),
                critical_count=len(results.get("critical_issues", [])),
                high_count=len(results.get("high_issues", [])),
                medium_count=results.get("total_issues", 0) - len(results.get("critical_issues", [])) - len(results.get("high_issues", [])),
                low_count=0,
            )
            pipeline.learn_from_review(review_result)
        except Exception as e:
            logger.warning(f"Nightly learning pipeline failed: {e}")
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/unit/test_nightly_runner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tools/muscle/code_review/nightly_runner.py tests/unit/test_nightly_runner.py
git commit -m "feat: wire LearningPipeline into nightly runner"
```

---

### Task 5: Add Skill Lifecycle Methods to SkillGenerator

**Files:**
- Modify: `tools/muscle/code_review/skill_generator.py`
- Test: `tests/unit/test_skill_generator.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/unit/test_skill_generator.py

class TestSkillLifecycle:
    def test_update_skill_appends_context(self, tmp_path):
        gen = SkillGenerator(str(tmp_path), m27_client=MagicMock())
        skill_path = tmp_path / ".muscle" / "skills" / "test_skill.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("---\nname: test\n---\n\n# Test\n\nOriginal content")

        gen.update_skill(skill_path, "New context discovered")

        content = skill_path.read_text()
        assert "New context discovered" in content
        assert "Original content" in content

    def test_archive_skill(self, tmp_path):
        gen = SkillGenerator(str(tmp_path), m27_client=MagicMock())
        skill_path = tmp_path / ".muscle" / "skills" / "stale_skill.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("---\nname: stale\n---\n\n# Stale skill")

        archived = gen.archive_skill(skill_path)
        assert not skill_path.exists()
        assert archived.exists()
        assert "archived" in str(archived)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/unit/test_skill_generator.py::TestSkillLifecycle -v`
Expected: FAIL

- [ ] **Step 3: Add lifecycle methods**

In `tools/muscle/code_review/skill_generator.py`, add:

```python
    def update_skill(self, skill_path: Path, new_context: str) -> bool:
        """Append new context to an existing skill."""
        if not skill_path.exists():
            return False

        content = skill_path.read_text()
        timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        update_section = f"\n\n## Update ({timestamp})\n\n{new_context}\n"
        content += update_section
        skill_path.write_text(content)
        logger.info(f"Updated skill: {skill_path}")
        return True

    def archive_skill(self, skill_path: Path) -> Path:
        """Move a skill to the archived directory."""
        archive_dir = self.skills_dir / "archived"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived_path = archive_dir / skill_path.name
        skill_path.rename(archived_path)
        logger.info(f"Archived skill: {skill_path} -> {archived_path}")
        return archived_path
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/unit/test_skill_generator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tools/muscle/code_review/skill_generator.py tests/unit/test_skill_generator.py
git commit -m "feat: add skill update and archive lifecycle methods"
```

---

### Task 6: End-to-End Integration Test

**Files:**
- Test: `tests/unit/test_learning_pipeline.py` (add integration tests)

- [ ] **Step 1: Write end-to-end test**

```python
# Add to tests/unit/test_learning_pipeline.py

class TestLearningPipelineEndToEnd:
    def test_full_cycle_learn_validate_archive(self, tmp_path):
        """Simulate: review with issues → rules added → clean review → rules validated → many clean reviews → rule archived."""
        pipeline = LearningPipeline(str(tmp_path))

        # Review 1: issues found → rules added
        issues = [
            _make_issue(title="Use print instead of logger", severity=Severity.HIGH),
            _make_issue(title="Missing null check", severity=Severity.CRITICAL),
        ]
        result1 = _make_review_result(issues)
        actions1 = pipeline.learn_from_review(result1)
        assert actions1["rules_added"] == 2

        rules = pipeline.memory_manager.read_rules()
        assert len(rules) == 2
        assert all(r["confidence"] == "low" for r in rules)

        # Review 2: clean → rules validated, confidence upgrades
        result2 = _make_review_result([])
        actions2 = pipeline.learn_from_review(result2)
        assert actions2["rules_validated"] == 2

        rules = pipeline.memory_manager.read_rules()
        assert all(r["validated_count"] >= 1 for r in rules)

        # Review 3: clean again → further validation
        result3 = _make_review_result([])
        pipeline.learn_from_review(result3)

        rules = pipeline.memory_manager.read_rules()
        assert any(r["confidence"] == "medium" for r in rules)

    def test_memory_md_tracks_sessions(self, tmp_path):
        pipeline = LearningPipeline(str(tmp_path))
        issues = [_make_issue(severity=Severity.HIGH)]
        result = _make_review_result(issues)
        pipeline.learn_from_review(result)

        memory_md = tmp_path / ".muscle" / "MEMORY.md"
        content = memory_md.read_text()
        assert "Review Sessions" in content
        assert "1 high" in content.lower() or "high" in content.lower()

    def test_outside_markers_untouched(self, tmp_path):
        """Verify that content outside MUSCLE markers is never modified."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir(parents=True, exist_ok=True)
        claude_md = muscle_dir / "CLAUDE.md"
        claude_md.write_text(
            "# My Project Rules\n\nDo not touch this.\n\n"
            "## MUSCLE Learned Rules\n"
            "<!-- MUSCLE_RULES_START -->\n\n"
            "### Do\n\n### Don't\n\n### Project Skills\n\n"
            "<!-- MUSCLE_RULES_END -->\n"
        )

        pipeline = LearningPipeline(str(tmp_path))
        issues = [_make_issue(title="New issue", severity=Severity.HIGH)]
        result = _make_review_result(issues)
        pipeline.learn_from_review(result)

        content = claude_md.read_text()
        assert "# My Project Rules" in content
        assert "Do not touch this." in content
        assert "New issue" in content
```

- [ ] **Step 2: Run all learning pipeline tests**

Run: `python3 -m pytest tests/unit/test_learning_pipeline.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/unit/ -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_learning_pipeline.py
git commit -m "test: add end-to-end integration tests for learning pipeline"
```

---

## Execution Checklist

| Task | Description | Depends On |
|------|------------|------------|
| 1 | MemoryManager structured sections + marker fix | None |
| 2 | LearningPipeline core class | Task 1 |
| 3 | Wire into CLI review command | Task 2 |
| 4 | Wire into nightly runner | Task 2 |
| 5 | Skill lifecycle methods | None |
| 6 | End-to-end integration tests | Tasks 1-4 |

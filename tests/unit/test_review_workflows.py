from __future__ import annotations

from pathlib import Path

from tools.muscle.code_review.review_artifacts import ReviewArtifactStore
from tools.muscle.code_review.review_workflows import ReviewWorkflowEngine, ReviewWorkflowLoader
from tools.muscle.code_review.types import IssueCategory, ReviewIssue, ReviewScope, Severity


class TestReviewWorkflowLoader:
    def test_loads_builtin_workflow(self):
        loader = ReviewWorkflowLoader()
        workflow = loader.load("review-smart")

        assert workflow.name == "review-smart"
        assert [node.node_type for node in workflow.nodes][:2] == ["classify", "review_agent"]
        assert workflow.ordered_nodes()[0].id == "classify"

    def test_engine_respects_agent_condition(self):
        loader = ReviewWorkflowLoader()
        workflow = loader.load("review-smart")
        engine = ReviewWorkflowEngine()
        scope = ReviewScope(
            complexity="small",
            review_agents=["correctness_security"],
        )

        def should_run(node, _outputs):
            if node.when is None:
                return True
            if node.when.startswith("agent_enabled:"):
                return node.when.split(":", 1)[1] in scope.review_agents
            return True

        def handler(node, _outputs):
            return node.id

        handlers = dict.fromkeys({"classify", "review_agent", "synthesize", "gate"}, handler)
        result = engine.execute(workflow, handlers, should_run)

        assert "correctness-security" in result.executed_nodes
        assert "error-handling" in result.skipped_nodes
        assert result.executed_nodes[0] == "classify"


class TestReviewArtifactStore:
    def test_writes_required_artifacts(self, tmp_path: Path):
        store = ReviewArtifactStore(str(tmp_path), "sess123")
        issue = ReviewIssue(
            file_path="src/app.py",
            line_number=3,
            severity=Severity.HIGH,
            category=IssueCategory.CORRECTNESS,
            cwe_id=None,
            title="Issue",
            description="Desc",
            code_snippet="print('x')",
            source_agent="correctness_security",
        )

        store.write_scope(ReviewScope(complexity="small", review_agents=["correctness_security"]))
        store.write_agent_findings({"correctness_security": [issue]})
        store.write_synthesis([issue], {"high": 1})
        store.write_fixes({"applied": [], "failed": []})
        store.write_validation({"performed": False, "status": "not-run"})
        store.write_summary("# Summary\n")

        root = Path(store.artifact_dir)
        assert (root / "scope.json").exists()
        assert (root / "agent-findings.json").exists()
        assert (root / "synthesis.json").exists()
        assert (root / "fixes.json").exists()
        assert (root / "validation.json").exists()
        assert (root / "summary.md").exists()

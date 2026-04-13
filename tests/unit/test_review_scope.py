from __future__ import annotations

from pathlib import Path

from tools.muscle.code_review.review_scope import ReviewScopeClassifier, ScopeInputs
from tools.muscle.code_review.types import ReviewMode


class TestReviewScopeClassifier:
    def test_smart_repo_review_defaults_to_correctness_only(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "service.py").write_text("def run() -> None:\n    pass\n", encoding="utf-8")
        (src / "helper.py").write_text("def helper() -> None:\n    pass\n", encoding="utf-8")

        classifier = ReviewScopeClassifier()
        scope = classifier.classify(
            ScopeInputs(
                target_path=str(src),
                workflow_name="review-smart",
                mode=ReviewMode.REVIEW,
            )
        )

        assert scope.complexity in {"small", "medium"}
        assert scope.review_agents == ["correctness_security"]

    def test_comprehensive_review_runs_full_committee(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "cli.py").write_text("def main() -> None:\n    pass\n", encoding="utf-8")

        classifier = ReviewScopeClassifier()
        scope = classifier.classify(
            ScopeInputs(
                target_path=str(src),
                workflow_name="review-comprehensive",
                mode=ReviewMode.REVIEW,
            )
        )

        assert scope.review_agents == [
            "correctness_security",
            "error_handling_concurrency",
            "test_impact_coverage",
            "docs_api_impact",
        ]

    def test_docs_only_scope_routes_to_docs_agent(self, tmp_path: Path):
        docs = tmp_path / "README.md"
        docs.write_text("# Docs only\n", encoding="utf-8")

        classifier = ReviewScopeClassifier()
        scope = classifier.classify(
            ScopeInputs(
                target_path=str(docs),
                workflow_name="review-smart",
                mode=ReviewMode.REVIEW,
            )
        )

        assert scope.docs_only is True
        assert scope.review_agents == ["docs_api_impact"]

    def test_single_file_fix_review_adds_specialists(self, tmp_path: Path):
        source = tmp_path / "api.py"
        source.write_text("import requests\nrequests.get('https://example.com')\n", encoding="utf-8")

        classifier = ReviewScopeClassifier()
        scope = classifier.classify(
            ScopeInputs(
                target_path=str(source),
                workflow_name="review-fix-verify",
                mode=ReviewMode.AUTO_FIX,
            )
        )

        assert "correctness_security" in scope.review_agents
        assert "error_handling_concurrency" in scope.review_agents
        assert "test_impact_coverage" in scope.review_agents

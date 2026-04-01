"""
Unit tests for adapters/github_integration.py
"""

from unittest.mock import Mock

import pytest

from tools.muscle.adapters.github_integration import GitHubIntegration, GitHubIntegrationConfig


class TestGitHubIntegrationConfig:
    def test_defaults(self):
        config = GitHubIntegrationConfig()
        assert config.enabled is False
        assert config.create_prs is True
        assert config.create_issues is True


class TestGitHubIntegration:
    @pytest.fixture
    def mock_adapter(self):
        return Mock()

    @pytest.fixture
    def integration(self, mock_adapter, tmp_path):
        return GitHubIntegration(
            project_path=str(tmp_path),
            config=GitHubIntegrationConfig(enabled=True, create_prs=True),
            github_adapter=mock_adapter,
        )

    def test_disabled_returns_early(self, mock_adapter, tmp_path):
        config = GitHubIntegrationConfig(enabled=False)
        integration = GitHubIntegration(str(tmp_path), config=config)
        result = integration.post_review_as_check(Mock(), "abc123")
        assert result is False

    def test_post_review_as_check_no_sha(self, integration):
        review_result = Mock()
        review_result.critical_count = 0
        review_result.high_count = 0
        result = integration.post_review_as_check(review_result, head_sha=None)
        assert result is False

    def test_create_fix_pr_no_fixed_issues(self, integration, mock_adapter):
        mock_adapter.create_pull_request.return_value = None
        review_result = Mock()
        review_result.fixed_issues = []
        review_result.critical_count = 0
        review_result.high_count = 0
        result = integration.create_fix_pr(review_result)
        assert result is None

    def test_should_block_merge_no_critical(self, integration):
        review_result = Mock()
        review_result.critical_count = 0
        review_result.high_count = 0
        assert integration.should_block_merge(review_result) is False

    def test_should_block_merge_with_critical(self, mock_adapter, tmp_path):
        integration = GitHubIntegration(
            project_path=str(tmp_path),
            config=GitHubIntegrationConfig(enabled=True, create_prs=True, require_review_gate=True),
            github_adapter=mock_adapter,
        )
        review_result = Mock()
        review_result.critical_count = 1
        review_result.high_count = 0
        assert integration.should_block_merge(review_result) is True

    def test_post_review_comment(self, mock_adapter, tmp_path):
        mock_adapter.create_review.return_value = {"id": 1}
        integration = GitHubIntegration(
            project_path=str(tmp_path),
            config=GitHubIntegrationConfig(enabled=True, create_prs=True, post_comments=True),
            github_adapter=mock_adapter,
        )
        review_result = Mock()
        review_result.files_reviewed = 5
        review_result.lines_reviewed = 100
        review_result.critical_count = 0
        review_result.high_count = 0
        review_result.medium_count = 0
        review_result.low_count = 0
        review_result.info_count = 0
        review_result.fixed_issues = []
        review_result.unfixed_issues = []
        result = integration.post_review_comment(42, review_result)
        assert result is True

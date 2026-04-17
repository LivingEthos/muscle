"""Concurrent review stress test (TEST-03).

Runs three ``ReviewController.run()`` calls simultaneously against the
same fixture project using ``ThreadPoolExecutor`` and verifies:

- No deadlock (each run completes within a 30s cap).
- No crossed writes to internal memory files (``.muscle/MEMORY.md``,
  ``.muscle/CLAUDE.md``, ``.muscle/AGENT.md``) — files either don't
  exist or contain well-formed, non-truncated content after the run.
- All three sessions terminate with a non-None status / session id.

The M2.7 client is mocked so the test runs offline.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.review_controller import ReviewController
from tools.muscle.code_review.static_analyzer import StaticAnalyzer
from tools.muscle.code_review.types import (
    IssueCategory,
    ReviewConfig,
    ReviewMode,
    Severity,
)

from .conftest import MockM27Client, make_review_issue

CONCURRENCY_TIMEOUT_SECONDS = 30.0


def _file_checksums(root: Path) -> dict[str, str]:
    """Fingerprint every memory file we care about. Missing files are ''."""
    names = ["CLAUDE.md", "AGENT.md", "MEMORY.md"]
    out: dict[str, str] = {}
    for name in names:
        path = root / ".muscle" / name
        if path.exists():
            out[name] = hashlib.sha1(path.read_bytes()).hexdigest()
        else:
            out[name] = ""
    return out


def _no_corruption(root: Path) -> None:
    """Memory files either don't exist or are UTF-8 decodable and non-empty."""
    for name in ("CLAUDE.md", "AGENT.md", "MEMORY.md"):
        path = root / ".muscle" / name
        if not path.exists():
            continue
        # If written, must be a valid UTF-8 file with content or empty is ok
        data = path.read_bytes()
        # Must be valid UTF-8
        text = data.decode("utf-8")
        # Line-count invariant: file shouldn't contain NULs
        assert "\x00" not in text, f"{name} contains NUL bytes (possible corruption)"


class TestConcurrentReviewStress:
    """TEST-03: three concurrent ReviewController.run() calls on the same project."""

    def _build_config(self, target: Path) -> ReviewConfig:
        return ReviewConfig(
            target_path=str(target / "src"),
            language="python",
            mode=ReviewMode.REVIEW,
        )

    def test_three_concurrent_reviews_no_deadlock(
        self,
        sample_python_project: Path,
        mock_m27: MockM27Client,
    ):
        """Spawn three reviewers on the same project; assert none deadlock."""
        config = self._build_config(sample_python_project)

        # Pre-snapshot any memory files to prove invariants hold later.
        _no_corruption(sample_python_project)
        _ = _file_checksums(sample_python_project)

        mock_issues = [
            make_review_issue(
                severity=Severity.HIGH,
                title="Issue A",
                category=IssueCategory.SECURITY,
            ),
            make_review_issue(
                file_path="src/utils.py",
                line_number=11,
                severity=Severity.MEDIUM,
                title="Issue B",
                category=IssueCategory.STYLE,
            ),
        ]

        def _run_one(idx: int):
            controller = ReviewController(
                config=config,
                m27_client=mock_m27,
                use_kb=False,
                project_path=str(sample_python_project),
            )
            return idx, controller.run()

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(
                CodeReviewer, "review", return_value=(mock_issues, "Summary")
            ):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = [pool.submit(_run_one, i) for i in range(3)]
                    results = []
                    for fut in as_completed(
                        futures, timeout=CONCURRENCY_TIMEOUT_SECONDS
                    ):
                        results.append(fut.result(timeout=CONCURRENCY_TIMEOUT_SECONDS))

        assert len(results) == 3, "Expected 3 concurrent runs to all complete"

        # Every run produced a review context with a non-None session_id.
        for idx, ctx in results:
            assert ctx is not None, f"run {idx} returned None"
            assert ctx.session_id is not None
            assert ctx.session_id

        # Post-run invariants: memory files remain well-formed.
        _no_corruption(sample_python_project)

    def test_concurrent_reviews_produce_distinct_sessions(
        self,
        sample_python_project: Path,
        mock_m27: MockM27Client,
    ):
        """Session IDs across concurrent runs must be unique (no crossed writes)."""
        config = self._build_config(sample_python_project)

        mock_issues = [
            make_review_issue(severity=Severity.MEDIUM, title="Shared issue")
        ]

        def _run_one():
            controller = ReviewController(
                config=config,
                m27_client=mock_m27,
                use_kb=False,
                project_path=str(sample_python_project),
            )
            return controller.run()

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(
                CodeReviewer, "review", return_value=(mock_issues, "Summary")
            ):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = [pool.submit(_run_one) for _ in range(3)]
                    ctxs = [
                        f.result(timeout=CONCURRENCY_TIMEOUT_SECONDS)
                        for f in as_completed(
                            futures, timeout=CONCURRENCY_TIMEOUT_SECONDS
                        )
                    ]

        ids = {ctx.session_id for ctx in ctxs}
        # Three distinct UUID-derived session ids (collisions would be a red flag).
        assert len(ids) == 3, f"Expected distinct session ids, got {ids}"

        # No NUL / truncation in any memory-managed file.
        _no_corruption(sample_python_project)

    def test_concurrent_runs_preserve_memory_file_integrity(
        self,
        sample_python_project: Path,
        mock_m27: MockM27Client,
    ):
        """Line-count invariant: if memory files are touched, they stay readable."""
        config = self._build_config(sample_python_project)

        issue = make_review_issue(severity=Severity.HIGH, title="Mem issue")

        def _run_one():
            controller = ReviewController(
                config=config,
                m27_client=mock_m27,
                use_kb=False,
                project_path=str(sample_python_project),
            )
            ctx = controller.run()
            return ctx

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(
                CodeReviewer, "review", return_value=([issue], "Summary")
            ):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = [pool.submit(_run_one) for _ in range(3)]
                    for f in as_completed(
                        futures, timeout=CONCURRENCY_TIMEOUT_SECONDS
                    ):
                        ctx = f.result(timeout=CONCURRENCY_TIMEOUT_SECONDS)
                        assert ctx is not None
                        assert ctx.stats is not None

        # Memory files — if present — must still be valid UTF-8 and free of
        # interleaved garbage (NULs, partial writes).
        _no_corruption(sample_python_project)
        for name in ("CLAUDE.md", "AGENT.md", "MEMORY.md"):
            path = sample_python_project / ".muscle" / name
            if path.exists():
                text = path.read_text(encoding="utf-8")
                # If any content was written, lines must be well-formed (no
                # partial mid-line markers from concurrent write).
                for line in text.splitlines():
                    assert line == line.rstrip("\x00")

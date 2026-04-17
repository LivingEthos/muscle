"""Tests for host_memory_templates.py — byte-stability and rendering."""

from tools.muscle.code_review.host_memory_templates import (
    INTERNAL_SEED,
    PINNED_SECTION_ORDER,
    PINNED_TEMPLATE,
    SECTION_DELEGATION,
    SECTION_EFFORT,
    SECTION_METHODOLOGY,
    render_pinned_block,
)


class TestHostMemoryTemplates:
    def test_pinned_template_is_stable(self) -> None:
        result = render_pinned_block()
        assert result == PINNED_TEMPLATE
        # Second call produces identical bytes.
        assert render_pinned_block() == result

    def test_pinned_template_contains_all_sections(self) -> None:
        assert SECTION_METHODOLOGY in PINNED_TEMPLATE
        assert SECTION_DELEGATION in PINNED_TEMPLATE
        assert SECTION_EFFORT in PINNED_TEMPLATE

    def test_section_order_matches_template(self) -> None:
        indices = [PINNED_TEMPLATE.index(s) for s in PINNED_SECTION_ORDER]
        assert indices == sorted(indices), "Pinned sections must appear in declaration order"

    def test_internal_seed_is_subset_of_pinned(self) -> None:
        # Every line in INTERNAL_SEED appears in PINNED_TEMPLATE.
        for line in INTERNAL_SEED.strip().splitlines():
            assert line in PINNED_TEMPLATE, f"Seed line missing from PINNED_TEMPLATE: {line!r}"

    def test_internal_seed_contains_methodology_bullets(self) -> None:
        assert "Think before coding" in INTERNAL_SEED
        assert "Simplicity first" in INTERNAL_SEED
        assert "Surgical changes" in INTERNAL_SEED
        assert "Goal-driven execution" in INTERNAL_SEED

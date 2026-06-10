"""Unit tests for the structured (tabular) payload compactor."""

from __future__ import annotations

from muscle.optimization.structured_compactor import (
    compact_records,
    expand_records,
)

ISSUES = [
    {"rule_id": "E501", "line_number": 12, "severity": "error", "message": "line too long"},
    {"rule_id": "F401", "line_number": 3, "severity": "warning", "message": "unused import os"},
    {"rule_id": "B008", "line_number": 40, "severity": "error", "message": "call in defaults"},
]


class TestCompactRecords:
    def test_compacts_homogeneous_records_below_json_size(self):
        result = compact_records(ISSUES, label="Static analysis issues")
        assert result.applied is True
        # Compact form is meaningfully smaller than indented JSON.
        assert result.compact_chars < result.original_chars
        assert result.estimated_tokens_saved > 0
        # Header advertises the columns deterministically (sorted).
        assert "columns: line_number | message | rule_id | severity" in result.text
        assert "Static analysis issues (3)" in result.text

    def test_output_is_deterministic(self):
        first = compact_records(ISSUES, label="x").text
        second = compact_records(list(reversed(ISSUES)), label="x").text
        # Row order follows input, but column order and formatting are stable, so
        # the same input always renders byte-identically (prefix-cache friendly).
        assert compact_records(ISSUES, label="x").text == first
        assert first != second  # row order is preserved, not sorted

    def test_preserves_every_field_value(self):
        text = compact_records(ISSUES, label="x").text
        for record in ISSUES:
            for value in record.values():
                assert str(value) in text

    def test_empty_records_not_applied(self):
        result = compact_records([], label="x")
        assert result.applied is False
        assert result.text == ""

    def test_non_dict_records_fall_back_to_json(self):
        result = compact_records(["not", "dicts"], label="x")  # type: ignore[list-item]
        assert result.applied is False
        # Fallback is valid JSON the caller can still embed.
        assert "not" in result.text

    def test_irregular_records_still_value_preserving(self):
        records = [
            {"a": 1, "b": 2},
            {"a": 3, "c": 4},  # missing b, extra c
        ]
        result = compact_records(records, label="x")
        text = result.text
        for record in records:
            for value in record.values():
                assert str(value) in text


class TestRoundTrip:
    def test_round_trip_recovers_string_normalized_records(self):
        # Reversible-compression guarantee: the compact form can be expanded back
        # to the original records (values normalized to strings).
        result = compact_records(ISSUES, label="Static analysis issues")
        recovered = expand_records(result.text)
        expected = [{k: str(v) for k, v in record.items()} for record in ISSUES]
        assert recovered == expected

    def test_round_trip_survives_separator_characters_in_values(self):
        records = [
            {"id": "a", "msg": "value | with pipe"},
            {"id": "b", "msg": "back\\slash and\nnewline"},
        ]
        result = compact_records(records, label="x")
        recovered = expand_records(result.text)
        expected = [{k: str(v) for k, v in record.items()} for record in records]
        assert recovered == expected

    def test_round_trip_200_records(self):
        large = [{"id": str(i), "status": "ok" if i % 2 == 0 else "fail", "msg": f"item {i}"} for i in range(200)]
        result = compact_records(large, label="bulk")
        assert result.applied is True
        recovered = expand_records(result.text)
        expected = [{k: str(v) for k, v in record.items()} for record in large]
        assert recovered == expected

    def test_round_trip_with_pipe_and_newline_in_values(self):
        records = [
            {"id": "1", "desc": "has | pipe"},
            {"id": "2", "desc": "has \n newline"},
            {"id": "3", "desc": "has | pipe and \n newline"},
            {"id": "4", "desc": "has \\ backslash"},
            {"id": "5", "desc": "has | \n \\ all three"},
        ]
        result = compact_records(records, label="x")
        recovered = expand_records(result.text)
        expected = [{k: str(v) for k, v in record.items()} for record in records]
        assert recovered == expected

    def test_json_fallback_when_table_not_smaller(self):
        # Empty records have header overhead that exceeds JSON, so fallback.
        records = [{}, {}]
        result = compact_records(records, label="x")
        assert result.applied is False
        assert "{}" in result.text

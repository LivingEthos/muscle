# Structured Compactor Stress Test — 2026-06-04

## Objective
Validate that `tools/muscle/optimization/structured_compactor.py` (`compact_records` / `expand_records`):

1. Saves tokens at higher volume (≥ 40 static-analysis findings).
2. Remains fully reversible (round-trip preserves values).
3. Is parsed correctly by MiniMax-M3 in a live API call.
4. Gracefully falls back to JSON when compaction would not shrink the payload.

## Test Setup

- **Target:** Synthetic Python file with 40 functions containing `eval()` + bare `except:` — deliberately triggering many ruff rules.
- **Model:** MiniMax-M3 via Anthropic-compatible endpoint (`https://api.minimax.io/anthropic`).
- **Credentials:** Loaded from external key file (not committed).
- **Compactor toggle:** `MUSCLE_STRUCTURED_COMPACTION=1` (on) vs `=0` (off).

## Direct A/B Prompt Comparison

Using the actual ruff JSON output (44 issues) fed through `_render_issue_block`:

| Metric | Compacted Table | Indented JSON | Delta |
|--------|-----------------|---------------|-------|
| Characters | 9,420 | 18,328 | −8,908 (−49 %) |
| Live M3 input tokens* | 3,747 | 6,447 | −2,700 (−42 %) |
| Live M3 output tokens | 165 | 138 | — |
| Cached input tokens | 3,733 | 114 | — |

\*Measured by a direct `M27Client.chat()` call asking M3 to count `"error"` severities and list the first three rule codes. Both variants returned the identical correct answer:

```json
{"error_count": 44, "first_three_codes": ["I001", "F401", "F401"]}
```

**Conclusion:** M3 reads the compacted table without ambiguity and the token reduction is real.

## End-to-End CLI Review (Supplementary)

Two `muscle review` runs against the same synthetic file (`--mode review --workflow review-comprehensive --intensity moderate`):

| Variant | Session | Issues Found | Top Token Hotspot |
|---------|---------|--------------|-------------------|
| Compacted ON | `4e5f4011` | 23 (Critical 2, Medium 19, Low 2) | committee_review 16,378 tokens |
| Compacted OFF | `7362cf67` | 24 (Critical 2, Medium 18, Low 4) | committee_review 24,104 tokens |

> **Note:** The CLI runs include retries, lesson context, and workflow overhead, so the absolute numbers are noisier than the direct prompt test above. The compacted run did trigger M3 thinking-block retries (5 attempts before fallback routing succeeded), which inflates its reported token total. The direct prompt test is the cleanest signal for compactor savings.

## Edge-Case Unit Tests Added

New tests in `tests/unit/test_structured_compactor.py`:

1. **`test_round_trip_200_records`** — Feeds 200 flat records through `compact_records` → `expand_records` and asserts perfect round-trip (string-normalized).
2. **`test_round_trip_with_pipe_and_newline_in_values`** — Covers the escape/unescape path for `|`, `\n`, and `\` appearing together in cell values.
3. **`test_json_fallback_when_table_not_smaller`** — Confirms that when the table header overhead would exceed JSON size (empty-record case), `applied=False` and valid JSON is returned.

All 11 compactor tests pass.

## Quality Gate

- `mypy tools/muscle/` — clean
- `ruff check tools/muscle/` — clean
- `ruff format --check tools/muscle/` — clean
- `pytest tests/` — 2,488 passed, 3 skipped

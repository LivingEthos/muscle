---
description: Run MUSCLE benchmark comparisons across review strategies
args:
  - name: baseline
    description: "Baseline reviewer: legacy, review-smart, or review-comprehensive"
    required: false
  - name: candidate
    description: "Candidate workflow: review-smart, review-comprehensive, or review-fix-verify"
    required: false
  - name: suite
    description: "Fixture suite: all, core-review, neutral-baseline, related-project, unrelated-project, or model-pack"
    required: false
  - name: enforce-gates
    description: "Fail the command if release gates or focused offline guardrails fail"
    required: false
---

Run the manual benchmark harness. Execute:

```bash
muscle long-eval benchmark ${baseline:+--baseline "$baseline"} ${candidate:+--candidate "$candidate"}
```

To focus on one fixture family:

```bash
muscle long-eval benchmark --suite related-project
```

To use the benchmark as a release check:

```bash
muscle long-eval benchmark --enforce-gates
```

This writes JSON and Markdown benchmark reports under `.muscle/reports/benchmarks/`, saves release-gate evidence under `.muscle/reports/release_evidence/`, and compares recall, false-positive rate, token cost, and duration.

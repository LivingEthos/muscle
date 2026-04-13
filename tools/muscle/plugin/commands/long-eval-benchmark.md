---
description: Run MUSCLE benchmark comparisons across review strategies
args:
  - name: baseline
    description: "Baseline reviewer: legacy, review-smart, or review-comprehensive"
    required: false
  - name: candidate
    description: "Candidate workflow: review-smart, review-comprehensive, or review-fix-verify"
    required: false
---

Run the manual benchmark harness. Execute:

```bash
muscle long-eval benchmark ${baseline:+--baseline "$baseline"} ${candidate:+--candidate "$candidate"}
```

This writes JSON and Markdown reports under `.muscle/reports/benchmarks/` and compares recall, false-positive rate, token cost, and duration.

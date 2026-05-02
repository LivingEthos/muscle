---
description: Run MUSCLE benchmark comparisons across review strategies
argument-hint: "[baseline] [candidate] [suite] [--enforce-gates]"
---

Run the manual benchmark harness. Execute:

```bash
muscle long-eval benchmark
```

If the user specifies baseline or candidate workflows, append `--baseline <baseline>` and
`--candidate <candidate>`.

To focus on one fixture family:

```bash
muscle long-eval benchmark --suite related-project
```

To use the benchmark as a release check:

```bash
muscle long-eval benchmark --enforce-gates
```

This writes JSON and Markdown benchmark reports under `.muscle/reports/benchmarks/`, saves release-gate evidence under `.muscle/reports/release_evidence/`, and compares recall, false-positive rate, token cost, and duration.

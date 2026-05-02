---
description: Show the most related MUSCLE projects that can share provisional lessons
---

Suggest related MUSCLE projects for this repo without importing anything automatically.
Project-local memory remains authoritative, and imported lessons stay provisional until validated
here.

```bash
muscle memory related
```

To refresh the current fingerprint and prune stale catalog entries while checking overlaps:
```bash
muscle memory related --refresh --prune-stale --stale-days 90
```

To include stale registrations in the suggestion table:
```bash
muscle memory related --include-stale
```

If you want to import lessons from a suggested project:
```bash
muscle memory import-project --project /path/to/other/project --mode snapshot
```

Or keep a live read-through attachment instead:
```bash
muscle memory import-project --project /path/to/other/project --mode attach
```

To inspect recent lesson usage and validation outcomes:

```bash
muscle memory history
```

---
description: Import or attach provisional lessons from a related MUSCLE project
args:
  - name: project
    description: Path to the source MUSCLE project
    required: true
---

Project-local memory remains primary. Imported or attached lessons stay provisional until they
prove themselves in the current project.

To snapshot-import lessons from a related project:
```bash
muscle memory import-project --project /path/to/other/project --mode snapshot
```

To attach a related project as a live read-through source instead:
```bash
muscle memory import-project --project /path/to/other/project --mode attach
```

To inspect currently linked related projects:
```bash
muscle memory linked
```

To remove a related-project link later:
```bash
muscle memory unlink --project /path/to/other/project
```

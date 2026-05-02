---
description: Build a content-addressed context pack so repeated MUSCLE subtasks reuse the same distilled scope
argument-hint: "[task] [scope] [acceptance] [out]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Build the pack once for a delegation, then let `/muscle:review`, `/muscle:rescue`, and the verification agent consume the same pack id so the response cache short-circuits identical calls.

Build a distilled, content-addressed context packet. Execute:

```bash
muscle pack --task "<task>" --scope <path> [--acceptance "<criteria>"] [--out <file>]
```

The command writes the pack body to `.muscle/packs/<id>.md` and records metadata in the project memory database. The `id` is the first 16 hex chars of the sha256 over the *canonical* (timestamp-free) body, so identical inputs produce the same id across invocations.

Example — build a pack for a targeted review, then reuse it:

```bash
muscle pack --task "Review the auth module for missing input validation" --scope src/auth/
muscle pack list
muscle pack gc --older-than 30d
```

Pass the resulting pack id to downstream commands that accept `--pack <id>` so the response cache key incorporates it (Phase B.3 integration): identical pack + identical task produces a cache hit instead of a fresh M2.7 call.

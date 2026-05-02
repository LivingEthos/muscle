---
description: Set or configure the MINIMAX/M2.7 API key for MUSCLE
argument-hint: "[--key <key>] [--source env|opencode|ask]"
---

Configure the MUSCLE API key. To check current status non-interactively (safe
to run from this slash command):

```bash
muscle settings api-key
```

When stdin is not a TTY (which is the case for any slash-command invocation),
this prints the current API key status and returns. From an interactive
terminal it will additionally prompt for a new key.

To set a key directly:

```bash
muscle settings api-key --key sk-xxxx
```

To switch the credential source:

```bash
muscle settings api-key --source env       # use $MINIMAX_API_KEY
muscle settings api-key --source opencode  # use OpenCode-managed credential
muscle settings api-key --source ask       # prompt next time a key is needed
```

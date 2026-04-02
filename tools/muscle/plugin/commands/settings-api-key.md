---
description: Set or configure the MINIMAX/M2.7 API key for MUSCLE
args:
  - name: key
    description: API key to set
    required: false
  - name: source
    description: "API key source: env, opencode, ask"
    required: false
---

Configure the MUSCLE API key. Execute:

```bash
muscle settings api-key ${source:+--source "$source"} ${key:+--key "$key"}
```

If no key or source is provided, show current API key status.

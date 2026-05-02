# MUSCLE Privacy Notes

MUSCLE is designed as a local-first developer tool.

## What Stays Local

- Project memory and review evidence are written to the current project's
  `.muscle/` directory.
- Shared MUSCLE state, such as model-pack cache and global project indexes,
  lives under `~/.muscle/`.
- `muscle discover` is read-only by default and does not mutate project memory.
- `muscle doctor` is observational unless a refresh flag is used.

## What May Leave Your Machine

MUSCLE review and generation commands call the model endpoint configured by your
environment, such as `MINIMAX_API_KEY` and `ANTHROPIC_BASE_URL`. The content sent
depends on the command target and selected workflow.

Model-pack export, import, and submission flows are explicit user actions.
MUSCLE does not silently upload project memory.

## Secrets

Do not commit API keys or local credentials. Configure keys through environment
variables or local settings files that are excluded from version control.

## Project-Local Authority

Related-project lessons, model-pack lessons, and output filters are overlays.
They do not become authoritative project memory unless validated or explicitly
trusted for the current project.

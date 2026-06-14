# Contributing to MUSCLE

Thanks for your interest in improving MUSCLE. This guide covers local setup,
the quality gates every change must pass, and what we expect in a pull request.

## Development setup

MUSCLE uses the [`uv`](https://github.com/astral-sh/uv) package manager.

```bash
# Install dependencies (including dev tools)
uv sync --extra dev
```

The import package is `muscle` (under `src/muscle/`), the distribution is
`muscle-cli`, and the CLI entry point is `muscle`.

## Quality gates

All four gates must pass before a change can merge. Always invoke them through
`uv run` so you use the pinned tool versions (a globally installed `mypy` can
produce false positives/negatives due to stub mismatches):

```bash
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
uv run pytest tests/ -q
```

Auto-fix lint and formatting issues with:

```bash
uv run ruff check src/muscle/ --fix
uv run ruff format src/muscle/
```

## Testing conventions

- Tests live in `tests/unit/` with a `test_` prefix matching the module under
  test (e.g. `test_cli.py` covers `cli.py`).
- We rely heavily on `unittest.mock`; shared fixtures are in `tests/conftest.py`.
- The suite uses `pytest-asyncio` in `auto` mode.
- New behavior should ship with a test. Keep tests fast and hermetic — no
  network calls, no real API keys.

## Pull request expectations

- All four quality gates pass locally before you open the PR.
- Keep changes focused and commits small and self-contained; one logical change
  per commit.
- Update relevant docs (`README.md`, `CHANGELOG.md`) when behavior changes.
- Describe what changed and why in the PR description.

## Code of conduct

By participating in this project you agree to abide by the
[Code of Conduct](CODE_OF_CONDUCT.md).

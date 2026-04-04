# Plan: Minimal, Useful `opensrc` Review Enrichment

## Summary

Add an optional review-time enrichment path that uses `opensrc` to fetch third-party npm package
source code and supply a small, high-signal dependency context to MUSCLE's semantic review.

This should improve review quality for JS/TS projects without turning MUSCLE into a package-source
manager.

### v1 boundaries

- Only active when the user passes `--fetch-sources`
- Only for JS/TS review flows using npm packages
- Only for foreground `review`, `plan`, `auto-fix`, and `hybrid` modes
- No custom lockfile parser
- No custom cache format
- No shadow/nightly/pressure support

---

## Explicit Non-Goals

This plan intentionally does not try to:

- make MUSCLE a general dependency indexing system
- maintain its own package source cache format or metadata schema
- support every `opensrc` feature exposed by the upstream CLI
- fetch transitive dependencies recursively
- analyze dependency code as first-class review targets
- alter fix generation, handoff generation, or verification logic based on dependency code
- persist source-enrichment results in MUSCLE databases or knowledge bases
- optimize for maximum source coverage over prompt quality

If any of those become desirable later, they should be handled in a separate follow-up proposal.

---

## Scope

### In scope

- Foreground `muscle review`
- Review enrichment for `.js`, `.jsx`, `.ts`, and `.tsx` targets
- Optional, user-triggered dependency source fetching
- Compact, curated prompt context only

### Out of scope for v1

- `shadow` mode
- `nightly` mode
- `pressure` mode
- PyPI, crates, or GitHub repo fetching
- Persistent MUSCLE-managed source storage beyond what `opensrc` already provides

---

## User-Facing Behavior

### CLI additions

- `--fetch-sources`
- `--source-package <name>` repeatable

### Behavior rules

- If `--fetch-sources` is not passed, review behavior is unchanged.
- If `--fetch-sources` is passed with `--shadow`, reject the command with a clear error.
- If `opensrc` is not installed, print a warning and continue the review without enrichment.
- If the target is not a JS/TS review target, print a short skip message and continue.
- If `--source-package` is provided, only those packages are considered.
- Otherwise, packages are inferred from imports in reviewed JS/TS files.

### Recommended user messages

- `opensrc not installed; continuing without dependency context. Install with: npm install -g opensrc`
- `Skipping dependency context: source fetching currently supports JS/TS foreground review only`
- `No third-party JS/TS package imports found; continuing without dependency context`
- `Failed to fetch package sources via opensrc; continuing without dependency context`

---

## Public Interfaces

### `tools/muscle/code_review/types.py`

Add to `ReviewConfig`:

```python
fetch_sources: bool = False
fetch_source_packages: list[str] | None = None
```

### `tools/muscle/cli.py`

- Add `--fetch-sources`
- Add repeatable `--source-package <name>`
- Reject `--fetch-sources --shadow`

### `tools/muscle/code_review/code_reviewer.py`

Change:

```python
review(target_path, issues)
```

to:

```python
review(target_path, issues, supplemental_context: str = "")
```

No other public interface changes are needed in v1.

---

## Estimated Complexity

### Overall estimate

- Implementation size: small to medium
- Risk: medium
- Expected files touched: 5 to 7
- Expected new tests: 1 new unit test module, 1 small integration-style test

### Complexity by area

- CLI and config plumbing: low
- Import extraction and package normalization: medium
- `opensrc` subprocess orchestration: medium
- Prompt budget enforcement: medium
- Test coverage updates: medium

### Main risks

- import parsing missing common JS/TS patterns
- prompt context becoming too large and degrading review quality
- incorrect assumptions about fetched package directory structure
- brittle tests around subprocess behavior and temp filesystem layout

---

## Architecture

### New module

Add:

```text
tools/muscle/code_review/source_context.py
```

Primary class:

- `SourceContextBuilder`

### Ownership split

- `ReviewController` decides whether enrichment runs and passes the resulting context onward.
- `CodeReviewer` only appends supplemental context to the review prompt.
- `SourceContextBuilder` contains all `opensrc`-specific logic.

This keeps the integration isolated, easier to test, and easy to extend later.

---

## Recommended Rollout Order

Implement in this order to minimize rework:

1. Add `ReviewConfig` fields and CLI flags.
2. Reject unsupported CLI combinations such as `--fetch-sources --shadow`.
3. Create `source_context.py` with project-root resolution and import extraction first.
4. Add package selection, `opensrc` invocation, and `opensrc list --json` parsing.
5. Add compact context construction with strict budget enforcement.
6. Thread `supplemental_context` through `ReviewController` into `CodeReviewer`.
7. Add and update tests.
8. Run targeted tests first, then broader review-related tests.

This order keeps the risky logic isolated before prompt and controller integration.

---

## `SourceContextBuilder` Design

### 1. Resolve project root

Walk upward from `target_path` until the first directory containing any of:

- `package.json`
- `package-lock.json`
- `pnpm-lock.yaml`
- `yarn.lock`
- `.git`

If nothing is found:

- treat enrichment as unavailable
- return an empty context with a skip reason

### 2. Determine reviewed files

Within `target_path`, only inspect:

- `.js`
- `.jsx`
- `.ts`
- `.tsx`

If `target_path` is a file, inspect only that file.

### 3. Extract package imports

Support common import shapes:

- `import x from "pkg"`
- `import { x } from "pkg/subpath"`
- `export * from "pkg"`
- `require("pkg")`
- `import("pkg")`

Ignore:

- relative imports
- absolute filesystem imports
- built-ins like `node:*`

Normalize:

- `lodash/fp` -> `lodash`
- `@scope/pkg/subpath` -> `@scope/pkg`

### 4. Choose packages

If `fetch_source_packages` is set:

- use that list directly
- preserve user order

Otherwise:

- rank packages by import frequency across reviewed files

Apply caps:

- max 3 packages total

Priority:

- explicit package list first
- otherwise most frequently imported packages first

### 5. Fetch with `opensrc`

Run a single command:

```bash
opensrc <pkg1> <pkg2> ... --cwd <project_root> --modify=false
```

Requirements:

- single invocation only
- timeout protected
- capture stdout and stderr
- never allow file modifications during review
- continue on failure
- treat any non-zero exit code as enrichment failure, not review failure

Do not implement custom version resolution. Rely on `opensrc`.

### 6. Discover fetched sources

Run:

```bash
opensrc list --json --cwd <project_root>
```

Use returned metadata to locate fetched package directories under `opensrc/`.

Do not assume directories are named `name@version`.

### 7. Build compact LLM context

For each selected package, include:

- package name
- resolved version
- fetched path
- `description`
- `main`
- `module`
- `types`
- `exports["."]` when present

Then include up to 2 snippets from likely entry files, chosen from:

- `main`
- `module`
- `types`
- `index.js`
- `index.ts`
- `dist/index.js`
- `src/index.ts`

Hard limits:

- max 60 lines per snippet
- max 2 snippets per package
- max 3 packages
- max 180 total lines across all package context

If the budget is exceeded:

- truncate later packages and snippets first
- preserve metadata even when code snippets are reduced

Selection rule for entry files:

- prefer explicit `main` and `module` paths first
- then prefer `types` if it points to source-like declarations that help understand API shape
- then fall back to common entry filenames in priority order
- skip files that do not exist instead of failing the build

Context formatting rule:

- use a stable, plain-text structure so tests can assert on it easily
- do not include giant raw JSON blobs from `package.json`

---

## Prompting Changes

In `CodeReviewer.review(...)`:

- append a section only when `supplemental_context` is non-empty

Suggested section header:

- `Third-Party Dependency Context`

Prompt instruction should explicitly say:

- the dependency context is partial
- use it only when directly relevant
- do not invent dependency internals beyond the supplied excerpts

This keeps prompts bounded and reduces hallucination risk.

---

## Controller Integration

Integrate in `tools/muscle/code_review/review_controller.py` before semantic review:

1. Run static analysis as today.
2. If config enables source fetching and mode is supported:
   - build supplemental dependency context
3. Pass the context into `code_reviewer.review(...)`

Do not invoke this builder in:

- pressure mode
- shadow worker
- nightly runner

Failure handling rule:

- enrichment failures must be logged or surfaced via user-facing messages, but they must never
  change the final review exit path

Implementation preference:

- instantiate the builder inside `ReviewController`, not `CodeReviewer`
- keep `CodeReviewer` unaware of `opensrc`, subprocesses, or package discovery details
- treat supplemental context as optional input only

---

## File Touch Plan

Expected implementation touch points:

- `tools/muscle/code_review/types.py`
- `tools/muscle/cli.py`
- `tools/muscle/code_review/review_controller.py`
- `tools/muscle/code_review/code_reviewer.py`
- `tools/muscle/code_review/source_context.py`
- `tests/unit/test_source_context.py`
- small updates in existing review CLI/controller/reviewer tests

Files that should not change in v1:

- `tools/muscle/code_review/shadow_worker.py`
- `tools/muscle/code_review/nightly_runner.py`
- `tools/muscle/code_review/fix_generator.py`
- `tools/muscle/code_review/verification_loop.py`
- MUSCLE database schema or migrations
- learning pipeline and memory-management modules

---

## Testing Plan

### New unit tests

Add `tests/unit/test_source_context.py` covering:

- project root resolution
- import extraction
- scoped package normalization
- subpath normalization
- explicit package override
- package ranking and cap
- context trimming to budget
- subprocess command includes `--cwd` and `--modify=false`
- graceful handling of missing `opensrc`
- graceful handling of malformed `opensrc list --json`

### Update existing tests

#### `tests/unit/test_code_reviewer.py`

- supplemental context omitted when empty
- supplemental context appended when present

#### `tests/unit/test_review_controller.py`

- builder invoked only when enabled
- review continues if builder returns empty context
- review continues if builder raises or fetch fails

#### `tests/unit/test_cli_review.py`

- `--fetch-sources` populates config
- repeated `--source-package` populates list
- `--fetch-sources --shadow` fails fast

### Integration-style test

Add one patched-subprocess test that simulates:

- JS/TS target with imports
- successful `opensrc` fetch
- valid `opensrc list --json`
- fetched package tree on disk

Assert:

- `ReviewController` passes non-empty supplemental context into `CodeReviewer`

### Suggested verification order

1. `tests/unit/test_source_context.py`
2. `tests/unit/test_code_reviewer.py`
3. `tests/unit/test_review_controller.py`
4. `tests/unit/test_cli_review.py`
5. one integration-style review pipeline test covering enrichment handoff

Only after those pass:

- run the broader review test suite

---

## Suggested Implementation Checklist

- Add config fields with safe defaults
- Add CLI flag parsing and invalid-combination guard
- Implement project-root discovery
- Implement JS/TS import extraction and package normalization
- Implement package selection and capping
- Implement `opensrc` fetch invocation
- Implement `opensrc list --json` parsing
- Implement bounded dependency context rendering
- Thread `supplemental_context` into semantic review
- Add user-facing warning and skip messages
- Add unit tests for builder logic
- Update existing CLI, controller, and reviewer tests
- Add one integration-style enrichment handoff test

---

## Acceptance Criteria

The feature is complete when:

- review behavior is unchanged without the flag
- JS/TS foreground reviews can optionally fetch dependency sources
- `opensrc` does not modify `.gitignore`, `tsconfig.json`, or `AGENTS.md`
- prompt enrichment remains compact and bounded
- failures degrade gracefully
- tests cover CLI, controller, reviewer, and builder behavior

Stretch acceptance, if convenient but not required:

- deterministic package ordering in context output
- deterministic snippet selection for stable tests

---

## Assumptions And Defaults

- v1 is npm and JS/TS only, even though `opensrc` supports more later.
- v1 supports foreground review flows only.
- MUSCLE will not allow `opensrc` to edit repo files during review runs.
- The goal is better review quality, not permanent dependency source management.

---

## Future Extensions

After v1 proves useful, consider:

- support for `pressure` mode
- support for shadow and nightly flows
- support for PyPI and crates via `opensrc`
- smarter snippet selection based on imported symbol usage

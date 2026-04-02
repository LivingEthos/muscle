# MUSCLE Check

Run a single-shot validation against a file or directory. Runs compiler, linter, and test checks once without any iteration loop.

## Usage

```
/muscle:check [--target <path>] [--language <lang>] [--format <format>]
```

## Options

- `--target` - Path to validate (file or directory, required)
- `--language` - Programming language (auto-detected if not specified)
- `--format` - Output format: `text`, `json` (default: `text`)

## Examples

```
/muscle:check --target ./src
/muscle:check --target ./src --language python --format json
/muscle:check --target ./tests
```

## Output

Returns exit code 0 if all checks pass, non-zero otherwise. Shows:
- Compiler errors
- Test failures
- Linter warnings
- Assertion failures

# MUSCLE Review

Run a code review on the current project or specified files.

## Usage

```
/muscle:review [--target <path>] [--mode <mode>] [--severity <level>] [--format <format>]
```

## Options

- `--target` - Path to review (default: current directory)
- `--mode` - Review mode: `review`, `pressure`, `auto-fix`, `plan`, `hybrid` (default: `review`)
- `--severity` - Minimum severity: `critical`, `high`, `medium`, `low` (default: `low`)
- `--format` - Output format: `text`, `json` (default: `text`)
- `--background` - Run review in background

## Examples

```
/muscle:review
/muscle:review --target ./src --mode pressure
/muscle:review --severity high --format json
/muscle:review --background
```

## Modes

- **review** - Standard code review
- **pressure** - Adversarial review that challenges design decisions
- **auto-fix** - Attempt to fix issues automatically
- **plan** - Generate fix plans without implementing
- **hybrid** - Combine review and auto-fix

## Output

Shows issues found with severity, location, and suggested fixes. Use `/muscle:status` to check background jobs.

# MUSCLE Review

Run a code review on the current project or specified files.

## Usage

```
/muscle:review [--target <path>] [--mode <mode>] [--severity <level>] [--format <format>] [--options...]
```

## Options

- `--target` - Path to review (default: current directory)
- `--mode` - Review mode: `review`, `pressure`, `auto-fix`, `plan`, `hybrid` (default: `review`)
- `--severity` - Minimum severity: `critical`, `high`, `medium`, `low` (default: `low`)
- `--language` - Programming language (auto-detected if not specified)
- `--max-fixes` - Maximum auto-fixes per round (default: 5)
- `--output` - Output file for handoff plan (markdown)
- `--format` - Output format: `text`, `json` (default: `text`)
- `--shadow` - Run in shadow (background) mode
- `--intensity` - Review intensity: `minimal`, `moderate`, `intensive`, `exhaustive` (default: `moderate`)
- `--failsafe` - Stop on critical issues
- `--focus` - Pressure focus areas (comma-separated): `design`, `failure`, `race`, `auth`, `data`, `rollback`, `reliability`

## Examples

```
/muscle:review
/muscle:review --target ./src --mode pressure
/muscle:review --severity high --format json
/muscle:review --shadow --intensity exhaustive
/muscle:review --mode auto-fix --max-fixes 10
/muscle:review --focus design,failure,race --intensity intensive
```

## Modes

- **review** - Standard code review
- **pressure** - Adversarial review that challenges design decisions
- **auto-fix** - Attempt to fix issues automatically
- **plan** - Generate fix plans without implementing
- **hybrid** - Combine review and auto-fix

## Intensity Levels

- **minimal** - Quick scan, surface-level analysis
- **moderate** - Standard thorough review
- **intensive** - Deep analysis with multiple passes
- **exhaustive** - Comprehensive analysis including edge cases

## Output

Shows issues found with severity, location, and suggested fixes. Use `/muscle:status` to check shadow jobs and `/muscle:result` to get results.

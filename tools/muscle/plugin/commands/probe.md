# MUSCLE Probe

Check the status of MUSCLE shadow (background) review jobs.

## Usage

```
/muscle:probe [--job-id <id>]
```

## Options

- `--job-id` - Specific job ID to check (optional, shows all if not specified)

## Examples

```
/muscle:probe
/muscle:probe --job-id abc12345
```

## Output

Shows all active and recent jobs without `--job-id`, or detailed status of a specific job including:
- Status (pending, running, completed, failed)
- Target path
- Mode (review, pressure, etc.)
- Creation and completion timestamps

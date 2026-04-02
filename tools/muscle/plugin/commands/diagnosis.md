# MUSCLE Diagnosis

Get the final diagnosis/results from a completed MUSCLE shadow job.

## Usage

```
/muscle:diagnosis [--job-id <id>]
```

## Options

- `--job-id` - Specific job ID to get diagnosis (optional, shows most recent if not specified)

## Examples

```
/muscle:diagnosis
/muscle:diagnosis --job-id abc12345
```

## Output

Shows the completed job's:
- Issues found (critical, high, medium counts)
- Top issues with severity and title
- Pressure findings (if run in pressure mode)
- Root cause analysis (if available)

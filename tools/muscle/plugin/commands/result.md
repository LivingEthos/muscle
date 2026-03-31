# MUSCLE Result

Get the results from a completed MUSCLE job.

## Usage

```
/muscle:result [job-id]
```

## Examples

```
/muscle:result
/muscle:result abc123
```

## Output

Shows the final stored output for a finished job including:
- Issues found
- Fixes applied
- Session ID (can be resumed with `codex resume <session-id>`)

See also: `/muscle:status`

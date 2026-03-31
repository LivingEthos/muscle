# MUSCLE Cancel

Cancel a running or pending MUSCLE job.

## Usage

```
/muscle:cancel [job-id]
```

## Examples

```
/muscle:cancel
/muscle:cancel abc123
```

## Output

Confirms cancellation of:
- Running jobs (SIGTERM to worker)
- Pending jobs (removed from queue)

Without job-id, shows interactive list of cancelable jobs.

## Notes

- Running jobs are gracefully stopped (worker finishes current operation)
- Canceled jobs are marked as `canceled` in history
- Results from canceled jobs are not available
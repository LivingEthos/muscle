# MUSCLE Setup

Configure MUSCLE settings including the review gate.

## Usage

```
/muscle:setup [--enable-review-gate] [--disable-review-gate] [--list]
```

## Options

- `--enable-review-gate` - Enable automatic review after Claude Code tasks
- `--disable-review-gate` - Disable automatic review
- `--list` - List current configuration

## Examples

```
/muscle:setup --list
/muscle:setup --enable-review-gate
/muscle:setup --disable-review-gate
```

## Review Gate

When enabled, MUSCLE runs a review after every Claude Code task. Issues found are:
- **Critical/High**: Blocked until fixed or bypassed
- **Medium/Low**: Warned but can be skipped

The review gate catches mistakes before they accumulate. Use `/muscle:setup --disable-review-gate` if it becomes too intrusive.

See also: `/muscle:review`, `/muscle:pressure`

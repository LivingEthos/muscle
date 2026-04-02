# MUSCLE Setup

Configure MUSCLE settings including automatic post-task review.

## Usage

```
/muscle:setup [--enable-auto-review] [--disable-auto-review] [--list]
```

## Options

- `--enable-auto-review` - Enable automatic review after tasks
- `--disable-auto-review` - Disable automatic review
- `--list` - List current configuration

## Examples

```
/muscle:setup --list
/muscle:setup --enable-auto-review
/muscle:setup --disable-auto-review
```

## Automatic Review

When enabled, MUSCLE runs a review after every task. Issues found are:
- **Critical/High**: Blocked until fixed or bypassed
- **Medium/Low**: Warned but can be skipped

The automatic review catches mistakes before they accumulate. Use `/muscle:setup --disable-auto-review` if it becomes too intrusive.

See also: `/muscle:review`, `/muscle:pressure`

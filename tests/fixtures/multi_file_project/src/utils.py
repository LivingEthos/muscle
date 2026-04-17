"""
Sample utility module with common code quality issues.
"""

import re
import subprocess


def run_command(cmd: str) -> str:
    """Command injection vulnerability - unsanitized shell command."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout


def parse_version(version_str: str) -> tuple:
    """Fragile version parsing without error handling."""
    parts = version_str.split(".")
    return tuple(int(p) for p in parts)


def deep_merge(base: dict, override: dict) -> dict:
    """Recursive merge - no depth limit (stack overflow risk)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_email(email: str) -> bool:
    """ReDoS-vulnerable regex."""
    pattern = r"^([a-zA-Z0-9_.+-])+@(([a-zA-Z0-9-])+\.)+([a-zA-Z0-9]{2,4})+$"
    return bool(re.match(pattern, email))


# Global mutable state
_cache: dict = {}


def cached_lookup(key: str, fetcher) -> object:
    """Cache with no expiry or size limit."""
    if key not in _cache:
        _cache[key] = fetcher(key)
    return _cache[key]


def format_currency(amount: float) -> str:
    """Floating point for currency - precision issues."""
    return f"${amount:.2f}"

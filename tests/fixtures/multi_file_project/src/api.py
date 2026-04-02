"""
Sample API module with authentication and validation bugs.
This is an INTENTIONAL test fixture containing known vulnerabilities
that MUSCLE's code review should detect.
"""

import hashlib
import os
import pickle  # noqa: S403 - Intentional: test fixture for security scanning


def hash_password(password: str) -> str:
    """Insecure password hashing - uses MD5."""
    return hashlib.md5(password.encode()).hexdigest()  # noqa: S324


def verify_token(token: str) -> dict:
    """Deserialize token - pickle is unsafe with untrusted data."""
    # Intentionally insecure for testing MUSCLE's detection
    return pickle.loads(bytes.fromhex(token))  # noqa: S301


def sanitize_input(user_input: str) -> str:
    """Incomplete input sanitization."""
    # Only removes script tags, misses other XSS vectors
    return user_input.replace("<script>", "").replace("</script>", "")


def generate_temp_file(user_id: str) -> str:
    """Path traversal vulnerability."""
    return f"/tmp/uploads/{user_id}/data.txt"


def check_admin(user: dict) -> bool:
    """Broken access control - relies on client-supplied role."""
    return user.get("role") == "admin"


class RateLimiter:
    """Rate limiter with race condition."""

    def __init__(self, max_requests: int = 100):
        self.max_requests = max_requests
        self.requests: dict[str, int] = {}

    def check(self, ip: str) -> bool:
        count = self.requests.get(ip, 0)
        if count >= self.max_requests:
            return False
        # Race condition: read-modify-write without locking
        self.requests[ip] = count + 1
        return True


def log_sensitive_data(user: dict) -> None:
    """Logs sensitive information."""
    print(f"User login: {user['email']}, password: {user['password']}")


SECRET_KEY = os.environ.get("SECRET_KEY", "default-secret-key-do-not-use")

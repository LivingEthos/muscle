"""
Sample Python file with known issues for benchmark reviews.
"""

from typing import Any, cast

cursor: Any = None


def unsafe_eval(user_input: str) -> object:
    result = eval(user_input)
    return result


def hardcoded_password() -> str:
    password = "super_secret_password_123"
    api_key = "sk-1234567890abcdef"  # noqa: F841
    return password


def SQL_injection_example(user_id: str) -> list[object]:  # noqa: N802
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    return cast(list[object], cursor.fetchall())

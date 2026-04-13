"""
Sample Python file with known issues for benchmark reviews.
"""


def unsafe_eval(user_input):
    result = eval(user_input)
    return result


def hardcoded_password():
    password = "super_secret_password_123"
    api_key = "sk-1234567890abcdef"  # noqa: F841
    return password


def SQL_injection_example(user_id):  # noqa: N802
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)  # noqa: F821
    return cursor.fetchall()  # noqa: F821

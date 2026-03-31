"""
Sample Python file with known issues for testing static analysis.
"""

import os
import subprocess
import json


def unsafe_eval(user_input):
    """This function has a security issue - using eval with user input."""
    result = eval(user_input)
    return result


def hardcoded_password():
    """Function with hardcoded credentials - security issue."""
    password = "super_secret_password_123"
    api_key = "sk-1234567890abcdef"
    return password


def SQL_injection_example(user_id):
    """Classic SQL injection vulnerability."""
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    return cursor.fetchall()


def unused_import():
    """This imports but never uses subprocess."""
    import subprocess
    print("Hello")


def line_too_long_function():
    """This is a very very very very very very very very very very very very very very very very very very very very long function name that exceeds 88 characters limit."""
    pass


class EmptyClass:
    """Empty class with pass - code smell."""
    pass


def missing_docstring(x, y):
    """This function has params but no docstring for them."""
    return x + y


def global_variable_usage():
    """Using global variables is not ideal."""
    global counter
    counter += 1
    return counter


# Module level constant
API_URL = "https://api.example.com"
DEBUG = True

"""
Sample database module with connection management bugs.
"""

import sqlite3
from threading import local

_thread_local = local()


def get_connection(db_path: str = "app.db") -> sqlite3.Connection:
    """Get database connection - leaks connections across threads."""
    if not hasattr(_thread_local, "connection"):
        _thread_local.connection = sqlite3.connect(db_path)
    return _thread_local.connection


def execute_query(query: str, params: tuple = ()) -> list:
    """Execute query with SQL injection vulnerability."""
    conn = get_connection()
    cursor = conn.cursor()
    # Bug: f-string instead of parameterized query
    cursor.execute(f"SELECT * FROM data WHERE {query}")
    return cursor.fetchall()


def insert_record(table: str, data: dict) -> int:
    """Insert record - no input validation on table name."""
    conn = get_connection()
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    cursor = conn.cursor()
    cursor.execute(query, tuple(data.values()))
    conn.commit()
    return cursor.lastrowid


def close_all():
    """Close connection - but doesn't handle errors."""
    if hasattr(_thread_local, "connection"):
        _thread_local.connection.close()
        del _thread_local.connection

"""
Neutral baseline fixture with straightforward, defensive code.
"""

from __future__ import annotations


def normalize_customer(record: dict[str, str]) -> dict[str, str]:
    """Return a normalized customer record without side effects."""
    name = record.get("name", "").strip()
    email = record.get("email", "").strip().lower()
    status = record.get("status", "active").strip().lower()
    return {
        "name": name,
        "email": email,
        "status": status,
    }

"""
Reference code for a related project whose lessons should transfer well.
"""

from __future__ import annotations


def validate_payment_payload(payload: dict[str, object]) -> bool:
    required = {"payment_id", "status", "currency"}
    return required.issubset(payload)

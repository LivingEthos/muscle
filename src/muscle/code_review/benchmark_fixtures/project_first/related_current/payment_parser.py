"""
Project-first related-project fixture with brittle payment response parsing.
"""

from __future__ import annotations

import json
from typing import Any


def read_payment_status(raw_response: str) -> dict[str, Any]:
    payload = json.loads(raw_response)
    return {
        "payment_id": payload["payment_id"],
        "status": payload["status"],
        "amount_cents": payload.get("amount_cents", 0),
        "currency": payload["currency"],
    }

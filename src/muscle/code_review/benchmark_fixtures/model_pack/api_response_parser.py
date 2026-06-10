"""
Model-pack fixture with fragile nested API response assumptions.
"""

from __future__ import annotations

import json
from typing import Any


def load_profile(response_text: str) -> dict[str, Any]:
    payload = json.loads(response_text)
    return {
        "user_id": payload["user"]["id"],
        "email": payload["user"]["email"],
        "plan": payload["subscription"]["plan"],
        "status": payload["subscription"]["status"],
    }

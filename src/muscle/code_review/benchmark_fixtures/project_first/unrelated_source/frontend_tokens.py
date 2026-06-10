"""
Reference code for an unrelated project whose lessons should not overlap payment parsing work.
"""

from __future__ import annotations


def button_palette(theme: str) -> dict[str, str]:
    if theme == "dark":
        return {"background": "#111827", "foreground": "#f9fafb"}
    return {"background": "#ffffff", "foreground": "#111827"}

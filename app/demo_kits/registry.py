"""Detect a curated demo kit from a free-text intent string.

Case-insensitive substring match against each kit's `triggers`.
Returns the matching `DemoKit` or `None`. First match wins, ordered by
specificity (more specific tokens first to avoid false positives).
"""
from __future__ import annotations

from .kits import CALCULATOR_KIT, POMODORO_KIT, SNAKE_KIT, TETRIS_KIT
from .schemas import DemoKit

# Order matters: prefer more specific tokens first. "snake game" before "snake",
# "tomato timer" before "pomodoro", etc.
ALL_KITS: list[DemoKit] = [
    TETRIS_KIT,
    POMODORO_KIT,
    CALCULATOR_KIT,
    SNAKE_KIT,
]


def detect_kit(intent: str) -> DemoKit | None:
    if not intent:
        return None
    lower = intent.lower()
    for kit in ALL_KITS:
        for trigger in kit.triggers:
            if trigger.lower() in lower:
                return kit
    return None


def kit_by_id(kit_id: str) -> DemoKit | None:
    for kit in ALL_KITS:
        if kit.kit_id == kit_id:
            return kit
    return None

"""Actuator interface for executing one game action."""

from __future__ import annotations

from typing import Protocol


class ActionActuator(Protocol):
    """Thin execution boundary for one planned action."""

    def execute(self, action: str) -> None:
        """Execute the requested action or raise on failure."""

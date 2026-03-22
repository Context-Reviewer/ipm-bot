"""Actuator interface for executing one game action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


ActuatorExecutionStatus = Literal["NOT_REQUIRED", "COMPLETED", "FAILED"]


@dataclass(frozen=True, slots=True)
class ActuatorExecutionMetadata:
    actuator_type: str
    actuator_execution_status: ActuatorExecutionStatus
    actuator_command_count: int
    actuator_command_summary: list[str]

    def __post_init__(self) -> None:
        if not self.actuator_type:
            raise ValueError("Actuator execution metadata actuator_type must not be empty.")
        if self.actuator_command_count < 0:
            raise ValueError("Actuator command count must be non-negative.")
        if self.actuator_command_count != len(self.actuator_command_summary):
            raise ValueError(
                "Actuator command count must match the number of command summary entries."
            )


class ActuatorExecutionError(Exception):
    """Raised when a concrete actuator fails while issuing commands."""

    def __init__(
        self,
        message: str,
        metadata: ActuatorExecutionMetadata,
    ) -> None:
        super().__init__(message)
        self.metadata = metadata


class ActionActuator(Protocol):
    """Thin execution boundary for one planned action."""

    actuator_type: str

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        """Execute the requested action or raise on failure."""

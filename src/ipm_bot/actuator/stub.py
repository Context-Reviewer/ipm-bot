"""Concrete local stub actuator used for development and testing."""

from __future__ import annotations

from typing import Callable

from .boundary import (
    ActionActuator,
    ActuatorConfigSnapshot,
    ActuatorExecutionError,
    ActuatorExecutionMetadata,
)


class StubActionActuator(ActionActuator):
    """Local stub actuator that logs the action instead of driving ADB."""

    actuator_type = "stub"
    config_snapshot = ActuatorConfigSnapshot(actuator_type="stub")

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        normalized_action = action.strip()
        if not normalized_action:
            raise ActuatorExecutionError(
                "Action name must not be empty.",
                ActuatorExecutionMetadata(
                    actuator_type=self.actuator_type,
                    actuator_execution_status="FAILED",
                    actuator_command_count=0,
                    actuator_command_summary=[],
                ),
            )

        handler = _ACTION_HANDLERS.get(normalized_action)
        if handler is None:
            raise ActuatorExecutionError(
                f"Unsupported action: {normalized_action}",
                ActuatorExecutionMetadata(
                    actuator_type=self.actuator_type,
                    actuator_execution_status="FAILED",
                    actuator_command_count=0,
                    actuator_command_summary=[],
                ),
            )

        handler()
        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=1,
            actuator_command_summary=[f"stub:{normalized_action}"],
        )


def _execute_activate_ad_boost() -> None:
    print("Executing action: activate_ad_boost")


def _execute_claim_ark_reward() -> None:
    print("Executing action: claim_ark_reward")


def _execute_idle() -> None:
    print("Executing action: idle")


_ACTION_HANDLERS: dict[str, Callable[[], None]] = {
    "activate_ad_boost": _execute_activate_ad_boost,
    "claim_ark_reward": _execute_claim_ark_reward,
    "idle": _execute_idle,
}

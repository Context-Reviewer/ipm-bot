"""Concrete local stub actuator used for development and testing."""

from __future__ import annotations

from typing import Callable

from .boundary import ActionActuator


class StubActionActuator(ActionActuator):
    """Local stub actuator that logs the action instead of driving ADB."""

    def execute(self, action: str) -> None:
        normalized_action = action.strip()
        if not normalized_action:
            raise ValueError("Action name must not be empty.")

        handler = _ACTION_HANDLERS.get(normalized_action)
        if handler is None:
            raise ValueError(f"Unsupported action: {normalized_action}")

        handler()


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

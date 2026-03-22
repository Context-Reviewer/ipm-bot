"""Canonical action contracts for the closed-loop control system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ipm_bot.save.schema import SNAPSHOT_FIELD_ORDER


_KNOWN_FIELDS = frozenset(SNAPSHOT_FIELD_ORDER)


def _validate_known_field(field_name: str) -> None:
    if field_name not in _KNOWN_FIELDS:
        raise ValueError(f"Unknown snapshot field in action contract: '{field_name}'.")


@dataclass(frozen=True, slots=True)
class ActionContractIdentity:
    action: str
    expectation_keys: tuple[str, ...]
    required_expected_values: dict[str, Any]
    supporting_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.action:
            raise ValueError("Action contract identity action must not be empty.")
        for field_name in self.required_expected_values:
            _validate_known_field(field_name)
        for field_name in self.supporting_fields:
            _validate_known_field(field_name)


@dataclass(frozen=True, slots=True)
class ActionContract:
    expectations: dict[str, Any]
    supporting_fields: tuple[str, ...]
    default_timeout_seconds: float

    def __post_init__(self) -> None:
        if self.default_timeout_seconds <= 0:
            raise ValueError("Action contract timeout must be greater than zero.")

        for key in ("must_change", "must_not_change"):
            raw_fields = self.expectations.get(key, [])
            if not isinstance(raw_fields, list):
                raise TypeError(f"Action contract field '{key}' must be a list of field names.")
            for field_name in raw_fields:
                _validate_known_field(field_name)

        expected_values = self.expectations.get("expected_values", {})
        if not isinstance(expected_values, Mapping):
            raise TypeError("Action contract 'expected_values' must be a mapping.")
        for field_name in expected_values:
            _validate_known_field(field_name)

        for field_name in self.supporting_fields:
            _validate_known_field(field_name)

    def identity(self, action: str) -> ActionContractIdentity:
        """Return a lean, deterministic identity block for this action contract."""

        return ActionContractIdentity(
            action=action,
            expectation_keys=tuple(sorted(self.expectations)),
            required_expected_values=dict(self.expectations.get("expected_values", {})),
            supporting_fields=tuple(self.supporting_fields),
        )


ACTION_CONTRACTS: dict[str, ActionContract] = {
    "activate_ad_boost": ActionContract(
        expectations={
            "must_not_change": ["player_level"],
            "expected_values": {
                "ad_boost_active": True,
            },
        },
        supporting_fields=("ads_watched", "save_timestamp"),
        default_timeout_seconds=30.0,
    ),
    "claim_ark_reward": ActionContract(
        expectations={
            "must_not_change": ["player_level"],
            "expected_values": {
                "ark_reward_ready_to_claim": False,
            },
        },
        supporting_fields=("save_timestamp",),
        default_timeout_seconds=30.0,
    ),
    "idle": ActionContract(
        expectations={},
        supporting_fields=(),
        default_timeout_seconds=1.0,
    ),
}


def get_action_contract(action: str) -> ActionContract:
    """Return the canonical contract for a supported action."""

    contract = ACTION_CONTRACTS.get(action)
    if contract is None:
        raise ValueError(f"No action contract configured for action '{action}'.")
    return contract

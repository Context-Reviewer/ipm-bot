"""Deterministic action selection from a parsed player snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from ipm_bot.save.models import PlayerSnapshot


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    selected_action: str
    decision_reason: str
    actuation_required: bool

    def __post_init__(self) -> None:
        if not self.selected_action:
            raise ValueError("Planner decision selected_action must not be empty.")
        if not self.decision_reason:
            raise ValueError("Planner decision decision_reason must not be empty.")


def decide_next_action(snapshot: PlayerSnapshot) -> str:
    """Choose the next action from the current normalized save state."""

    return decide_next_action_details(snapshot).selected_action


def decide_next_action_details(snapshot: PlayerSnapshot) -> PlannerDecision:
    """Choose the next action and expose the deterministic rule that selected it."""

    ark_reward_ready = snapshot.ad.ark_reward_ready_to_claim
    if ark_reward_ready is None:
        raise ValueError("Missing required snapshot field: ark_reward_ready_to_claim.")

    ad_boost_active = snapshot.ad.ad_boost_active
    if ad_boost_active is None:
        raise ValueError("Missing required snapshot field: ad_boost_active.")
    if not ad_boost_active:
        return PlannerDecision(
            selected_action="activate_ad_boost",
            decision_reason="ad_boost_inactive",
            actuation_required=True,
        )

    # Ark remains available for explicit/manual experiments, but production auto-selection
    # does not choose it because recorded live runs showed incompatible provider-specific
    # UI paths that are outside the current no-detection/no-branching constraints.
    if ark_reward_ready:
        return PlannerDecision(
            selected_action="idle",
            decision_reason="no_action_needed",
            actuation_required=False,
        )

    return PlannerDecision(
        selected_action="idle",
        decision_reason="no_action_needed",
        actuation_required=False,
    )

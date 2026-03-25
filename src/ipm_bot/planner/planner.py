"""Deterministic action selection from a parsed player snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ipm_bot.control.save_source import SaveProductionSlotSnapshot, SaveSnapshot
from ipm_bot.control.timing import summarize_production_timing
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


def decide_next_action(
    snapshot: PlayerSnapshot,
    save_snapshot: SaveSnapshot | None = None,
) -> str:
    """Choose the next action from the current normalized save state."""

    return decide_next_action_details(snapshot, save_snapshot=save_snapshot).selected_action


def decide_next_action_details(
    snapshot: PlayerSnapshot,
    save_snapshot: SaveSnapshot | None = None,
) -> PlannerDecision:
    """Choose the next action and expose the deterministic rule that selected it."""

    ark_reward_ready = snapshot.ad.ark_reward_ready_to_claim
    if ark_reward_ready is None:
        raise ValueError("Missing required snapshot field: ark_reward_ready_to_claim.")

    ad_boost_active = snapshot.ad.ad_boost_active
    if ad_boost_active is None:
        raise ValueError("Missing required snapshot field: ad_boost_active.")
    if not ad_boost_active:
        if _should_defer_for_imminent_completion(save_snapshot):
            return PlannerDecision(
                selected_action="idle",
                decision_reason="defer_ad_boost_for_imminent_completion",
                actuation_required=False,
            )
        return PlannerDecision(
            selected_action="activate_ad_boost",
            decision_reason="ad_boost_inactive",
            actuation_required=True,
        )

    # Ark remains available for explicit/manual experiments, but production auto-selection
    # does not choose it because recorded live runs showed incompatible provider-specific
    # UI paths that are outside the current no-detection/no-branching constraints.
    if ark_reward_ready:
        return _idle_decision_from_save_snapshot(save_snapshot)

    return _idle_decision_from_save_snapshot(save_snapshot)


def decide_from_save_snapshot(save_snapshot: SaveSnapshot) -> PlannerDecision:
    """Demonstrate a deterministic planner decision driven only by SaveSnapshot timing data."""

    return _idle_decision_from_save_snapshot(save_snapshot)


def format_active_smelter_lines(save_snapshot: SaveSnapshot) -> tuple[str, ...]:
    """Render active smelter timing as stable human-readable lines."""

    return tuple(
        (
            f"slot {slot.index}: recipe={slot.recipe_number} "
            f"duration={slot.duration_estimate:.3f}s "
            f"left={slot.timespan_left.total_seconds():.3f}s"
        )
        for slot in _active_smelters(save_snapshot)
    )


def _idle_decision_from_save_snapshot(
    save_snapshot: SaveSnapshot | None,
) -> PlannerDecision:
    timing = summarize_production_timing(save_snapshot)
    if not timing.has_active_production:
        return PlannerDecision(
            selected_action="idle",
            decision_reason="no_action_needed",
            actuation_required=False,
        )

    if timing.completion_imminent:
        return PlannerDecision(
            selected_action="idle",
            decision_reason="production_completion_imminent",
            actuation_required=False,
        )

    return PlannerDecision(
        selected_action="idle",
        decision_reason="production_in_flight",
        actuation_required=False,
    )


def _active_smelters(save_snapshot: SaveSnapshot) -> Iterable[SaveProductionSlotSnapshot]:
    return (slot for slot in save_snapshot.smelters if slot.on)


def _should_defer_for_imminent_completion(save_snapshot: SaveSnapshot | None) -> bool:
    return summarize_production_timing(save_snapshot).completion_imminent

"""Reward-state mapping derived from normalized save fields."""

from __future__ import annotations

from dataclasses import dataclass

from ipm_bot.save.models import PlayerSnapshot


@dataclass(frozen=True, slots=True)
class RewardState:
    pending_reward_type_raw: int | None
    reward_type: str
    reward_available: bool
    reward_requires_ad: bool
    reward_claim_pending: bool
    reward_applied: bool | None
    ark_reward_ready_to_claim: bool | None
    reward_is_dark_matter: bool | None
    free_rewards_claimed_count: int | None
    miner_pass_rewards_claimed_count: int | None


def map_snapshot_to_reward_state(snapshot: PlayerSnapshot) -> RewardState:
    pending_reward_type = snapshot.ad.pending_reward_type
    ark_reward_ready = snapshot.ad.ark_reward_ready_to_claim
    has_pending_reward_type = pending_reward_type not in (None, 0)
    reward_available = bool(ark_reward_ready) or has_pending_reward_type
    return RewardState(
        pending_reward_type_raw=pending_reward_type,
        reward_type=_map_reward_type(pending_reward_type),
        reward_available=reward_available,
        reward_requires_ad=bool(ark_reward_ready),
        reward_claim_pending=reward_available,
        reward_applied=None,
        ark_reward_ready_to_claim=ark_reward_ready,
        reward_is_dark_matter=snapshot.ad.reward_is_dark_matter,
        free_rewards_claimed_count=snapshot.event.free_rewards_claimed_count,
        miner_pass_rewards_claimed_count=snapshot.event.miner_pass_rewards_claimed_count,
    )


def evaluate_reward_application(
    before: PlayerSnapshot,
    after: PlayerSnapshot,
) -> RewardState:
    after_state = map_snapshot_to_reward_state(after)
    reward_applied = _reward_application_proven(before, after)
    return RewardState(
        pending_reward_type_raw=after_state.pending_reward_type_raw,
        reward_type=after_state.reward_type,
        reward_available=after_state.reward_available,
        reward_requires_ad=after_state.reward_requires_ad,
        reward_claim_pending=after_state.reward_claim_pending,
        reward_applied=reward_applied,
        ark_reward_ready_to_claim=after_state.ark_reward_ready_to_claim,
        reward_is_dark_matter=after_state.reward_is_dark_matter,
        free_rewards_claimed_count=after_state.free_rewards_claimed_count,
        miner_pass_rewards_claimed_count=after_state.miner_pass_rewards_claimed_count,
    )


def _map_reward_type(pending_reward_type: int | None) -> str:
    if pending_reward_type in (None, 0):
        return "none"
    return f"pending_reward_type_{pending_reward_type}"


def _reward_application_proven(before: PlayerSnapshot, after: PlayerSnapshot) -> bool:
    if before.ad.pending_reward_type != after.ad.pending_reward_type:
        return True
    if (
        before.event.free_rewards_claimed_count is not None
        and after.event.free_rewards_claimed_count is not None
        and after.event.free_rewards_claimed_count > before.event.free_rewards_claimed_count
    ):
        return True
    if (
        before.event.miner_pass_rewards_claimed_count is not None
        and after.event.miner_pass_rewards_claimed_count is not None
        and (
            after.event.miner_pass_rewards_claimed_count
            > before.event.miner_pass_rewards_claimed_count
        )
    ):
        return True
    if (
        before.ad.ark_reward_ready_to_claim is True
        and after.ad.ark_reward_ready_to_claim is False
    ):
        return True
    if (
        before.ad.arks_claimed is not None
        and after.ad.arks_claimed is not None
        and after.ad.arks_claimed > before.ad.arks_claimed
    ):
        return True
    return False

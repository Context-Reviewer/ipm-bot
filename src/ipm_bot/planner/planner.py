"""Deterministic action selection from a parsed player snapshot."""

from __future__ import annotations

from ipm_bot.save.models import PlayerSnapshot


def decide_next_action(snapshot: PlayerSnapshot) -> str:
    """Choose the next action from the current normalized save state."""

    ark_reward_ready = snapshot.ad.ark_reward_ready_to_claim
    if ark_reward_ready is None:
        raise ValueError("Missing required snapshot field: ark_reward_ready_to_claim.")
    if ark_reward_ready:
        return "claim_ark_reward"

    ad_boost_active = snapshot.ad.ad_boost_active
    if ad_boost_active is None:
        raise ValueError("Missing required snapshot field: ad_boost_active.")
    if not ad_boost_active:
        return "activate_ad_boost"

    return "idle"

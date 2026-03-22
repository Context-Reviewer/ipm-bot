"""Normalized save-state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


ScalarValue = bool | int | float | str | datetime | None


@dataclass(frozen=True, slots=True)
class CurrencyState:
    cash: float | None = None
    dark_matter: int | None = None
    energy_cell: int | None = None
    holo_bolts: int | None = None
    prestige_currency: int | None = None


@dataclass(frozen=True, slots=True)
class AdState:
    ad_boost_active: bool | None = None
    ad_boost_start_date: datetime | None = None
    last_ad_watched_date: datetime | None = None
    ads_watched: int | None = None
    arks_claimed: int | None = None
    pending_reward_type: int | None = None
    reward_is_dark_matter: bool | None = None
    ark_reward_ready_to_claim: bool | None = None
    daily_gift_ready: bool | None = None
    daily_gift_ad_watched: bool | None = None


@dataclass(frozen=True, slots=True)
class EventState:
    event_mission_showed: bool | None = None
    is_local_event_running: bool | None = None
    local_event_id: int | None = None
    local_event_close_time: datetime | None = None
    last_closed_local_event_global_id: str | None = None
    last_miner_pass_owned: int | None = None
    is_miner_pass_activated: bool | None = None
    free_rewards_claimed_ref: int | None = None
    miner_pass_rewards_claimed_ref: int | None = None


@dataclass(frozen=True, slots=True)
class SaveMetadata:
    save_timestamp: datetime | None = None
    initial_data_uploaded_to_firestore: bool | None = None
    corrupted_data_uploaded_on_playfab: bool | None = None
    source_path: str | None = None
    source_format: str = "unknown"
    top_level_member_count: int = 0


@dataclass(frozen=True, slots=True)
class PlayerProgressState:
    player_level: int | None = None
    player_xp: int | None = None


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    currencies: CurrencyState
    ad: AdState
    event: EventState
    metadata: SaveMetadata
    player: PlayerProgressState
    raw_fields: dict[str, Any] = field(default_factory=dict)
    unresolved_references: dict[str, int] = field(default_factory=dict)

    def flat_fields(self) -> dict[str, ScalarValue]:
        """Return the normalized scalar fields used by diffing and summaries."""

        return {
            "cash": self.currencies.cash,
            "dark_matter": self.currencies.dark_matter,
            "energy_cell": self.currencies.energy_cell,
            "holo_bolts": self.currencies.holo_bolts,
            "prestige_currency": self.currencies.prestige_currency,
            "ad_boost_active": self.ad.ad_boost_active,
            "ad_boost_start_date": self.ad.ad_boost_start_date,
            "last_ad_watched_date": self.ad.last_ad_watched_date,
            "ads_watched": self.ad.ads_watched,
            "arks_claimed": self.ad.arks_claimed,
            "pending_reward_type": self.ad.pending_reward_type,
            "reward_is_dark_matter": self.ad.reward_is_dark_matter,
            "ark_reward_ready_to_claim": self.ad.ark_reward_ready_to_claim,
            "daily_gift_ready": self.ad.daily_gift_ready,
            "daily_gift_ad_watched": self.ad.daily_gift_ad_watched,
            "event_mission_showed": self.event.event_mission_showed,
            "is_local_event_running": self.event.is_local_event_running,
            "local_event_id": self.event.local_event_id,
            "local_event_close_time": self.event.local_event_close_time,
            "last_closed_local_event_global_id": (
                self.event.last_closed_local_event_global_id
            ),
            "last_miner_pass_owned": self.event.last_miner_pass_owned,
            "is_miner_pass_activated": self.event.is_miner_pass_activated,
            "save_timestamp": self.metadata.save_timestamp,
            "initial_data_uploaded_to_firestore": (
                self.metadata.initial_data_uploaded_to_firestore
            ),
            "corrupted_data_uploaded_on_playfab": (
                self.metadata.corrupted_data_uploaded_on_playfab
            ),
            "player_level": self.player.player_level,
            "player_xp": self.player.player_xp,
        }

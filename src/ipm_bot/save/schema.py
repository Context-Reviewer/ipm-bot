"""Static inventory of the high-value PlayerData fields used in v1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchemaField:
    source_name: str
    normalized_name: str
    bucket: str
    type_name: str
    notes: str = ""
    include_in_snapshot: bool = True


FIELD_INVENTORY: tuple[SchemaField, ...] = (
    SchemaField("cash", "cash", "currency", "Double", "Current soft currency."),
    SchemaField(
        "darkMatter",
        "dark_matter",
        "currency",
        "Int32",
        "Premium currency.",
    ),
    SchemaField(
        "energyCell",
        "energy_cell",
        "currency",
        "Int32",
        "Current energy cell balance.",
    ),
    SchemaField(
        "holoBolts",
        "holo_bolts",
        "currency",
        "Int32",
        "Current holo bolts balance.",
    ),
    SchemaField(
        "prestigeCurrency",
        "prestige_currency",
        "currency",
        "Int32",
        "Current prestige currency balance.",
    ),
    SchemaField(
        "adBoostActive",
        "ad_boost_active",
        "ad",
        "Boolean",
        "Whether the ad boost is currently active.",
    ),
    SchemaField(
        "adBoostStartDate",
        "ad_boost_start_date",
        "ad",
        "DateTime",
        "Raw top-level DateTime in PlayerData.",
    ),
    SchemaField(
        "lastAdWatchedDate",
        "last_ad_watched_date",
        "ad",
        "DateTime",
        "Last rewarded ad watch timestamp.",
    ),
    SchemaField(
        "adsWatched",
        "ads_watched",
        "ad",
        "Int32",
        "Lifetime or current-run watched-ad counter.",
    ),
    SchemaField(
        "arksClaimed",
        "arks_claimed",
        "ad",
        "Int32",
        "Number of claimed ark rewards.",
    ),
    SchemaField(
        "pendingRewardType",
        "pending_reward_type",
        "ad",
        "Int32",
        "Pending reward enum/int marker.",
    ),
    SchemaField(
        "rewardIsDarkMatterBool",
        "reward_is_dark_matter",
        "ad",
        "Boolean",
        "Whether the pending reward is dark matter.",
    ),
    SchemaField(
        "arkRewardReadyToClaim",
        "ark_reward_ready_to_claim",
        "ad",
        "Boolean",
        "Whether an ark reward is claimable.",
    ),
    SchemaField(
        "dailyGiftReadyBool",
        "daily_gift_ready",
        "ad",
        "Boolean",
        "Whether the daily gift is ready.",
    ),
    SchemaField(
        "dailyGiftAdWatchedBool",
        "daily_gift_ad_watched",
        "ad",
        "Boolean",
        "Whether the daily gift ad has been watched.",
    ),
    SchemaField(
        "saveTimestamp",
        "save_timestamp",
        "save",
        "DateTime",
        "Top-level save timestamp used for verification.",
    ),
    SchemaField(
        "initialDataUploadedToFirestore",
        "initial_data_uploaded_to_firestore",
        "save",
        "Boolean",
        "Cloud/bootstrap upload bookkeeping.",
    ),
    SchemaField(
        "corruptedDataUploadedOnPlayfab",
        "corrupted_data_uploaded_on_playfab",
        "save",
        "Boolean",
        "Corruption reporting/upload bookkeeping.",
    ),
    SchemaField(
        "playerLevel",
        "player_level",
        "player",
        "Int32",
        "Current player level.",
    ),
    SchemaField(
        "playerXP",
        "player_xp",
        "player",
        "Int32",
        "Current player XP.",
    ),
    SchemaField(
        "eventMissionShowed",
        "event_mission_showed",
        "event",
        "Boolean",
        "Whether the event mission UI/state has shown.",
    ),
    SchemaField(
        "isLocalEventRunning",
        "is_local_event_running",
        "event",
        "Boolean",
        "Whether a local event is active.",
    ),
    SchemaField(
        "localEventId",
        "local_event_id",
        "event",
        "Int32",
        "Current local event identifier.",
    ),
    SchemaField(
        "localEventCloseTime",
        "local_event_close_time",
        "event",
        "DateTime",
        "Local event close time.",
    ),
    SchemaField(
        "lastClosedLocalEventGlobalId",
        "last_closed_local_event_global_id",
        "event",
        "String",
        "Global ID of the last closed local event.",
    ),
    SchemaField(
        "lastMinerPassOwned",
        "last_miner_pass_owned",
        "event",
        "Int32",
        "Top-level miner-pass ownership marker.",
    ),
    SchemaField(
        "isMinerPassActivated",
        "is_miner_pass_activated",
        "event",
        "Boolean",
        "Whether the current miner pass is activated.",
    ),
    SchemaField(
        "freeRewardsClaimed",
        "free_rewards_claimed_ref",
        "event",
        "List<Boolean>",
        "Currently tracked as an unresolved top-level object reference only.",
        include_in_snapshot=False,
    ),
    SchemaField(
        "minerPassRewardsClaimed",
        "miner_pass_rewards_claimed_ref",
        "event",
        "List<Boolean>",
        "Currently tracked as an unresolved top-level object reference only.",
        include_in_snapshot=False,
    ),
)

FIELDS_BY_SOURCE_NAME = {field.source_name: field for field in FIELD_INVENTORY}
FIELDS_BY_NORMALIZED_NAME = {
    field.normalized_name: field for field in FIELD_INVENTORY
}
SNAPSHOT_FIELD_ORDER = tuple(
    field.normalized_name for field in FIELD_INVENTORY if field.include_in_snapshot
)


def get_field(source_name: str) -> SchemaField | None:
    """Return the schema metadata for a PlayerData source field."""

    return FIELDS_BY_SOURCE_NAME.get(source_name)


def fields_for_bucket(bucket: str) -> tuple[SchemaField, ...]:
    """Return all inventoried fields in a bucket."""

    return tuple(field for field in FIELD_INVENTORY if field.bucket == bucket)

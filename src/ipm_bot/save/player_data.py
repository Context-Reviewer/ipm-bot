"""Read-only PlayerData model built from sub-record parser output.

Provides typed, structured access to game state extracted from playerInfo.dat.
No mutation logic — read-only layer only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .sub_records import (
    ArraySubRecord,
    ClassSubRecord,
    ObjectArraySubRecord,
    RectangularArraySubRecord,
    StringSubRecord,
    SubRecordParseResult,
    parse_sub_records,
)


# ── Slot dataclasses ──


@dataclass(frozen=True, slots=True)
class SmelterSlot:
    """State of a single smelter slot."""
    index: int
    on: bool
    recipe_selected: bool
    alternate_recipe_selected: bool
    recipe_number: int
    start_date: datetime | None
    end_date: datetime | None
    original_end_date: datetime | None
    timespan_left: timedelta
    seconds_completed: float


@dataclass(frozen=True, slots=True)
class CrafterSlot:
    """State of a single crafter slot."""
    index: int
    on: bool
    recipe_selected: bool
    alternate_recipe_selected: bool
    recipe_number: int
    start_date: datetime | None
    end_date: datetime | None
    original_end_date: datetime | None
    timespan_left: timedelta
    seconds_completed: float


@dataclass(frozen=True, slots=True)
class PlanetSlot:
    """State of a single planet."""
    index: int
    unlocked: bool
    mining_speed_level: int
    speed_level: int
    cargo_level: int
    trip_start_date: datetime | None
    trip_end_date: datetime | None


@dataclass(frozen=True, slots=True)
class ResourceSlot:
    """State of a single resource type."""
    index: int
    discovered: bool
    count: float
    gathered_total: float
    gathered_this_galaxy: float
    sold_total: float
    sold_this_galaxy: float


@dataclass(frozen=True, slots=True)
class PlayerData:
    """Structured read-only representation of the parsed save file."""
    smelters: tuple[SmelterSlot, ...]
    crafters: tuple[CrafterSlot, ...]
    planets: tuple[PlanetSlot, ...]
    resources: tuple[ResourceSlot, ...]
    # Raw parse result retained for access to any field not modeled above
    raw: SubRecordParseResult


# ── Helpers ──


def _get_array_values(result: SubRecordParseResult, field_name: str) -> tuple[Any, ...]:
    """Get the values tuple for a named array field."""
    for obj_id, rec in result.sub_records.items():
        if isinstance(rec, (ArraySubRecord, RectangularArraySubRecord)) and rec.field_name == field_name:
            return rec.values
    return ()


def _safe_datetime(val: Any) -> datetime | None:
    """Return None for epoch/sentinel DateTimes."""
    if val is None:
        return None
    if isinstance(val, datetime) and val.year <= 1:
        return None
    return val


# ── Factory ──


def load_player_data(source: str | Path | bytes) -> PlayerData:
    """Parse a playerInfo.dat file and return a structured PlayerData model."""
    result = parse_sub_records(source)

    # ── Smelters ──
    smelter_on = _get_array_values(result, "smelterOn")
    smelt_recipe_selected = _get_array_values(result, "smeltRecipeSelectedBool")
    alt_smelt_recipe = _get_array_values(result, "alternateSmeltRecipeSelected")
    smelt_recipe_num = _get_array_values(result, "smeltRecipeNumber")
    smelter_start = _get_array_values(result, "smelterStartDate")
    smelter_end = _get_array_values(result, "smelterEndDate")
    smelter_orig_end = _get_array_values(result, "smelterOriginalEndDate")
    smelter_timespan = _get_array_values(result, "smelterTimespanLeft")
    smelter_seconds = _get_array_values(result, "smelterSecondsCompleted")

    n_smelters = len(smelter_on)
    smelters = tuple(
        SmelterSlot(
            index=i,
            on=smelter_on[i] if i < len(smelter_on) else False,
            recipe_selected=smelt_recipe_selected[i] if i < len(smelt_recipe_selected) else False,
            alternate_recipe_selected=alt_smelt_recipe[i] if i < len(alt_smelt_recipe) else False,
            recipe_number=smelt_recipe_num[i] if i < len(smelt_recipe_num) else 0,
            start_date=_safe_datetime(smelter_start[i]) if i < len(smelter_start) else None,
            end_date=_safe_datetime(smelter_end[i]) if i < len(smelter_end) else None,
            original_end_date=_safe_datetime(smelter_orig_end[i]) if i < len(smelter_orig_end) else None,
            timespan_left=smelter_timespan[i] if i < len(smelter_timespan) else timedelta(0),
            seconds_completed=smelter_seconds[i] if i < len(smelter_seconds) else 0.0,
        )
        for i in range(n_smelters)
    )

    # ── Crafters ──
    crafter_on = _get_array_values(result, "crafterOn")
    craft_recipe_selected = _get_array_values(result, "craftRecipeSelectedBool")
    alt_craft_recipe = _get_array_values(result, "alternateCraftRecipeSelected")
    craft_recipe_num = _get_array_values(result, "craftRecipeNumber")
    crafter_start = _get_array_values(result, "crafterStartDate")
    crafter_end = _get_array_values(result, "crafterEndDate")
    crafter_orig_end = _get_array_values(result, "crafterOriginalEndDate")
    crafter_timespan = _get_array_values(result, "crafterTimespanLeft")
    crafter_seconds = _get_array_values(result, "crafterSecondsCompleted")

    n_crafters = len(crafter_on)
    crafters = tuple(
        CrafterSlot(
            index=i,
            on=crafter_on[i] if i < len(crafter_on) else False,
            recipe_selected=craft_recipe_selected[i] if i < len(craft_recipe_selected) else False,
            alternate_recipe_selected=alt_craft_recipe[i] if i < len(alt_craft_recipe) else False,
            recipe_number=craft_recipe_num[i] if i < len(craft_recipe_num) else 0,
            start_date=_safe_datetime(crafter_start[i]) if i < len(crafter_start) else None,
            end_date=_safe_datetime(crafter_end[i]) if i < len(crafter_end) else None,
            original_end_date=_safe_datetime(crafter_orig_end[i]) if i < len(crafter_orig_end) else None,
            timespan_left=crafter_timespan[i] if i < len(crafter_timespan) else timedelta(0),
            seconds_completed=crafter_seconds[i] if i < len(crafter_seconds) else 0.0,
        )
        for i in range(n_crafters)
    )

    # ── Planets ──
    planet_unlocked = _get_array_values(result, "planetUnlocked")
    mining_speed = _get_array_values(result, "miningSpeedLevel")
    speed_level = _get_array_values(result, "speedLevel")
    cargo_level = _get_array_values(result, "cargoLevel")
    trip_start = _get_array_values(result, "tripStartDate")
    trip_end = _get_array_values(result, "tripEndDate")

    n_planets = len(planet_unlocked)
    planets = tuple(
        PlanetSlot(
            index=i,
            unlocked=planet_unlocked[i] if i < len(planet_unlocked) else False,
            mining_speed_level=mining_speed[i] if i < len(mining_speed) else 0,
            speed_level=speed_level[i] if i < len(speed_level) else 0,
            cargo_level=cargo_level[i] if i < len(cargo_level) else 0,
            trip_start_date=_safe_datetime(trip_start[i]) if i < len(trip_start) else None,
            trip_end_date=_safe_datetime(trip_end[i]) if i < len(trip_end) else None,
        )
        for i in range(n_planets)
    )

    # ── Resources ──
    res_discovered = _get_array_values(result, "resourceDiscovered")
    res_count = _get_array_values(result, "resourceCount")
    res_gathered_total = _get_array_values(result, "resourceGatheredTotal")
    res_gathered_galaxy = _get_array_values(result, "resourceGatheredThisGalaxy")
    res_sold_total = _get_array_values(result, "resourceSoldTotal")
    res_sold_galaxy = _get_array_values(result, "resourceSoldThisGalaxy")

    n_resources = len(res_discovered)
    resources = tuple(
        ResourceSlot(
            index=i,
            discovered=res_discovered[i] if i < len(res_discovered) else False,
            count=res_count[i] if i < len(res_count) else 0.0,
            gathered_total=res_gathered_total[i] if i < len(res_gathered_total) else 0.0,
            gathered_this_galaxy=res_gathered_galaxy[i] if i < len(res_gathered_galaxy) else 0.0,
            sold_total=res_sold_total[i] if i < len(res_sold_total) else 0.0,
            sold_this_galaxy=res_sold_galaxy[i] if i < len(res_sold_galaxy) else 0.0,
        )
        for i in range(n_resources)
    )

    return PlayerData(
        smelters=smelters,
        crafters=crafters,
        planets=planets,
        resources=resources,
        raw=result,
    )

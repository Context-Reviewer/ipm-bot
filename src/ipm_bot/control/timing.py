"""Shared production timing summary derived from SaveSnapshot."""

from __future__ import annotations

from dataclasses import dataclass

from ipm_bot.control.save_source import SaveSnapshot


@dataclass(frozen=True, slots=True)
class ProductionTimingSummary:
    has_active_production: bool
    active_smelters: int
    active_crafters: int
    nearest_completion_seconds: float | None
    completion_imminent: bool


def summarize_production_timing(
    save_snapshot: SaveSnapshot | None,
) -> ProductionTimingSummary:
    """Derive production timing facts from a SaveSnapshot.

    Returns a summary with zero counts and no active production when
    *save_snapshot* is ``None``.
    """

    if save_snapshot is None:
        return ProductionTimingSummary(
            has_active_production=False,
            active_smelters=0,
            active_crafters=0,
            nearest_completion_seconds=None,
            completion_imminent=False,
        )

    active_smelter_slots = tuple(
        slot for slot in save_snapshot.smelters if slot.on
    )
    active_crafter_slots = tuple(
        slot for slot in save_snapshot.crafters if slot.on
    )
    active_slots = (*active_smelter_slots, *active_crafter_slots)

    nearest_completion_seconds: float | None = None
    if active_slots:
        nearest_completion_seconds = min(
            slot.timespan_left.total_seconds() for slot in active_slots
        )

    return ProductionTimingSummary(
        has_active_production=len(active_slots) > 0,
        active_smelters=len(active_smelter_slots),
        active_crafters=len(active_crafter_slots),
        nearest_completion_seconds=nearest_completion_seconds,
        completion_imminent=(
            nearest_completion_seconds is not None
            and nearest_completion_seconds <= 5.0
        ),
    )

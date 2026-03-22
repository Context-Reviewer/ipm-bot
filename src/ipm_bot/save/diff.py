"""Snapshot comparison helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import PlayerSnapshot, ScalarValue
from .schema import SNAPSHOT_FIELD_ORDER


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    before: ScalarValue
    after: ScalarValue


def diff_snapshots(before: PlayerSnapshot, after: PlayerSnapshot) -> list[FieldChange]:
    """Return the normalized field changes between two snapshots."""

    before_fields = before.flat_fields()
    after_fields = after.flat_fields()
    changes: list[FieldChange] = []

    for field_name in SNAPSHOT_FIELD_ORDER:
        before_value = before_fields.get(field_name)
        after_value = after_fields.get(field_name)
        if before_value != after_value:
            changes.append(
                FieldChange(
                    field=field_name,
                    before=before_value,
                    after=after_value,
                )
            )

    return changes


def render_snapshot_diff(changes: list[FieldChange]) -> str:
    """Render a human-readable diff."""

    if not changes:
        return "(no normalized field changes)"

    return "\n".join(
        f"{change.field}: {_format_value(change.before)} -> {_format_value(change.after)}"
        for change in changes
    )


def _format_value(value: ScalarValue) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)

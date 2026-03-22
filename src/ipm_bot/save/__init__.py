"""Read-only save parsing and state normalization."""

from .diff import FieldChange, diff_snapshots, render_snapshot_diff
from .exceptions import (
    FieldDecodeError,
    SaveParseError,
    UnsupportedSaveFormatError,
    UnsupportedTopLevelRecordError,
)
from .models import (
    AdState,
    CurrencyState,
    EventState,
    PlayerProgressState,
    PlayerSnapshot,
    SaveMetadata,
)
from .parser import extract_top_level_values, parse_player_snapshot

__all__ = [
    "AdState",
    "CurrencyState",
    "EventState",
    "FieldChange",
    "FieldDecodeError",
    "PlayerProgressState",
    "PlayerSnapshot",
    "SaveMetadata",
    "SaveParseError",
    "UnsupportedSaveFormatError",
    "UnsupportedTopLevelRecordError",
    "diff_snapshots",
    "extract_top_level_values",
    "parse_player_snapshot",
    "render_snapshot_diff",
]

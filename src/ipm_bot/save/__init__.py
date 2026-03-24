"""Read-only save parsing and state normalization."""

from .byte_diff import ByteSpanChange, diff_binary_files, diff_binary_payloads, render_binary_diff
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
    "ByteSpanChange",
    "FieldChange",
    "FieldDecodeError",
    "PlayerProgressState",
    "PlayerSnapshot",
    "SaveMetadata",
    "SaveParseError",
    "UnsupportedSaveFormatError",
    "UnsupportedTopLevelRecordError",
    "diff_snapshots",
    "diff_binary_files",
    "diff_binary_payloads",
    "extract_top_level_values",
    "parse_player_snapshot",
    "render_binary_diff",
    "render_snapshot_diff",
]

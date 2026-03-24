"""Binary save diff helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ByteSpanChange:
    start_offset: int
    before_end_offset: int
    after_end_offset: int
    before_bytes: bytes
    after_bytes: bytes

    @property
    def before_length(self) -> int:
        return len(self.before_bytes)

    @property
    def after_length(self) -> int:
        return len(self.after_bytes)


def diff_binary_files(before_path: Path, after_path: Path) -> list[ByteSpanChange]:
    """Return contiguous byte-span changes between two files."""

    return diff_binary_payloads(before_path.read_bytes(), after_path.read_bytes())


def diff_binary_payloads(before: bytes, after: bytes) -> list[ByteSpanChange]:
    """Return contiguous byte-span changes between two payloads."""

    prefix_length = 0
    max_prefix = min(len(before), len(after))
    while prefix_length < max_prefix and before[prefix_length] == after[prefix_length]:
        prefix_length += 1

    if len(before) == len(after) and prefix_length == len(before):
        return []

    suffix_length = 0
    max_suffix = min(len(before), len(after)) - prefix_length
    while (
        suffix_length < max_suffix
        and before[len(before) - 1 - suffix_length] == after[len(after) - 1 - suffix_length]
    ):
        suffix_length += 1

    before_mid = before[prefix_length : len(before) - suffix_length if suffix_length else len(before)]
    after_mid = after[prefix_length : len(after) - suffix_length if suffix_length else len(after)]

    return _split_midsection(prefix_length, before_mid, after_mid)


def _split_midsection(start_offset: int, before_mid: bytes, after_mid: bytes) -> list[ByteSpanChange]:
    changes: list[ByteSpanChange] = []
    max_length = max(len(before_mid), len(after_mid))
    index = 0

    while index < max_length:
        before_byte = before_mid[index] if index < len(before_mid) else None
        after_byte = after_mid[index] if index < len(after_mid) else None
        if before_byte == after_byte:
            index += 1
            continue

        span_start = index
        while index < max_length:
            before_byte = before_mid[index] if index < len(before_mid) else None
            after_byte = after_mid[index] if index < len(after_mid) else None
            if before_byte == after_byte:
                break
            index += 1

        before_slice = before_mid[span_start:min(index, len(before_mid))]
        after_slice = after_mid[span_start:min(index, len(after_mid))]
        changes.append(
            ByteSpanChange(
                start_offset=start_offset + span_start,
                before_end_offset=start_offset + span_start + len(before_slice),
                after_end_offset=start_offset + span_start + len(after_slice),
                before_bytes=before_slice,
                after_bytes=after_slice,
            )
        )

    return changes


def render_binary_diff(changes: list[ByteSpanChange], preview_bytes: int = 16) -> str:
    """Render a human-readable binary diff summary."""

    if not changes:
        return "(no byte-level changes)"

    lines: list[str] = []
    for change in changes:
        before_preview = change.before_bytes[:preview_bytes].hex(" ")
        after_preview = change.after_bytes[:preview_bytes].hex(" ")
        lines.append(
            f"offset=0x{change.start_offset:08X} "
            f"before_len={change.before_length} after_len={change.after_length} "
            f"before=[{before_preview}] after=[{after_preview}]"
        )
    return "\n".join(lines)

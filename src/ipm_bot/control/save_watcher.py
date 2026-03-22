"""Polling utilities for detecting new parseable save snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import time

from ipm_bot.save import SaveParseError, parse_player_snapshot
from ipm_bot.save.models import PlayerSnapshot


@dataclass(frozen=True, slots=True)
class SaveFingerprint:
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SaveObservation:
    fingerprint: SaveFingerprint
    snapshot: PlayerSnapshot


def get_save_fingerprint(path: Path) -> SaveFingerprint:
    """Return a stable identity for the current save file contents."""

    data = _read_save_bytes(path)
    return _fingerprint_bytes(data)


def wait_for_save_change(
    path: Path,
    baseline_hash: str,
    timeout_s: float,
    poll_interval_s: float,
) -> SaveObservation | None:
    """Poll until the save contents change and the new contents parse successfully."""

    if timeout_s <= 0:
        raise ValueError("timeout_s must be greater than zero.")
    if poll_interval_s <= 0:
        raise ValueError("poll_interval_s must be greater than zero.")
    if not baseline_hash:
        raise ValueError("baseline_hash must not be empty.")

    deadline = time.monotonic() + timeout_s
    last_parse_error: SaveParseError | None = None

    while time.monotonic() < deadline:
        data = _read_save_bytes(path)
        fingerprint = _fingerprint_bytes(data)
        if fingerprint.sha256 != baseline_hash:
            try:
                snapshot = _parse_snapshot(path, data)
                return SaveObservation(
                    fingerprint=fingerprint,
                    snapshot=snapshot,
                )
            except SaveParseError as exc:
                last_parse_error = exc

        remaining_s = deadline - time.monotonic()
        if remaining_s > 0:
            time.sleep(min(poll_interval_s, remaining_s))

    if last_parse_error is not None:
        raise TimeoutError(
            f"Timed out waiting for a readable updated save at {path}. "
            f"Last parse error: {last_parse_error}"
        )

    return None


def _read_save_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Save file does not exist: {path}")
    return path.read_bytes()


def _fingerprint_bytes(data: bytes) -> SaveFingerprint:
    return SaveFingerprint(
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _parse_snapshot(path: Path, data: bytes) -> PlayerSnapshot:
    if path.suffix.lower() == ".json":
        return parse_player_snapshot(path)
    return parse_player_snapshot(data)

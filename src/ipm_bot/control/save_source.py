"""Save-source boundary for preparing a local save path before one control tick."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


DEFAULT_PULLED_SAVE_PATH = Path(__file__).resolve().parents[3] / "data" / "pulled" / "playerInfo.dat"


@dataclass(frozen=True, slots=True)
class SaveSourceMetadata:
    save_source_type: str
    original_requested_path: str
    prepared_local_path: str
    preparation_performed: bool

    def __post_init__(self) -> None:
        if not self.save_source_type:
            raise ValueError("save_source_type must not be empty.")
        if not self.original_requested_path:
            raise ValueError("original_requested_path must not be empty.")
        if not self.prepared_local_path:
            raise ValueError("prepared_local_path must not be empty.")


class SaveSourcePreparationError(Exception):
    """Raised when a save source cannot prepare a local save path."""


class SaveCommandRunner(Protocol):
    """Thin command boundary for save preparation commands."""

    def run(self, command: Sequence[str]) -> None:
        """Execute one command or raise on failure."""


class SaveSource(Protocol):
    """Boundary for preparing a local save path used by one control tick."""

    save_source_type: str

    def prepare(self, requested_path: Path) -> SaveSourceMetadata:
        """Prepare a local save path and return provenance metadata."""


class LocalSaveSource:
    """Save source that uses the requested local path directly."""

    save_source_type = "local"

    def prepare(self, requested_path: Path) -> SaveSourceMetadata:
        return SaveSourceMetadata(
            save_source_type=self.save_source_type,
            original_requested_path=str(requested_path),
            prepared_local_path=str(requested_path.resolve()),
            preparation_performed=False,
        )


@dataclass(frozen=True, slots=True)
class AdbPulledSaveSourceConfig:
    adb_path: str = "adb"
    device_serial: str | None = None
    prepared_local_path: Path = DEFAULT_PULLED_SAVE_PATH

    def __post_init__(self) -> None:
        if not self.adb_path.strip():
            raise ValueError("adb_path must not be empty.")


class AdbPulledSaveSource:
    """Save source that pulls the remote save to a configured local path via ADB."""

    save_source_type = "adb_pull"

    def __init__(
        self,
        config: AdbPulledSaveSourceConfig,
        command_runner: SaveCommandRunner,
    ) -> None:
        self._config = config
        self._command_runner = command_runner

    def prepare(self, requested_path: Path) -> SaveSourceMetadata:
        prepared_local_path = self._config.prepared_local_path.resolve()
        prepared_local_path.parent.mkdir(parents=True, exist_ok=True)
        remote_path = requested_path.as_posix()
        command = self._adb_pull_command(remote_path, prepared_local_path)
        try:
            self._command_runner.run(command)
        except Exception as exc:
            raise SaveSourcePreparationError(
                f"Failed to prepare local save via ADB pull: {' '.join(command)}"
            ) from exc

        return SaveSourceMetadata(
            save_source_type=self.save_source_type,
            original_requested_path=remote_path,
            prepared_local_path=str(prepared_local_path),
            preparation_performed=True,
        )

    def _adb_pull_command(self, requested_path: str, prepared_local_path: Path) -> list[str]:
        command = [self._config.adb_path]
        if self._config.device_serial is not None:
            command.extend(["-s", self._config.device_serial])
        command.extend(["pull", requested_path, str(prepared_local_path)])
        return command

"""Save-source boundary for preparing a local save path and loading a read-only snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from pathlib import PureWindowsPath
import shutil
import subprocess
import tempfile
import time
from typing import Protocol, Sequence

from ipm_bot.save.player_data import (
    CrafterSlot,
    PlanetSlot,
    PlayerData,
    ResourceSlot,
    SmelterSlot,
    load_player_data,
)


DEFAULT_PULLED_SAVE_PATH = Path(__file__).resolve().parents[3] / "data" / "pulled" / "playerInfo.dat"
DEFAULT_BLUESTACKS_VHDX_PATH = Path(r"C:\ProgramData\BlueStacks_nxt\Engine\Pie64\Data.vhdx")
SUPPORTED_VHDX_SAVE_NAMES = ("playerInfo.dat", "playerInfoBackup.dat")
VHDX_SAVE_MEMBER_PATHS = {
    "playerInfo.dat": (
        r"media\0\Android\data\com.TironiumTech.IdlePlanetMiner\files\playerInfo.dat"
    ),
    "playerInfoBackup.dat": (
        r"media\0\Android\data\com.TironiumTech.IdlePlanetMiner\files\playerInfoBackup.dat"
    ),
}


@dataclass(frozen=True, slots=True)
class SaveSourceConfigSnapshot:
    save_source_type: str
    preparation_performed: bool
    prepared_local_path: str
    original_requested_path: str
    local_source_path: str | None = None
    adb_path: str | None = None
    adb_serial: str | None = None
    remote_save_path: str | None = None
    vhdx_path: str | None = None
    vhdx_member_name: str | None = None
    seven_zip_path: str | None = None

    def __post_init__(self) -> None:
        if not self.save_source_type:
            raise ValueError("Save source config snapshot type must not be empty.")
        if not self.prepared_local_path:
            raise ValueError("Save source config snapshot prepared_local_path must not be empty.")
        if not self.original_requested_path:
            raise ValueError(
                "Save source config snapshot original_requested_path must not be empty."
            )


@dataclass(frozen=True, slots=True)
class SaveSourceMetadata:
    save_source_type: str
    original_requested_path: str
    prepared_local_path: str
    preparation_performed: bool
    config_snapshot: SaveSourceConfigSnapshot | None = None

    def __post_init__(self) -> None:
        if not self.save_source_type:
            raise ValueError("save_source_type must not be empty.")
        if not self.original_requested_path:
            raise ValueError("original_requested_path must not be empty.")
        if not self.prepared_local_path:
            raise ValueError("prepared_local_path must not be empty.")
        if self.config_snapshot is not None:
            if self.config_snapshot.save_source_type != self.save_source_type:
                raise ValueError(
                    "config_snapshot.save_source_type must match save_source_type."
                )
            if self.config_snapshot.prepared_local_path != self.prepared_local_path:
                raise ValueError(
                    "config_snapshot.prepared_local_path must match prepared_local_path."
                )
            if self.config_snapshot.original_requested_path != self.original_requested_path:
                raise ValueError(
                    "config_snapshot.original_requested_path must match original_requested_path."
                )
            if self.config_snapshot.preparation_performed != self.preparation_performed:
                raise ValueError(
                    "config_snapshot.preparation_performed must match preparation_performed."
                )


class SaveSourcePreparationError(Exception):
    """Raised when a save source cannot prepare a local save path."""


@dataclass(frozen=True, slots=True)
class SaveResourceSnapshot:
    index: int
    discovered: bool
    count: float
    gathered_total: float
    gathered_this_galaxy: float
    sold_total: float
    sold_this_galaxy: float


@dataclass(frozen=True, slots=True)
class SavePlanetSnapshot:
    index: int
    unlocked: bool
    mining_speed_level: int
    speed_level: int
    cargo_level: int
    trip_start_date: datetime | None
    trip_end_date: datetime | None


@dataclass(frozen=True, slots=True)
class SaveProductionSlotSnapshot:
    index: int
    on: bool
    recipe_number: int
    start_date: datetime | None
    end_date: datetime | None
    original_end_date: datetime | None
    timespan_left: timedelta
    seconds_completed: float
    duration_estimate: float


@dataclass(frozen=True, slots=True)
class SaveSnapshot:
    source_path: str | None
    resources: tuple[SaveResourceSnapshot, ...]
    planets: tuple[SavePlanetSnapshot, ...]
    smelters: tuple[SaveProductionSlotSnapshot, ...]
    crafters: tuple[SaveProductionSlotSnapshot, ...]


class SaveCommandRunner(Protocol):
    """Thin command boundary for save preparation commands."""

    def run(self, command: Sequence[str]) -> None:
        """Execute one command or raise on failure."""


@dataclass(frozen=True, slots=True)
class SaveRefreshTelemetry:
    refresh_interval_seconds: float | None
    refresh_attempt_count: int
    refresh_failure_count: int
    warning_messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.refresh_interval_seconds is not None and self.refresh_interval_seconds <= 0:
            raise ValueError("refresh_interval_seconds must be greater than zero when provided.")
        if self.refresh_attempt_count < 0:
            raise ValueError("refresh_attempt_count must be non-negative.")
        if self.refresh_failure_count < 0:
            raise ValueError("refresh_failure_count must be non-negative.")


class SaveRefreshController(Protocol):
    """Boundary for refreshing a prepared local save during one verification loop."""

    def maybe_refresh(self) -> None:
        """Perform one refresh attempt when the configured interval has elapsed."""

    def telemetry(self) -> SaveRefreshTelemetry:
        """Return the current refresh telemetry snapshot."""


class PeriodicSaveRefreshController:
    """Time-gated save refresher that records intermittent failure telemetry."""

    def __init__(
        self,
        *,
        refresh_fn,
        refresh_interval_seconds: float,
        label: str,
        monotonic_fn=time.monotonic,
    ) -> None:
        if refresh_interval_seconds <= 0:
            raise ValueError("refresh_interval_seconds must be greater than zero.")
        self._refresh_fn = refresh_fn
        self._refresh_interval_seconds = refresh_interval_seconds
        self._label = label
        self._monotonic_fn = monotonic_fn
        self._last_refresh_started_at: float | None = None
        self._refresh_attempt_count = 0
        self._refresh_failure_count = 0
        self._warning_messages: list[str] = []

    def maybe_refresh(self) -> None:
        now = self._monotonic_fn()
        if self._last_refresh_started_at is not None:
            elapsed = now - self._last_refresh_started_at
            if elapsed < self._refresh_interval_seconds:
                return

        self._last_refresh_started_at = now
        self._refresh_attempt_count += 1
        try:
            self._refresh_fn()
        except Exception as exc:
            self._refresh_failure_count += 1
            self._warning_messages.append(
                f"Save refresh attempt {self._refresh_attempt_count} failed for {self._label}: {exc}"
            )

    def telemetry(self) -> SaveRefreshTelemetry:
        return SaveRefreshTelemetry(
            refresh_interval_seconds=self._refresh_interval_seconds,
            refresh_attempt_count=self._refresh_attempt_count,
            refresh_failure_count=self._refresh_failure_count,
            warning_messages=tuple(self._warning_messages),
        )


@dataclass(frozen=True, slots=True)
class SevenZipCommandResult:
    returncode: int
    stdout: str
    stderr: str


class SevenZipCommandRunner(Protocol):
    """Thin command boundary for 7z extraction commands."""

    def run(self, command: Sequence[str]) -> SevenZipCommandResult:
        """Execute one 7z command and return the completed result."""


class VhdxExtractor(Protocol):
    """Boundary for extracting one file from an offline BlueStacks VHDX image."""

    def extract_file(self, image_path: Path, member_path: str, output_path: Path) -> None:
        """Extract one member path from the VHDX image into output_path."""


class SaveSource(Protocol):
    """Boundary for preparing a local save path used by one control tick."""

    save_source_type: str

    def prepare(self, requested_path: Path) -> SaveSourceMetadata:
        """Prepare a local save path and return provenance metadata."""


class LocalSaveSource:
    """Save source that uses the requested local path directly."""

    save_source_type = "local"

    def prepare(self, requested_path: Path) -> SaveSourceMetadata:
        resolved_path = str(requested_path.resolve())
        return SaveSourceMetadata(
            save_source_type=self.save_source_type,
            original_requested_path=str(requested_path),
            prepared_local_path=resolved_path,
            preparation_performed=False,
            config_snapshot=SaveSourceConfigSnapshot(
                save_source_type=self.save_source_type,
                preparation_performed=False,
                prepared_local_path=resolved_path,
                original_requested_path=str(requested_path),
                local_source_path=resolved_path,
            ),
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
            config_snapshot=SaveSourceConfigSnapshot(
                save_source_type=self.save_source_type,
                preparation_performed=True,
                prepared_local_path=str(prepared_local_path),
                original_requested_path=remote_path,
                adb_path=self._config.adb_path,
                adb_serial=self._config.device_serial,
                remote_save_path=remote_path,
            ),
        )

    def build_refresh_controller(
        self,
        requested_path: Path,
        *,
        refresh_interval_seconds: float,
        monotonic_fn=time.monotonic,
    ) -> SaveRefreshController:
        prepared_local_path = self._config.prepared_local_path.resolve()
        remote_path = requested_path.as_posix()

        def _refresh() -> None:
            prepared_local_path.parent.mkdir(parents=True, exist_ok=True)
            self._command_runner.run(self._adb_pull_command(remote_path, prepared_local_path))

        return PeriodicSaveRefreshController(
            refresh_fn=_refresh,
            refresh_interval_seconds=refresh_interval_seconds,
            label=remote_path,
            monotonic_fn=monotonic_fn,
        )

    def _adb_pull_command(self, requested_path: str, prepared_local_path: Path) -> list[str]:
        command = [self._config.adb_path]
        if self._config.device_serial is not None:
            command.extend(["-s", self._config.device_serial])
        command.extend(["pull", requested_path, str(prepared_local_path)])
        return command


@dataclass(frozen=True, slots=True)
class VhdxSaveSourceConfig:
    vhdx_path: Path = DEFAULT_BLUESTACKS_VHDX_PATH
    save_name: str = "playerInfo.dat"
    prepared_local_path: Path = DEFAULT_PULLED_SAVE_PATH

    def __post_init__(self) -> None:
        if self.save_name not in SUPPORTED_VHDX_SAVE_NAMES:
            raise ValueError(
                f"Unsupported VHDX save name: {self.save_name!r}. "
                f"Expected one of {SUPPORTED_VHDX_SAVE_NAMES!r}."
            )


class SevenZipVhdxExtractor:
    """Read-only VHDX extractor backed by the 7z command-line tool."""

    def __init__(
        self,
        seven_zip_path: str = "7z",
        command_runner: SevenZipCommandRunner | None = None,
    ) -> None:
        if not seven_zip_path.strip():
            raise ValueError("seven_zip_path must not be empty.")
        self._seven_zip_path = seven_zip_path
        self._command_runner = (
            SubprocessSevenZipCommandRunner() if command_runner is None else command_runner
        )

    @property
    def seven_zip_path(self) -> str:
        return self._seven_zip_path

    def extract_file(self, image_path: Path, member_path: str, output_path: Path) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_root = Path(tmpdir)
            command = [
                self._seven_zip_path,
                "x",
                str(image_path),
                member_path,
                f"-o{extract_root}",
                "-y",
            ]
            try:
                result = self._command_runner.run(command)
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"7z executable was not found: {self._seven_zip_path!r}."
                ) from exc
            except Exception as exc:
                raise RuntimeError(
                    f"7z failed to extract {member_path!r} from {image_path}: {exc}"
                ) from exc

            extracted_path = extract_root.joinpath(*PureWindowsPath(member_path).parts)
            if extracted_path.is_file():
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(extracted_path, output_path)
                return

            details = self._format_7z_details(result)
            raise FileNotFoundError(
                "7z did not materialize the selected save from the VHDX image: "
                f"{member_path}. {details}"
            )

    @staticmethod
    def _format_7z_details(result: SevenZipCommandResult) -> str:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        return f"returncode={result.returncode}; details={detail}"


class SubprocessSevenZipCommandRunner:
    """Default subprocess-backed command runner for 7z extraction commands."""

    def run(self, command: Sequence[str]) -> SevenZipCommandResult:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )
        return SevenZipCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class VhdxSaveSource:
    """Save source that extracts one trusted IPM save from an offline BlueStacks VHDX."""

    save_source_type = "vhdx"

    def __init__(
        self,
        config: VhdxSaveSourceConfig,
        extractor: VhdxExtractor,
    ) -> None:
        self._config = config
        self._extractor = extractor

    def prepare(self, requested_path: Path) -> SaveSourceMetadata:
        del requested_path

        vhdx_path = self._config.vhdx_path.resolve()
        if not vhdx_path.is_file():
            raise SaveSourcePreparationError(f"VHDX image does not exist: {vhdx_path}")

        member_path = VHDX_SAVE_MEMBER_PATHS[self._config.save_name]
        prepared_local_path = self._config.prepared_local_path.resolve()
        try:
            self._extractor.extract_file(vhdx_path, member_path, prepared_local_path)
        except Exception as exc:
            raise SaveSourcePreparationError(
                f"Failed to extract {self._config.save_name!r} from VHDX {vhdx_path}: {exc}"
            ) from exc

        return SaveSourceMetadata(
            save_source_type=self.save_source_type,
            original_requested_path=f"{vhdx_path}::{member_path}",
            prepared_local_path=str(prepared_local_path),
            preparation_performed=True,
            config_snapshot=SaveSourceConfigSnapshot(
                save_source_type=self.save_source_type,
                preparation_performed=True,
                prepared_local_path=str(prepared_local_path),
                original_requested_path=f"{vhdx_path}::{member_path}",
                vhdx_path=str(vhdx_path),
                vhdx_member_name=self._config.save_name,
                seven_zip_path=getattr(self._extractor, "seven_zip_path", None),
            ),
        )


def load_save_snapshot(source: str | Path | bytes) -> SaveSnapshot:
    """Load one save source through PlayerData into the bot-facing snapshot shape."""

    player_data = load_player_data(source)
    source_path = str(Path(source).resolve()) if isinstance(source, (str, Path)) else None
    return player_data_to_save_snapshot(player_data, source_path=source_path)


def player_data_to_save_snapshot(
    player_data: PlayerData,
    *,
    source_path: str | None = None,
) -> SaveSnapshot:
    """Project validated PlayerData into a small immutable bot-facing snapshot."""

    return SaveSnapshot(
        source_path=source_path,
        resources=tuple(_resource_snapshot(slot) for slot in player_data.resources),
        planets=tuple(_planet_snapshot(slot) for slot in player_data.planets),
        smelters=tuple(_production_snapshot(slot) for slot in player_data.smelters),
        crafters=tuple(_production_snapshot(slot) for slot in player_data.crafters),
    )


def prepare_and_load_save_snapshot(
    save_source: SaveSource,
    requested_path: Path,
) -> tuple[SaveSourceMetadata, SaveSnapshot]:
    """Prepare one local save path and immediately load the read-only snapshot from it."""

    metadata = save_source.prepare(requested_path)
    snapshot = load_save_snapshot(metadata.prepared_local_path)
    return metadata, snapshot


def _resource_snapshot(slot: ResourceSlot) -> SaveResourceSnapshot:
    return SaveResourceSnapshot(
        index=slot.index,
        discovered=slot.discovered,
        count=slot.count,
        gathered_total=slot.gathered_total,
        gathered_this_galaxy=slot.gathered_this_galaxy,
        sold_total=slot.sold_total,
        sold_this_galaxy=slot.sold_this_galaxy,
    )


def _planet_snapshot(slot: PlanetSlot) -> SavePlanetSnapshot:
    return SavePlanetSnapshot(
        index=slot.index,
        unlocked=slot.unlocked,
        mining_speed_level=slot.mining_speed_level,
        speed_level=slot.speed_level,
        cargo_level=slot.cargo_level,
        trip_start_date=slot.trip_start_date,
        trip_end_date=slot.trip_end_date,
    )


def _production_snapshot(slot: SmelterSlot | CrafterSlot) -> SaveProductionSlotSnapshot:
    return SaveProductionSlotSnapshot(
        index=slot.index,
        on=slot.on,
        recipe_number=slot.recipe_number,
        start_date=slot.start_date,
        end_date=slot.end_date,
        original_end_date=slot.original_end_date,
        timespan_left=slot.timespan_left,
        seconds_completed=slot.seconds_completed,
        duration_estimate=slot.seconds_completed + slot.timespan_left.total_seconds(),
    )

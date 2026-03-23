"""Save-source boundary for preparing a local save path before one control tick."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from pathlib import PureWindowsPath
import shutil
import subprocess
import tempfile
from typing import Protocol, Sequence


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

    def __init__(self, seven_zip_path: str = "7z") -> None:
        if not seven_zip_path.strip():
            raise ValueError("seven_zip_path must not be empty.")
        self._seven_zip_path = seven_zip_path

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
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"7z executable was not found: {self._seven_zip_path!r}."
                ) from exc
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.strip()
                stdout = exc.stdout.strip()
                details = stderr or stdout or f"exit code {exc.returncode}"
                raise RuntimeError(
                    f"7z failed to extract {member_path!r} from {image_path}: {details}"
                ) from exc

            extracted_path = extract_root.joinpath(*PureWindowsPath(member_path).parts)
            if not extracted_path.is_file():
                raise FileNotFoundError(
                    f"Extracted member was not found after 7z completed: {member_path}"
                )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(extracted_path, output_path)


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
        )

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.control.composition import add_tick_composition_arguments, build_save_source
from ipm_bot.control.save_source import (
    AdbPulledSaveSource,
    AdbPulledSaveSourceConfig,
    LocalSaveSource,
    PeriodicSaveRefreshController,
    SaveSnapshot,
    SaveSourcePreparationError,
    SevenZipCommandResult,
    SevenZipVhdxExtractor,
    VHDX_SAVE_MEMBER_PATHS,
    VhdxSaveSource,
    VhdxSaveSourceConfig,
    load_save_snapshot,
    prepare_and_load_save_snapshot,
)
from ipm_bot.save.player_data import CrafterSlot, PlanetSlot, PlayerData, ResourceSlot, SmelterSlot


class SaveSourceTests(unittest.TestCase):
    def test_local_save_source_returns_requested_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "playerInfo.dat"
            save_path.write_text("save", encoding="utf-8")

            metadata = LocalSaveSource().prepare(save_path)

            self.assertEqual(metadata.save_source_type, "local")
            self.assertEqual(metadata.original_requested_path, str(save_path))
            self.assertEqual(metadata.prepared_local_path, str(save_path.resolve()))
            self.assertFalse(metadata.preparation_performed)

    def test_adb_pulled_save_source_emits_expected_pull_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prepared_local_path = Path(tmpdir) / "pulled" / "playerInfo.dat"
            runner = RecordingCommandRunner()
            save_source = AdbPulledSaveSource(
                config=AdbPulledSaveSourceConfig(
                    adb_path="adb",
                    device_serial="emulator-5554",
                    prepared_local_path=prepared_local_path,
                ),
                command_runner=runner,
            )

            metadata = save_source.prepare(Path("/sdcard/Android/data/game/files/playerInfo.dat"))

            self.assertEqual(
                runner.commands,
                [[
                    "adb",
                    "-s",
                    "emulator-5554",
                    "pull",
                    "/sdcard/Android/data/game/files/playerInfo.dat",
                    str(prepared_local_path.resolve()),
                ]],
            )
            self.assertEqual(metadata.save_source_type, "adb_pull")
            self.assertTrue(metadata.preparation_performed)
            self.assertEqual(
                metadata.original_requested_path,
                "/sdcard/Android/data/game/files/playerInfo.dat",
            )
            self.assertEqual(metadata.prepared_local_path, str(prepared_local_path.resolve()))

    def test_adb_pulled_save_source_builds_periodic_refresh_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prepared_local_path = Path(tmpdir) / "pulled" / "playerInfo.dat"
            runner = RecordingCommandRunner()
            save_source = AdbPulledSaveSource(
                config=AdbPulledSaveSourceConfig(
                    adb_path="adb",
                    device_serial="emulator-5554",
                    prepared_local_path=prepared_local_path,
                ),
                command_runner=runner,
            )
            clock = RecordingClock()

            controller = save_source.build_refresh_controller(
                Path("/sdcard/Android/data/game/files/playerInfo.dat"),
                refresh_interval_seconds=1.0,
                monotonic_fn=clock.monotonic,
            )

            self.assertIsInstance(controller, PeriodicSaveRefreshController)
            controller.maybe_refresh()
            controller.maybe_refresh()
            clock.advance(1.0)
            controller.maybe_refresh()

            self.assertEqual(
                runner.commands,
                [
                    [
                        "adb",
                        "-s",
                        "emulator-5554",
                        "pull",
                        "/sdcard/Android/data/game/files/playerInfo.dat",
                        str(prepared_local_path.resolve()),
                    ],
                    [
                        "adb",
                        "-s",
                        "emulator-5554",
                        "pull",
                        "/sdcard/Android/data/game/files/playerInfo.dat",
                        str(prepared_local_path.resolve()),
                    ],
                ],
            )
            telemetry = controller.telemetry()
            self.assertEqual(telemetry.refresh_interval_seconds, 1.0)
            self.assertEqual(telemetry.refresh_attempt_count, 2)
            self.assertEqual(telemetry.refresh_failure_count, 0)

    def test_load_save_snapshot_projects_validated_player_data(self) -> None:
        player_data = _sample_player_data()

        with patch("ipm_bot.control.save_source.load_player_data", return_value=player_data) as loader:
            snapshot = load_save_snapshot(Path("C:/tmp/playerInfo.dat"))

        loader.assert_called_once()
        self.assertIsInstance(snapshot, SaveSnapshot)
        self.assertEqual(snapshot.source_path, str(Path("C:/tmp/playerInfo.dat").resolve()))
        self.assertEqual(len(snapshot.resources), 1)
        self.assertEqual(snapshot.resources[0].count, 42.5)
        self.assertEqual(len(snapshot.planets), 1)
        self.assertTrue(snapshot.planets[0].unlocked)
        self.assertEqual(len(snapshot.smelters), 1)
        self.assertEqual(snapshot.smelters[0].recipe_number, 4)
        self.assertEqual(snapshot.smelters[0].duration_estimate, 53.333)
        self.assertEqual(snapshot.smelters[0].timespan_left, timedelta(seconds=34.821))
        self.assertEqual(len(snapshot.crafters), 1)
        self.assertEqual(snapshot.crafters[0].duration_estimate, 480.0)
        self.assertEqual(snapshot.crafters[0].start_date, datetime(2026, 3, 24, 18, 2, 31))

    def test_prepare_and_load_save_snapshot_uses_prepared_local_path(self) -> None:
        player_data = _sample_player_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "playerInfo.dat"
            save_path.write_bytes(b"save")

            with patch("ipm_bot.control.save_source.load_player_data", return_value=player_data) as loader:
                metadata, snapshot = prepare_and_load_save_snapshot(LocalSaveSource(), save_path)

        self.assertEqual(metadata.save_source_type, "local")
        self.assertEqual(metadata.prepared_local_path, str(save_path.resolve()))
        loader.assert_called_once_with(metadata.prepared_local_path)
        self.assertEqual(snapshot.source_path, str(save_path.resolve()))
        self.assertEqual(snapshot.crafters[0].duration_estimate, 480.0)

    def test_vhdx_save_source_extracts_primary_save_to_prepared_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vhdx_path = root / "Data.vhdx"
            vhdx_path.write_bytes(b"vhdx")
            prepared_local_path = root / "prepared" / "playerInfo.dat"
            extractor = RecordingVhdxExtractor(
                content_by_member={
                    VHDX_SAVE_MEMBER_PATHS["playerInfo.dat"]: b"primary-save",
                }
            )
            save_source = VhdxSaveSource(
                config=VhdxSaveSourceConfig(
                    vhdx_path=vhdx_path,
                    save_name="playerInfo.dat",
                    prepared_local_path=prepared_local_path,
                ),
                extractor=extractor,
            )

            metadata = save_source.prepare(Path("ignored-by-vhdx"))

            self.assertEqual(
                extractor.calls,
                [(
                    vhdx_path.resolve(),
                    VHDX_SAVE_MEMBER_PATHS["playerInfo.dat"],
                    prepared_local_path.resolve(),
                )],
            )
            self.assertEqual(prepared_local_path.read_bytes(), b"primary-save")
            self.assertEqual(metadata.save_source_type, "vhdx")
            self.assertEqual(
                metadata.original_requested_path,
                f"{vhdx_path.resolve()}::{VHDX_SAVE_MEMBER_PATHS['playerInfo.dat']}",
            )
            self.assertEqual(metadata.prepared_local_path, str(prepared_local_path.resolve()))
            self.assertTrue(metadata.preparation_performed)

    def test_vhdx_save_source_supports_explicit_backup_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vhdx_path = root / "Data.vhdx"
            vhdx_path.write_bytes(b"vhdx")
            prepared_local_path = root / "prepared" / "playerInfoBackup.dat"
            extractor = RecordingVhdxExtractor(
                content_by_member={
                    VHDX_SAVE_MEMBER_PATHS["playerInfoBackup.dat"]: b"backup-save",
                }
            )
            save_source = VhdxSaveSource(
                config=VhdxSaveSourceConfig(
                    vhdx_path=vhdx_path,
                    save_name="playerInfoBackup.dat",
                    prepared_local_path=prepared_local_path,
                ),
                extractor=extractor,
            )

            metadata = save_source.prepare(Path("ignored-by-vhdx"))

            self.assertEqual(
                extractor.calls[0][1],
                VHDX_SAVE_MEMBER_PATHS["playerInfoBackup.dat"],
            )
            self.assertEqual(prepared_local_path.read_bytes(), b"backup-save")
            self.assertEqual(
                metadata.original_requested_path,
                f"{vhdx_path.resolve()}::{VHDX_SAVE_MEMBER_PATHS['playerInfoBackup.dat']}",
            )

    def test_vhdx_save_source_fails_loud_when_selected_save_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vhdx_path = root / "Data.vhdx"
            vhdx_path.write_bytes(b"vhdx")
            prepared_local_path = root / "prepared" / "playerInfo.dat"
            extractor = RecordingVhdxExtractor(content_by_member={})
            save_source = VhdxSaveSource(
                config=VhdxSaveSourceConfig(
                    vhdx_path=vhdx_path,
                    save_name="playerInfo.dat",
                    prepared_local_path=prepared_local_path,
                ),
                extractor=extractor,
            )

            with self.assertRaises(SaveSourcePreparationError) as context:
                save_source.prepare(Path("ignored-by-vhdx"))

            self.assertIn("playerInfo.dat", str(context.exception))
            self.assertFalse(prepared_local_path.exists())

    def test_vhdx_save_source_fails_loud_when_extraction_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vhdx_path = root / "Data.vhdx"
            vhdx_path.write_bytes(b"vhdx")
            prepared_local_path = root / "prepared" / "playerInfo.dat"
            extractor = FailingVhdxExtractor(PermissionError("VHDX is locked"))
            save_source = VhdxSaveSource(
                config=VhdxSaveSourceConfig(
                    vhdx_path=vhdx_path,
                    save_name="playerInfo.dat",
                    prepared_local_path=prepared_local_path,
                ),
                extractor=extractor,
            )

            with self.assertRaises(SaveSourcePreparationError) as context:
                save_source.prepare(Path("ignored-by-vhdx"))

            self.assertIn("VHDX is locked", str(context.exception))
            self.assertFalse(prepared_local_path.exists())

    def test_vhdx_save_source_fails_loud_when_vhdx_image_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            missing_vhdx_path = root / "missing.vhdx"
            prepared_local_path = root / "prepared" / "playerInfo.dat"
            extractor = RecordingVhdxExtractor(
                content_by_member={
                    VHDX_SAVE_MEMBER_PATHS["playerInfo.dat"]: b"primary-save",
                }
            )
            save_source = VhdxSaveSource(
                config=VhdxSaveSourceConfig(
                    vhdx_path=missing_vhdx_path,
                    save_name="playerInfo.dat",
                    prepared_local_path=prepared_local_path,
                ),
                extractor=extractor,
            )

            with self.assertRaises(SaveSourcePreparationError) as context:
                save_source.prepare(Path("ignored-by-vhdx"))

            self.assertIn(str(missing_vhdx_path.resolve()), str(context.exception))
            self.assertEqual(extractor.calls, [])

    def test_seven_zip_vhdx_extractor_accepts_warning_result_when_member_is_materialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "Data.vhdx"
            image_path.write_bytes(b"vhdx")
            output_path = root / "prepared" / "playerInfo.dat"
            member_path = VHDX_SAVE_MEMBER_PATHS["playerInfo.dat"]
            runner = RecordingSevenZipCommandRunner(
                results=[
                    SevenZipCommandResult(
                        returncode=2,
                        stdout="Open Errors: 1",
                        stderr="0.img\r\nERRORS:\r\nHeaders Error\r\n",
                    )
                ],
                materialized_members={member_path: b"primary-save"},
            )
            extractor = SevenZipVhdxExtractor(
                seven_zip_path="C:\\tools\\7z.exe",
                command_runner=runner,
            )

            extractor.extract_file(image_path, member_path, output_path)

            self.assertEqual(output_path.read_bytes(), b"primary-save")
            self.assertEqual(
                runner.commands,
                [[
                    "C:\\tools\\7z.exe",
                    "x",
                    str(image_path),
                    member_path,
                    f"-o{runner.output_directories[0]}",
                    "-y",
                ]],
            )

    def test_seven_zip_vhdx_extractor_fails_loud_when_member_is_not_materialized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "Data.vhdx"
            image_path.write_bytes(b"vhdx")
            output_path = root / "prepared" / "playerInfo.dat"
            member_path = VHDX_SAVE_MEMBER_PATHS["playerInfo.dat"]
            runner = RecordingSevenZipCommandRunner(
                results=[
                    SevenZipCommandResult(
                        returncode=2,
                        stdout="Open Errors: 1",
                        stderr="0.img\r\nERRORS:\r\nHeaders Error\r\n",
                    )
                ],
                materialized_members={},
            )
            extractor = SevenZipVhdxExtractor(
                seven_zip_path="C:\\tools\\7z.exe",
                command_runner=runner,
            )

            with self.assertRaises(FileNotFoundError) as context:
                extractor.extract_file(image_path, member_path, output_path)

            self.assertIn("Headers Error", str(context.exception))
            self.assertFalse(output_path.exists())

    def test_seven_zip_vhdx_extractor_fails_loud_when_seven_zip_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image_path = root / "Data.vhdx"
            image_path.write_bytes(b"vhdx")
            output_path = root / "prepared" / "playerInfo.dat"
            member_path = VHDX_SAVE_MEMBER_PATHS["playerInfo.dat"]
            extractor = SevenZipVhdxExtractor(
                seven_zip_path="C:\\missing\\7z.exe",
                command_runner=MissingSevenZipCommandRunner(),
            )

            with self.assertRaises(RuntimeError) as context:
                extractor.extract_file(image_path, member_path, output_path)

            self.assertIn("7z executable was not found", str(context.exception))
            self.assertFalse(output_path.exists())

    def test_composition_builds_vhdx_save_source_with_explicit_backup_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vhdx_path = root / "Data.vhdx"
            vhdx_path.write_bytes(b"vhdx")
            prepared_local_path = root / "prepared" / "playerInfoBackup.dat"
            extractor = RecordingVhdxExtractor(
                content_by_member={
                    VHDX_SAVE_MEMBER_PATHS["playerInfoBackup.dat"]: b"backup-save",
                }
            )
            parser = argparse.ArgumentParser()
            add_tick_composition_arguments(parser)
            args = parser.parse_args(
                [
                    "--save-source",
                    "vhdx",
                    "--vhdx-path",
                    str(vhdx_path),
                    "--vhdx-save-name",
                    "playerInfoBackup.dat",
                    "--seven-zip-path",
                    "C:\\tools\\7z.exe",
                    "--prepared-save-path",
                    str(prepared_local_path),
                    "ignored-by-vhdx",
                ]
            )

            with patch("ipm_bot.control.composition.SevenZipVhdxExtractor", return_value=extractor) as extractor_cls:
                save_source = build_save_source(args)

            extractor_cls.assert_called_once_with(seven_zip_path="C:\\tools\\7z.exe")
            self.assertIsInstance(save_source, VhdxSaveSource)

            metadata = save_source.prepare(args.save_path)

            self.assertEqual(prepared_local_path.read_bytes(), b"backup-save")
            self.assertEqual(metadata.save_source_type, "vhdx")
            self.assertEqual(
                extractor.calls,
                [(
                    vhdx_path.resolve(),
                    VHDX_SAVE_MEMBER_PATHS["playerInfoBackup.dat"],
                    prepared_local_path.resolve(),
                )],
            )


class RecordingCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> None:
        self.commands.append(list(command))


class RecordingVhdxExtractor:
    def __init__(self, content_by_member: dict[str, bytes]) -> None:
        self._content_by_member = content_by_member
        self.calls: list[tuple[Path, str, Path]] = []

    def extract_file(self, image_path: Path, member_path: str, output_path: Path) -> None:
        self.calls.append((image_path, member_path, output_path))
        content = self._content_by_member.get(member_path)
        if content is None:
            raise FileNotFoundError(f"Missing member: {member_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)


class FailingVhdxExtractor:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def extract_file(self, image_path: Path, member_path: str, output_path: Path) -> None:
        del image_path, member_path, output_path
        raise self._error


class RecordingSevenZipCommandRunner:
    def __init__(
        self,
        *,
        results: list[SevenZipCommandResult],
        materialized_members: dict[str, bytes],
    ) -> None:
        self._results = list(results)
        self._materialized_members = dict(materialized_members)
        self.commands: list[list[str]] = []
        self.output_directories: list[Path] = []

    def run(self, command: list[str]) -> SevenZipCommandResult:
        self.commands.append(list(command))
        output_directory = _extract_output_directory(command)
        self.output_directories.append(output_directory)
        member_path = command[3]
        content = self._materialized_members.get(member_path)
        if content is not None:
            extracted_path = output_directory.joinpath(*Path(member_path).parts)
            extracted_path.parent.mkdir(parents=True, exist_ok=True)
            extracted_path.write_bytes(content)
        return self._results.pop(0)


class MissingSevenZipCommandRunner:
    def run(self, command: list[str]) -> SevenZipCommandResult:
        del command
        raise FileNotFoundError("7z missing")


class RecordingClock:
    def __init__(self) -> None:
        self._value = 0.0

    def monotonic(self) -> float:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += seconds


def _sample_player_data() -> PlayerData:
    return PlayerData(
        smelters=(
            SmelterSlot(
                index=0,
                on=True,
                recipe_selected=True,
                alternate_recipe_selected=False,
                recipe_number=4,
                start_date=datetime(2026, 3, 24, 18, 3, 30),
                end_date=datetime(2026, 3, 24, 18, 4, 23),
                original_end_date=datetime(2026, 3, 24, 18, 4, 23),
                timespan_left=timedelta(seconds=34.821),
                seconds_completed=18.512,
            ),
        ),
        crafters=(
            CrafterSlot(
                index=1,
                on=True,
                recipe_selected=True,
                alternate_recipe_selected=False,
                recipe_number=3,
                start_date=datetime(2026, 3, 24, 18, 2, 31),
                end_date=datetime(2026, 3, 24, 18, 10, 31),
                original_end_date=datetime(2026, 3, 24, 18, 10, 31),
                timespan_left=timedelta(seconds=455.933),
                seconds_completed=24.067,
            ),
        ),
        planets=(
            PlanetSlot(
                index=0,
                unlocked=True,
                mining_speed_level=5,
                speed_level=4,
                cargo_level=3,
                trip_start_date=datetime(2026, 3, 24, 18, 0, 0),
                trip_end_date=datetime(2026, 3, 24, 18, 0, 30),
            ),
        ),
        resources=(
            ResourceSlot(
                index=0,
                discovered=True,
                count=42.5,
                gathered_total=100.0,
                gathered_this_galaxy=75.0,
                sold_total=20.0,
                sold_this_galaxy=10.0,
            ),
        ),
        raw=object(),
    )


def _extract_output_directory(command: list[str]) -> Path:
    for part in command:
        if part.startswith("-o"):
            return Path(part[2:])
    raise AssertionError(f"Command did not contain an output directory: {command!r}")


if __name__ == "__main__":
    unittest.main()

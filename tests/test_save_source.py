from __future__ import annotations

import argparse
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
    SaveSourcePreparationError,
    VHDX_SAVE_MEMBER_PATHS,
    VhdxSaveSource,
    VhdxSaveSourceConfig,
)


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


if __name__ == "__main__":
    unittest.main()

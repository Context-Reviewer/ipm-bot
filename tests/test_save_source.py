from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.control.save_source import (
    AdbPulledSaveSource,
    AdbPulledSaveSourceConfig,
    LocalSaveSource,
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


class RecordingCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> None:
        self.commands.append(list(command))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.adb import AdbActionActuator, AdbActuatorConfig, TapPoint


class AdbActuatorTests(unittest.TestCase):
    def test_activate_ad_boost_emits_expected_commands(self) -> None:
        runner = RecordingCommandRunner()
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                app_activity="MainActivity",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                claim_ark_reward_tap=TapPoint(x=333, y=444),
            ),
            command_runner=runner,
        )

        actuator.execute("activate_ad_boost")

        self.assertEqual(
            runner.commands,
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "am",
                    "start",
                    "-n",
                    "com.example.idleplanetminer/MainActivity",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "111",
                    "222",
                ],
            ],
        )

    def test_claim_ark_reward_emits_expected_commands(self) -> None:
        runner = RecordingCommandRunner()
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(
                adb_path="adb",
                device_serial="emulator-5554",
                app_package="com.example.idleplanetminer",
                activate_ad_boost_tap=TapPoint(x=111, y=222),
                claim_ark_reward_tap=TapPoint(x=333, y=444),
            ),
            command_runner=runner,
        )

        actuator.execute("claim_ark_reward")

        self.assertEqual(
            runner.commands,
            [
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "monkey",
                    "-p",
                    "com.example.idleplanetminer",
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                [
                    "adb",
                    "-s",
                    "emulator-5554",
                    "shell",
                    "input",
                    "tap",
                    "333",
                    "444",
                ],
            ],
        )

    def test_idle_emits_no_commands(self) -> None:
        runner = RecordingCommandRunner()
        actuator = AdbActionActuator(
            config=AdbActuatorConfig(),
            command_runner=runner,
        )

        actuator.execute("idle")

        self.assertEqual(runner.commands, [])


class RecordingCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> None:
        self.commands.append(list(command))


if __name__ == "__main__":
    unittest.main()

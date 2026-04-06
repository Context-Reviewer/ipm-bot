from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.adb import AdbActionActuator, TapPoint
from ipm_bot.control.composition import add_tick_composition_arguments, build_actuator


class CompositionTests(unittest.TestCase):
    def test_build_actuator_threads_same_app_endcard_recovery_arguments(self) -> None:
        parser = argparse.ArgumentParser()
        add_tick_composition_arguments(parser)
        args = parser.parse_args(
            [
                "--actuator",
                "adb",
                "--adb-path",
                "C:\\dev\\platform-tools\\adb.exe",
                "--adb-serial",
                "emulator-5554",
                "--app-package",
                "com.TironiumTech.IdlePlanetMiner",
                "--app-activity",
                "com.unity3d.player.UnityPlayerActivity",
                "--claim-ark-adplayer-close-tap",
                "839,75",
                "--claim-ark-adplayer-close-attempts",
                "2",
                "--claim-ark-adplayer-close-interval-seconds",
                "0.5",
                "--claim-ark-adplayer-back-attempts",
                "1",
                "--claim-ark-adplayer-back-interval-seconds",
                "0.25",
                "--claim-ark-adplayer-grace-seconds",
                "4.0",
                "--claim-ark-same-app-endcard-close-tap",
                "839,75",
                "--claim-ark-same-app-endcard-close-attempts",
                "2",
                "--claim-ark-same-app-endcard-close-interval-seconds",
                "0.5",
                "--claim-ark-same-app-back-attempts",
                "2",
                "--claim-ark-same-app-back-interval-seconds",
                "0.75",
                "playerInfo.dat",
            ]
        )

        actuator = build_actuator(args)

        self.assertIsInstance(actuator, AdbActionActuator)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_close_tap, "839,75")
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_close_attempts, 2)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_close_interval_seconds, 0.5)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_back_attempts, 1)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_back_interval_seconds, 0.25)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_grace_seconds, 4.0)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_endcard_close_tap, "839,75")
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_endcard_close_attempts, 2)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_endcard_close_interval_seconds, 0.5)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_back_attempts, 2)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_back_interval_seconds, 0.75)
        self.assertEqual(actuator._config.claim_ark_adplayer_close_tap, TapPoint(x=839, y=75))
        self.assertEqual(actuator._config.claim_ark_adplayer_close_attempts, 2)
        self.assertEqual(actuator._config.claim_ark_adplayer_close_interval_seconds, 0.5)
        self.assertEqual(actuator._config.claim_ark_adplayer_back_attempts, 1)
        self.assertEqual(actuator._config.claim_ark_adplayer_back_interval_seconds, 0.25)
        self.assertEqual(actuator._config.claim_ark_adplayer_grace_seconds, 4.0)
        self.assertEqual(actuator._config.claim_ark_same_app_endcard_close_tap, TapPoint(x=839, y=75))
        self.assertEqual(actuator._config.claim_ark_same_app_endcard_close_attempts, 2)
        self.assertEqual(actuator._config.claim_ark_same_app_endcard_close_interval_seconds, 0.5)
        self.assertEqual(actuator._config.claim_ark_same_app_back_attempts, 2)
        self.assertEqual(actuator._config.claim_ark_same_app_back_interval_seconds, 0.75)

    def test_build_actuator_keeps_same_app_endcard_recovery_defaults_aligned(self) -> None:
        parser = argparse.ArgumentParser()
        add_tick_composition_arguments(parser)
        args = parser.parse_args(
            [
                "--actuator",
                "adb",
                "playerInfo.dat",
            ]
        )

        actuator = build_actuator(args)

        self.assertIsInstance(actuator, AdbActionActuator)
        self.assertIsNone(actuator.config_snapshot.claim_ark_adplayer_close_tap)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_close_attempts, 0)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_close_interval_seconds, 1.0)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_back_attempts, 0)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_back_interval_seconds, 1.0)
        self.assertEqual(actuator.config_snapshot.claim_ark_adplayer_grace_seconds, 0.0)
        self.assertIsNone(actuator.config_snapshot.claim_ark_same_app_endcard_close_tap)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_endcard_close_attempts, 0)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_endcard_close_interval_seconds, 1.0)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_back_attempts, 1)
        self.assertEqual(actuator.config_snapshot.claim_ark_same_app_back_interval_seconds, 1.0)
        self.assertIsNone(actuator._config.claim_ark_adplayer_close_tap)
        self.assertEqual(actuator._config.claim_ark_adplayer_close_attempts, 0)
        self.assertEqual(actuator._config.claim_ark_adplayer_close_interval_seconds, 1.0)
        self.assertEqual(actuator._config.claim_ark_adplayer_back_attempts, 0)
        self.assertEqual(actuator._config.claim_ark_adplayer_back_interval_seconds, 1.0)
        self.assertEqual(actuator._config.claim_ark_adplayer_grace_seconds, 0.0)
        self.assertIsNone(actuator._config.claim_ark_same_app_endcard_close_tap)
        self.assertEqual(actuator._config.claim_ark_same_app_endcard_close_attempts, 0)
        self.assertEqual(actuator._config.claim_ark_same_app_endcard_close_interval_seconds, 1.0)
        self.assertEqual(actuator._config.claim_ark_same_app_back_attempts, 1)
        self.assertEqual(actuator._config.claim_ark_same_app_back_interval_seconds, 1.0)

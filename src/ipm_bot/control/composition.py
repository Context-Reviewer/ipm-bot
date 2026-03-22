"""Shared composition helpers for one control tick and experiment harnesses."""

from __future__ import annotations

import argparse

from ipm_bot.actuator.adb import AdbActionActuator, AdbActuatorConfig, SubprocessCommandRunner, TapPoint
from ipm_bot.actuator.boundary import ActionActuator
from ipm_bot.actuator.stub import StubActionActuator
from ipm_bot.control.save_source import (
    AdbPulledSaveSource,
    AdbPulledSaveSourceConfig,
    DEFAULT_PULLED_SAVE_PATH,
    LocalSaveSource,
    SaveSource,
)


def add_tick_composition_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared save-source and actuator arguments for one tick."""

    parser.add_argument("save_path", type=_path_type, help="Path to the current playerInfo.dat save.")
    parser.add_argument(
        "--save-source",
        choices=("local", "adb-pull"),
        default="local",
        help="Save-source implementation used to prepare the local save for this control tick.",
    )
    parser.add_argument(
        "--actuator",
        choices=("stub", "adb"),
        default="stub",
        help="Concrete actuator implementation to use for this control tick.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="Override the canonical action timeout used for closed-loop verification.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=0.5,
        help="Polling interval used while waiting for a new parseable save.",
    )
    parser.add_argument(
        "--prepared-save-path",
        type=_path_type,
        default=DEFAULT_PULLED_SAVE_PATH,
        help="Local path used when --save-source adb-pull prepares the save.",
    )
    parser.add_argument(
        "--adb-path",
        default="adb",
        help="ADB executable path when an ADB-backed integration is selected.",
    )
    parser.add_argument(
        "--adb-serial",
        default=None,
        help="Optional ADB device serial when an ADB-backed integration is selected.",
    )
    parser.add_argument(
        "--app-package",
        default=None,
        help="Optional Android package name to foreground before action taps.",
    )
    parser.add_argument(
        "--app-activity",
        default=None,
        help="Optional Android activity name paired with --app-package.",
    )
    parser.add_argument(
        "--activate-ad-boost-tap",
        default="540,960",
        help="Tap coordinates for activate_ad_boost as X,Y when using the ADB actuator.",
    )
    parser.add_argument(
        "--claim-ark-reward-tap",
        default="540,780",
        help="Tap coordinates for claim_ark_reward as X,Y when using the ADB actuator.",
    )


def build_actuator(args: argparse.Namespace) -> ActionActuator:
    """Build the configured actuator implementation from parsed arguments."""

    if args.actuator == "stub":
        return StubActionActuator()
    if args.actuator != "adb":
        raise ValueError(f"Unsupported actuator type: {args.actuator}")

    return AdbActionActuator(
        config=AdbActuatorConfig(
            adb_path=args.adb_path,
            device_serial=args.adb_serial,
            app_package=args.app_package,
            app_activity=args.app_activity,
            activate_ad_boost_tap=parse_tap_point(args.activate_ad_boost_tap),
            claim_ark_reward_tap=parse_tap_point(args.claim_ark_reward_tap),
        ),
        command_runner=SubprocessCommandRunner(),
    )


def build_save_source(args: argparse.Namespace) -> SaveSource:
    """Build the configured save-source implementation from parsed arguments."""

    if args.save_source == "local":
        return LocalSaveSource()
    if args.save_source != "adb-pull":
        raise ValueError(f"Unsupported save source type: {args.save_source}")

    return AdbPulledSaveSource(
        config=AdbPulledSaveSourceConfig(
            adb_path=args.adb_path,
            device_serial=args.adb_serial,
            prepared_local_path=args.prepared_save_path,
        ),
        command_runner=SubprocessCommandRunner(),
    )


def parse_tap_point(raw_value: str) -> TapPoint:
    """Parse a tap coordinate string in X,Y form."""

    parts = [part.strip() for part in raw_value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Invalid tap coordinate value: {raw_value!r}")
    try:
        x = int(parts[0])
        y = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"Invalid tap coordinate value: {raw_value!r}") from exc
    return TapPoint(x=x, y=y)


def _path_type(raw_value: str):
    from pathlib import Path

    return Path(raw_value)

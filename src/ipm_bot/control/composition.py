"""Shared composition helpers for one control tick and experiment harnesses."""

from __future__ import annotations

import argparse

from ipm_bot.actuator.adb import AdbActionActuator, AdbActuatorConfig, SubprocessCommandRunner, TapPoint
from ipm_bot.actuator.boundary import ActionActuator
from ipm_bot.actuator.stub import StubActionActuator
from ipm_bot.control.save_source import (
    AdbPulledSaveSource,
    AdbPulledSaveSourceConfig,
    DEFAULT_BLUESTACKS_VHDX_PATH,
    DEFAULT_PULLED_SAVE_PATH,
    LocalSaveSource,
    SaveSource,
    SevenZipVhdxExtractor,
    SUPPORTED_VHDX_SAVE_NAMES,
    VhdxSaveSource,
    VhdxSaveSourceConfig,
)


def add_tick_composition_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared save-source and actuator arguments for one tick."""

    parser.add_argument("save_path", type=_path_type, help="Path to the current playerInfo.dat save.")
    parser.add_argument(
        "--save-source",
        choices=("local", "adb-pull", "vhdx"),
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
        help="Local path used when a non-local save source prepares the save.",
    )
    parser.add_argument(
        "--vhdx-path",
        type=_path_type,
        default=DEFAULT_BLUESTACKS_VHDX_PATH,
        help="BlueStacks Data.vhdx path used by --save-source vhdx. BlueStacks must be closed.",
    )
    parser.add_argument(
        "--vhdx-save-name",
        choices=SUPPORTED_VHDX_SAVE_NAMES,
        default="playerInfo.dat",
        help="Explicit trusted save file selected from Data.vhdx when --save-source vhdx is used.",
    )
    parser.add_argument(
        "--seven-zip-path",
        default="7z",
        help="7z executable path used by --save-source vhdx for read-only extraction.",
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
        default="852,311",
        help="Tap coordinates for the Ark entry button as X,Y when using the ADB actuator.",
    )
    parser.add_argument(
        "--claim-ark-watch-tap",
        default="449,836",
        help="Tap coordinates for the Ark watch-video button as X,Y when using the ADB actuator.",
    )
    parser.add_argument(
        "--claim-ark-skip-tap",
        default="50,47",
        help="Tap coordinates for the fixed in-ad Ark skip/close button as X,Y when using the ADB actuator.",
    )
    parser.add_argument(
        "--claim-ark-final-claim-tap",
        default="454,968",
        help="Tap coordinates for the Ark final claim button as X,Y when using the ADB actuator.",
    )
    parser.add_argument(
        "--ark-popup-wait-seconds",
        type=float,
        default=1.5,
        help="Wait time after tapping the Ark entry button before tapping watch-video.",
    )
    parser.add_argument(
        "--ark-ad-wait-seconds",
        type=float,
        default=20.0,
        help="Fixed wait budget before the Ark in-ad skip/close tap.",
    )
    parser.add_argument(
        "--ark-skip-close-wait-seconds",
        type=float,
        default=1.0,
        help="Fixed wait after the Ark in-ad skip/close tap before sending Escape.",
    )
    parser.add_argument(
        "--ark-return-wait-seconds",
        type=float,
        default=3.0,
        help="Wait time after the final Ark ad close attempt before the claim tap.",
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
            claim_ark_reward_watch_tap=parse_tap_point(args.claim_ark_watch_tap),
            claim_ark_skip_tap=parse_tap_point(args.claim_ark_skip_tap),
            claim_ark_reward_final_claim_tap=parse_tap_point(args.claim_ark_final_claim_tap),
            ark_popup_wait_seconds=args.ark_popup_wait_seconds,
            ark_ad_wait_seconds=args.ark_ad_wait_seconds,
            ark_skip_close_wait_seconds=args.ark_skip_close_wait_seconds,
            ark_return_wait_seconds=args.ark_return_wait_seconds,
        ),
        command_runner=SubprocessCommandRunner(),
    )


def build_save_source(args: argparse.Namespace) -> SaveSource:
    """Build the configured save-source implementation from parsed arguments."""

    if args.save_source == "local":
        return LocalSaveSource()
    if args.save_source == "adb-pull":
        return AdbPulledSaveSource(
            config=AdbPulledSaveSourceConfig(
                adb_path=args.adb_path,
                device_serial=args.adb_serial,
                prepared_local_path=args.prepared_save_path,
            ),
            command_runner=SubprocessCommandRunner(),
        )
    if args.save_source == "vhdx":
        return VhdxSaveSource(
            config=VhdxSaveSourceConfig(
                vhdx_path=args.vhdx_path,
                save_name=args.vhdx_save_name,
                prepared_local_path=args.prepared_save_path,
            ),
            extractor=SevenZipVhdxExtractor(seven_zip_path=args.seven_zip_path),
        )

    raise ValueError(f"Unsupported save source type: {args.save_source}")


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

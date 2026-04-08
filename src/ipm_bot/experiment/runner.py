"""Experiment harness for one governed end-to-end emulator experiment run."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Sequence

from ipm_bot.actuator.runner import MiningVerificationMode
from ipm_bot.control.composition import add_tick_composition_arguments, build_actuator, build_save_source
from ipm_bot.control.experiment_store import ExperimentManifest, normalize_utc_timestamp, write_experiment_manifest
from ipm_bot.control.save_source import AdbPulledSaveSource
from ipm_bot.main import ExitCode, run_single_control_tick


@dataclass(frozen=True, slots=True)
class ExperimentRunResult:
    experiment_id: str
    receipt_path: Path
    manifest_path: Path
    exit_code: int


def main(argv: Sequence[str] | None = None) -> int:
    """Run one governed experiment and return its deterministic exit code."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        actuator = build_actuator(args)
        save_source = build_save_source(args)
        result = run_experiment(
            save_path=args.save_path,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            actuator=actuator,
            save_source=save_source,
            action_override=args.action_override,
            mining_verification_mode=(
                None
                if args.mining_verification_mode is None
                else MiningVerificationMode(args.mining_verification_mode)
            ),
            save_repull_interval_seconds=args.save_repull_interval_seconds,
            manual_observation_mode=args.manual_observation_mode,
        )
    except SystemExit:
        return int(ExitCode.ERROR)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return int(ExitCode.ERROR)

    print(f"Experiment ID: {result.experiment_id}")
    print(f"Receipt path: {result.receipt_path}")
    print(f"Manifest path: {result.manifest_path}")
    print(f"Exit code: {result.exit_code}")
    return result.exit_code


def run_experiment(
    save_path: Path,
    timeout_seconds: float | None,
    poll_interval_seconds: float,
    actuator,
    save_source,
    action_override: str | None = None,
    mining_verification_mode: MiningVerificationMode | None = None,
    save_repull_interval_seconds: float = 1.0,
    manual_observation_mode: bool = False,
) -> ExperimentRunResult:
    """Run exactly one control tick and persist a matching experiment manifest."""

    save_refresh_controller = None
    effective_poll_interval_seconds = poll_interval_seconds
    if manual_observation_mode and action_override not in {"claim_reward", "claim_ark_reward"}:
        raise ValueError(
            "Manual observation mode currently requires --action-override claim_reward."
        )
    if isinstance(save_source, AdbPulledSaveSource):
        save_refresh_controller = save_source.build_refresh_controller(
            save_path,
            refresh_interval_seconds=save_repull_interval_seconds,
        )
        effective_poll_interval_seconds = min(
            poll_interval_seconds,
            save_repull_interval_seconds,
        )

    started_at = datetime.now(timezone.utc)
    action, receipt, receipt_path = run_single_control_tick(
        save_path=save_path,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=effective_poll_interval_seconds,
        actuator=actuator,
        save_source=save_source,
        mining_verification_mode=mining_verification_mode,
        action_override=action_override,
        save_refresh_controller=save_refresh_controller,
        verification_timeout_starts_after_actuation=True,
        manual_observation_mode=manual_observation_mode,
    )
    completed_at = datetime.now(timezone.utc)

    exit_code = receipt.runtime_context.exit_code
    if exit_code is None:
        raise ValueError("Control tick receipt is missing its exit code.")
    if receipt.save_source_metadata is None:
        raise ValueError("Control tick receipt is missing save source metadata.")

    manifest = ExperimentManifest(
        started_at_utc=normalize_utc_timestamp(started_at),
        completed_at_utc=normalize_utc_timestamp(completed_at),
        actuator_type=receipt.actuator_execution.actuator_type,
        save_source_type=receipt.save_source_metadata.save_source_type,
        original_requested_save_path=receipt.save_source_metadata.original_requested_path,
        prepared_local_save_path=receipt.save_source_metadata.prepared_local_path,
        receipt_path=str(receipt_path),
        exit_code=exit_code,
        final_status=receipt.final_status,
        failure_reason=receipt.failure_reason,
        selected_action=action,
    )
    experiment_id, manifest_path = write_experiment_manifest(manifest)
    return ExperimentRunResult(
        experiment_id=experiment_id,
        receipt_path=receipt_path,
        manifest_path=manifest_path,
        exit_code=exit_code,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one governed experiment around a single control tick."
    )
    add_tick_composition_arguments(parser)
    parser.add_argument(
        "--action-override",
        choices=("activate_ad_boost", "claim_reward", "claim_ark_reward", "idle"),
        default=None,
        help="Experiment-only explicit action override that bypasses planner selection.",
    )
    parser.add_argument(
        "--mining-verification-mode",
        choices=tuple(mode.value for mode in MiningVerificationMode),
        default=None,
        help="Experiment-only explicit mining verification mode for claim vs settlement.",
    )
    parser.add_argument(
        "--save-repull-interval-seconds",
        type=float,
        default=1.0,
        help="Experiment-only interval for periodic ADB save re-pull during verification.",
    )
    parser.add_argument(
        "--manual-observation-mode",
        action="store_true",
        help="Experiment-only Ark signal-discovery mode with no automated Ark taps or Escape input.",
    )
    parser.add_argument(
        "--manual-observation-window-seconds",
        type=float,
        default=20.0,
        help="Observation window used by experiment-only manual observation mode.",
    )
    parser.add_argument(
        "--manual-observation-probe-interval-seconds",
        type=float,
        default=1.0,
        help="Probe interval used by experiment-only manual observation mode.",
    )
    return parser

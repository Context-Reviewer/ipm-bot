"""Minimal closed-loop bot orchestrator."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from dataclasses import replace
from enum import IntEnum
from pathlib import Path
import sys
from typing import Sequence

from ipm_bot.actuator.boundary import ActionActuator
from ipm_bot.actuator.runner import ActionAttemptReceipt, run_action_until_verified
from ipm_bot.control.composition import add_tick_composition_arguments, build_actuator, build_save_source
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_store import (
    check_ad_boost_suppressed,
    check_reward_claim_suppressed,
    write_receipt,
)
from ipm_bot.control.save_source import (
    SaveRefreshController,
    SaveSnapshot,
    SaveSource,
    SaveSourceMetadata,
    load_save_snapshot,
)
from ipm_bot.control.timing import summarize_production_timing
from ipm_bot.planner.planner import PlannerDecision, decide_next_action_details
from ipm_bot.save import PlayerSnapshot, parse_player_snapshot


class ExitCode(IntEnum):
    PASS = 0
    FAIL = 1
    AMBIGUOUS = 2
    ERROR = 3


EXIT_CODE_BY_STATUS = {
    "PASS": ExitCode.PASS,
    "FAIL": ExitCode.FAIL,
    "AMBIGUOUS": ExitCode.AMBIGUOUS,
}


@dataclass(frozen=True, slots=True)
class SaveSnapshotObservability:
    save_snapshot_available: bool
    active_smelters: int
    active_crafters: int
    nearest_completion_seconds: float | None


@dataclass(frozen=True, slots=True)
class PlannerTimingObservability:
    planner_nearest_completion_seconds: float | None
    planner_save_snapshot_used: bool
    planner_deferred_for_imminent_completion: bool


def main(argv: Sequence[str] | None = None) -> int:
    """Run one governed single control tick and return a deterministic exit code."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        actuator = build_actuator(args)
        save_source = build_save_source(args)
        action, receipt, receipt_path = run_single_control_tick(
            save_path=args.save_path,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            actuator=actuator,
            save_source=save_source,
        )
    except SystemExit:
        return int(ExitCode.ERROR)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return int(ExitCode.ERROR)

    _print_control_tick_result(action, receipt, receipt_path)
    return int(exit_code_for_status(receipt.final_status))


def run_single_control_tick(
    save_path: Path,
    timeout_seconds: float | None,
    poll_interval_seconds: float,
    actuator: ActionActuator,
    save_source: SaveSource,
    action_override: str | None = None,
    save_refresh_controller: SaveRefreshController | None = None,
    verification_timeout_starts_after_actuation: bool = False,
    manual_observation_mode: bool = False,
    unattended_safe: bool = False,
    ad_boost_suppressed: bool = False,
    receipt_dir: Path | None = None,
) -> tuple[str, ActionAttemptReceipt, Path]:
    """Execute exactly one governed control tick and persist its receipt."""

    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than zero.")
    if poll_interval_seconds <= 0:
        raise ValueError("--poll-interval-seconds must be greater than zero.")

    if not ad_boost_suppressed:
        ad_boost_suppressed = check_ad_boost_suppressed(receipt_dir)
        claim_reward_suppressed = check_reward_claim_suppressed(receipt_dir)

    save_source_metadata = save_source.prepare(save_path)
    prepared_save_path = Path(save_source_metadata.prepared_local_path)
    save_snapshot = _load_save_snapshot(prepared_save_path)
    save_snapshot_observability = _observe_save_snapshot(save_snapshot)
    snapshot_before = _load_snapshot(prepared_save_path)
    planner_decision = decide_next_action_details(
        snapshot_before,
        save_snapshot=save_snapshot,
        unattended_safe=unattended_safe,
            ad_boost_suppressed=ad_boost_suppressed,
            claim_reward_suppressed=claim_reward_suppressed,
        )
    planner_timing_observability = _observe_planner_timing(
        planner_decision=planner_decision,
        save_snapshot_observability=save_snapshot_observability,
    )
    action = planner_decision.selected_action
    if action_override is not None:
        action = action_override
        planner_decision = PlannerDecision(
            selected_action=action_override,
            decision_reason="experiment_action_override",
            actuation_required=action_override != "idle",
        )
    contract = get_action_contract(action)

    receipt = run_action_until_verified(
        action=action,
        save_path=prepared_save_path,
        snapshot_before=snapshot_before,
        contract=contract,
        actuator=actuator,
        poll_interval_s=poll_interval_seconds,
        timeout_s=timeout_seconds,
        save_refresh_controller=save_refresh_controller,
        verification_timeout_starts_after_actuation=verification_timeout_starts_after_actuation,
        manual_observation_mode=manual_observation_mode,
    )
    exit_code = exit_code_for_status(receipt.final_status)
    receipt = _enrich_tick_receipt(
        receipt=receipt,
        planner_decision=planner_decision,
        exit_code=exit_code,
        save_source_metadata=save_source_metadata,
        actuator=actuator,
        action_override=action_override,
        manual_observation_mode=manual_observation_mode,
        save_snapshot_observability=save_snapshot_observability,
        planner_timing_observability=planner_timing_observability,
    )
    receipt_path = write_receipt(receipt)
    return action, receipt, receipt_path


def exit_code_for_status(status: str) -> ExitCode:
    """Return the canonical exit code for a terminal control-tick status."""

    exit_code = EXIT_CODE_BY_STATUS.get(status)
    if exit_code is None:
        raise ValueError(f"Unsupported terminal status for exit-code mapping: {status}")
    return exit_code


def _enrich_tick_receipt(
    receipt: ActionAttemptReceipt,
    planner_decision: PlannerDecision,
    exit_code: ExitCode,
    save_source_metadata: SaveSourceMetadata,
    actuator: ActionActuator,
    action_override: str | None = None,
    manual_observation_mode: bool = False,
    save_snapshot_observability: SaveSnapshotObservability | None = None,
    planner_timing_observability: PlannerTimingObservability | None = None,
) -> ActionAttemptReceipt:
    observability = (
        SaveSnapshotObservability(
            save_snapshot_available=False,
            active_smelters=0,
            active_crafters=0,
            nearest_completion_seconds=None,
        )
        if save_snapshot_observability is None
        else save_snapshot_observability
    )
    planner_observability = (
        PlannerTimingObservability(
            planner_nearest_completion_seconds=None,
            planner_save_snapshot_used=False,
            planner_deferred_for_imminent_completion=False,
        )
        if planner_timing_observability is None
        else planner_timing_observability
    )
    return replace(
        receipt,
        planner_decision=planner_decision,
        actuation_attempted=planner_decision.actuation_required,
        save_source_metadata=save_source_metadata,
        actuator_config_snapshot=actuator.config_snapshot,
        runtime_context=replace(
            receipt.runtime_context,
            exit_code=int(exit_code),
            action_override_used=action_override is not None,
            action_override_requested_action=action_override,
            manual_observation_mode=manual_observation_mode,
            save_snapshot_available=observability.save_snapshot_available,
            active_smelters=observability.active_smelters,
            active_crafters=observability.active_crafters,
            nearest_completion_seconds=observability.nearest_completion_seconds,
            planner_nearest_completion_seconds=(
                planner_observability.planner_nearest_completion_seconds
            ),
            planner_save_snapshot_used=planner_observability.planner_save_snapshot_used,
            planner_deferred_for_imminent_completion=(
                planner_observability.planner_deferred_for_imminent_completion
            ),
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for one governed control tick."""

    parser = argparse.ArgumentParser(
        description="Run one governed single control tick against a parsed save."
    )
    add_tick_composition_arguments(parser)
    return parser


def _load_snapshot(save_path: Path) -> PlayerSnapshot:
    if not save_path.is_file():
        raise FileNotFoundError(f"Save file does not exist: {save_path}")
    return parse_player_snapshot(save_path)


def _load_save_snapshot(save_path: Path) -> SaveSnapshot | None:
    if not save_path.is_file():
        raise FileNotFoundError(f"Save file does not exist: {save_path}")
    if save_path.suffix.lower() == ".json":
        return None
    return load_save_snapshot(save_path)


def _observe_save_snapshot(save_snapshot: SaveSnapshot | None) -> SaveSnapshotObservability:
    timing = summarize_production_timing(save_snapshot)
    return SaveSnapshotObservability(
        save_snapshot_available=save_snapshot is not None,
        active_smelters=timing.active_smelters,
        active_crafters=timing.active_crafters,
        nearest_completion_seconds=timing.nearest_completion_seconds,
    )


def _observe_planner_timing(
    *,
    planner_decision: PlannerDecision,
    save_snapshot_observability: SaveSnapshotObservability,
) -> PlannerTimingObservability:
    return PlannerTimingObservability(
        planner_nearest_completion_seconds=save_snapshot_observability.nearest_completion_seconds,
        planner_save_snapshot_used=save_snapshot_observability.save_snapshot_available,
        planner_deferred_for_imminent_completion=(
            planner_decision.decision_reason == "defer_ad_boost_for_imminent_completion"
        ),
    )


def _print_control_tick_result(
    action: str,
    receipt: ActionAttemptReceipt,
    receipt_path: Path,
) -> None:
    print(f"Selected action: {action}")
    print(f"Final status: {receipt.final_status}")
    print(f"Failure reason: {receipt.failure_reason}")
    print(
        "Save snapshot: "
        f"available={receipt.runtime_context.save_snapshot_available} "
        f"active_smelters={receipt.runtime_context.active_smelters} "
        f"active_crafters={receipt.runtime_context.active_crafters} "
        f"nearest_completion_seconds={receipt.runtime_context.nearest_completion_seconds}"
    )
    print(f"Receipt path: {receipt_path}")


if __name__ == "__main__":
    raise SystemExit(main())

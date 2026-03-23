"""Minimal closed-loop bot orchestrator."""

from __future__ import annotations

import argparse
from dataclasses import replace
from enum import IntEnum
from pathlib import Path
import sys
from typing import Sequence

from ipm_bot.actuator.boundary import ActionActuator
from ipm_bot.actuator.runner import ActionAttemptReceipt, run_action_until_verified
from ipm_bot.control.composition import add_tick_composition_arguments, build_actuator, build_save_source
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_store import write_receipt
from ipm_bot.control.save_source import (
    SaveSource,
    SaveSourceMetadata,
)
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
) -> tuple[str, ActionAttemptReceipt, Path]:
    """Execute exactly one governed control tick and persist its receipt."""

    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than zero.")
    if poll_interval_seconds <= 0:
        raise ValueError("--poll-interval-seconds must be greater than zero.")

    save_source_metadata = save_source.prepare(save_path)
    prepared_save_path = Path(save_source_metadata.prepared_local_path)
    snapshot_before = _load_snapshot(prepared_save_path)
    planner_decision = decide_next_action_details(snapshot_before)
    action = planner_decision.selected_action
    contract = get_action_contract(action)

    receipt = run_action_until_verified(
        action=action,
        save_path=prepared_save_path,
        snapshot_before=snapshot_before,
        contract=contract,
        actuator=actuator,
        poll_interval_s=poll_interval_seconds,
        timeout_s=timeout_seconds,
    )
    exit_code = exit_code_for_status(receipt.final_status)
    receipt = _enrich_tick_receipt(
        receipt=receipt,
        planner_decision=planner_decision,
        exit_code=exit_code,
        save_source_metadata=save_source_metadata,
        actuator=actuator,
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
) -> ActionAttemptReceipt:
    return replace(
        receipt,
        planner_decision=planner_decision,
        actuation_attempted=planner_decision.actuation_required,
        save_source_metadata=save_source_metadata,
        actuator_config_snapshot=actuator.config_snapshot,
        runtime_context=replace(receipt.runtime_context, exit_code=int(exit_code)),
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


def _print_control_tick_result(
    action: str,
    receipt: ActionAttemptReceipt,
    receipt_path: Path,
) -> None:
    print(f"Selected action: {action}")
    print(f"Final status: {receipt.final_status}")
    print(f"Failure reason: {receipt.failure_reason}")
    print(f"Receipt path: {receipt_path}")


if __name__ == "__main__":
    raise SystemExit(main())

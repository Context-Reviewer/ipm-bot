"""Minimal closed-loop bot orchestrator."""

from __future__ import annotations

import argparse
from pathlib import Path

from ipm_bot.actuator.runner import ActionAttemptReceipt, run_action_until_verified
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_store import write_receipt
from ipm_bot.planner.planner import decide_next_action
from ipm_bot.save import PlayerSnapshot, parse_player_snapshot


def main() -> int:
    """Run one closed-loop iteration against a single save file path."""

    parser = argparse.ArgumentParser(
        description="Run one minimal closed-loop bot iteration against a parsed save."
    )
    parser.add_argument("save_path", type=Path, help="Path to the current playerInfo.dat save.")
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
    args = parser.parse_args()

    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than zero.")
    if args.poll_interval_seconds <= 0:
        raise ValueError("--poll-interval-seconds must be greater than zero.")

    snapshot_before = _load_snapshot(args.save_path)
    action = decide_next_action(snapshot_before)
    contract = get_action_contract(action)

    print(f"Selected action: {action}")
    receipt = run_action_until_verified(
        action=action,
        save_path=args.save_path,
        snapshot_before=snapshot_before,
        contract=contract,
        poll_interval_s=args.poll_interval_seconds,
        timeout_s=args.timeout_seconds,
    )
    receipt_path = write_receipt(receipt)
    _print_receipt(receipt, receipt_path)

    return 0 if receipt.final_status == "PASS" else 1


def _load_snapshot(save_path: Path) -> PlayerSnapshot:
    if not save_path.is_file():
        raise FileNotFoundError(f"Save file does not exist: {save_path}")
    return parse_player_snapshot(save_path)


def _print_receipt(receipt: ActionAttemptReceipt, receipt_path: Path) -> None:
    print(f"Verification status: {receipt.final_status}")
    print(f"Failure reason: {receipt.failure_reason}")
    print(f"Elapsed seconds: {receipt.elapsed_seconds:.3f}")
    print(f"Changed saves observed: {receipt.changed_save_count}")
    print(f"Receipt path: {receipt_path}")
    for message in receipt.verifier_messages:
        print(f"- {message}")


if __name__ == "__main__":
    raise SystemExit(main())

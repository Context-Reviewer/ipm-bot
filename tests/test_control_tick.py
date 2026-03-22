from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.runner import (
    ActionAttemptReceipt,
    FailureReason,
    ReceiptRuntimeContext,
)
from ipm_bot.actuator.boundary import ActuatorExecutionMetadata
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_store import write_receipt
from ipm_bot.control.save_source import SaveSourceMetadata
from ipm_bot.main import ExitCode, main
from ipm_bot.planner.planner import PlannerDecision


class ControlTickTests(unittest.TestCase):
    def test_pass_returns_exit_code_zero_and_writes_receipt(self) -> None:
        save_payload = {
            "adBoostActive": False,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": False,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="activate_ad_boost",
            final_status="PASS",
            failure_reason=FailureReason.NONE,
        )

        exit_code, stdout_value, runner_mock, written_files, payloads = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
        )

        self.assertEqual(exit_code, int(ExitCode.PASS))
        self.assertEqual(runner_mock.call_count, 1)
        self.assertEqual(runner_mock.call_args.kwargs["action"], "activate_ad_boost")
        self.assertEqual(len(written_files), 1)
        self.assertEqual(payloads[0]["runtime_context"]["exit_code"], int(ExitCode.PASS))
        self.assertTrue(payloads[0]["planner_decision"]["actuation_required"])
        self.assertTrue(payloads[0]["actuation_attempted"])
        self.assertEqual(payloads[0]["actuator_execution"]["actuator_type"], "stub")
        self.assertEqual(payloads[0]["save_source"]["save_source_type"], "local")
        self.assertFalse(payloads[0]["save_source"]["preparation_performed"])
        self.assertIn("Selected action: activate_ad_boost", stdout_value)
        self.assertIn("Final status: PASS", stdout_value)

    def test_fail_returns_exit_code_one(self) -> None:
        save_payload = {
            "adBoostActive": False,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": False,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="activate_ad_boost",
            final_status="FAIL",
            failure_reason=FailureReason.TIMEOUT_NO_SAVE_CHANGE,
        )

        exit_code, _, runner_mock, _, _ = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
        )

        self.assertEqual(exit_code, int(ExitCode.FAIL))
        self.assertEqual(runner_mock.call_count, 1)

    def test_ambiguous_returns_exit_code_two(self) -> None:
        save_payload = {
            "adBoostActive": True,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": True,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="claim_ark_reward",
            final_status="AMBIGUOUS",
            failure_reason=FailureReason.AMBIGUOUS_TRANSITION,
        )

        exit_code, stdout_value, runner_mock, _, _ = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
        )

        self.assertEqual(exit_code, int(ExitCode.AMBIGUOUS))
        self.assertEqual(runner_mock.call_count, 1)
        self.assertEqual(runner_mock.call_args.kwargs["action"], "claim_ark_reward")
        self.assertIn("Failure reason: AMBIGUOUS_TRANSITION", stdout_value)

    def test_idle_planner_decision_is_persisted_with_no_actuation_required(self) -> None:
        save_payload = {
            "adBoostActive": True,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": False,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="idle",
            final_status="PASS",
            failure_reason=FailureReason.NONE,
            planner_decision=PlannerDecision(
                selected_action="idle",
                decision_reason="no_action_needed",
                actuation_required=False,
            ),
            actuation_attempted=False,
        )

        exit_code, stdout_value, runner_mock, _, payloads = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
        )

        self.assertEqual(exit_code, int(ExitCode.PASS))
        self.assertEqual(runner_mock.call_count, 1)
        self.assertEqual(runner_mock.call_args.kwargs["action"], "idle")
        self.assertEqual(payloads[0]["planner_decision"]["selected_action"], "idle")
        self.assertEqual(payloads[0]["planner_decision"]["decision_reason"], "no_action_needed")
        self.assertFalse(payloads[0]["planner_decision"]["actuation_required"])
        self.assertFalse(payloads[0]["actuation_attempted"])
        self.assertEqual(payloads[0]["actuator_execution"]["actuator_execution_status"], "NOT_REQUIRED")
        self.assertEqual(payloads[0]["actuator_execution"]["actuator_command_count"], 0)
        self.assertIn("Selected action: idle", stdout_value)


def _run_main_with_receipt(
    *,
    save_payload: dict[str, object],
    receipt: ActionAttemptReceipt,
) -> tuple[int, str, object, list[Path], list[dict[str, object]]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        save_path = root / "save.json"
        save_path.write_text(json.dumps(save_payload), encoding="utf-8")
        output_dir = root / "logs" / "receipts"
        stdout = io.StringIO()

        def _write_to_temp(receipt_to_write: ActionAttemptReceipt) -> Path:
            return write_receipt(
                receipt_to_write,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

        with (
            patch("sys.stdout", stdout),
            patch("ipm_bot.main.run_action_until_verified", return_value=receipt) as runner_mock,
            patch("ipm_bot.main.write_receipt", side_effect=_write_to_temp),
        ):
            exit_code = main([str(save_path)])

        written_files = list(output_dir.glob("*.json"))
        payloads = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in written_files
        ]
        return exit_code, stdout.getvalue(), runner_mock, written_files, payloads


def _sample_receipt(
    *,
    action: str,
    final_status: str,
    failure_reason: FailureReason,
    planner_decision: PlannerDecision | None = None,
    actuation_attempted: bool | None = None,
) -> ActionAttemptReceipt:
    contract = get_action_contract(action)
    resolved_planner_decision = planner_decision
    if resolved_planner_decision is None:
        if action == "claim_ark_reward":
            resolved_planner_decision = PlannerDecision(
                selected_action=action,
                decision_reason="ark_reward_ready_to_claim",
                actuation_required=True,
            )
        elif action == "activate_ad_boost":
            resolved_planner_decision = PlannerDecision(
                selected_action=action,
                decision_reason="ad_boost_inactive",
                actuation_required=True,
            )
        else:
            resolved_planner_decision = PlannerDecision(
                selected_action=action,
                decision_reason="no_action_needed",
                actuation_required=False,
            )
    resolved_actuation_attempted = (
        resolved_planner_decision.actuation_required
        if actuation_attempted is None
        else actuation_attempted
    )
    return ActionAttemptReceipt(
        action=action,
        save_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
        baseline_hash="abc123",
        final_status=final_status,
        failure_reason=failure_reason,
        elapsed_seconds=1.25,
        changed_save_count=1,
        candidate_hashes=["def456"],
        final_candidate_hash="def456",
        contract_identity=contract.identity(action),
        runtime_context=ReceiptRuntimeContext(
            receipt_schema_version=2,
            poll_interval_seconds=0.5,
            timeout_seconds=30.0,
        ),
        actuator_execution=ActuatorExecutionMetadata(
            actuator_type="stub",
            actuator_execution_status=(
                "NOT_REQUIRED" if action == "idle" else "COMPLETED"
            ),
            actuator_command_count=(0 if action == "idle" else 1),
            actuator_command_summary=([] if action == "idle" else [f"stub:{action}"]),
        ),
        verifier_messages=["verification message"],
        planner_decision=resolved_planner_decision,
        actuation_attempted=resolved_actuation_attempted,
        save_source_metadata=SaveSourceMetadata(
            save_source_type="local",
            original_requested_path="C:\\dev\\ipm-bot\\data\\save.json",
            prepared_local_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
            preparation_performed=False,
        ),
    )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    MiningVerificationMode,
    ReceiptRuntimeContext,
)
from ipm_bot.actuator.boundary import (
    ActuatorConfigSnapshot,
    ActuatorExecutionMetadata,
)
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_schema import CURRENT_RECEIPT_SCHEMA_VERSION
from ipm_bot.control.receipt_store import write_receipt
from ipm_bot.control.save_source import (
    LocalSaveSource,
    SaveSnapshot,
    SavePlanetSnapshot,
    SaveProductionSlotSnapshot,
    SaveResourceSnapshot,
    SaveSourceConfigSnapshot,
    SaveSourceMetadata,
)
from ipm_bot.main import ExitCode, main, run_single_control_tick
from ipm_bot.planner.planner import PlannerDecision
from ipm_bot.actuator.stub import StubActionActuator


class ControlTickTests(unittest.TestCase):
    def test_two_tick_sequence_boost_then_claim_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_path = root / "save.json"

            tick_one_payload = {
                "adBoostActive": False,
                "adsWatched": 1,
                "saveTimestamp": "2026-03-22T14:31:05",
                "arkRewardReadyToClaim": False,
                "playerLevel": 5,
            }
            tick_two_payload = {
                "adBoostActive": True,
                "adsWatched": 2,
                "saveTimestamp": "2026-03-22T14:36:05",
                "arkRewardReadyToClaim": True,
                "playerLevel": 5,
            }

            receipt_one = _sample_receipt(
                action="activate_ad_boost",
                final_status="PASS",
                failure_reason=FailureReason.NONE,
                planner_decision=PlannerDecision(
                    selected_action="activate_ad_boost",
                    decision_reason="ad_boost_inactive",
                    actuation_required=True,
                ),
            )
            receipt_two = _sample_receipt(
                action="claim_reward",
                final_status="PASS",
                failure_reason=FailureReason.NONE,
                planner_decision=PlannerDecision(
                    selected_action="claim_reward",
                    decision_reason="reward_available:none",
                    actuation_required=True,
                ),
            )

            with (
                patch("ipm_bot.main.check_ad_boost_suppressed", return_value=False),
                patch("ipm_bot.main.check_reward_claim_suppressed", return_value=False),
                patch("ipm_bot.main.run_action_until_verified", side_effect=[receipt_one, receipt_two]) as runner,
                patch("ipm_bot.main.write_receipt", return_value=root / "receipt.json"),
            ):
                save_path.write_text(json.dumps(tick_one_payload), encoding="utf-8")
                action_one, receipt_one_out, _ = run_single_control_tick(
                    save_path=save_path,
                    timeout_seconds=None,
                    poll_interval_seconds=0.5,
                    actuator=StubActionActuator(),
                    save_source=LocalSaveSource(),
                )

                save_path.write_text(json.dumps(tick_two_payload), encoding="utf-8")
                action_two, receipt_two_out, _ = run_single_control_tick(
                    save_path=save_path,
                    timeout_seconds=None,
                    poll_interval_seconds=0.5,
                    actuator=StubActionActuator(),
                    save_source=LocalSaveSource(),
                )

            self.assertEqual(action_one, "activate_ad_boost")
            self.assertEqual(receipt_one_out.planner_decision.selected_action, "activate_ad_boost")
            self.assertEqual(action_two, "claim_reward")
            self.assertEqual(receipt_two_out.planner_decision.selected_action, "claim_reward")
            self.assertEqual(runner.call_count, 2)
            self.assertNotEqual(action_one, action_two)

    def test_ad_boost_suppressed_does_not_block_claim_reward_when_active(self) -> None:
        save_payload = {
            "adBoostActive": True,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": True,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="claim_reward",
            final_status="PASS",
            failure_reason=FailureReason.NONE,
            planner_decision=PlannerDecision(
                selected_action="claim_reward",
                decision_reason="reward_available:none",
                actuation_required=True,
            ),
        )

        exit_code, stdout_value, runner_mock, _, payloads = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
            ad_boost_suppressed=True,
            claim_reward_suppressed=False,
        )

        self.assertEqual(exit_code, int(ExitCode.PASS))
        self.assertEqual(runner_mock.call_count, 1)
        self.assertEqual(runner_mock.call_args.kwargs["action"], "claim_reward")
        self.assertEqual(payloads[0]["planner_decision"]["selected_action"], "claim_reward")
        self.assertIn("Selected action: claim_reward", stdout_value)

    def test_claim_reward_suppressed_returns_idle_in_control_tick(self) -> None:
        save_payload = {
            "adBoostActive": True,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": True,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="idle",
            final_status="PASS",
            failure_reason=FailureReason.NONE,
            planner_decision=PlannerDecision(
                selected_action="idle",
                decision_reason="claim_reward_suppressed_after_repeated_failures",
                actuation_required=False,
            ),
            actuation_attempted=False,
        )

        exit_code, stdout_value, runner_mock, _, payloads = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
            ad_boost_suppressed=False,
            claim_reward_suppressed=True,
        )

        self.assertEqual(exit_code, int(ExitCode.PASS))
        self.assertEqual(runner_mock.call_count, 1)
        self.assertEqual(runner_mock.call_args.kwargs["action"], "idle")
        self.assertEqual(payloads[0]["planner_decision"]["selected_action"], "idle")
        self.assertFalse(payloads[0]["planner_decision"]["actuation_required"])
        self.assertIn("Selected action: idle", stdout_value)
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
        self.assertEqual(
            payloads[0]["runtime_context"]["receipt_schema_version"],
            CURRENT_RECEIPT_SCHEMA_VERSION,
        )
        self.assertEqual(payloads[0]["prepared_save_hash"], receipt.baseline_hash)
        self.assertTrue(payloads[0]["planner_decision"]["actuation_required"])
        self.assertTrue(payloads[0]["actuation_attempted"])
        self.assertEqual(payloads[0]["actuator_execution"]["actuator_type"], "stub")
        self.assertEqual(payloads[0]["actuator_config"]["actuator_type"], "stub")
        self.assertEqual(payloads[0]["save_source"]["save_source_type"], "local")
        self.assertFalse(payloads[0]["save_source"]["preparation_performed"])
        self.assertFalse(payloads[0]["runtime_context"]["save_snapshot_available"])
        self.assertEqual(payloads[0]["runtime_context"]["active_smelters"], 0)
        self.assertEqual(payloads[0]["runtime_context"]["active_crafters"], 0)
        self.assertIsNone(payloads[0]["runtime_context"]["nearest_completion_seconds"])
        self.assertIsNone(payloads[0]["runtime_context"]["planner_nearest_completion_seconds"])
        self.assertFalse(payloads[0]["runtime_context"]["planner_save_snapshot_used"])
        self.assertFalse(
            payloads[0]["runtime_context"]["planner_deferred_for_imminent_completion"]
        )
        self.assertEqual(
            payloads[0]["save_source"]["local_source_path"],
            payloads[0]["save_source"]["prepared_local_path"],
        )
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
            "adBoostActive": False,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": True,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="claim_reward",
            final_status="AMBIGUOUS",
            failure_reason=FailureReason.AMBIGUOUS_TRANSITION,
        )

        exit_code, stdout_value, runner_mock, _, _ = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
        )

        self.assertEqual(exit_code, int(ExitCode.AMBIGUOUS))
        self.assertEqual(runner_mock.call_count, 1)
        self.assertEqual(runner_mock.call_args.kwargs["action"], "claim_reward")
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
        self.assertEqual(payloads[0]["actuator_config"]["actuator_type"], "stub")
        self.assertIn("Selected action: idle", stdout_value)

    def test_ark_ready_claims_reward_in_control_tick_when_boost_is_already_active(self) -> None:
        save_payload = {
            "adBoostActive": True,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": True,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="claim_reward",
            final_status="PASS",
            failure_reason=FailureReason.NONE,
            planner_decision=PlannerDecision(
                selected_action="claim_reward",
                decision_reason="reward_available:none",
                actuation_required=True,
            ),
        )

        exit_code, stdout_value, runner_mock, _, payloads = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
        )

        self.assertEqual(exit_code, int(ExitCode.PASS))
        self.assertEqual(runner_mock.call_count, 1)
        self.assertEqual(runner_mock.call_args.kwargs["action"], "claim_reward")
        self.assertEqual(payloads[0]["planner_decision"]["selected_action"], "claim_reward")
        self.assertEqual(
            payloads[0]["planner_decision"]["decision_reason"],
            "reward_available:none",
        )
        self.assertTrue(payloads[0]["planner_decision"]["actuation_required"])
        self.assertTrue(payloads[0]["actuation_attempted"])
        self.assertIn("Selected action: claim_reward", stdout_value)

    def test_run_single_control_tick_passes_save_snapshot_into_planner_for_binary_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "playerInfo.dat"
            save_path.write_bytes(b"binary-save")
            receipt = _sample_receipt(
                action="idle",
                final_status="PASS",
                failure_reason=FailureReason.NONE,
            )
            player_snapshot = object()
            save_snapshot = SaveSnapshot(
                source_path=str(save_path.resolve()),
                resources=(
                    SaveResourceSnapshot(
                        index=0,
                        discovered=True,
                        count=1.0,
                        gathered_total=1.0,
                        gathered_this_galaxy=1.0,
                        sold_total=0.0,
                        sold_this_galaxy=0.0,
                    ),
                ),
                planets=(
                    SavePlanetSnapshot(
                        index=0,
                        unlocked=True,
                        mining_speed_level=1,
                        speed_level=1,
                        cargo_level=1,
                        trip_start_date=None,
                        trip_end_date=None,
                    ),
                ),
                smelters=(),
                crafters=(
                    SaveProductionSlotSnapshot(
                        index=1,
                        on=True,
                        recipe_number=3,
                        start_date=None,
                        end_date=None,
                        original_end_date=None,
                        timespan_left=timedelta(seconds=3.0),
                        seconds_completed=477.0,
                        duration_estimate=480.0,
                    ),
                ),
            )
            planner_decision = PlannerDecision(
                selected_action="idle",
                decision_reason="defer_ad_boost_for_imminent_completion",
                actuation_required=False,
            )

            with (
                patch("ipm_bot.main.load_save_snapshot", return_value=save_snapshot) as save_loader,
                patch("ipm_bot.main._load_snapshot", return_value=player_snapshot) as player_loader,
                patch("ipm_bot.main.check_ad_boost_suppressed", return_value=False),
                patch("ipm_bot.main.check_reward_claim_suppressed", return_value=False),
                patch("ipm_bot.main.decide_next_action_details", return_value=planner_decision) as planner,
                patch("ipm_bot.main.run_action_until_verified", return_value=receipt),
                patch("ipm_bot.main.write_receipt", return_value=Path(tmpdir) / "receipt.json"),
            ):
                action, enriched_receipt, _ = run_single_control_tick(
                    save_path=save_path,
                    timeout_seconds=None,
                    poll_interval_seconds=0.5,
                    actuator=StubActionActuator(),
                    save_source=LocalSaveSource(),
                )

        save_loader.assert_called_once_with(save_path.resolve())
        player_loader.assert_called_once_with(save_path.resolve())
        planner.assert_called_once_with(
            player_snapshot,
            save_snapshot=save_snapshot,
            unattended_safe=False,
            ad_boost_suppressed=False,
            claim_reward_suppressed=False,
        )
        self.assertEqual(action, "idle")
        self.assertEqual(
            enriched_receipt.planner_decision.decision_reason,
            "defer_ad_boost_for_imminent_completion",
        )
        self.assertTrue(enriched_receipt.runtime_context.save_snapshot_available)
        self.assertEqual(enriched_receipt.runtime_context.active_smelters, 0)
        self.assertEqual(enriched_receipt.runtime_context.active_crafters, 1)
        self.assertEqual(enriched_receipt.runtime_context.nearest_completion_seconds, 3.0)
        self.assertEqual(
            enriched_receipt.runtime_context.planner_nearest_completion_seconds,
            3.0,
        )
        self.assertTrue(enriched_receipt.runtime_context.planner_save_snapshot_used)
        self.assertTrue(
            enriched_receipt.runtime_context.planner_deferred_for_imminent_completion
        )

    def test_run_single_control_tick_defaults_claim_reward_suppressed_when_ad_boost_is_pre_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            save_path.write_text(
                json.dumps(
                    {
                        "adBoostActive": True,
                        "adsWatched": 1,
                        "saveTimestamp": "2026-03-22T14:31:05",
                        "arkRewardReadyToClaim": False,
                        "playerLevel": 5,
                    }
                ),
                encoding="utf-8",
            )
            receipt = _sample_receipt(
                action="idle",
                final_status="PASS",
                failure_reason=FailureReason.NONE,
            )
            player_snapshot = object()
            planner_decision = PlannerDecision(
                selected_action="idle",
                decision_reason="no_action_needed",
                actuation_required=False,
            )

            with (
                patch("ipm_bot.main._load_snapshot", return_value=player_snapshot),
                patch("ipm_bot.main.decide_next_action_details", return_value=planner_decision) as planner,
                patch("ipm_bot.main.run_action_until_verified", return_value=receipt),
                patch("ipm_bot.main.write_receipt", return_value=Path(tmpdir) / "receipt.json"),
            ):
                run_single_control_tick(
                    save_path=save_path,
                    timeout_seconds=None,
                    poll_interval_seconds=0.5,
                    actuator=StubActionActuator(),
                    save_source=LocalSaveSource(),
                    ad_boost_suppressed=True,
                )

        planner.assert_called_once_with(
            player_snapshot,
            save_snapshot=None,
            unattended_safe=False,
            ad_boost_suppressed=True,
            claim_reward_suppressed=False,
        )

    def test_main_threads_explicit_mining_verification_mode_to_runner(self) -> None:
        save_payload = {
            "adBoostActive": True,
            "adsWatched": 1,
            "saveTimestamp": "2026-03-22T14:31:05",
            "arkRewardReadyToClaim": True,
            "playerLevel": 5,
        }
        receipt = _sample_receipt(
            action="claim_reward",
            final_status="PASS",
            failure_reason=FailureReason.NONE,
        )

        exit_code, _, runner_mock, _, _ = _run_main_with_receipt(
            save_payload=save_payload,
            receipt=receipt,
            argv_extra=["--mining-verification-mode", MiningVerificationMode.USER_CLAIM.value],
        )

        self.assertEqual(exit_code, int(ExitCode.PASS))
        self.assertEqual(
            runner_mock.call_args.kwargs["mining_verification_mode"],
            MiningVerificationMode.USER_CLAIM,
        )


def _run_main_with_receipt(
    *,
    save_payload: dict[str, object],
    receipt: ActionAttemptReceipt,
    ad_boost_suppressed: bool = False,
    claim_reward_suppressed: bool = False,
    argv_extra: list[str] | None = None,
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
            patch("ipm_bot.main.check_ad_boost_suppressed", return_value=ad_boost_suppressed),
            patch("ipm_bot.main.check_reward_claim_suppressed", return_value=claim_reward_suppressed),
            patch("ipm_bot.main.run_action_until_verified", return_value=receipt) as runner_mock,
            patch("ipm_bot.main.write_receipt", side_effect=_write_to_temp),
        ):
            argv = [str(save_path)]
            if argv_extra is not None:
                argv.extend(argv_extra)
            exit_code = main(argv)

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
        if action == "claim_reward":
            resolved_planner_decision = PlannerDecision(
                selected_action=action,
                decision_reason="reward_available:none",
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
            receipt_schema_version=CURRENT_RECEIPT_SCHEMA_VERSION,
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
        actuator_config_snapshot=ActuatorConfigSnapshot(actuator_type="stub"),
        verifier_messages=["verification message"],
        planner_decision=resolved_planner_decision,
        actuation_attempted=resolved_actuation_attempted,
        save_source_metadata=SaveSourceMetadata(
            save_source_type="local",
            original_requested_path="C:\\dev\\ipm-bot\\data\\save.json",
            prepared_local_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
            preparation_performed=False,
            config_snapshot=SaveSourceConfigSnapshot(
                save_source_type="local",
                preparation_performed=False,
                prepared_local_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
                original_requested_path="C:\\dev\\ipm-bot\\data\\save.json",
                local_source_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()

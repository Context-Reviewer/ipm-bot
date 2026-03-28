from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.boundary import (
    ActuatorConfigSnapshot,
    ActuatorExecutionError,
    ActuatorExecutionMetadata,
)
from ipm_bot.actuator.runner import FailureReason, run_action_until_verified
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.save_source import SaveRefreshTelemetry
from ipm_bot.save import parse_player_snapshot


class RunnerReceiptTests(unittest.TestCase):
    def test_pass_receipt_for_activate_ad_boost(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.15,
                    dict(
                        ad_boost_active=True,
                        ads_watched=2,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.failure_reason, FailureReason.NONE)
            self.assertEqual(receipt.changed_save_count, 1)
            self.assertEqual(len(receipt.candidate_hashes), 1)
            self.assertEqual(actuator.actions, ["activate_ad_boost"])
            self.assertEqual(receipt.actuator_execution.actuator_type, "recording")
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "COMPLETED")
            self.assertEqual(receipt.actuator_execution.actuator_command_count, 1)
            self.assertTrue(receipt.verifier_messages)

    def test_pass_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.15,
                    dict(
                        ad_boost_active=True,
                        ads_watched=1,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="claim_ark_reward",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("claim_ark_reward"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.failure_reason, FailureReason.NONE)
            self.assertEqual(receipt.changed_save_count, 1)
            self.assertEqual(len(receipt.candidate_hashes), 1)
            self.assertEqual(actuator.actions, ["claim_ark_reward"])
            self.assertEqual(receipt.actuator_execution.actuator_type, "recording")
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "COMPLETED")
            self.assertEqual(receipt.actuator_execution.actuator_command_count, 1)
            self.assertTrue(receipt.verifier_messages)

    def test_pass_receipt_for_claim_ark_reward_when_reward_application_is_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = ClaimingActuator()
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
                dark_matter=10,
                arks_claimed=5,
                cash=100.0,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.15,
                    dict(
                        ad_boost_active=True,
                        ads_watched=1,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                        dark_matter=15,
                        arks_claimed=6,
                        cash=100.0,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="claim_ark_reward",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("claim_ark_reward"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.failure_reason, FailureReason.NONE)
            self.assertTrue(receipt.claim_attempted)
            self.assertEqual(receipt.number_of_claim_taps, 1)
            self.assertEqual(receipt.claim_tap_timestamps, [0.25])
            self.assertTrue(
                any("Reward application proven" in message for message in receipt.verifier_messages)
            )

    def test_claim_attempt_with_cash_only_drift_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = ClaimingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
                dark_matter=10,
                arks_claimed=5,
                cash=100.0,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.1,
                    dict(
                        ad_boost_active=True,
                        ads_watched=2,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                        dark_matter=10,
                        arks_claimed=5,
                        cash=125.0,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "AMBIGUOUS")
            self.assertEqual(receipt.failure_reason, FailureReason.AMBIGUOUS_TRANSITION)
            self.assertTrue(
                any(
                    "did not prove reward application" in message
                    for message in receipt.verifier_messages
                )
            )

    def test_timeout_no_save_change_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=0.25,
            )

            self.assertEqual(receipt.final_status, "FAIL")
            self.assertEqual(
                receipt.failure_reason,
                FailureReason.TIMEOUT_NO_SAVE_CHANGE,
            )
            self.assertEqual(receipt.changed_save_count, 0)
            self.assertEqual(receipt.candidate_hashes, [])
            self.assertEqual(actuator.actions, ["activate_ad_boost"])
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "COMPLETED")
            self.assertEqual(receipt.verifier_messages, [])

    def test_timeout_no_save_change_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
            )
            snapshot_before = parse_player_snapshot(save_path)

            receipt = run_action_until_verified(
                action="claim_ark_reward",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("claim_ark_reward"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=0.25,
            )

            self.assertEqual(receipt.final_status, "FAIL")
            self.assertEqual(
                receipt.failure_reason,
                FailureReason.TIMEOUT_NO_SAVE_CHANGE,
            )
            self.assertEqual(receipt.changed_save_count, 0)
            self.assertEqual(receipt.candidate_hashes, [])
            self.assertEqual(actuator.actions, ["claim_ark_reward"])
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "COMPLETED")
            self.assertEqual(receipt.verifier_messages, [])

    def test_timeout_after_save_changes_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.1,
                    dict(
                        ad_boost_active=False,
                        ads_watched=2,
                        save_timestamp=started_at,
                        ark_reward_ready_to_claim=True,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="claim_ark_reward",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("claim_ark_reward"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=0.4,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "FAIL")
            self.assertEqual(
                receipt.failure_reason,
                FailureReason.TIMEOUT_AFTER_SAVE_CHANGES,
            )
            self.assertEqual(receipt.changed_save_count, 1)
            self.assertEqual(len(receipt.candidate_hashes), 1)
            self.assertEqual(actuator.actions, ["claim_ark_reward"])
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "COMPLETED")
            self.assertTrue(receipt.verifier_messages)

    def test_ambiguous_transition_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.1,
                    dict(
                        ad_boost_active=False,
                        ads_watched=2,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "AMBIGUOUS")
            self.assertEqual(
                receipt.failure_reason,
                FailureReason.AMBIGUOUS_TRANSITION,
            )
            self.assertEqual(receipt.changed_save_count, 1)
            self.assertEqual(actuator.actions, ["activate_ad_boost"])
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "COMPLETED")
            self.assertTrue(receipt.verifier_messages)

    def test_activate_ad_boost_claim_attempt_without_reward_proof_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = ClaimingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
                dark_matter=10,
                arks_claimed=5,
                cash=100.0,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.1,
                    dict(
                        ad_boost_active=True,
                        ads_watched=2,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                        dark_matter=10,
                        arks_claimed=5,
                        cash=100.0,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "AMBIGUOUS")
            self.assertEqual(receipt.failure_reason, FailureReason.AMBIGUOUS_TRANSITION)
            self.assertTrue(receipt.claim_attempted)
            self.assertEqual(receipt.number_of_claim_taps, 1)
            self.assertTrue(
                any(
                    "did not prove reward application" in message
                    for message in receipt.verifier_messages
                )
            )

    def test_ambiguous_transition_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.1,
                    dict(
                        ad_boost_active=True,
                        ads_watched=1,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=True,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="claim_ark_reward",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("claim_ark_reward"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "AMBIGUOUS")
            self.assertEqual(
                receipt.failure_reason,
                FailureReason.AMBIGUOUS_TRANSITION,
            )
            self.assertEqual(receipt.changed_save_count, 1)
            self.assertEqual(actuator.actions, ["claim_ark_reward"])
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "COMPLETED")
            self.assertTrue(receipt.verifier_messages)

    def test_claim_reward_signals_are_not_inferred_when_actuator_metadata_omits_claim_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
                dark_matter=10,
                arks_claimed=5,
                cash=100.0,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.1,
                    dict(
                        ad_boost_active=True,
                        ads_watched=2,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                        dark_matter=15,
                        arks_claimed=6,
                        cash=125.0,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "PASS")
            self.assertFalse(receipt.claim_attempted)
            self.assertEqual(receipt.number_of_claim_taps, 0)

    def test_idle_does_not_invoke_actuator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=datetime(2026, 3, 22, 12, 0, 0),
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)

            receipt = run_action_until_verified(
                action="idle",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("idle"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=0.25,
            )

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.failure_reason, FailureReason.NONE)
            self.assertEqual(actuator.actions, [])
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "NOT_REQUIRED")
            self.assertEqual(receipt.actuator_execution.actuator_command_count, 0)

    def test_actuator_failure_is_classified_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            actuator = FailingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=datetime(2026, 3, 22, 12, 0, 0),
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=0.25,
            )

            self.assertEqual(receipt.final_status, "FAIL")
            self.assertEqual(receipt.failure_reason, FailureReason.COMMAND_EXECUTION_ERROR)
            self.assertEqual(receipt.actuator_execution.actuator_type, "failing")
            self.assertEqual(receipt.actuator_execution.actuator_execution_status, "FAILED")
            self.assertEqual(receipt.actuator_execution.actuator_command_count, 1)
            self.assertEqual(receipt.actuator_execution.actuator_command_summary, ["failing:activate_ad_boost"])

    def test_periodic_refresh_updates_local_file_and_is_observed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)
            refresh_controller = RefreshingController(
                refresh_steps=[
                    RefreshStep(
                        ad_boost_active=True,
                        ads_watched=2,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                    )
                ],
                target_path=save_path,
                refresh_interval_seconds=0.05,
            )

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
                save_refresh_controller=refresh_controller,
            )

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.runtime_context.save_repull_interval_seconds, 0.05)
            self.assertGreaterEqual(receipt.runtime_context.save_repull_count, 1)
            self.assertEqual(receipt.runtime_context.save_repull_failure_count, 0)

    def test_refresh_failures_are_logged_but_do_not_abort_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = RecordingActuator()
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)
            refresh_controller = RefreshingController(
                refresh_steps=[
                    RuntimeError("adb pull failed"),
                    RefreshStep(
                        ad_boost_active=True,
                        ads_watched=2,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                    ),
                ],
                target_path=save_path,
                refresh_interval_seconds=0.05,
            )

            receipt = run_action_until_verified(
                action="activate_ad_boost",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("activate_ad_boost"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=1.0,
                save_refresh_controller=refresh_controller,
            )

            self.assertEqual(receipt.final_status, "PASS")
            self.assertGreaterEqual(receipt.runtime_context.save_repull_count, 2)
            self.assertEqual(receipt.runtime_context.save_repull_failure_count, 1)
            self.assertTrue(
                any("Save refresh attempt 1 failed" in message for message in receipt.verifier_messages)
            )

    def test_long_actuation_can_still_verify_when_timeout_starts_after_actuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = SlowActuator(delay_seconds=0.2)
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
            )
            snapshot_before = parse_player_snapshot(save_path)

            update_thread = threading.Thread(
                target=_delayed_write,
                args=(
                    save_path,
                    0.3,
                    dict(
                        ad_boost_active=True,
                        ads_watched=1,
                        save_timestamp=started_at + timedelta(seconds=5),
                        ark_reward_ready_to_claim=False,
                    ),
                ),
            )
            update_thread.start()

            receipt = run_action_until_verified(
                action="claim_ark_reward",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("claim_ark_reward"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=0.2,
                verification_timeout_starts_after_actuation=True,
            )

            update_thread.join()

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.failure_reason, FailureReason.NONE)
            self.assertEqual(
                receipt.runtime_context.timeout_scope,
                "verification_only_after_actuation",
            )
            self.assertGreaterEqual(receipt.runtime_context.actuation_elapsed_seconds, 0.15)
            self.assertGreater(receipt.runtime_context.verification_elapsed_seconds, 0.0)
            self.assertTrue(receipt.runtime_context.verification_started)
            self.assertFalse(receipt.runtime_context.verification_starved_by_timeout)

    def test_total_run_timeout_can_be_starved_by_long_actuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            actuator = SlowActuator(delay_seconds=0.2)
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
            )
            snapshot_before = parse_player_snapshot(save_path)

            receipt = run_action_until_verified(
                action="claim_ark_reward",
                save_path=save_path,
                snapshot_before=snapshot_before,
                contract=get_action_contract("claim_ark_reward"),
                actuator=actuator,
                poll_interval_s=0.05,
                timeout_s=0.1,
            )

            self.assertEqual(receipt.final_status, "FAIL")
            self.assertEqual(receipt.failure_reason, FailureReason.TIMEOUT_NO_SAVE_CHANGE)
            self.assertEqual(receipt.runtime_context.timeout_scope, "total_run")
            self.assertGreaterEqual(receipt.runtime_context.actuation_elapsed_seconds, 0.19)
            self.assertLess(receipt.runtime_context.verification_elapsed_seconds, 0.02)
            self.assertTrue(receipt.runtime_context.verification_started)
            self.assertTrue(receipt.runtime_context.verification_starved_by_timeout)
            self.assertTrue(
                any("Verification budget was exhausted by actuation" in message for message in receipt.verifier_messages)
            )


def _delayed_write(path: Path, delay_s: float, payload: dict[str, object]) -> None:
    time.sleep(delay_s)
    _write_save(path, **payload)


def _write_save(
    path: Path,
    *,
    ad_boost_active: bool,
    ads_watched: int,
    save_timestamp: datetime,
    ark_reward_ready_to_claim: bool,
    dark_matter: int = 0,
    arks_claimed: int = 0,
    cash: float = 0.0,
    player_level: int = 5,
) -> None:
    payload = {
        "cash": cash,
        "darkMatter": dark_matter,
        "adBoostActive": ad_boost_active,
        "adsWatched": ads_watched,
        "arksClaimed": arks_claimed,
        "saveTimestamp": save_timestamp.isoformat(),
        "arkRewardReadyToClaim": ark_reward_ready_to_claim,
        "playerLevel": player_level,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class RecordingActuator:
    actuator_type = "recording"
    config_snapshot = ActuatorConfigSnapshot(actuator_type="recording")

    def __init__(self) -> None:
        self.actions: list[str] = []

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        self.actions.append(action)
        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=1,
            actuator_command_summary=[f"recording:{action}"],
        )


class ClaimingActuator:
    actuator_type = "claiming"
    config_snapshot = ActuatorConfigSnapshot(actuator_type="claiming")

    def __init__(self) -> None:
        self.actions: list[str] = []

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        self.actions.append(action)
        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=1,
            actuator_command_summary=[f"claiming:{action}"],
            claim_attempted=True,
            number_of_claim_taps=1,
            claim_tap_timestamps=[0.25],
        )


class FailingActuator:
    actuator_type = "failing"
    config_snapshot = ActuatorConfigSnapshot(actuator_type="failing")

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        raise ActuatorExecutionError(
            f"Failed to execute action: {action}",
            ActuatorExecutionMetadata(
                actuator_type=self.actuator_type,
                actuator_execution_status="FAILED",
                actuator_command_count=1,
                actuator_command_summary=[f"failing:{action}"],
            ),
        )


class SlowActuator:
    actuator_type = "slow"
    config_snapshot = ActuatorConfigSnapshot(actuator_type="slow")

    def __init__(self, *, delay_seconds: float) -> None:
        self._delay_seconds = delay_seconds
        self.actions: list[str] = []

    def execute(self, action: str) -> ActuatorExecutionMetadata:
        self.actions.append(action)
        time.sleep(self._delay_seconds)
        return ActuatorExecutionMetadata(
            actuator_type=self.actuator_type,
            actuator_execution_status="COMPLETED",
            actuator_command_count=1,
            actuator_command_summary=[f"slow:{action}"],
        )


class RefreshingController:
    def __init__(
        self,
        *,
        refresh_steps: list["RefreshStep | Exception"],
        target_path: Path,
        refresh_interval_seconds: float,
    ) -> None:
        self._steps = list(refresh_steps)
        self._target_path = target_path
        self._refresh_interval_seconds = refresh_interval_seconds
        self._refresh_attempt_count = 0
        self._refresh_failure_count = 0
        self._warning_messages: list[str] = []

    def maybe_refresh(self) -> None:
        self._refresh_attempt_count += 1
        if not self._steps:
            return
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            self._refresh_failure_count += 1
            self._warning_messages.append(
                f"Save refresh attempt {self._refresh_attempt_count} failed for fake: {step}"
            )
            return
        _write_save(
            self._target_path,
            ad_boost_active=step.ad_boost_active,
            ads_watched=step.ads_watched,
            save_timestamp=step.save_timestamp,
            ark_reward_ready_to_claim=step.ark_reward_ready_to_claim,
        )

    def telemetry(self) -> SaveRefreshTelemetry:
        return SaveRefreshTelemetry(
            refresh_interval_seconds=self._refresh_interval_seconds,
            refresh_attempt_count=self._refresh_attempt_count,
            refresh_failure_count=self._refresh_failure_count,
            warning_messages=tuple(self._warning_messages),
        )


class RefreshStep:
    def __init__(
        self,
        *,
        ad_boost_active: bool,
        ads_watched: int,
        save_timestamp: datetime,
        ark_reward_ready_to_claim: bool,
    ) -> None:
        self.ad_boost_active = ad_boost_active
        self.ads_watched = ads_watched
        self.save_timestamp = save_timestamp
        self.ark_reward_ready_to_claim = ark_reward_ready_to_claim


if __name__ == "__main__":
    unittest.main()

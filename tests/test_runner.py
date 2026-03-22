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

from ipm_bot.actuator.boundary import ActuatorExecutionError, ActuatorExecutionMetadata
from ipm_bot.actuator.runner import FailureReason, run_action_until_verified
from ipm_bot.control.contracts import get_action_contract
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
    player_level: int = 5,
) -> None:
    payload = {
        "adBoostActive": ad_boost_active,
        "adsWatched": ads_watched,
        "saveTimestamp": save_timestamp.isoformat(),
        "arkRewardReadyToClaim": ark_reward_ready_to_claim,
        "playerLevel": player_level,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class RecordingActuator:
    actuator_type = "recording"

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


class FailingActuator:
    actuator_type = "failing"

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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.runner import FailureReason, run_action_until_verified
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.save import parse_player_snapshot


class RunnerReceiptTests(unittest.TestCase):
    def test_pass_receipt_for_activate_ad_boost(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
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

            with patch("ipm_bot.actuator.runner.run_action"):
                receipt = run_action_until_verified(
                    action="activate_ad_boost",
                    save_path=save_path,
                    snapshot_before=snapshot_before,
                    contract=get_action_contract("activate_ad_boost"),
                    poll_interval_s=0.05,
                    timeout_s=1.0,
                )

            update_thread.join()

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.failure_reason, FailureReason.NONE)
            self.assertEqual(receipt.changed_save_count, 1)
            self.assertEqual(len(receipt.candidate_hashes), 1)
            self.assertTrue(receipt.verifier_messages)

    def test_pass_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
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

            with patch("ipm_bot.actuator.runner.run_action"):
                receipt = run_action_until_verified(
                    action="claim_ark_reward",
                    save_path=save_path,
                    snapshot_before=snapshot_before,
                    contract=get_action_contract("claim_ark_reward"),
                    poll_interval_s=0.05,
                    timeout_s=1.0,
                )

            update_thread.join()

            self.assertEqual(receipt.final_status, "PASS")
            self.assertEqual(receipt.failure_reason, FailureReason.NONE)
            self.assertEqual(receipt.changed_save_count, 1)
            self.assertEqual(len(receipt.candidate_hashes), 1)
            self.assertTrue(receipt.verifier_messages)

    def test_timeout_no_save_change_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            _write_save(
                save_path,
                ad_boost_active=False,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=False,
            )
            snapshot_before = parse_player_snapshot(save_path)

            with patch("ipm_bot.actuator.runner.run_action"):
                receipt = run_action_until_verified(
                    action="activate_ad_boost",
                    save_path=save_path,
                    snapshot_before=snapshot_before,
                    contract=get_action_contract("activate_ad_boost"),
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
            self.assertEqual(receipt.verifier_messages, [])

    def test_timeout_no_save_change_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
            _write_save(
                save_path,
                ad_boost_active=True,
                ads_watched=1,
                save_timestamp=started_at,
                ark_reward_ready_to_claim=True,
            )
            snapshot_before = parse_player_snapshot(save_path)

            with patch("ipm_bot.actuator.runner.run_action"):
                receipt = run_action_until_verified(
                    action="claim_ark_reward",
                    save_path=save_path,
                    snapshot_before=snapshot_before,
                    contract=get_action_contract("claim_ark_reward"),
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
            self.assertEqual(receipt.verifier_messages, [])

    def test_timeout_after_save_changes_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
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

            with patch("ipm_bot.actuator.runner.run_action"):
                receipt = run_action_until_verified(
                    action="claim_ark_reward",
                    save_path=save_path,
                    snapshot_before=snapshot_before,
                    contract=get_action_contract("claim_ark_reward"),
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
            self.assertTrue(receipt.verifier_messages)

    def test_ambiguous_transition_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
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

            with patch("ipm_bot.actuator.runner.run_action"):
                receipt = run_action_until_verified(
                    action="activate_ad_boost",
                    save_path=save_path,
                    snapshot_before=snapshot_before,
                    contract=get_action_contract("activate_ad_boost"),
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
            self.assertTrue(receipt.verifier_messages)

    def test_ambiguous_transition_receipt_for_claim_ark_reward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "save.json"
            started_at = datetime(2026, 3, 22, 12, 0, 0)
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

            with patch("ipm_bot.actuator.runner.run_action"):
                receipt = run_action_until_verified(
                    action="claim_ark_reward",
                    save_path=save_path,
                    snapshot_before=snapshot_before,
                    contract=get_action_contract("claim_ark_reward"),
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
            self.assertTrue(receipt.verifier_messages)


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.actuator.boundary import ActuatorConfigSnapshot, ActuatorExecutionMetadata
from ipm_bot.actuator.runner import (
    ActionAttemptReceipt,
    FailureReason,
    ReceiptRuntimeContext,
)
from ipm_bot.actuator.stub import StubActionActuator
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_schema import CURRENT_RECEIPT_SCHEMA_VERSION
from ipm_bot.control.receipt_store import check_ad_boost_suppressed, write_receipt
from ipm_bot.control.save_source import LocalSaveSource, SaveSourceMetadata, SaveSourceConfigSnapshot
from ipm_bot.main import run_single_control_tick
from ipm_bot.planner.planner import PlannerDecision


class CheckAdBoostSuppressedTests(unittest.TestCase):

    def test_fewer_than_threshold_failures_not_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_dir = Path(tmpdir)
            _write_fake_receipt(receipt_dir, "2026-03-24T10-00-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-01-00Z", "activate_ad_boost", "FAIL")

            result = check_ad_boost_suppressed(receipt_dir, threshold=3)

            self.assertFalse(result)

    def test_threshold_consecutive_failures_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_dir = Path(tmpdir)
            _write_fake_receipt(receipt_dir, "2026-03-24T10-00-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-01-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-02-00Z", "activate_ad_boost", "FAIL")

            result = check_ad_boost_suppressed(receipt_dir, threshold=3)

            self.assertTrue(result)

    def test_non_ad_boost_receipt_breaks_streak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_dir = Path(tmpdir)
            _write_fake_receipt(receipt_dir, "2026-03-24T10-00-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-01-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-02-00Z", "idle", "PASS")

            result = check_ad_boost_suppressed(receipt_dir, threshold=3)

            self.assertFalse(result)

    def test_pass_ad_boost_receipt_breaks_streak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_dir = Path(tmpdir)
            _write_fake_receipt(receipt_dir, "2026-03-24T10-00-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-01-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-02-00Z", "activate_ad_boost", "PASS")

            result = check_ad_boost_suppressed(receipt_dir, threshold=3)

            self.assertFalse(result)

    def test_empty_directory_not_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = check_ad_boost_suppressed(Path(tmpdir), threshold=3)

            self.assertFalse(result)

    def test_missing_directory_not_suppressed(self) -> None:
        result = check_ad_boost_suppressed(Path("/nonexistent/dir"), threshold=3)

        self.assertFalse(result)


class ControlTickSuppressionIntegrationTests(unittest.TestCase):

    def test_run_single_control_tick_computes_suppression_from_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            receipt_dir = root / "receipts"
            receipt_dir.mkdir()
            _write_fake_receipt(receipt_dir, "2026-03-24T10-00-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-01-00Z", "activate_ad_boost", "FAIL")
            _write_fake_receipt(receipt_dir, "2026-03-24T10-02-00Z", "activate_ad_boost", "FAIL")

            save_path = root / "save.json"
            save_path.write_text(json.dumps({
                "adBoostActive": False,
                "adsWatched": 1,
                "saveTimestamp": "2026-03-24T14:31:05",
                "arkRewardReadyToClaim": False,
                "playerLevel": 5,
            }), encoding="utf-8")

            receipt = _sample_receipt(action="idle", final_status="PASS")

            with (
                patch("ipm_bot.main.run_action_until_verified", return_value=receipt),
                patch("ipm_bot.main.write_receipt", return_value=root / "receipt.json"),
            ):
                action, enriched_receipt, _ = run_single_control_tick(
                    save_path=save_path,
                    timeout_seconds=None,
                    poll_interval_seconds=0.5,
                    actuator=StubActionActuator(),
                    save_source=LocalSaveSource(),
                    receipt_dir=receipt_dir,
                )

            self.assertEqual(action, "idle")
            self.assertEqual(
                enriched_receipt.planner_decision.decision_reason,
                "ad_boost_suppressed_after_repeated_failures",
            )


def _write_fake_receipt(
    receipt_dir: Path,
    timestamp: str,
    action: str,
    final_status: str,
) -> Path:
    path = receipt_dir / f"{timestamp}_{action}.json"
    path.write_text(
        json.dumps({"action": action, "final_status": final_status}),
        encoding="utf-8",
    )
    return path


def _sample_receipt(*, action: str, final_status: str) -> ActionAttemptReceipt:
    contract = get_action_contract(action)
    planner_decision = PlannerDecision(
        selected_action=action,
        decision_reason="ad_boost_suppressed_after_repeated_failures" if action == "idle" else "ad_boost_inactive",
        actuation_required=action != "idle",
    )
    return ActionAttemptReceipt(
        action=action,
        save_path=str(Path("C:/dev/ipm-bot/data/save.json").resolve()),
        baseline_hash="abc123",
        final_status=final_status,
        failure_reason=FailureReason.NONE if final_status == "PASS" else FailureReason.TIMEOUT_NO_SAVE_CHANGE,
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
            actuator_execution_status="NOT_REQUIRED" if action == "idle" else "COMPLETED",
            actuator_command_count=0 if action == "idle" else 1,
            actuator_command_summary=[] if action == "idle" else [f"stub:{action}"],
        ),
        actuator_config_snapshot=ActuatorConfigSnapshot(actuator_type="stub"),
        verifier_messages=["test"],
        planner_decision=planner_decision,
        actuation_attempted=action != "idle",
        save_source_metadata=SaveSourceMetadata(
            save_source_type="local",
            original_requested_path="C:\\dev\\ipm-bot\\data\\save.json",
            prepared_local_path=str(Path("C:/dev/ipm-bot/data/save.json").resolve()),
            preparation_performed=False,
            config_snapshot=SaveSourceConfigSnapshot(
                save_source_type="local",
                preparation_performed=False,
                prepared_local_path=str(Path("C:/dev/ipm-bot/data/save.json").resolve()),
                original_requested_path="C:\\dev\\ipm-bot\\data\\save.json",
                local_source_path=str(Path("C:/dev/ipm-bot/data/save.json").resolve()),
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()

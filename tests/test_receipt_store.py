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
from ipm_bot.control.contracts import get_action_contract
from ipm_bot.control.receipt_store import write_receipt
from ipm_bot.main import main


class ReceiptStoreTests(unittest.TestCase):
    def test_write_receipt_creates_directory_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "nested" / "receipts"
            receipt = _sample_receipt()

            written_path = write_receipt(
                receipt,
                output_dir=output_dir,
                written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
            )

            self.assertTrue(output_dir.is_dir())
            self.assertTrue(written_path.is_file())
            self.assertEqual(
                written_path.name,
                "2026-03-22T14-31-05Z_activate_ad_boost.json",
            )

            payload = json.loads(written_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["action"], receipt.action)
            self.assertEqual(payload["baseline_hash"], receipt.baseline_hash)
            self.assertEqual(payload["final_status"], receipt.final_status)
            self.assertEqual(payload["failure_reason"], receipt.failure_reason)
            self.assertEqual(payload["elapsed_seconds"], receipt.elapsed_seconds)
            self.assertEqual(payload["changed_save_count"], receipt.changed_save_count)
            self.assertEqual(payload["candidate_hashes"], receipt.candidate_hashes)
            self.assertEqual(payload["save_path"], receipt.save_path)
            self.assertEqual(payload["final_candidate_hash"], receipt.final_candidate_hash)
            self.assertEqual(
                payload["receipt_written_at_utc"],
                "2026-03-22T14-31-05Z",
            )
            self.assertEqual(
                payload["contract_identity"]["action"],
                receipt.contract_identity.action,
            )
            self.assertEqual(
                payload["contract_identity"]["required_expected_values"],
                receipt.contract_identity.required_expected_values,
            )
            self.assertEqual(
                payload["runtime_context"]["receipt_schema_version"],
                receipt.runtime_context.receipt_schema_version,
            )
            self.assertEqual(
                payload["runtime_context"]["poll_interval_seconds"],
                receipt.runtime_context.poll_interval_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["timeout_seconds"],
                receipt.runtime_context.timeout_seconds,
            )
            self.assertEqual(
                payload["runtime_context"]["exit_code"],
                receipt.runtime_context.exit_code,
            )
            self.assertEqual(payload["verifier_messages"], receipt.verifier_messages)

    def test_main_writes_receipt_and_prints_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_tmp = Path(tmpdir)
            save_path = repo_tmp / "save.json"
            save_path.write_text(
                json.dumps(
                    {
                        "adBoostActive": False,
                        "adsWatched": 1,
                        "saveTimestamp": "2026-03-22T14:31:05",
                        "arkRewardReadyToClaim": False,
                        "playerLevel": 5,
                    }
                ),
                encoding="utf-8",
            )
            output_dir = repo_tmp / "logs" / "receipts"
            receipt = _sample_receipt()
            stdout = io.StringIO()

            def _write_to_temp(receipt_to_write: ActionAttemptReceipt) -> Path:
                return write_receipt(
                    receipt_to_write,
                    output_dir=output_dir,
                    written_at=datetime(2026, 3, 22, 14, 31, 5, tzinfo=timezone.utc),
                )

            with (
                patch("sys.argv", ["ipm_bot.main", str(save_path)]),
                patch("sys.stdout", stdout),
                patch("ipm_bot.main.run_action_until_verified", return_value=receipt),
                patch("ipm_bot.main.write_receipt", side_effect=_write_to_temp),
            ):
                exit_code = main()

            written_files = list(output_dir.glob("*.json"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(written_files), 1)
            self.assertIn("Receipt path:", stdout.getvalue())
            self.assertIn(str(written_files[0]), stdout.getvalue())


def _sample_receipt() -> ActionAttemptReceipt:
    contract = get_action_contract("activate_ad_boost")
    return ActionAttemptReceipt(
        action="activate_ad_boost",
        save_path=str((Path("C:/dev/ipm-bot/data/save.json")).resolve()),
        baseline_hash="abc123",
        final_status="PASS",
        failure_reason=FailureReason.NONE,
        elapsed_seconds=1.25,
        changed_save_count=1,
        candidate_hashes=["def456"],
        final_candidate_hash="def456",
        contract_identity=contract.identity("activate_ad_boost"),
        runtime_context=ReceiptRuntimeContext(
            receipt_schema_version=2,
            poll_interval_seconds=0.5,
            timeout_seconds=30.0,
            exit_code=0,
        ),
        verifier_messages=["Field 'ad_boost_active' matched the expected value: value=True."],
    )


if __name__ == "__main__":
    unittest.main()
